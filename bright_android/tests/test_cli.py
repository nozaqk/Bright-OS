"""CLI tests: commands, exit codes, and proof that the CLI cannot bypass the service."""

import ast
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bright_android.core import cli  # noqa: E402
from bright_android.core import service_client as sc  # noqa: E402

CLI_SOURCE = (PROJECT_ROOT / "bright_android/core/cli.py").read_text()
WRAPPER = PROJECT_ROOT / "config/includes.chroot/usr/bin/bright-android"

# Read-only waydroid_manager functions the CLI may use directly.
READ_ONLY = frozenset({"is_running", "get_status", "list_apps", "get_logs", "is_installed"})
STATE_CHANGING = frozenset({"init", "start_session", "stop_session", "install_apk",
                            "uninstall_app", "launch_app"})


class FakeClient:
    def __init__(self, error_on=None, error=None):
        self.calls = []
        self._error_on = error_on
        self._error = error

    def _maybe_fail(self, name):
        self.calls.append(name)
        if self._error_on == name:
            raise self._error

    def start_runtime(self, progress_cb=None):
        self._maybe_fail("start_runtime")
        if progress_cb:
            progress_cb("Android is ready")

    def launch_app(self, package, progress_cb=None):
        self.calls.append(("launch_app", package))
        if self._error_on == "launch_app":
            raise self._error

    def install_apk(self, path, progress_cb=None):
        self.calls.append(("install_apk", path))
        if self._error_on == "install_apk":
            raise self._error


def run_launch(client, *, running=True, start_on_demand=True, package="com.example.app"):
    out, err = io.StringIO(), io.StringIO()
    code = cli.launch(package, client,
                      is_running=lambda: running,
                      start_on_demand=lambda: start_on_demand,
                      out=out, err=err)
    return code, out.getvalue(), err.getvalue()


class LaunchCommandTests(unittest.TestCase):
    def test_launch_when_running_calls_service_only(self):
        client = FakeClient()
        code, _, _ = run_launch(client, running=True)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(client.calls, [("launch_app", "com.example.app")])

    def test_launch_starts_runtime_first_when_on_demand(self):
        client = FakeClient()
        code, _, err = run_launch(client, running=False, start_on_demand=True)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(client.calls, ["start_runtime", ("launch_app", "com.example.app")])
        self.assertIn("Android is ready", err)  # progress is shown on stderr

    def test_launch_refused_when_not_running_and_on_demand_disabled(self):
        client = FakeClient()
        code, _, err = run_launch(client, running=False, start_on_demand=False)
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("not running", err)
        self.assertEqual(client.calls, [])

    def test_missing_package_is_usage_error(self):
        client = FakeClient()
        code, _, err = run_launch(client, package=None)
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("Usage: bright-android --launch", err)
        self.assertEqual(client.calls, [])

    def test_launch_failure_reports_message(self):
        client = FakeClient(error_on="launch_app", error=sc.OperationFailed("Could not launch x"))
        code, _, err = run_launch(client)
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("Error launching app: Could not launch x", err)


class InstallCommandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.apk = self.dir / "example.apk"
        self.apk.write_bytes(b"not really an apk")
        self._cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_install_sends_absolute_path_to_service(self):
        client = FakeClient()
        out, err = io.StringIO(), io.StringIO()
        code = cli.install("example.apk", client, out, err)
        self.assertEqual(code, cli.EXIT_OK)
        sent = client.calls[0][1]
        self.assertTrue(os.path.isabs(sent))
        self.assertEqual(os.path.realpath(sent), os.path.realpath(self.apk))
        self.assertIn("Installed: example.apk", out.getvalue())

    def test_missing_file_is_rejected_before_calling_service(self):
        client = FakeClient()
        err = io.StringIO()
        code = cli.install("nope.apk", client, io.StringIO(), err)
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("no such file", err.getvalue())
        self.assertEqual(client.calls, [])

    def test_missing_path_is_usage_error(self):
        client = FakeClient()
        err = io.StringIO()
        self.assertEqual(cli.install(None, client, io.StringIO(), err), cli.EXIT_FAILED)
        self.assertIn("Usage: bright-android --install-apk", err.getvalue())

    def test_install_failure_reports_service_message(self):
        client = FakeClient(error_on="install_apk", error=sc.OperationFailed("INSTALL_FAILED"))
        err = io.StringIO()
        code = cli.install("example.apk", client, io.StringIO(), err)
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("INSTALL_FAILED", err.getvalue())


