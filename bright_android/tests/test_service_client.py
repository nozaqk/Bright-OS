"""Tests for the GUI's D-Bus client (bright_android/core/service_client.py).

These use fake connections, so they run without python3-dbus or a session bus.
Live D-Bus behaviour is covered only on a host with the service running.
"""

import ast
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bright_android.core import service_client as sc  # noqa: E402
from bright_android.core import android_service as svc  # noqa: E402

SERVICE_SOURCE = (PROJECT_ROOT / "bright_android/core/android_service.py").read_text()
CLIENT_SOURCE = (PROJECT_ROOT / "bright_android/core/service_client.py").read_text()


class FakeDBusError(Exception):
    def __init__(self, name, message=""):
        super().__init__(message)
        self._name = name
        self._message = message

    def get_dbus_name(self):
        return self._name

    def get_dbus_message(self):
        return self._message


class FakeIface:
    """Records calls and returns scripted results or raises scripted errors."""

    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            result = self.results.get(name)
            if isinstance(result, BaseException):
                raise result
            return result
        return method


def client_with(iface, waiter=None):
    bus = object()
    return sc.BrightAndroidClient(
        connection_factory=lambda: (iface, bus),
        waiter_factory=lambda b, op: waiter or FakeWaiter(),
    )


class FakeWaiter:
    def __init__(self, outcome=(True, ""), raises=None):
        self.outcome = outcome
        self.raises = raises
        self.waited_with = None
        self.closed = False

    def wait(self, timeout, progress_cb=None):
        self.waited_with = (timeout, progress_cb)
        if self.raises:
            raise self.raises
        return self.outcome

    def close(self):
        self.closed = True


class ClientForTest(sc.BrightAndroidClient):
    """Client with a default successful waiter, so no real D-Bus is needed."""

    def __init__(self, connection_factory=None):
        super().__init__(connection_factory=connection_factory,
                         waiter_factory=lambda b, op: FakeWaiter())


class ConstantsTests(unittest.TestCase):
    def test_bus_identifiers_match_service(self):
        self.assertEqual(sc.BUS_NAME, svc.BUS_NAME)
        self.assertEqual(sc.OBJECT_PATH, svc.OBJECT_PATH)
        self.assertEqual(sc.INTERFACE, svc.INTERFACE)

    def test_denial_error_names_match_service(self):
        self.assertEqual(sc.ERR_NOT_AUTHORIZED, "org.bright_os.BrightAndroid.NotAuthorized")
        self.assertIn(sc.ERR_NOT_AUTHORIZED, SERVICE_SOURCE)
        self.assertEqual(sc.ERR_INVALID_ARGUMENT, "org.bright_os.BrightAndroid.InvalidArgument")
        self.assertIn(sc.ERR_INVALID_ARGUMENT, SERVICE_SOURCE)


class ErrorMappingTests(unittest.TestCase):
    def test_not_authorized_maps_to_denied(self):
        err = sc.translate_error(sc.ERR_NOT_AUTHORIZED, "Start requires auth")
        self.assertIsInstance(err, sc.AuthorizationDenied)
        self.assertIn("Start requires auth", str(err))

    def test_invalid_argument_maps_to_rejected(self):
        err = sc.translate_error(sc.ERR_INVALID_ARGUMENT, "Rejected config change")
        self.assertIsInstance(err, sc.RequestRejected)

    def test_unreachable_service_maps_to_unavailable(self):
        for name in ("org.freedesktop.DBus.Error.ServiceUnknown",
                     "org.freedesktop.DBus.Error.NameHasNoOwner",
                     "org.freedesktop.DBus.Error.NoServer"):
            self.assertIsInstance(sc.translate_error(name, ""), sc.ServiceUnavailable, name)

    def test_no_reply_maps_to_operation_failed_with_timeout_text(self):
        err = sc.translate_error("org.freedesktop.DBus.Error.NoReply", "")
        self.assertIsInstance(err, sc.OperationFailed)
        self.assertIn("did not finish in time", str(err))

    def test_unknown_error_maps_to_operation_failed(self):
        err = sc.translate_error("org.bright_os.BrightAndroid.StartFailed", "boom")
        self.assertIsInstance(err, sc.OperationFailed)
        self.assertEqual(str(err), "boom")

    def test_service_error_reaches_gui_as_typed_exception(self):
        iface = FakeIface({"StartRuntime": FakeDBusError(sc.ERR_NOT_AUTHORIZED, "denied")})
        with self.assertRaises(sc.AuthorizationDenied):
            client_with(iface).start_runtime()

    def test_bare_exception_is_operation_failed(self):
        iface = FakeIface({"StopRuntime": RuntimeError("bad")})
        with self.assertRaises(sc.OperationFailed):
            client_with(iface).stop_runtime()

    def test_missing_dbus_is_service_unavailable(self):
        def no_dbus():
            raise sc.ServiceUnavailable("python3-dbus is not installed")
        client = ClientForTest(connection_factory=no_dbus)
        with self.assertRaises(sc.ServiceUnavailable):
            client.start_runtime()


