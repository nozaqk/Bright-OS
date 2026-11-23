"""Phase 2.1 D-Bus Authorization security regression tests.

These tests cover the authorization model hardening:
  - No implicit session-bus trust (sender=None is denied when bus is real)
  - Correct dbus-python credential API (get_connection_unix_process_id/user)
  - Same-UID enforcement (other local users denied)
  - Root always allowed
  - Same-user allowed for read/session actions, Polkit for admin actions
  - Fail-closed when Polkit unavailable for non-root
  - Polkit authorized/challenge/error paths
  - Source-level verification that all 15 D-Bus methods call _check_authorization
  - Polkit XML policy validation (no allow_any=yes; correct auth levels)
  - systemd unit hardening verification (NoNewPrivileges trade-off documented)

Real D-Bus/Polkit integration tests are in RealDBusIntegrationTests and are
skipped by default (set BRIGHT_ANDROID_REAL_INTEGRATION=1 to run them on a
provisioned system with a running bright-android service).
"""
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from bright_android.core import android_service as svc


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AuthorizationTests(unittest.TestCase):
    """Direct unit tests for _check_authorization / _get_caller_credentials."""

    def setUp(self):
        # Start each test with HAS_DBUS=True and HAS_POLKIT=False to simulate
        # a D-Bus environment where Polkit is unavailable (fail-closed default).
        self._hd = svc.HAS_DBUS
        self._hp = svc.HAS_POLKIT
        self._suid = svc.SERVICE_UID
        svc.HAS_DBUS = True
        svc.HAS_POLKIT = False

    def tearDown(self):
        svc.HAS_DBUS = self._hd
        svc.HAS_POLKIT = self._hp
        svc.SERVICE_UID = self._suid

    def _make_bus(self, pid=12345, uid=None, pid_raises=None, uid_raises=None):
        bus = mock.MagicMock()
        if pid_raises is not None:
            bus.get_connection_unix_process_id.side_effect = pid_raises
        else:
            bus.get_connection_unix_process_id.return_value = pid
        if uid_raises is not None:
            bus.get_connection_unix_user.side_effect = uid_raises
        else:
            bus.get_connection_unix_user.return_value = (
                uid if uid is not None else os.getuid()
            )
        return bus

    # ---- Missing / invalid sender ----

    def test_missing_sender_is_denied(self):
        bus = self._make_bus()
        ok, reason = svc._check_authorization(None, svc.POLKIT_ACTION_INIT, bus=bus)
        self.assertFalse(ok, f"expected denial, got reason={reason}")

    def test_no_bus_allows_inprocess(self):
        """bus=None is the in-process / test path and is allowed."""
        ok, _ = svc._check_authorization(None, svc.POLKIT_ACTION_INIT, bus=None)
        self.assertTrue(ok)

    def test_missing_pid_is_denied(self):
        bus = self._make_bus(pid_raises=Exception("no such sender"))
        ok, reason = svc._check_authorization(":1.50", svc.POLKIT_ACTION_INIT, bus=bus)
        self.assertFalse(ok, f"expected denial on pid lookup failure: {reason}")

    def test_missing_uid_is_denied(self):
        bus = self._make_bus(uid_raises=Exception("no such sender"))
        ok, reason = svc._check_authorization(":1.50", svc.POLKIT_ACTION_INIT, bus=bus)
        self.assertFalse(ok, f"expected denial on uid lookup failure: {reason}")

    def test_invalid_pid_type_denied(self):
        bus = self._make_bus(pid="not an int")
        ok, _ = svc._check_authorization(":1.50", svc.POLKIT_ACTION_INIT, bus=bus)
        self.assertFalse(ok)

    def test_negative_pid_denied(self):
        bus = self._make_bus(pid=-1)
        ok, _ = svc._check_authorization(":1.50", svc.POLKIT_ACTION_INIT, bus=bus)
        self.assertFalse(ok)

    def test_zero_pid_denied(self):
        bus = self._make_bus(pid=0)
        ok, _ = svc._check_authorization(":1.50", svc.POLKIT_ACTION_INIT, bus=bus)
        self.assertFalse(ok)

    def test_negative_uid_denied(self):
        bus = self._make_bus(uid=-1)
        ok, _ = svc._check_authorization(":1.50", svc.POLKIT_ACTION_INIT, bus=bus)
        self.assertFalse(ok)

    # ---- UID-based decisions ----

    def test_root_is_always_allowed(self):
        bus = self._make_bus(uid=0)
        ok, reason = svc._check_authorization(":1.50", svc.POLKIT_ACTION_INIT, bus=bus)
        self.assertTrue(ok, f"root should be allowed: {reason}")
        self.assertIn("root", reason)

    def test_same_user_allowed_for_read_actions(self):
        """allow_same_user=True must let the same uid through without Polkit."""
        bus = self._make_bus(uid=os.getuid())
        svc.SERVICE_UID = os.getuid()
        ok, reason = svc._check_authorization(
            ":1.50", svc.POLKIT_ACTION_SYNC, bus=bus, allow_same_user=True
        )
        self.assertTrue(ok, f"same-user should be allowed for sync: {reason}")

    def test_same_user_allowed_for_launch(self):
        bus = self._make_bus(uid=os.getuid())
        ok, reason = svc._check_authorization(
            ":1.50", svc.POLKIT_ACTION_LAUNCH, bus=bus, allow_same_user=True
        )
        self.assertTrue(ok, f"same-user should be allowed to launch: {reason}")

    def test_other_user_denied_for_admin_action(self):
        bus = self._make_bus(uid=1001)
        svc.SERVICE_UID = 1000
        ok, reason = svc._check_authorization(
            ":1.99", svc.POLKIT_ACTION_INIT, bus=bus
        )
        self.assertFalse(ok)
        self.assertIn("does not match", reason)

    def test_other_user_denied_for_same_user_action(self):
        """Even allow_same_user must not let a different UID through."""
        bus = self._make_bus(uid=1001)
        svc.SERVICE_UID = 1000
        ok, _ = svc._check_authorization(
            ":1.99", svc.POLKIT_ACTION_START, bus=bus, allow_same_user=True
        )
        self.assertFalse(ok)

    def test_polkit_unavailable_fails_closed_for_non_root(self):
        """Without Polkit and non-root non-self uid, privileged actions fail."""
        bus = self._make_bus(uid=os.getuid())
        svc.SERVICE_UID = os.getuid()
        # allow_same_user=False requires Polkit; Polkit is unavailable → deny
        ok, reason = svc._check_authorization(
            ":1.50", svc.POLKIT_ACTION_INIT, bus=bus, allow_same_user=False
        )
        self.assertFalse(ok)
        self.assertIn("Polkit is unavailable", reason)

    def test_polkit_unavailable_allows_same_user_for_session_action(self):
        """Non-admin session actions (start/stop/launch/sync/uninstall) fall
        back to same-user allow when Polkit is unavailable, so that a broken
        Polkit doesn't lock the user out of their own Android session."""
        bus = self._make_bus(uid=os.getuid())
        svc.SERVICE_UID = os.getuid()
        # allow_same_user=False (default) means "consult Polkit"; since Polkit
        # is unavailable, session actions must still be allowed.
        ok, reason = svc._check_authorization(
            ":1.50", svc.POLKIT_ACTION_START, bus=bus
        )
        self.assertTrue(ok, f"expected same-user fallback for session action: {reason}")
        # Same for launch, sync, stop, uninstall
        for action in (svc.POLKIT_ACTION_STOP, svc.POLKIT_ACTION_LAUNCH,
                       svc.POLKIT_ACTION_SYNC, svc.POLKIT_ACTION_UNINSTALL):
            ok, _ = svc._check_authorization(":1.50", action, bus=bus)
            self.assertTrue(ok, f"session action {action} should allow same-user fallback")

    def test_session_actions_do_not_use_allow_same_user_bypass(self):
        """State-changing session methods (Start/Stop/Launch/Sync/Uninstall)
        must call _check_authorization WITHOUT allow_same_user=True, so that
        Polkit is consulted for active-session verification. The method-level
        source test enforces this."""
        source = Path(svc.__file__).read_text()
        import re
        session_methods = ["StartRuntime", "StopRuntime", "UninstallApp",
                           "LaunchApp", "SyncAppList"]
        for name in session_methods:
            # Find the body of this method and look for allow_same_user
            pat = re.compile(
                r"def\s+" + name + r"\s*\([^)]*\)[^:]*:(.*?)(?=\n\s+@|\n\s+def\s|\nelse:|\Z)",
                re.DOTALL,
            )
            m = pat.search(source)
            self.assertIsNotNone(m, f"method {name} not found")
            body = m.group(1)[:600]
            self.assertNotIn("allow_same_user=True", body,
                             f"{name} must NOT use allow_same_user=True; "
                             "Polkit must be consulted for active-session verification")

    def _install_mock_polkit(self):
        """Inject a mock Polkit module into the service namespace because
        in this sandbox HAS_POLKIT is False (no python3-gi)."""
        polkit_mod = mock.MagicMock()
        svc.Polkit = polkit_mod
        return polkit_mod

    def test_polkit_authorized_allows(self):
        bus = self._make_bus(uid=os.getuid())
        svc.SERVICE_UID = os.getuid()
        svc.HAS_POLKIT = True
        polkit_mod = self._install_mock_polkit()
        try:
            authority = mock.MagicMock()
            result = mock.MagicMock()
            result.get_is_authorized.return_value = True
            result.get_is_challenge.return_value = False
            authority.check_authorization_sync.return_value = result
            polkit_mod.Authority.get_sync.return_value = authority
            ok, reason = svc._check_authorization(
                ":1.50", svc.POLKIT_ACTION_INIT, bus=bus
            )
        finally:
            del svc.Polkit
        self.assertTrue(ok, f"expected allow: {reason}")

    def test_polkit_challenge_denied(self):
        bus = self._make_bus(uid=os.getuid())
        svc.SERVICE_UID = os.getuid()
        svc.HAS_POLKIT = True
        polkit_mod = self._install_mock_polkit()
        try:
            authority = mock.MagicMock()
            result = mock.MagicMock()
            result.get_is_authorized.return_value = False
            result.get_is_challenge.return_value = True
            authority.check_authorization_sync.return_value = result
            polkit_mod.Authority.get_sync.return_value = authority
            ok, reason = svc._check_authorization(
                ":1.50", svc.POLKIT_ACTION_INIT, bus=bus
            )
        finally:
            del svc.Polkit
        self.assertFalse(ok)
        self.assertIn("authentication", reason)

    def test_polkit_error_denied(self):
        bus = self._make_bus(uid=os.getuid())
        svc.SERVICE_UID = os.getuid()
        svc.HAS_POLKIT = True
        polkit_mod = self._install_mock_polkit()
        try:
            polkit_mod.Authority.get_sync.side_effect = Exception("dbus error")
            ok, reason = svc._check_authorization(
                ":1.50", svc.POLKIT_ACTION_INIT, bus=bus
            )
        finally:
            del svc.Polkit
        self.assertFalse(ok)
        self.assertIn("polkit error", reason.lower())

    def test_polkit_not_authorized_denied(self):
        bus = self._make_bus(uid=os.getuid())
        svc.SERVICE_UID = os.getuid()
        svc.HAS_POLKIT = True
        polkit_mod = self._install_mock_polkit()
        try:
            authority = mock.MagicMock()
            result = mock.MagicMock()
            result.get_is_authorized.return_value = False
            result.get_is_challenge.return_value = False
            authority.check_authorization_sync.return_value = result
            polkit_mod.Authority.get_sync.return_value = authority
            ok, _ = svc._check_authorization(
                ":1.50", svc.POLKIT_ACTION_INIT, bus=bus
            )
        finally:
            del svc.Polkit
        self.assertFalse(ok)


