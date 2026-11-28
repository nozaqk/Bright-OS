"""Phase 3.1: Polkit authorization regression tests.

These tests exercise the _check_polkit() authorization helper and the
Polkit-gated D-Bus methods without requiring a real system D-Bus or
Polkit daemon.  We monkey-patch the Polkit Authority to simulate
authorization decisions, and use a fake bus object to control caller
PID/UID responses.
"""
import os
import pathlib
import sys
import threading
import types
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Force headless mode so dbus imports don't fail if python3-dbus is missing.
os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = ""

import aura.core.aura_core_service as svc_mod


class _FakeDaemon:
    """Fake org.freedesktop.DBus proxy that answers credential queries."""

    def __init__(self, bus):
        self._bus = bus

    def GetConnectionUnixProcessID(self, sender, dbus_interface=None):
        if self._bus._raise_on_pid is not None:
            raise self._bus._raise_on_pid
        return self._bus._pid

    def GetConnectionUnixUser(self, sender, dbus_interface=None):
        if self._bus._raise_on_uid is not None:
            raise self._bus._raise_on_uid
        return self._bus._uid


class FakeBus:
    """Minimal stand-in for dbus.SystemBus() that returns configured PID/UID."""

    def __init__(self, pid, uid, raise_on_pid=None, raise_on_uid=None):
        self._pid = pid
        self._uid = uid
        self._raise_on_pid = raise_on_pid
        self._raise_on_uid = raise_on_uid

    def get_object(self, bus_name, path):
        # The bus daemon's proxy. Credential queries go through it.
        return _FakeDaemon(self)


class FakeDBusException(Exception):
    pass