class TimeoutTests(unittest.TestCase):
    def _timeout_for(self, call):
        iface = FakeIface()
        call(client_with(iface))
        self.assertEqual(len(iface.calls), 1)
        return iface.calls[0]

    def test_start_and_stop_queue_quickly_and_wait_separately(self):
        # The D-Bus call only queues the operation, so it uses the default timeout.
        # The long wait for completion is covered by AsyncOperationTests.
        self.assertEqual(self._timeout_for(lambda c: c.start_runtime())[2]["timeout"], sc.TIMEOUT_DEFAULT)
        self.assertEqual(self._timeout_for(lambda c: c.stop_runtime())[2]["timeout"], sc.TIMEOUT_DEFAULT)

    def test_install_queues_with_default_timeout(self):
        # InstallApk only queues the job, so the D-Bus call itself is short.
        # The long wait is for OperationComplete (InstallOperationTests).
        name, args, kw = self._timeout_for(lambda c: c.install_apk("/tmp/a.apk"))
        self.assertEqual(name, "InstallApk")
        self.assertEqual(args, ("/tmp/a.apk",))
        self.assertEqual(kw["timeout"], sc.TIMEOUT_DEFAULT)

    def test_set_config_uses_admin_timeout(self):
        self.assertEqual(self._timeout_for(lambda c: c.set_config("runtime/auto_start", True))[2]["timeout"],
                         sc.TIMEOUT_ADMIN)

    def test_timeouts_exceed_dbus_default(self):
        # The D-Bus default reply timeout is 25 s; every long-running call must exceed it.
        for value in (sc.TIMEOUT_START, sc.TIMEOUT_INSTALL, sc.TIMEOUT_ADMIN, sc.TIMEOUT_INIT):
            self.assertGreater(value, 25)

    def test_start_timeout_covers_service_block(self):
        # The service's StartRuntime may block up to 120 s in waydroid_manager.
        self.assertGreater(sc.TIMEOUT_START, 120)


class MethodMappingTests(unittest.TestCase):
    def test_every_called_method_exists_on_service(self):
        called = set(re.findall(r'_call\(\s*"([A-Za-z]+)"', CLIENT_SOURCE))
        called |= set(re.findall(r'"(InitializeRuntime)"', CLIENT_SOURCE))
        self.assertTrue(called)
        for name in called:
            self.assertRegex(SERVICE_SOURCE, rf"def {name}\(self", msg=name)

    def test_set_config_sends_section_key_path_and_string_values(self):
        iface = FakeIface()
        client_with(iface).set_config("storage/shared_pictures", False)
        name, args, _ = iface.calls[0]
        self.assertEqual(name, "SetConfig")
        self.assertEqual(args, ("storage/shared_pictures", "false"))

    def test_set_config_passes_true_as_true_string(self):
        iface = FakeIface()
        client_with(iface).set_config("runtime/auto_start", True)
        self.assertEqual(iface.calls[0][1], ("runtime/auto_start", "true"))

    def test_launch_app_false_result_is_failure(self):
        iface = FakeIface({"LaunchApp": False})
        with self.assertRaises(sc.OperationFailed):
            client_with(iface).launch_app("com.example.app")

    def test_launch_app_true_result_is_success(self):
        iface = FakeIface({"LaunchApp": True})
        client_with(iface).launch_app("com.example.app")
        self.assertEqual(iface.calls[0][0], "LaunchApp")


class ConnectionTests(unittest.TestCase):
    def test_failed_call_drops_cached_proxy(self):
        ifaces = [FakeIface({"StartRuntime": FakeDBusError("org.freedesktop.DBus.Error.ServiceUnknown")}),
                  FakeIface()]
        factory = mock.Mock(side_effect=[(i, object()) for i in ifaces])
        client = ClientForTest(connection_factory=factory)
        with self.assertRaises(sc.ServiceUnavailable):
            client.start_runtime()
        client.start_runtime()  # reconnects
        self.assertEqual(factory.call_count, 2)

    def test_proxy_is_reused_between_successful_calls(self):
        factory = mock.Mock(return_value=(FakeIface(), object()))
        client = ClientForTest(connection_factory=factory)
        client.stop_runtime()
        client.stop_runtime()
        self.assertEqual(factory.call_count, 1)