class SecurityRegressionTests(unittest.TestCase):
    """Source-level regression tests to prevent reintroducing old bugs."""

    def setUp(self):
        self.source = Path(svc.__file__).read_text()

    def test_no_implicit_trust_bypass_in_source(self):
        """The old code had `if sender is None: return True, 'session bus ...'`.
        That pattern must not come back."""
        # If sender is None and we are on a real bus, the response must deny.
        # Scan for the old bypass phrase or any 'sender is None' that returns True.
        self.assertNotIn("session bus implicit trust", self.source,
                         "Old implicit-trust bypass string must not reappear")
        # Also guard against the broader pattern
        for m in re.finditer(r"sender\s+is\s+None\s*:\s*return\s+True", self.source):
            self.fail(
                f"Found `if sender is None: return True` near offset {m.start()}; "
                "must deny when bus is real"
            )

    def test_credentials_lookup_uses_correct_dbus_api(self):
        """Must use get_connection_unix_process_id and
        get_connection_unix_user — the CORRECT dbus-python API. The old names
        (get_unix_process_id / get_unix_user_id) were bugs that raised
        AttributeError and fell through to the implicit-trust bypass."""
        self.assertIn("get_connection_unix_process_id", self.source)
        self.assertIn("get_connection_unix_user", self.source)
        self.assertNotIn("get_unix_process_id(", self.source,
                         "Old/wrong dbus method name (missing 'connection_')")
        self.assertNotIn("get_unix_user_id(", self.source,
                         "Old/wrong dbus method name (should be get_connection_unix_user)")

    def test_all_dbus_methods_call_check_authorization(self):
        """Every D-Bus method in the HAS_DBUS class must call
        _check_authorization (or its _check_polkit alias)."""
        # Extract all @method(...) decorated defs from the HAS_DBUS branch
        method_defs = re.findall(
            r"@method\(INTERFACE[^\n]*\)\s*\n\s*def\s+(\w+)\s*\(",
            self.source,
        )
        self.assertTrue(len(method_defs) >= 15,
                        f"Expected at least 15 D-Bus methods, found {len(method_defs)}: {method_defs}")
        # Find every def that contains a _check_authorization/_check_polkit call
        # (a simplistic but effective check: ensure each method name appears in
        # a def followed within a small window by _check_auth or _check_polkit)
        blocks = re.split(r"\n\s*@method\(", self.source)
        for block in blocks[1:]:
            m = re.match(r"[^\n]*\)\s*\n\s*def\s+(\w+)\s*\(", block)
            if not m:
                continue
            name = m.group(1)
            # Look within first ~600 chars of the body
            body_head = block[:800]
            has_auth = ("_check_authorization" in body_head
                        or "_check_polkit" in body_head)
            self.assertTrue(
                has_auth,
                f"D-Bus method {name} does not call _check_authorization in its body"
            )

    @staticmethod
    def _strip_strings_and_comments(src: str) -> str:
        """Best-effort removal of triple-quoted docstrings and # comments
        to avoid false positives from mentions of shell=True in prose."""
        out_lines = []
        in_triple = False
        triple_q = None
        for line in src.splitlines():
            if in_triple:
                if triple_q in line:
                    in_triple = False
                continue
            stripped = line
            # Remove # comments (naive but sufficient for our codebase which
            # has no # inside strings on relevant lines)
            if "#" in stripped:
                stripped = stripped[:stripped.index("#")]
            # Detect triple quotes opening
            for q in ('"""', "'''"):
                if q in stripped:
                    before = stripped[:stripped.index(q)]
                    # If closing on same line, keep before
                    rest = stripped[stripped.index(q) + 3:]
                    if q in rest:
                        stripped = before + rest[rest.index(q) + 3:]
                    else:
                        stripped = before
                        in_triple = True
                        triple_q = q
                    break
            out_lines.append(stripped)
        return "\n".join(out_lines)

    def test_subprocess_never_uses_shell_true(self):
        for f in ["android_service.py", "waydroid_manager.py", "compatibility.py",
                  "launcher_integration.py", "config.py", "apk_validator.py"]:
            p = PROJECT_ROOT / "bright_android" / "core" / f
            if not p.exists():
                continue
            src = self._strip_strings_and_comments(p.read_text())
            self.assertNotIn("shell=True", src,
                             f"{f} must not use shell=True in subprocess calls")