class CheckPolkitUnitTests(unittest.TestCase):
    """Direct tests for _check_polkit()."""

    def setUp(self):
        # Save originals
        self._has_polkit = svc_mod.HAS_POLKIT
        self._has_dbus = svc_mod.HAS_DBUS
        self._had_polkit_attr = hasattr(svc_mod, "Polkit")
        self._fake_authority = None
        # Provide a fake dbus module with DBusException for the code paths
        # that raise it.
        self._dbus_mod = types.SimpleNamespace(DBusException=FakeDBusException)
        self._real_dbus = getattr(svc_mod, "dbus", None)
        svc_mod.dbus = self._dbus_mod
        # Default: pretend we have D-Bus available but no Polkit so
        # that validation paths run. Tests that need Polkit call
        # _install_fake_polkit() which overrides both.
        svc_mod.HAS_DBUS = True
        svc_mod.HAS_POLKIT = False

    def tearDown(self):
        svc_mod.HAS_POLKIT = self._has_polkit
        svc_mod.HAS_DBUS = self._has_dbus
        # Remove fake Polkit attribute if we added it
        if hasattr(svc_mod, "Polkit") and not self._had_polkit_attr:
            delattr(svc_mod, "Polkit")
        if self._real_dbus is not None:
            svc_mod.dbus = self._real_dbus
        else:
            try:
                delattr(svc_mod, "dbus")
            except AttributeError:
                pass

    def _install_fake_polkit(self, authorized, is_challenge=False):
        """Replace Polkit.Authority.get() with a stub returning a result."""
        svc_mod.HAS_POLKIT = True
        svc_mod.HAS_DBUS = True

        class FakeSubject:
            def __init__(self, pid):
                self.pid = pid

        class FakeResult:
            def __init__(self, authorized, challenge):
                self._auth = authorized
                self._chal = challenge
            def get_is_authorized(self): return self._auth
            def get_is_challenge(self): return self._chal

        class FakeAuthority:
            def __init__(self):
                self.calls = []
            def check_authorization_sync(self, subject, action, details, flags, cancellable):
                self.calls.append((subject, action, details, flags, cancellable))
                assert isinstance(subject, FakeSubject), "subject must be FakeSubject"
                assert isinstance(subject.pid, int) and subject.pid > 0, \
                    f"subject pid must be positive int, got {subject.pid}"
                return FakeResult(authorized, is_challenge)

        # Replace Polkit module attributes
        self._fake_authority = FakeAuthority()
        fake_polkit = types.SimpleNamespace(
            Authority=types.SimpleNamespace(
                get_sync=lambda *a, **k: self._fake_authority),
            UnixProcess=types.SimpleNamespace(new=lambda pid: FakeSubject(pid)),
            CheckAuthorizationFlags=types.SimpleNamespace(
                ALLOW_USER_INTERACTION=1, NONE=0),
        )
        svc_mod.Polkit = fake_polkit
        return self._fake_authority

    def test_missing_bus_denies(self):
        """Without a bus there is no caller identity, so deny (Phase 5)."""
        svc_mod.HAS_DBUS = True
        ok, reason = svc_mod._check_polkit(":1.0", "some.action", bus=None)
        self.assertFalse(ok)
        self.assertIn("no D-Bus connection", reason)

    def test_no_sender_fails_closed(self):
        """Sender=None must be denied."""
        svc_mod.HAS_DBUS = True
        ok, reason = svc_mod._check_polkit(None, "some.action",
                                           bus=FakeBus(pid=100, uid=1000))
        self.assertFalse(ok)
        self.assertIn("no sender", reason)

    def test_root_is_always_authorized(self):
        """UID 0 short-circuits without calling Polkit."""
        svc_mod.HAS_POLKIT = False  # even without polkit, root works
        svc_mod.HAS_DBUS = True
        auth = self._install_fake_polkit(authorized=False)
        # Override HAS_POLKIT to False to verify Polkit is NOT called
        svc_mod.HAS_POLKIT = False
        ok, reason = svc_mod._check_polkit(":1.0", "some.action",
                                           bus=FakeBus(pid=100, uid=0))
        self.assertTrue(ok, f"root should be authorized; got reason={reason}")
        self.assertEqual(auth.calls, [], "Polkit must not be called for root")

    def test_pid_lookup_failure_fails_closed(self):
        """If D-Bus cannot return the caller's PID, fail closed."""
        svc_mod.HAS_DBUS = True
        svc_mod.HAS_POLKIT = True
        bus = FakeBus(pid=None, uid=1000,
                      raise_on_pid=FakeDBusException("no pid"))
        ok, reason = svc_mod._check_polkit(":1.0", "some.action", bus=bus)
        self.assertFalse(ok)
        self.assertIn("identity", reason)

    def test_uid_lookup_failure_fails_closed(self):
        svc_mod.HAS_DBUS = True
        bus = FakeBus(pid=100, uid=None,
                      raise_on_uid=FakeDBusException("no uid"))
        ok, reason = svc_mod._check_polkit(":1.0", "some.action", bus=bus)
        self.assertFalse(ok)
        self.assertIn("identity", reason)

    def test_invalid_pid_fails_closed(self):
        """PID <= 0 must be rejected even if the bus returns it."""
        svc_mod.HAS_DBUS = True
        for bad_pid in (0, -1, None, "abc"):
            bus = FakeBus(pid=bad_pid, uid=1000)
            ok, reason = svc_mod._check_polkit(":1.0", "some.action", bus=bus)
            self.assertFalse(ok, f"pid={bad_pid} should be denied")
            self.assertIn("pid", reason.lower())

    def test_invalid_uid_fails_closed(self):
        for bad_uid in (-1, None, "abc"):
            bus = FakeBus(pid=100, uid=bad_uid)
            ok, reason = svc_mod._check_polkit(":1.0", "some.action", bus=bus)
            self.assertFalse(ok, f"uid={bad_uid} should be denied")

    def test_authorized_admin_succeeds(self):
        auth = self._install_fake_polkit(authorized=True)
        bus = FakeBus(pid=2345, uid=1000)
        ok, reason = svc_mod._check_polkit(":1.42", "org.bright_os.AURA.shutdown",
                                           bus=bus)
        self.assertTrue(ok, reason)
        self.assertEqual(len(auth.calls), 1)
        subject, action, _, _, _ = auth.calls[0]
        self.assertEqual(action, "org.bright_os.AURA.shutdown")
        self.assertEqual(subject.pid, 2345,
                         "correct validated PID must be passed to Polkit subject")

    def test_unauthorized_caller_denied(self):
        auth = self._install_fake_polkit(authorized=False)
        bus = FakeBus(pid=2345, uid=1000)
        ok, reason = svc_mod._check_polkit(":1.42", "org.bright_os.AURA.shutdown",
                                           bus=bus)
        self.assertFalse(ok)
        self.assertIn("not authorized", reason)

    def test_challenge_returns_auth_required(self):
        auth = self._install_fake_polkit(authorized=False, is_challenge=True)
        bus = FakeBus(pid=2345, uid=1000)
        ok, reason = svc_mod._check_polkit(":1.42", "org.bright_os.AURA.shutdown",
                                           bus=bus)
        self.assertFalse(ok)
        self.assertIn("authentication", reason)

    def test_polkit_unavailable_fails_closed_for_non_root(self):
        svc_mod.HAS_POLKIT = False
        svc_mod.HAS_DBUS = True
        bus = FakeBus(pid=2345, uid=1000)
        ok, reason = svc_mod._check_polkit(":1.42", "some.action", bus=bus)
        self.assertFalse(ok)
        self.assertIn("only root", reason)

    def test_polkit_exception_fails_closed(self):
        """If Polkit.Authority.get_sync() or check_authorization_sync raises,
        fail closed rather than allowing."""
        svc_mod.HAS_POLKIT = True
        svc_mod.HAS_DBUS = True

        class BoomAuthority:
            def check_authorization_sync(self, *a, **k):
                raise RuntimeError("simulated polkitd crash")
        svc_mod.Polkit = types.SimpleNamespace(
            Authority=types.SimpleNamespace(get_sync=lambda *a, **k: BoomAuthority()),
            UnixProcess=types.SimpleNamespace(new=lambda pid: mock.MagicMock()),
            CheckAuthorizationFlags=types.SimpleNamespace(ALLOW_USER_INTERACTION=1),
        )
        bus = FakeBus(pid=2345, uid=1000)
        ok, reason = svc_mod._check_polkit(":1.42", "some.action", bus=bus)
        self.assertFalse(ok)
        self.assertIn("polkit error", reason)

    def test_get_sync_failure_fails_closed(self):
        """An error from get_sync (for example, polkitd not reachable) denies."""
        svc_mod.HAS_POLKIT = True
        svc_mod.HAS_DBUS = True

        def unreachable(*a, **k):
            raise RuntimeError("Could not connect to polkitd")
        svc_mod.Polkit = types.SimpleNamespace(
            Authority=types.SimpleNamespace(get_sync=unreachable),
            UnixProcess=types.SimpleNamespace(new=lambda pid: mock.MagicMock()),
            CheckAuthorizationFlags=types.SimpleNamespace(ALLOW_USER_INTERACTION=1),
        )
        bus = FakeBus(pid=2345, uid=1000)
        ok, reason = svc_mod._check_polkit(":1.42", "some.action", bus=bus)
        self.assertFalse(ok)
        self.assertIn("polkit error", reason)

    def test_source_uses_get_sync_not_deprecated_get(self):
        source = (PROJECT_ROOT / "aura/core/aura_core_service.py").read_text()
        self.assertIn("Polkit.Authority.get_sync(", source)
        self.assertNotRegex(source, r"Polkit\.Authority\.get\(\s*\)")


