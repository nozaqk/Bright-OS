"""Client for the Bright Android D-Bus service.

The GUI performs every state-changing operation through this module. Each
call is a D-Bus method call that the service authorizes (sender credentials,
root policy, Polkit) and validates, so the GUI never needs root and never
bypasses the service.

This module must not import waydroid_manager or run privileged commands.
Read-only status queries stay in the GUI and read the same state directly.

Timeouts are explicit because the D-Bus default reply timeout (25 s) is too
short for runtime start and APK install. The service runs StartRuntime and
StopRuntime synchronously, so those calls block the service while they run.
"""

import time
from typing import Any, Callable, Optional, Tuple

BUS_NAME = "org.bright_os.BrightAndroid"
OBJECT_PATH = "/org/bright_os/BrightAndroid"
INTERFACE = "org.bright_os.BrightAndroid"

ERR_NOT_AUTHORIZED = "org.bright_os.BrightAndroid.NotAuthorized"
ERR_INVALID_ARGUMENT = "org.bright_os.BrightAndroid.InvalidArgument"

# Seconds.
TIMEOUT_DEFAULT = 30     # quick calls (launch, uninstall)
TIMEOUT_ADMIN = 120      # SetConfig; may wait on a Polkit admin prompt
TIMEOUT_START = 180      # StartRuntime / StopRuntime (service blocks while they run)
TIMEOUT_INSTALL = 300    # InstallApk
TIMEOUT_INIT = 1800      # InitializeRuntime completion (downloads 400-700 MB)

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


class OperationFailed(BrightAndroidClientError):
    """The service accepted the request, but the operation failed or did not finish."""


def translate_error(name: str, message: str) -> BrightAndroidClientError:
    """Map a D-Bus error name and message to a client exception."""
    if name == ERR_NOT_AUTHORIZED:
        return AuthorizationDenied(message or "Not authorized")
    if name == ERR_INVALID_ARGUMENT:
        return RequestRejected(message or "Request rejected")
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


def _default_connection() -> Tuple[Any, Any]:
    """Return (method interface, bus) for the real service on the session bus."""
    try:
        import dbus
    except ImportError as exc:
        raise ServiceUnavailable(
            "python3-dbus is not installed, so the Bright Android service cannot be reached."
        ) from exc
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object(BUS_NAME, OBJECT_PATH)
    except dbus.exceptions.DBusException as exc:
        raise _from_exception(exc) from exc
    return dbus.Interface(obj, INTERFACE), bus


class _CompletionWaiter:
    """Waits for OperationComplete for one operation name.

    Signal receivers are registered before InitializeRuntime is called, so a
    fast completion is not missed. This uses the connection's read/dispatch
    loop, which runs in the caller's thread and needs no GLib main loop.
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
                    "The Bright Android service did not report that initialization "
                    "finished. Check the logs before retrying.")
            if not self._bus.read_write_dispatch(int(min(remaining, 1.0) * 1000)):
                raise ServiceUnavailable("Lost the D-Bus connection while waiting.")
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
    StatusWorker. The service emits progress only for InitializeRuntime, so
    the other methods accept the callback and do not use it.

    ``connection_factory`` returns (method interface, bus). ``waiter_factory``
    returns an object with wait(timeout, progress_cb) and close(). Tests inject
    both; the defaults use the real session bus.
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

    def start_runtime(self, progress_cb=None) -> None:
        self._call("StartRuntime", timeout=TIMEOUT_START)

    def stop_runtime(self, progress_cb=None) -> None:
        self._call("StopRuntime", timeout=TIMEOUT_START)

    def install_apk(self, path: str, progress_cb=None) -> None:
        self._call("InstallApk", path, timeout=TIMEOUT_INSTALL)

    def uninstall_app(self, package: str, progress_cb=None) -> None:
        self._call("UninstallApp", package, timeout=TIMEOUT_DEFAULT)

    def launch_app(self, package: str, progress_cb=None) -> None:
        launched = self._call("LaunchApp", package, timeout=TIMEOUT_DEFAULT)
        if not launched:
            raise OperationFailed(f"Could not launch {package}. See the logs for details.")

    def set_config(self, path: str, value: Any, progress_cb=None) -> None:
        """Set one setting. ``path`` is "section/key"; booleans become "true"/"false"."""
        if isinstance(value, bool):
            value = "true" if value else "false"
        self._call("SetConfig", path, str(value), timeout=TIMEOUT_ADMIN)

    def initialize_runtime(self, progress_cb=None) -> None:
        """Start InitializeRuntime and wait for its OperationComplete signal."""
        self._interface()
        waiter = self._waiter_factory(self._bus, "init")
        try:
            self._call("InitializeRuntime", timeout=TIMEOUT_DEFAULT)
            success, message = waiter.wait(TIMEOUT_INIT, progress_cb)
        finally:
            waiter.close()
        if not success:
            raise OperationFailed(message or "Initialization failed. See the logs for details.")