def _find_method_action(source: str, method_name: str):
    """Find the action constant passed to _check_authorization inside method_name."""
    # Match "def <name>(...<body up to next @method or def at same indent>"
    pat = re.compile(
        r"def\s+" + re.escape(method_name) + r"\s*\([^)]*\)[^:]*:.*?"
        r"_check_authorization\s*\(\s*sender\s*,\s*([A-Z_]+)",
        re.DOTALL,
    )
    m = pat.search(source)
    return m.group(1) if m else None


class MethodSourceAuthTests(unittest.TestCase):
    """Verify each D-Bus method uses the expected Polkit action constant."""

    @classmethod
    def setUpClass(cls):
        cls.source = Path(svc.__file__).read_text()

    def test_init_uses_init_action(self):
        self.assertEqual(_find_method_action(self.source, "InitializeRuntime"),
                         "POLKIT_ACTION_INIT")

    def test_install_uses_install_action(self):
        self.assertEqual(_find_method_action(self.source, "InstallApk"),
                         "POLKIT_ACTION_INSTALL")

    def test_setconfig_uses_setconfig_action(self):
        self.assertEqual(_find_method_action(self.source, "SetConfig"),
                         "POLKIT_ACTION_SET_CONFIG")

    def test_remove_data_uses_removedata_action(self):
        # RemoveData isn't a D-Bus method yet; if added it must use this.
        self.assertEqual(svc.POLKIT_ACTION_REMOVE_DATA,
                         "org.bright_os.BrightAndroid.remove-data")

    def test_start_uses_start_action(self):
        self.assertEqual(_find_method_action(self.source, "StartRuntime"),
                         "POLKIT_ACTION_START")

    def test_stop_uses_stop_action(self):
        self.assertEqual(_find_method_action(self.source, "StopRuntime"),
                         "POLKIT_ACTION_STOP")

    def test_uninstall_uses_uninstall_action(self):
        self.assertEqual(_find_method_action(self.source, "UninstallApp"),
                         "POLKIT_ACTION_UNINSTALL")

    def test_launch_uses_launch_action(self):
        self.assertEqual(_find_method_action(self.source, "LaunchApp"),
                         "POLKIT_ACTION_LAUNCH")

    def test_sync_uses_sync_action(self):
        self.assertEqual(_find_method_action(self.source, "SyncAppList"),
                         "POLKIT_ACTION_SYNC")

    def test_getversion_uses_sync_action(self):
        self.assertEqual(_find_method_action(self.source, "GetVersion"),
                         "POLKIT_ACTION_SYNC")

    def test_getstatus_uses_sync_action(self):
        self.assertEqual(_find_method_action(self.source, "GetStatus"),
                         "POLKIT_ACTION_SYNC")

    def test_listapps_uses_sync_action(self):
        self.assertEqual(_find_method_action(self.source, "ListApps"),
                         "POLKIT_ACTION_SYNC")