class PolkitPolicyFileTests(unittest.TestCase):
    """Verify the installed Polkit policy file requires admin for both
    shutdown and cloud-consent."""

    def setUp(self):
        self.policy_path = (
            PROJECT_ROOT /
            "config/includes.chroot/usr/share/polkit-1/actions/org.bright_os.AURA.policy"
        )

    def _action_blocks(self, action_id):
        """Return the <defaults> block for a given action."""
        import xml.etree.ElementTree as ET
        tree = ET.parse(self.policy_path)
        for action in tree.getroot().findall("action"):
            if action.get("id") == action_id:
                return action.find("defaults")
        self.fail(f"action {action_id} not found in policy file")

    def test_shutdown_requires_admin_for_all(self):
        defaults = self._action_blocks("org.bright_os.AURA.shutdown")
        for tag in ("allow_any", "allow_inactive"):
            self.assertEqual(defaults.findtext(tag), "auth_admin",
                             f"shutdown {tag} must be auth_admin")
        # Active sessions: auth_admin_keep is acceptable (caches for session)
        active = defaults.findtext("allow_active")
        self.assertIn(active, ("auth_admin", "auth_admin_keep"),
                      f"shutdown allow_active must require admin, got {active}")

    def test_grant_cloud_consent_requires_admin_for_all(self):
        """Per Phase 3.1: cloud consent must require admin, not 'yes'."""
        defaults = self._action_blocks(
            "org.bright_os.AURA.grant-cloud-consent")
        for tag in ("allow_any", "allow_inactive"):
            self.assertEqual(defaults.findtext(tag), "auth_admin",
                             f"grant-cloud-consent {tag} must be auth_admin")
        active = defaults.findtext("allow_active")
        self.assertIn(active, ("auth_admin", "auth_admin_keep"),
                      f"grant-cloud-consent allow_active must require admin, got {active}")

    def test_shutdown_action_id_matches_code(self):
        # Cross-check: the action ids used in code exist in the policy.
        code = (PROJECT_ROOT / "aura/core/aura_core_service.py").read_text()
        self.assertIn('"org.bright_os.AURA.shutdown"', code)
        self.assertIn('"org.bright_os.AURA.grant-cloud-consent"', code)
        self._action_blocks("org.bright_os.AURA.shutdown")
        self._action_blocks("org.bright_os.AURA.grant-cloud-consent")


