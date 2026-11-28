"""Phase 5: AURA authorization fails closed.

Every path through _check_polkit() that is not an explicit authorization
must deny. There is no headless or in-process fallback. Root is allowed only
after the sender and its PID/UID have been validated.

These tests use a fake bus daemon and a fake Polkit authority, so they run
without a system bus. The real-bus behaviour of the same code is covered by
the Bright Android integration tests, which run on a session bus.
"""
import os
import pathlib
import sys
import threading
import time
import types
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = ""

import aura.core.aura_core_service as svc_mod  # noqa: E402

SERVICE_SRC = (PROJECT_ROOT / "aura/core/aura_core_service.py").read_text()
SENDER = ":1.42"
ACTION = "org.bright_os.AURA.grant-cloud-consent"


class _FakeDaemon:
    def __init__(self, bus):
        self._bus = bus

    def GetConnectionUnixProcessID(self, sender, dbus_interface=None):
        if self._bus.pid_error is not None:
            raise self._bus.pid_error
        return self._bus.pid

    def GetConnectionUnixUser(self, sender, dbus_interface=None):
        if self._bus.uid_error is not None:
            raise self._bus.uid_error
        return self._bus.uid


class FakeBus:
    """Bus daemon stand-in that answers credential queries."""

    def __init__(self, pid=2345, uid=1000, pid_error=None, uid_error=None):
        self.pid = pid
        self.uid = uid
        self.pid_error = pid_error
        self.uid_error = uid_error
        self.lookups = 0

    def get_object(self, bus_name, path):
        self.lookups += 1
        return _FakeDaemon(self)


class _Subject:
    def __init__(self, pid):
        self.pid = pid


class _Result:
    def __init__(self, authorized, challenge=False):
        self._auth = authorized
        self._chal = challenge

    def get_is_authorized(self):
        return self._auth

    def get_is_challenge(self):
        return self._chal


class FakeAuthority:
    """Polkit authority stub. `answer` is returned, or a callable to block."""

    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    def check_authorization_sync(self, subject, action, details, flags, cancellable):
        self.calls.append((subject, action))
        if self.error is not None:
            raise self.error
        if callable(self.answer):
            return self.answer()
        return self.answer


class AuthorizationTestBase(unittest.TestCase):
    def setUp(self):
        self._patches = [
            mock.patch.object(svc_mod, "HAS_DBUS", True),
            mock.patch.object(svc_mod, "HAS_POLKIT", False),
        ]
        for p in self._patches:
            p.start()
        self.authority = None
        self._release = threading.Event()

    def tearDown(self):
        self._release.set()  # unblock any fake authority that is waiting
        for p in reversed(self._patches):
            p.stop()

    def _polkit(self, answer=None, error=None):
        """Install a fake Polkit with the given authority behaviour."""
        self.authority = FakeAuthority(answer=answer, error=error)
        fake = types.SimpleNamespace(
            Authority=types.SimpleNamespace(get_sync=lambda *a, **k: self.authority),
            UnixProcess=types.SimpleNamespace(new=lambda pid: _Subject(pid)),
            CheckAuthorizationFlags=types.SimpleNamespace(ALLOW_USER_INTERACTION=1, NONE=0),
        )
        patch = mock.patch.object(svc_mod, "Polkit", fake, create=True)
        patch.start()
        self._patches.append(patch)
        svc_mod.HAS_POLKIT = True
        return self.authority


class MissingBusTests(AuthorizationTestBase):
    def test_1_missing_bus_denies(self):
        self._polkit(answer=_Result(True))
        ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=None)
        self.assertFalse(ok)
        self.assertIn("no D-Bus connection", reason)
        self.assertEqual(self.authority.calls, [], "Polkit must not be asked without a bus")

    def test_missing_bus_denies_even_for_root_style_call(self):
        ok, _ = svc_mod._check_polkit(SENDER, ACTION, bus=None)
        self.assertFalse(ok)

    def test_dbus_unavailable_denies(self):
        with mock.patch.object(svc_mod, "HAS_DBUS", False):
            ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=0))
        self.assertFalse(ok)
        self.assertIn("D-Bus unavailable", reason)


class MissingSenderTests(AuthorizationTestBase):
    def test_2_missing_sender_denies(self):
        ok, reason = svc_mod._check_polkit(None, ACTION, bus=FakeBus(uid=1000))
        self.assertFalse(ok)
        self.assertIn("no sender", reason)

    def test_missing_sender_denies_root(self):
        ok, _ = svc_mod._check_polkit(None, ACTION, bus=FakeBus(uid=0))
        self.assertFalse(ok)

    def test_empty_sender_denies(self):
        ok, _ = svc_mod._check_polkit("", ACTION, bus=FakeBus(uid=0))
        self.assertFalse(ok)

    def test_non_string_sender_denies(self):
        ok, _ = svc_mod._check_polkit(42, ACTION, bus=FakeBus(uid=0))
        self.assertFalse(ok)


class InvalidCredentialTests(AuthorizationTestBase):
    def test_3_invalid_credentials_deny(self):
        cases = [
            FakeBus(pid=0, uid=1000),
            FakeBus(pid=-5, uid=1000),
            FakeBus(pid="123", uid=1000),
            FakeBus(pid=True, uid=1000),
            FakeBus(pid=2345, uid=-1),
            FakeBus(pid=2345, uid="1000"),
            FakeBus(pid=2345, uid=False),
            FakeBus(pid=2345, uid=None),
        ]
        for bus in cases:
            with self.subTest(pid=bus.pid, uid=bus.uid):
                self._polkit(answer=_Result(True))
                ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=bus)
                self.assertFalse(ok, reason)
                self.assertEqual(self.authority.calls, [])

    def test_credential_lookup_exception_denies(self):
        self._polkit(answer=_Result(True))
        bus = FakeBus(uid_error=RuntimeError("bus went away"))
        ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=bus)
        self.assertFalse(ok)
        self.assertIn("could not determine caller identity", reason)
        self.assertEqual(self.authority.calls, [])

    def test_pid_lookup_exception_denies(self):
        self._polkit(answer=_Result(True))
        bus = FakeBus(pid_error=AttributeError("no such method"))
        ok, _ = svc_mod._check_polkit(SENDER, ACTION, bus=bus)
        self.assertFalse(ok)