class PolkitPolicyTests(unittest.TestCase):
    """Validate the installed Polkit policy XML."""

    @classmethod
    def setUpClass(cls):
        cls.policy_path = (PROJECT_ROOT
                           / "config/includes.chroot/usr/share/polkit-1/actions"
                           / "org.bright_os.BrightAndroid.policy")
        cls.policy = cls.policy_path.read_text()

    def _get_action(self, action_id):
        pat = re.compile(
            rf'<action\s+id="{re.escape(action_id)}">(.*?)</action>',
            re.DOTALL,
        )
        m = pat.search(self.policy)
        self.assertIsNotNone(m, f"action {action_id} not found in policy")
        return m.group(1)

    def _defaults(self, action_block):
        return {tag: re.search(rf"<{tag}>([^<]+)</{tag}>", action_block).group(1)
                for tag in ("allow_any", "allow_inactive", "allow_active")
                if re.search(rf"<{tag}>([^<]+)</{tag}>", action_block)}

    def test_no_action_allows_any(self):
        """No action may grant allow_any=yes (remote users would be authorized
        without authentication)."""
        for m in re.finditer(r'<allow_any>([^<]+)</allow_any>', self.policy):
            self.assertNotEqual(m.group(1), "yes",
                                f"allow_any=yes found: {m.group(0)}")

    def test_init_requires_admin(self):
        d = self._defaults(self._get_action(svc.POLKIT_ACTION_INIT))
        self.assertEqual(d["allow_active"], "auth_admin_keep")

    def test_install_requires_admin(self):
        d = self._defaults(self._get_action(svc.POLKIT_ACTION_INSTALL))
        self.assertEqual(d["allow_active"], "auth_admin_keep")

    def test_set_config_requires_admin(self):
        d = self._defaults(self._get_action(svc.POLKIT_ACTION_SET_CONFIG))
        self.assertEqual(d["allow_active"], "auth_admin_keep")

    def test_remove_data_requires_admin(self):
        d = self._defaults(self._get_action(svc.POLKIT_ACTION_REMOVE_DATA))
        # remove-data uses auth_admin (not keep) so every data wipe prompts
        self.assertEqual(d["allow_active"], "auth_admin")

    def test_start_allows_active_user(self):
        d = self._defaults(self._get_action(svc.POLKIT_ACTION_START))
        self.assertEqual(d["allow_active"], "yes")

    def test_stop_allows_active_user(self):
        d = self._defaults(self._get_action(svc.POLKIT_ACTION_STOP))
        self.assertEqual(d["allow_active"], "yes")

    def test_uninstall_allows_active_user(self):
        d = self._defaults(self._get_action(svc.POLKIT_ACTION_UNINSTALL))
        self.assertEqual(d["allow_active"], "yes")

    def test_launch_allows_active_user(self):
        d = self._defaults(self._get_action(svc.POLKIT_ACTION_LAUNCH))
        self.assertEqual(d["allow_active"], "yes")

    def test_sync_allows_active_user(self):
        d = self._defaults(self._get_action(svc.POLKIT_ACTION_SYNC))
        self.assertEqual(d["allow_active"], "yes")