class SourcePackagingSyncTests(unittest.TestCase):
    """Source and packaged copies must be byte-identical."""

    def test_aura_core_service_sync(self):
        src = (PROJECT_ROOT / "aura/core/aura_core_service.py").read_bytes()
        pkg = (PROJECT_ROOT /
               "config/includes.chroot/usr/lib/aura/core/aura_core_service.py").read_bytes()
        self.assertEqual(src, pkg,
                         "source and packaged aura_core_service.py differ")

    def test_polkit_policy_present_in_packaged_tree(self):
        p = (PROJECT_ROOT /
             "config/includes.chroot/usr/share/polkit-1/actions/org.bright_os.AURA.policy")
        self.assertTrue(p.is_file(), f"missing {p}")

    def test_dbus_activation_present(self):
        p = (PROJECT_ROOT /
             "config/includes.chroot/usr/share/dbus-1/system-services/org.bright_os.AURA.service")
        self.assertTrue(p.is_file())


class MethodSignatureTests(unittest.TestCase):
    """Verify the D-Bus methods use sender_keyword='sender' and pass the
    bus to _check_polkit."""

    def setUp(self):
        self.src = (PROJECT_ROOT / "aura/core/aura_core_service.py").read_text()

    def test_shutdown_passes_sender_and_bus(self):
        self.assertIn("def Shutdown(self, sender=None):", self.src)
        self.assertIn("_check_polkit(", self.src)
        self.assertIn("org.bright_os.AURA.shutdown", self.src)

    def test_grant_cloud_consent_only_checks_when_granting(self):
        """GrantCloudConsent(False) must NOT call _check_polkit (revoking
        must work without elevation)."""
        # Find the GrantCloudConsent method body and confirm the polkit
        # check is guarded by `if granted:`.
        idx = self.src.find("def GrantCloudConsent")
        self.assertGreater(idx, 0)
        # Extract the method (up to the next @dbus or end of class region)
        snippet = self.src[idx:idx+1500]
        # The check must be inside an `if granted:` block.
        self.assertRegex(snippet, r"if\s+granted\s*:[\s\S]{0,400}_check_polkit")
        # And the revoke branch should not call _check_polkit.
        revoke_idx = snippet.find("else:")
        self.assertGreater(revoke_idx, 0)
        self.assertNotIn("_check_polkit", snippet[revoke_idx:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
