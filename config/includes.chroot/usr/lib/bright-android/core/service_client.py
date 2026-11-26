"""Client for the Bright Android D-Bus service.

The GUI and the CLI perform every state-changing operation through this
module. Each call is a D-Bus method call that the service authorizes
(sender credentials, root policy, Polkit) and validates, so callers never
need root and never bypass the service.

This module must not import waydroid_manager or run privileged commands.
Read-only status queries stay in the GUI and CLI and read state directly.

Runtime start, stop, and init are asynchronous on the service. The client
subscribes to the operation's signals before it makes the call, waits for
OperationComplete, and forwards OperationProgress to the caller. Other
operations are synchronous, so their D-Bus call timeouts are explicit: the
D-Bus default reply timeout (25 s) is too short for APK install and for
admin prompts.
"""

import time
from typing import Any, Callable, Optional, Tuple

BUS_NAME = "org.bright_os.BrightAndroid"
OBJECT_PATH = "/org/bright_os/BrightAndroid"
INTERFACE = "org.bright_os.BrightAndroid"

ERR_NOT_AUTHORIZED = "org.bright_os.BrightAndroid.NotAuthorized"
ERR_INVALID_ARGUMENT = "org.bright_os.BrightAndroid.InvalidArgument"
ERR_BUSY = "org.bright_os.BrightAndroid.Busy"
ERR_WRITE_FAILED = "org.bright_os.BrightAndroid.WriteFailed"

# Seconds.
TIMEOUT_DEFAULT = 30     # quick calls (launch, uninstall, queueing an async operation)
TIMEOUT_ADMIN = 120      # SetConfig / SetConfigs; may wait on a Polkit admin prompt
TIMEOUT_START = 180      # waiting for a runtime start or stop to complete
TIMEOUT_INSTALL = 300    # InstallApk (synchronous on the service)
TIMEOUT_INIT = 1800      # waiting for init to complete (downloads 400-700 MB)

_UNAVAILABLE_ERRORS = frozenset({
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.NameHasNoOwner",
    "org.freedesktop.DBus.Error.NoServer",
    "org.freedesktop.DBus.Error.Disconnected",
    "org.freedesktop.DBus.Error.Spawn.ServiceNotFound",
})
_TIMEOUT_ERRORS = frozenset({"org.freedesktop.DBus.Error.NoReply"})


class BrightAndroidClientError(Exception):
    """Base class. str() is the message to show the user."""


class ServiceUnavailable(BrightAndroidClientError):
    """The service cannot be reached: D-Bus or python3-dbus is missing, or the service is not running."""


class AuthorizationDenied(BrightAndroidClientError):
    """The service refused the caller (Polkit denied, or the caller was not authorized)."""


class RequestRejected(BrightAndroidClientError):
    """The service rejected the request's arguments (for example, a config key outside the allowlist)."""


class ServiceBusy(BrightAndroidClientError):
    """Another runtime operation is already running on the service."""


class OperationFailed(BrightAndroidClientError):
    """The service accepted the request, but the operation failed or did not finish."""


def translate_error(name: str, message: str) -> BrightAndroidClientError:
    """Map a D-Bus error name and message to a client exception."""
    if name == ERR_NOT_AUTHORIZED:
        return AuthorizationDenied(message or "Not authorized")
    if name == ERR_INVALID_ARGUMENT:
        return RequestRejected(message or "Request rejected")
    if name == ERR_BUSY:
        return ServiceBusy(message or "Another runtime operation is in progress")
    if name == ERR_WRITE_FAILED:
        return OperationFailed(message or "Settings not saved; previous settings kept")
    if name in _UNAVAILABLE_ERRORS:
        return ServiceUnavailable(
            "The Bright Android service is not running or cannot be reached.")
    if name in _TIMEOUT_ERRORS:
        return OperationFailed(
            "The Bright Android service did not finish in time. "
            "Check the status and logs before retrying.")
    return OperationFailed(message or name or "Operation failed")