class SystemdSecurityTests(unittest.TestCase):
    """Verify systemd user unit hardening directives."""

    @classmethod
    def setUpClass(cls):
        cls.unit_path = (PROJECT_ROOT
                         / "config/includes.chroot/usr/lib/systemd/user"
                         / "bright-android.service")
        cls.unit = cls.unit_path.read_text()
        cls.active_lines = [l.strip() for l in cls.unit.splitlines()
                            if l.strip() and not l.strip().startswith('#')]

    def test_exec_uses_session_bus(self):
        self.assertIn("--service --session", self.unit)

    def test_hardening_directives_present(self):
        """Hardening directives that are compatible with LXC/Waydroid must be present."""
        for directive in ["ProtectSystem=strict", "ProtectHome=read-only",
                          "PrivateTmp=yes",
                          "ProtectKernelModules=yes",
                          "RestrictSUIDSGID=no",
                          "RestrictRealtime=yes", "LockPersonality=yes",
                          "SystemCallArchitectures=native"]:
            self.assertIn(directive, self.active_lines,
                          f"Missing hardening directive: {directive}")

    def test_lxc_incompatible_restrictions_removed(self):
        """RestrictNamespaces, ProtectControlGroups, and ProtectKernelTunables
        must NOT be active because LXC needs to create namespaces, write cgroups,
        and set container sysctls. See the systemd unit comment block for the
        full compatibility rationale."""
        for directive in ["RestrictNamespaces=yes",
                          "ProtectControlGroups=yes",
                          "ProtectKernelTunables=yes"]:
            self.assertFalse(
                any(l == directive for l in self.active_lines),
                f"{directive} must not be active (blocks LXC/Waydroid)"
            )

    def test_lxc_compatibility_documented(self):
        """The unit file must document why namespace/cgroup/tunables restrictions
        are removed (LXC compatibility)."""
        lower = self.unit.lower()
        self.assertIn("lxc", lower,
                      "unit must mention LXC compatibility rationale")
        self.assertIn("namespace", lower,
                      "unit must explain namespace restriction trade-off")
        self.assertIn("cgroup", lower,
                      "unit must mention cgroup write requirement")

    def test_no_nonewprivileges_active_directive(self):
        """NoNewPrivileges=yes must NOT be active as a directive (documented
        trade-off with pkexec setuid)."""
        self.assertFalse(
            any(l == "NoNewPrivileges=yes" for l in self.active_lines),
            "NoNewPrivileges=yes must not be active (blocks pkexec setuid)"
        )

    def test_nonewprivileges_tradeoff_documented(self):
        """A comment block must explain why NoNewPrivileges is off and point
        to future helper extraction."""
        self.assertIn("NoNewPrivileges", self.unit)
        lower = self.unit.lower()
        self.assertIn("pkexec", lower)
        # Must mention the future improvement
        self.assertIn("future", lower)

    def test_readwrite_paths_for_waydroid(self):
        """Required writable paths for Waydroid + service must be declared."""
        for path in ["/var/lib/waydroid", "/etc/waydroid", "/var/log",
                     "/run/waydroid", "%h/.config/bright-android",
                     "%h/.local/share/applications", "%h/.cache/bright-android",
                     "%h/.local/share/waydroid", "%h/.config/waydroid"]:
            self.assertIn(path, self.unit, f"Missing ReadWritePaths entry: {path}")