class InitializeRuntimeTests(unittest.TestCase):
    def test_success_waits_for_completion_with_init_timeout(self):
        iface = FakeIface()
        waiter = FakeWaiter(outcome=(True, ""))
        cb = mock.Mock()
        client_with(iface, waiter).initialize_runtime(progress_cb=cb)
        self.assertEqual(iface.calls[0][0], "InitializeRuntime")
        self.assertEqual(waiter.waited_with, (sc.TIMEOUT_INIT, cb))
        self.assertTrue(waiter.closed)

    def test_failed_completion_raises_with_service_message(self):
        waiter = FakeWaiter(outcome=(False, "download failed"))
        with self.assertRaises(sc.OperationFailed) as ctx:
            client_with(FakeIface(), waiter).initialize_runtime()
        self.assertIn("download failed", str(ctx.exception))
        self.assertTrue(waiter.closed)

    def test_waiter_closed_when_call_fails(self):
        iface = FakeIface({"InitializeRuntime": FakeDBusError(sc.ERR_NOT_AUTHORIZED, "no")})
        waiter = FakeWaiter()
        with self.assertRaises(sc.AuthorizationDenied):
            client_with(iface, waiter).initialize_runtime()
        self.assertTrue(waiter.closed)

    def test_timeout_while_waiting_raises_and_closes(self):
        waiter = FakeWaiter(raises=sc.OperationFailed("timed out"))
        with self.assertRaises(sc.OperationFailed):
            client_with(FakeIface(), waiter).initialize_runtime()
        self.assertTrue(waiter.closed)


class ClientIsolationTests(unittest.TestCase):
    """The client must not be a way around the service."""

    def test_client_does_not_import_privileged_modules(self):
        tree = ast.parse(CLIENT_SOURCE)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[-1])
        for forbidden in ("waydroid_manager", "subprocess", "os", "pkexec", "config", "apk_validator"):
            self.assertNotIn(forbidden, imported, forbidden)

    def test_client_contains_no_shell_or_pkexec_text(self):
        self.assertNotIn("pkexec", CLIENT_SOURCE)
        self.assertNotIn("os.system", CLIENT_SOURCE)


class AsyncOperationTests(unittest.TestCase):
    """StartRuntime, StopRuntime and InitializeRuntime wait for OperationComplete."""

    def _client(self, iface, waiter):
        names = []
        bus = object()

        def waiter_factory(b, op):
            names.append(op)
            return waiter

        client = sc.BrightAndroidClient(connection_factory=lambda: (iface, bus),
                                        waiter_factory=waiter_factory)
        return client, names

    def test_start_uses_start_operation_and_waits(self):
        iface = FakeIface()
        waiter = FakeWaiter(outcome=(True, ""))
        client, names = self._client(iface, waiter)
        client.start_runtime()
        self.assertEqual(names, ["start"])
        self.assertEqual(iface.calls[0][0], "StartRuntime")
        self.assertEqual(waiter.waited_with[0], sc.TIMEOUT_START)
        self.assertTrue(waiter.closed)

    def test_stop_uses_stop_operation(self):
        iface = FakeIface()
        client, names = self._client(iface, FakeWaiter())
        client.stop_runtime()
        self.assertEqual(names, ["stop"])
        self.assertEqual(iface.calls[0][0], "StopRuntime")

    def test_failed_start_completion_raises_with_message(self):
        waiter = FakeWaiter(outcome=(False, "waydroid exploded"))
        client, _ = self._client(FakeIface(), waiter)
        with self.assertRaises(sc.OperationFailed) as ctx:
            client.start_runtime()
        self.assertIn("waydroid exploded", str(ctx.exception))
        self.assertTrue(waiter.closed)

    def test_progress_is_forwarded_to_caller(self):
        seen = []

        class ProgressWaiter(FakeWaiter):
            def wait(self, timeout, progress_cb=None):
                progress_cb("Starting container")
                return (True, "")

        client, _ = self._client(FakeIface(), ProgressWaiter())
        client.start_runtime(progress_cb=seen.append)
        self.assertEqual(seen, ["Starting container"])

    def test_busy_refusal_is_reported_and_waiter_closed(self):
        iface = FakeIface({"StartRuntime": FakeDBusError(sc.ERR_BUSY, "init is already in progress")})
        waiter = FakeWaiter()
        client, _ = self._client(iface, waiter)
        with self.assertRaises(sc.ServiceBusy) as ctx:
            client.start_runtime()
        self.assertIn("init is already in progress", str(ctx.exception))
        self.assertTrue(waiter.closed)

    def test_completion_timeout_is_operation_failed(self):
        waiter = FakeWaiter(raises=sc.OperationFailed("no completion"))
        client, _ = self._client(FakeIface(), waiter)
        with self.assertRaises(sc.OperationFailed):
            client.stop_runtime()
        self.assertTrue(waiter.closed)