class ExitCodeTests(unittest.TestCase):
    def test_denied_request_exits_with_denied_code(self):
        client = FakeClient(error_on="launch_app",
                            error=sc.AuthorizationDenied("Launch not authorized: polkit denied"))
        code, _, err = run_launch(client)
        self.assertEqual(code, cli.EXIT_DENIED)
        self.assertIn("not authorized", err)

    def test_unavailable_service_exits_with_unavailable_code(self):
        client = FakeClient(error_on="launch_app", error=sc.ServiceUnavailable("not running"))
        code, _, err = run_launch(client)
        self.assertEqual(code, cli.EXIT_UNAVAILABLE)
        self.assertIn("not running", err)

    def test_busy_service_exits_with_busy_code(self):
        client = FakeClient(error_on="launch_app", error=sc.ServiceBusy("start is already in progress"))
        code, _, _ = run_launch(client)
        self.assertEqual(code, cli.EXIT_BUSY)

    def test_rejected_request_exits_with_failure_code(self):
        client = FakeClient(error_on="install_apk", error=sc.RequestRejected("bad"))
        code = cli.install("/dev/null", client, io.StringIO(), io.StringIO())
        self.assertEqual(code, cli.EXIT_FAILED)

    def test_exit_codes_are_distinct_for_distinct_causes(self):
        codes = {cli.EXIT_OK, cli.EXIT_FAILED, cli.EXIT_DENIED, cli.EXIT_UNAVAILABLE, cli.EXIT_BUSY}
        self.assertEqual(len(codes), 5)


class DispatchTests(unittest.TestCase):
    def test_run_launch_calls_service_when_running(self):
        from unittest import mock
        client = FakeClient()
        with mock.patch.object(cli.waydroid_manager, "is_running", return_value=True):
            code = cli.run(["--launch", "com.example.app"], client_factory=lambda: client,
                           out=io.StringIO(), err=io.StringIO())
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(client.calls, [("launch_app", "com.example.app")])

    def test_run_install_calls_service_with_absolute_path(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as d:
            apk = Path(d) / "x.apk"
            apk.write_bytes(b"x")
            code = cli.run(["--install-apk", str(apk)], client_factory=lambda: client,
                           out=io.StringIO(), err=io.StringIO())
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(client.calls[0][0], "install_apk")

    def test_run_without_command_prints_usage(self):
        err = io.StringIO()
        self.assertEqual(cli.run([], client_factory=FakeClient, out=io.StringIO(), err=err),
                         cli.EXIT_FAILED)
        self.assertIn("Usage", err.getvalue())


class NoBypassTests(unittest.TestCase):
    """The CLI cannot change state except through the service client."""

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(CLI_SOURCE)

    def test_only_read_only_waydroid_functions_are_used(self):
        used = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "waydroid_manager":
                used.add(node.attr)
        self.assertTrue(used <= READ_ONLY, f"state-changing use: {sorted(used - READ_ONLY)}")

    def test_no_config_setters_or_process_calls(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "ba_config":
                self.assertFalse(node.attr.startswith("set_"), node.attr)
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotEqual(a.name, "subprocess")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, {"Popen", "system", "run", "call"})

    def test_cli_uses_the_service_client(self):
        self.assertIn("BrightAndroidClient", CLI_SOURCE)
        self.assertIn(".start_runtime(", CLI_SOURCE)
        self.assertIn(".launch_app(", CLI_SOURCE)
        self.assertIn(".install_apk(", CLI_SOURCE)

    def test_wrapper_sends_state_changes_to_cli_module(self):
        tree = ast.parse(WRAPPER.read_text())
        forbidden = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "waydroid_manager":
                forbidden.append(node.attr)
            if isinstance(node, ast.ImportFrom) and node.module and "waydroid_manager" in node.module:
                forbidden.append(node.module)
        self.assertEqual(forbidden, [])
        self.assertIn("bright_android.core.cli", WRAPPER.read_text())


if __name__ == "__main__":
    unittest.main()