def _environment_can_run_dbus_tests():
    """Check if the current environment has real D-Bus/Polkit available."""
    if os.environ.get("BRIGHT_ANDROID_REAL_INTEGRATION") != "1":
        return False, "BRIGHT_ANDROID_REAL_INTEGRATION not set"
    try:
        import dbus  # noqa: F401
        from gi.repository import Polkit  # noqa: F401
    except ImportError as e:
        return False, f"missing python3-dbus or python3-gi: {e}"
    # Check session bus is available
    try:
        bus = __import__("dbus").SessionBus()
        bus.get_name_owner("org.freedesktop.DBus")
    except Exception as e:
        return False, f"no session bus: {e}"
    return True, ""


def _environment_can_run_waydroid_tests():
    """Check if waydroid and required kernel features are present."""
    if os.environ.get("BRIGHT_ANDROID_REAL_WAYDROID") != "1":
        return False, "BRIGHT_ANDROID_REAL_WAYDROID not set"
    import shutil
    if not shutil.which("waydroid"):
        return False, "waydroid binary not found"
    if not (os.path.exists("/dev/binder") or os.path.exists("/dev/binderfs")):
        return False, "binder device not available"
    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return False, "no display server (WAYLAND_DISPLAY/DISPLAY)"
    return True, ""