class BatchSettingsClientTests(unittest.TestCase):
    def test_set_configs_sends_one_call_with_pairs(self):
        iface = FakeIface({"SetConfigs": 2})
        count = ClientForTest(connection_factory=lambda: (iface, object())).set_configs(
            [("runtime/auto_start", True), ("storage/shared_pictures", False)])
        self.assertEqual(count, 2)
        self.assertEqual(len(iface.calls), 1)
        name, args, kwargs = iface.calls[0]
        self.assertEqual(name, "SetConfigs")
        self.assertEqual(args[0], [("runtime/auto_start", "true"),
                                   ("storage/shared_pictures", "false")])
        self.assertEqual(kwargs["timeout"], sc.TIMEOUT_ADMIN)

    def test_set_configs_rejection_is_request_rejected(self):
        iface = FakeIface({"SetConfigs": FakeDBusError(sc.ERR_INVALID_ARGUMENT, "setting 2: unknown section")})
        with self.assertRaises(sc.RequestRejected):
            ClientForTest(connection_factory=lambda: (iface, object())).set_configs(
                [("runtime/auto_start", True), ("evil/x", True)])

    def test_set_configs_write_failure_is_operation_failed_with_kept_message(self):
        iface = FakeIface({"SetConfigs": FakeDBusError(sc.ERR_WRITE_FAILED, "previous settings kept")})
        with self.assertRaises(sc.OperationFailed) as ctx:
            ClientForTest(connection_factory=lambda: (iface, object())).set_configs(
                [("runtime/auto_start", True)])
        self.assertIn("previous settings kept", str(ctx.exception))

    def test_set_configs_denial_is_authorization_denied(self):
        iface = FakeIface({"SetConfigs": FakeDBusError(sc.ERR_NOT_AUTHORIZED, "admin auth denied")})
        with self.assertRaises(sc.AuthorizationDenied):
            ClientForTest(connection_factory=lambda: (iface, object())).set_configs(
                [("runtime/auto_start", True)])


if __name__ == "__main__":
    unittest.main()


class InstallOperationTests(unittest.TestCase):
    """InstallApk is asynchronous: the client queues it, then waits for completion."""

    def _client(self, iface, waiter):
        names = []
        bus = object()

        def waiter_factory(b, op):
            names.append(op)
            return waiter

        client = sc.BrightAndroidClient(connection_factory=lambda: (iface, bus),
                                        waiter_factory=waiter_factory)
        return client, names

    def test_install_waits_for_install_completion(self):
        iface = FakeIface()
        waiter = FakeWaiter(outcome=(True, "Installed: Example"))
        client, names = self._client(iface, waiter)
        client.install_apk("/home/u/example.apk")
        self.assertEqual(names, ["install"])
        self.assertEqual(iface.calls[0][0], "InstallApk")
        self.assertEqual(iface.calls[0][1], ("/home/u/example.apk",))
        self.assertEqual(waiter.waited_with[0], sc.TIMEOUT_INSTALL)
        self.assertTrue(waiter.closed)

    def test_failed_install_raises_service_message(self):
        waiter = FakeWaiter(outcome=(False, "APK installation failed (exit 124): Timed out after 180s"))
        client, _ = self._client(FakeIface(), waiter)
        with self.assertRaises(sc.OperationFailed) as ctx:
            client.install_apk("/home/u/example.apk")
        self.assertIn("Timed out after 180s", str(ctx.exception))
        self.assertTrue(waiter.closed)

    def test_install_progress_is_forwarded(self):
        seen = []

        class ProgressWaiter(FakeWaiter):
            def wait(self, timeout, progress_cb=None):
                progress_cb("Installing example.apk...")
                return (True, "")

        client, _ = self._client(FakeIface(), ProgressWaiter())
        client.install_apk("/home/u/example.apk", progress_cb=seen.append)
        self.assertEqual(seen, ["Installing example.apk..."])

    def test_busy_refusal_raises_without_waiting(self):
        class BusyIface(FakeIface):
            def InstallApk(self, *args, **kw):
                raise sc._from_exception(
                    type("E", (Exception,), {"get_dbus_name": lambda self: sc.ERR_BUSY,
                                             "get_dbus_message": lambda self: "start is already in progress"})())

        waiter = FakeWaiter()
        client, _ = self._client(BusyIface(), waiter)
        with self.assertRaises(sc.ServiceBusy):
            client.install_apk("/home/u/example.apk")
        self.assertIsNone(waiter.waited_with)