def _from_exception(exc: Exception) -> BrightAndroidClientError:
    if isinstance(exc, BrightAndroidClientError):
        return exc
    get_name = getattr(exc, "get_dbus_name", None)
    if callable(get_name):
        return translate_error(get_name(), exc.get_dbus_message())
    return OperationFailed(str(exc) or exc.__class__.__name__)


def _as_text(value: Any) -> str:
    """Settings travel as text. Booleans become "true" or "false"."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


_shared_bus = None


def _default_connection() -> Tuple[Any, Any]:
    """Return (method interface, bus) for the real service on the session bus.

    The connection is attached to a GLib main loop. Signal receivers need one,
    and the waiter dispatches messages through it. The connection is created
    once per process and reused.
    """
    global _shared_bus
    try:
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
    except ImportError as exc:
        raise ServiceUnavailable(
            "python3-dbus is not installed, so the Bright Android service cannot be reached."
        ) from exc
    try:
        if _shared_bus is None:
            _shared_bus = dbus.SessionBus(mainloop=DBusGMainLoop(set_as_default=False))
        obj = _shared_bus.get_object(BUS_NAME, OBJECT_PATH)
    except dbus.exceptions.DBusException as exc:
        raise _from_exception(exc) from exc
    return dbus.Interface(obj, INTERFACE), _shared_bus


def dispatch_pending(wait_seconds: float) -> None:
    """Run the GLib default main context for up to wait_seconds.

    dbus-python delivers messages and signals through GLib sources, so a thread
    that waits for a signal must iterate that context. Requires the connection
    to be attached to a GLib main loop.
    """
    from gi.repository import GLib
    context = GLib.MainContext.default()
    deadline = time.monotonic() + wait_seconds
    while True:
        while context.pending():
            context.iteration(False)
        if time.monotonic() >= deadline:
            return
        time.sleep(0.01)


class _CompletionWaiter:
    """Waits for OperationComplete for one operation name.

    Signal receivers are registered before the operation is started, so a
    fast completion is not missed. Waiting iterates the GLib main context in
    the caller's thread (see dispatch_pending).
    """

    def __init__(self, bus, operation: str):
        self._bus = bus
        self._op = operation
        self._progress_cb: Optional[Callable[[str], None]] = None
        self._result: Optional[Tuple[bool, str]] = None
        bus.add_signal_receiver(self._on_complete, signal_name="OperationComplete",
                                dbus_interface=INTERFACE, bus_name=BUS_NAME,
                                path=OBJECT_PATH)
        bus.add_signal_receiver(self._on_progress, signal_name="OperationProgress",
                                dbus_interface=INTERFACE, bus_name=BUS_NAME,
                                path=OBJECT_PATH)

    def _on_progress(self, operation, message):
        if operation == self._op and self._progress_cb:
            self._progress_cb(str(message))

    def _on_complete(self, operation, message, success):
        if operation == self._op and self._result is None:
            self._result = (bool(success), str(message))

    def wait(self, timeout: float, progress_cb=None) -> Tuple[bool, str]:
        self._progress_cb = progress_cb
        deadline = time.monotonic() + timeout
        while self._result is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OperationFailed(
                    "The Bright Android service did not report that the operation "
                    "finished. Check the status and logs before retrying.")
            if not self._bus.get_is_connected():
                raise ServiceUnavailable("Lost the D-Bus connection while waiting.")
            dispatch_pending(min(remaining, 0.1))
        return self._result

    def close(self):
        self._bus.remove_signal_receiver(self._on_complete, signal_name="OperationComplete",
                                         dbus_interface=INTERFACE, bus_name=BUS_NAME,
                                         path=OBJECT_PATH)
        self._bus.remove_signal_receiver(self._on_progress, signal_name="OperationProgress",
                                         dbus_interface=INTERFACE, bus_name=BUS_NAME,
                                         path=OBJECT_PATH)


def _default_waiter(bus, operation: str) -> _CompletionWaiter:
    return _CompletionWaiter(bus, operation)


class BrightAndroidClient:
    """Calls the service's state-changing methods.

    Every method accepts ``progress_cb`` so it can run under the GUI's
    StatusWorker. Asynchronous operations forward progress to it. Synchronous
    operations accept it and do not use it.

    ``connection_factory`` returns (method interface, bus). ``waiter_factory``
    returns an object with wait(timeout, progress_cb) and close(). Tests inject
    both. The defaults use the real session bus.
    """

    def __init__(self, connection_factory: Optional[Callable[[], Tuple[Any, Any]]] = None,
                 waiter_factory: Optional[Callable[[Any, str], Any]] = None):
        self._connection_factory = connection_factory or _default_connection
        self._waiter_factory = waiter_factory or _default_waiter
        self._iface = None
        self._bus = None

    def _interface(self):
        if self._iface is None:
            self._iface, self._bus = self._connection_factory()
        return self._iface

    def _call(self, method: str, *args, timeout: float):
        try:
            iface = self._interface()
            return getattr(iface, method)(*args, timeout=timeout)
        except Exception as exc:
            # Drop the cached proxy after a failure so the next call reconnects.
            self._iface = None
            self._bus = None
            raise _from_exception(exc) from exc

    def _run_operation(self, method: str, op_name: str, progress_cb, wait_timeout: float,
                       *method_args):
        """Start an asynchronous service operation and wait for its completion signal."""
        self._interface()
        waiter = self._waiter_factory(self._bus, op_name)
        try:
            self._call(method, *method_args, timeout=TIMEOUT_DEFAULT)
            success, message = waiter.wait(wait_timeout, progress_cb)
        finally:
            waiter.close()
        if not success:
            raise OperationFailed(message or f"{op_name} failed. See the logs for details.")

    def start_runtime(self, progress_cb=None) -> None:
        self._run_operation("StartRuntime", "start", progress_cb, TIMEOUT_START)

    def stop_runtime(self, progress_cb=None) -> None:
        self._run_operation("StopRuntime", "stop", progress_cb, TIMEOUT_START)

    def initialize_runtime(self, progress_cb=None) -> None:
        self._run_operation("InitializeRuntime", "init", progress_cb, TIMEOUT_INIT)

    def install_apk(self, path: str, progress_cb=None) -> None:
        """Install an APK asynchronously.

        The InstallApk service method queues the install on the service's
        background worker and returns immediately; this client waits for
        OperationComplete("install-apk", ...). Pre-flight failures (auth,
        invalid path, runtime not running, busy) raise synchronously from
        the D-Bus call itself.
        """
        self._run_operation("InstallApk", "install-apk", progress_cb, TIMEOUT_INSTALL,
                            path)

    def uninstall_app(self, package: str, progress_cb=None) -> None:
        self._call("UninstallApp", package, timeout=TIMEOUT_DEFAULT)

    def launch_app(self, package: str, progress_cb=None) -> None:
        launched = self._call("LaunchApp", package, timeout=TIMEOUT_DEFAULT)
        if not launched:
            raise OperationFailed(f"Could not launch {package}. See the logs for details.")

    def set_config(self, path: str, value: Any, progress_cb=None) -> None:
        """Set one setting. ``path`` is "section/key"."""
        self._call("SetConfig", path, _as_text(value), timeout=TIMEOUT_ADMIN)

    def set_configs(self, changes, progress_cb=None) -> int:
        """Set several settings with one authorization and one atomic write.

        ``changes`` is an iterable of ("section/key", value). Returns the number
        of settings written. The service rejects the whole batch if any entry is
        invalid, so a rejected call changes nothing.
        """
        pairs = [(str(path), _as_text(value)) for path, value in changes]
        return int(self._call("SetConfigs", pairs, timeout=TIMEOUT_ADMIN))