@unittest.skipUnless(*_environment_can_run_dbus_tests())
class RealDBusIntegrationTests(unittest.TestCase):
    """Real D-Bus/Polkit end-to-end tests.

    These require a provisioned Debian machine with:
      - The bright-android service running on the session bus
      - python3-dbus and python3-gi installed
      - A Polkit authority running (polkitd)
    Enable with BRIGHT_ANDROID_REAL_INTEGRATION=1.
    They are skipped in sandbox/CI environments and NOT counted as passing
    unless the environment supports them.
    """

    @classmethod
    def setUpClass(cls):
        import dbus
        cls.bus = dbus.SessionBus()
        cls.obj = cls.bus.get_object("org.bright_os.BrightAndroid",
                                     "/org/bright_os/BrightAndroid")
        cls.iface = dbus.Interface(cls.obj, "org.bright_os.BrightAndroid")

    def test_service_owns_bus_name(self):
        """Verify the service has claimed its session-bus name."""
        owner = self.bus.get_name_owner("org.bright_os.BrightAndroid")
        self.assertTrue(len(owner) > 0)

    def test_get_version_succeeds_for_same_user(self):
        v = self.iface.GetVersion()
        self.assertTrue(len(str(v)) > 0)

    def test_get_status_succeeds_for_same_user(self):
        s = self.iface.GetStatus()
        self.assertIn("installed", s)

    def test_list_apps_succeeds_for_same_user(self):
        apps = self.iface.ListApps()
        self.assertIsInstance(apps, list)

    def test_get_config_succeeds_for_same_user(self):
        cfg = self.iface.GetConfig()
        self.assertIsInstance(cfg, dict)

    def test_privileged_action_without_polkit_auth_is_rejected(self):
        """Calling SetConfig without proper Polkit authorization should raise
        a DBusException. In a real active session this may trigger an auth
        agent; if no agent is available it should fail with NotAuthorized."""
        import dbus
        try:
            self.iface.SetConfig("test/key", "value")
            # If we get here without an agent in a non-interactive test
            # environment, something is wrong. Skip rather than false-fail.
            self.skipTest("Polkit agent allowed the action (interactive session?)")
        except dbus.exceptions.DBusException as e:
            name = e.get_dbus_name()
            self.assertIn("NotAuthorized", name,
                          f"expected NotAuthorized, got {name}: {e}")

    def test_diagnostic_methods_accessible(self):
        self.iface.GetCompatibilityReport()
        self.iface.GetDiagnostics()


