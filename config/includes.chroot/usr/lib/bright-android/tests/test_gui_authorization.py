"""GUI authorization tests (static).

gui.py needs PyQt6 and cannot be imported in the test environment, so these
tests parse its AST. They check that the GUI cannot change runtime state,
apps, or settings except through the service client, which sends each
request to the service's authorization and validation. Runtime GUI tests
need a host with PyQt6 and python3-dbus.
"""

import ast
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

GUI_PATH = PROJECT_ROOT / "bright_android" / "gui.py"
CLIENT_PATH = PROJECT_ROOT / "bright_android" / "core" / "service_client.py"

# Read-only waydroid_manager functions the GUI may call directly.
READ_ONLY_WAYDROID = frozenset({"is_running", "get_status", "list_apps", "get_logs", "is_installed"})

# State-changing waydroid_manager functions. The GUI must never call these.
STATE_CHANGING_WAYDROID = frozenset({
    "init", "start_session", "stop_session", "install_apk", "uninstall_app",
    "launch_app", "remove_data", "uninstall_runtime", "set_config",
})

# Read-only config accessors. Any setter is a direct write and is forbidden.
READ_ONLY_CONFIG = frozenset({"get_bool", "get_value", "get_int"})

# Client methods the GUI must use for state changes.
CLIENT_METHODS_USED = frozenset({
    "start_runtime", "stop_runtime", "initialize_runtime", "install_apk",
    "launch_app", "uninstall_app", "set_config",
})


def _gui_tree():
    return ast.parse(GUI_PATH.read_text(), filename=str(GUI_PATH))


def _attribute_names(tree, base):
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == base):
            names.add(node.attr)
    return names


class WaydroidBypassTests(unittest.TestCase):
    """The GUI reaches waydroid_manager only through read-only functions."""

    @classmethod
    def setUpClass(cls):
        cls.tree = _gui_tree()
        cls.used = _attribute_names(cls.tree, "waydroid_manager")

    def test_gui_uses_waydroid_manager_only_read_only(self):
        self.assertTrue(self.used, "expected read-only status calls in gui.py")
        self.assertTrue(self.used <= READ_ONLY_WAYDROID,
                        f"non read-only waydroid_manager use: {sorted(self.used - READ_ONLY_WAYDROID)}")

    def test_no_state_changing_waydroid_attribute_access(self):
        self.assertEqual(self.used & STATE_CHANGING_WAYDROID, set())

    def test_no_state_changing_waydroid_imports(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("waydroid_manager"):
                for alias in node.names:
                    self.assertNotIn(alias.name, STATE_CHANGING_WAYDROID, alias.name)
                    self.assertIn(alias.name, READ_ONLY_WAYDROID, alias.name)

    def test_no_bare_state_changing_names(self):
        # Catch aliasing such as `wm = waydroid_manager` and then `wm.init()`.
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) \
                    and node.value.id == "waydroid_manager":
                self.fail("waydroid_manager must not be aliased in gui.py")


class ConfigWriteTests(unittest.TestCase):
    """The GUI may read settings but must not write them directly."""

    @classmethod
    def setUpClass(cls):
        cls.used = _attribute_names(_gui_tree(), "ba_config")

    def test_only_read_accessors_are_used(self):
        self.assertTrue(self.used <= READ_ONLY_CONFIG,
                        f"direct config writes in gui.py: {sorted(self.used - READ_ONLY_CONFIG)}")

    def test_no_setter_names(self):
        for name in self.used:
            self.assertFalse(name.startswith("set_"), name)


class PrivilegeTests(unittest.TestCase):
    """The GUI does not run commands itself."""

    @classmethod
    def setUpClass(cls):
        cls.tree = _gui_tree()

    def test_no_subprocess_or_shell_import(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], {"subprocess", "shlex"})
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], {"subprocess", "shlex"})

    def test_no_process_execution_calls(self):
        forbidden = {"Popen", "system", "run", "call", "check_call", "check_output", "execv", "execvp"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, forbidden, node.func.attr)


class ClientRoutingTests(unittest.TestCase):
    """State-changing operations go through the service client."""

    @classmethod
    def setUpClass(cls):
        cls.tree = _gui_tree()

    def test_client_is_imported_from_service_client(self):
        found = False
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module \
                    and node.module.endswith("service_client"):
                found = True
        self.assertTrue(found)

    def test_every_state_change_uses_client_method(self):
        used = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and node.attr in CLIENT_METHODS_USED:
                used.add(node.attr)
        self.assertEqual(used, CLIENT_METHODS_USED)

    def test_client_module_cannot_reach_waydroid_manager(self):
        # The client is only the D-Bus route. The privileged work happens in the service.
        tree = ast.parse(CLIENT_PATH.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) \
                    else [node.module or ""]
                for n in names:
                    self.assertNotIn("waydroid_manager", n)


class GuiCopyTests(unittest.TestCase):
    """The packaged GUI copy must match the source."""

    def test_packaged_gui_matches_source(self):
        packaged = PROJECT_ROOT / "config/includes.chroot/usr/lib/bright-android/bright-android-gui.py"
        self.assertEqual(packaged.read_bytes(), GUI_PATH.read_bytes())


if __name__ == "__main__":
    unittest.main()