class MissingPolkitTests(AuthorizationTestBase):
    def test_4_missing_polkit_denies_non_root(self):
        svc_mod.HAS_POLKIT = False
        ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=1000))
        self.assertFalse(ok)
        self.assertIn("polkit unavailable", reason)

    def test_missing_polkit_does_not_grant_same_user(self):
        svc_mod.HAS_POLKIT = False
        ok, _ = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=1000))
        self.assertFalse(ok)


class DenialTests(AuthorizationTestBase):
    def test_5_authorization_denial(self):
        self._polkit(answer=_Result(False))
        ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=1000))
        self.assertFalse(ok)
        self.assertEqual(reason, "not authorized")

    def test_challenge_denies(self):
        self._polkit(answer=_Result(False, challenge=True))
        ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=1000))
        self.assertFalse(ok)
        self.assertEqual(reason, "authentication required")

    def test_polkit_exception_denies(self):
        self._polkit(error=RuntimeError("polkitd unreachable"))
        ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=1000))
        self.assertFalse(ok)
        self.assertIn("polkit error", reason)

    def test_invalid_polkit_responses_deny(self):
        class Odd:
            def __init__(self, auth, chal):
                self._a, self._c = auth, chal
            def get_is_authorized(self):
                return self._a
            def get_is_challenge(self):
                return self._c

        for auth, chal in [("yes", False), (None, False), (1, False), (True, "no"), (True, None)]:
            with self.subTest(authorized=auth, challenge=chal):
                self._polkit(answer=Odd(auth, chal))
                ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=1000))
                self.assertFalse(ok, reason)

    def test_result_without_methods_denies(self):
        self._polkit(answer=object())
        ok, _ = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=1000))
        self.assertFalse(ok)


class TimeoutTests(AuthorizationTestBase):
    def test_6_authorization_timeout_denies(self):
        # Patch the timeout to something short. Old code has no such constant,
        # so this patch raises and the test fails there.
        with mock.patch.object(svc_mod, "POLKIT_CHECK_TIMEOUT_SECONDS", 0.2):
            def blocked():
                self._release.wait(30)
                return _Result(True)

            self._polkit(answer=blocked)
            start = time.monotonic()
            ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=1000))
            elapsed = time.monotonic() - start
        self.assertFalse(ok)
        self.assertIn("timed out", reason)
        self.assertLess(elapsed, 5.0, "the call must return at the timeout, not wait for Polkit")

    def test_late_result_after_timeout_is_not_used(self):
        released = threading.Event()

        def slow():
            released.wait(30)
            return _Result(True)

        with mock.patch.object(svc_mod, "POLKIT_CHECK_TIMEOUT_SECONDS", 0.2):
            self._polkit(answer=slow)
            ok, _ = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=1000))
            self.assertFalse(ok)
            released.set()  # Polkit now says yes, after the caller was denied
            time.sleep(0.2)
        self.assertFalse(ok)


class ExplicitAuthorizationTests(AuthorizationTestBase):
    def test_7_explicit_authorization_succeeds(self):
        self._polkit(answer=_Result(True))
        bus = FakeBus(pid=2345, uid=1000)
        ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=bus)
        self.assertTrue(ok, reason)
        self.assertEqual(len(self.authority.calls), 1)
        subject, action = self.authority.calls[0]
        self.assertEqual(subject.pid, 2345)
        self.assertEqual(action, ACTION)

    def test_explicit_success_requires_is_authorized_true(self):
        # A truthy but non-bool authorization is not an explicit success.
        class Truthy:
            def get_is_authorized(self):
                return 1

            def get_is_challenge(self):
                return False

        self._polkit(answer=Truthy())
        ok, _ = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(uid=1000))
        self.assertFalse(ok)


class RootTests(AuthorizationTestBase):
    def test_8_root_with_valid_credentials_allowed(self):
        self._polkit(answer=_Result(False))
        ok, reason = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(pid=1, uid=0))
        self.assertTrue(ok, reason)
        self.assertEqual(self.authority.calls, [], "root does not consult Polkit")

    def test_root_still_needs_valid_pid(self):
        ok, _ = svc_mod._check_polkit(SENDER, ACTION, bus=FakeBus(pid=0, uid=0))
        self.assertFalse(ok)


class NoFallbackSourceTests(unittest.TestCase):
    """The service methods never pass a missing bus through as 'allow'."""

    def test_no_hasattr_fallback_for_bus(self):
        self.assertNotIn('hasattr(self, "_bus")', SERVICE_SRC)

    def test_gated_methods_pass_the_real_bus(self):
        self.assertEqual(SERVICE_SRC.count("bus=self._bus)"), 2)

    def test_no_headless_allow_return_in_check(self):
        start = SERVICE_SRC.index("def _check_polkit(")
        end = SERVICE_SRC.index("class AuraStarterComponent")
        body = SERVICE_SRC[start:end]
        self.assertNotIn("return True, \"\"\n    if sender", body)
        self.assertNotIn("headless", body.lower())
        # Only the root branch and the Polkit consult may grant.
        self.assertEqual(body.count("return True"), 1)


if __name__ == "__main__":
    unittest.main()