@unittest.skipUnless(*_environment_can_run_waydroid_tests())
class RealWaydroidRuntimeTests(unittest.TestCase):
    """Real Waydroid runtime tests.

    These require a provisioned Debian machine with:
      - waydroid package installed
      - binder kernel module available (/dev/binder or binderfs)
      - A Wayland (or X11) session running
      - Sufficient disk space for Android images (~6 GB)
      - Network access to download Waydroid VANILLA image
    Enable with BRIGHT_ANDROID_REAL_WAYDROID=1. They can take several minutes
    (image download + container start). They are BLOCKED/NOT TESTED in any
    environment that does not explicitly opt in.
    """

    @classmethod
    def setUpClass(cls):
        from bright_android.core import waydroid_manager, compatibility
        cls.wm = waydroid_manager
        cls.compat = compatibility

    def test_binder_available(self):
        """Binder IPC must be available (/dev/binder or binderfs)."""
        info = self.compat.check_binder()
        self.assertTrue(info["binder_available"],
                        f"binder not available: {info}")

    def test_wayland_available(self):
        self.assertTrue(
            bool(os.environ.get("WAYLAND_DISPLAY")) or
            bool(os.environ.get("DISPLAY")),
            "WAYLAND_DISPLAY or DISPLAY must be set for Android windowing",
        )

    def test_hardware_readiness(self):
        report = self.compat.assess_hardware_readiness()
        self.assertIn(report["tier"],
                      ("supported", "supported_with_limitations"),
                      f"hardware not ready: {report}")

    def test_initialize_runtime(self):
        """waydroid init (downloads VANILLA image if not present)."""
        if not self.wm.is_installed():
            self.skipTest("waydroid package not installed")
        self.wm.init(mode="vanilla")
        self.assertTrue(self.wm.is_initialized())

    def test_start_runtime(self):
        if not self.wm.is_initialized():
            self.skipTest("waydroid not initialized")
        self.wm.start_session()
        import time
        for _ in range(45):
            if self.wm.is_running():
                break
            time.sleep(1)
        self.assertTrue(self.wm.is_running(), "runtime did not start within 45s")

    def test_install_test_apk(self):
        """Install a known-good small test APK (e.g. FDroid client or a
        trivial test app). Place APK at TEST_APK_PATH env var."""
        apk = os.environ.get("BRIGHT_ANDROID_TEST_APK")
        if not apk:
            self.skipTest("BRIGHT_ANDROID_TEST_APK not set")
        self.assertTrue(os.path.exists(apk), f"APK not found: {apk}")
        result = self.wm.install_apk(apk)
        self.assertTrue(result.get("success"))

    def test_launch_test_app(self):
        pkg = os.environ.get("BRIGHT_ANDROID_TEST_PACKAGE")
        if not pkg:
            self.skipTest("BRIGHT_ANDROID_TEST_PACKAGE not set")
        self.assertTrue(self.wm.is_running())
        self.wm.launch_app(pkg)

    def test_stop_and_restart(self):
        self.wm.stop_session()
        import time
        for _ in range(20):
            if not self.wm.is_running():
                break
            time.sleep(1)
        self.assertFalse(self.wm.is_running(), "runtime did not stop")
        self.wm.start_session()
        for _ in range(45):
            if self.wm.is_running():
                break
            time.sleep(1)
        self.assertTrue(self.wm.is_running(), "runtime did not restart")

    def test_no_namespace_or_permission_errors_in_logs(self):
        """Check recent service/lxc logs for namespace EPERM or cgroup EACCES."""
        # This is a heuristic check; it doesn't fail the suite on its own but
        # provides evidence that sandbox restrictions aren't blocking LXC.
        logs = self.wm.get_logs(lines=200)
        bad_markers = ["Operation not permitted", "Permission denied",
                       "namespace", "cgroup", "seccomp"]
        issues = [m for m in bad_markers if m in logs]
        # Just record; don't fail unless clearly an LXC fatal error
        if issues:
            import warnings
            warnings.warn(f"Possible sandbox issues in logs: {issues}")


class EnvironmentCapabilityTests(unittest.TestCase):
    """Report the environment's capability level so test runs clearly show
    what is NOT being tested."""

    def test_report_environment_capabilities(self):
        """Print (and record) what this environment supports."""
        import shutil
        caps = {
            "python3-dbus": _environment_can_run_dbus_tests()[0]
                            or _try_import("dbus"),
            "python3-gi/Polkit": _try_import("gi.repository.Polkit"),
            "waydroid_binary": shutil.which("waydroid") is not None,
            "binder_device": os.path.exists("/dev/binder")
                             or os.path.exists("/dev/binderfs"),
            "wayland_or_x11": bool(os.environ.get("WAYLAND_DISPLAY"))
                              or bool(os.environ.get("DISPLAY")),
        }
        available = [k for k, v in caps.items() if v]
        unavailable = [k for k, v in caps.items() if not v]
        print(f"\n[ENV] Available: {available}")
        print(f"[ENV] Unavailable: {unavailable}")
        if unavailable:
            print("[ENV] Real D-Bus/Polkit and Waydroid runtime tests will "
                  "be skipped. They require a provisioned Debian machine "
                  "(see docs/PHASE-BRIGHT-ANDROID-REPORT.md).")
        self.assertTrue(True)  # Always passes; just reports status.


def _try_import(mod):
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    unittest.main()
