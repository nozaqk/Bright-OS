"""Bright Android D-Bus service.

Provides a system-bus or session-bus D-Bus interface for managing
the Android (Waydroid) runtime. Uses Polkit for privileged operations.

Bus:   org.bright_os.BrightAndroid
Path:  /org/bright_os/BrightAndroid
Iface: org.bright_os.BrightAndroid

The service runs as a user session service (not root). Privileged
operations use pkexec for authorization via Polkit policies.
"""
import os
import sys
import logging
import threading
import time
from typing import Optional, Dict, Any, List

# Set up logging before imports that may trigger module load
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s bright-android[%(process)d] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bright_android.service")

# ---------------------------------------------------------------------------
# D-Bus / Polkit integration — gracefully degrade when unavailable
# (headless/test mode, like AURA does)
# ---------------------------------------------------------------------------
HAS_DBUS = False
HAS_POLKIT = False
DBusObject = object
method = lambda *a, **k: (lambda f: f)  # no-op decorator fallback

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from dbus.service import method as dbus_method
    method = dbus_method
    HAS_DBUS = True
    try:
        from gi.repository import Polkit, Gio
        HAS_POLKIT = True
    except ImportError:
        HAS_POLKIT = False
except ImportError:
    HAS_DBUS = False

try:
    from gi.repository import GLib
    HAS_GLIB = True
except ImportError:
    HAS_GLIB = False

from . import config as ba_config
from . import waydroid_manager
from . import compatibility
from . import apk_validator
from . import launcher_integration


BUS_NAME = "org.bright_os.BrightAndroid"
OBJECT_PATH = "/org/bright_os/BrightAndroid"
INTERFACE = "org.bright_os.BrightAndroid"


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
# Polkit action IDs. Keep in sync with the policy file:
#   config/includes.chroot/usr/share/polkit-1/actions/org.bright_os.BrightAndroid.policy
POLKIT_ACTION_INIT = "org.bright_os.BrightAndroid.init"
POLKIT_ACTION_START = "org.bright_os.BrightAndroid.start"
POLKIT_ACTION_STOP = "org.bright_os.BrightAndroid.stop"
POLKIT_ACTION_INSTALL = "org.bright_os.BrightAndroid.install-apk"
POLKIT_ACTION_UNINSTALL = "org.bright_os.BrightAndroid.uninstall-app"
POLKIT_ACTION_REMOVE_DATA = "org.bright_os.BrightAndroid.remove-data"
POLKIT_ACTION_SET_CONFIG = "org.bright_os.BrightAndroid.set-config"
POLKIT_ACTION_LAUNCH = "org.bright_os.BrightAndroid.launch-app"
POLKIT_ACTION_SYNC = "org.bright_os.BrightAndroid.sync-apps"

# The service UID is captured at import time. Callers whose UID does not match
# this value (and are not root) are denied. This prevents other local users
# from controlling the current user's Android environment even if they can
# connect to the session bus.
SERVICE_UID = os.getuid()


def _get_caller_credentials(sender, bus) -> tuple:
    """Extract and validate caller PID and UID from D-Bus.

    Returns (ok: bool, pid: int, uid: int, reason: str). When ok is False,
    pid/uid are 0 and reason describes why credentials could not be obtained.

    Every failure returns ok=False (deny): dbus-python missing, no bus object,
    no sender, or credentials that cannot be read or are out of range.
    """
    if not HAS_DBUS:
        # dbus-python is not importable, so this process cannot receive or
        # verify D-Bus callers. Authorization must not be granted without a
        # verifiable caller identity: deny. (Nothing calls this path at
        # runtime: the authorized methods exist only on the D-Bus service
        # class, which is defined only when HAS_DBUS is True.)
        return False, 0, 0, "D-Bus unavailable (python3-dbus missing); denied"

    # When HAS_DBUS is True but bus is None, this is a programming error in
    # the caller (method was invoked without passing self._bus) or a direct
    # in-process call. To prevent accidentally authorizing a call that should
    # have gone through D-Bus, we deny here. Production dbus-python dispatch
    # always passes bus=self._bus.
    if bus is None:
        logger.warning(
            "Authorization called without bus while HAS_DBUS=True; "
            "denying to prevent in-process bypass"
        )
        return False, 0, 0, "no bus provided (in-process call denied when D-Bus is available)"

    if sender is None:
        return False, 0, 0, "no sender identity provided"

    try:
        # Correct dbus-python API for peer credentials:
        #   get_connection_unix_process_id(name) -> int PID
        #   get_connection_unix_user(name)        -> int UID
        # (Note: get_unix_process_id / get_unix_user_id are NOT valid methods;
        # they were a bug in earlier revisions that caused AttributeError and
        # fell through to the old implicit-trust bypass.)
        pid = bus.get_connection_unix_process_id(sender)
        uid = bus.get_connection_unix_user(sender)
    except Exception as e:
        # Catches dbus.DBusException (unknown sender), AttributeError (bad bus),
        # and any other lookup failure. Broad Exception catch is deliberate:
        # any failure must result in denial regardless of error type.
        logger.warning("Could not determine caller identity for %s: %s", sender, e)
        return False, 0, 0, f"could not determine caller identity: {e}"

    # Type/range validation
    if not isinstance(pid, int) or pid <= 0:
        return False, 0, 0, f"invalid caller pid: {pid!r}"
    if not isinstance(uid, int) or uid < 0:
        return False, 0, 0, f"invalid caller uid: {uid!r}"

    return True, pid, uid, ""


# Maximum time to wait for a Polkit decision. ALLOW_USER_INTERACTION may show
# an authentication prompt, so this must be generous.
POLKIT_CHECK_TIMEOUT_SECONDS = 60

# Maximum Polkit checks in flight at once, including checks that have timed
# out but whose thread is still blocked. A slot is released only when the
# worker thread actually finishes, so hung threads cannot accumulate without
# bound. When every slot is taken, new requests are denied immediately.
POLKIT_MAX_IN_FLIGHT = 4
_POLKIT_SLOTS = threading.BoundedSemaphore(POLKIT_MAX_IN_FLIGHT)


def _polkit_consult(action_id: str, pid: int, uid: int,
                    timeout: float = None) -> tuple:
    """Ask Polkit whether process `pid` may perform `action_id`.

    Returns (allowed: bool, reason: str). Fails closed: a missing authority,
    an exception, a timeout, a saturated pool, or a response that is not
    exactly True/False is a denial. Only an explicit is_authorized() == True
    allows.

    Resource limits:
    - At most POLKIT_MAX_IN_FLIGHT checks run at once. The slot is acquired
      without blocking, so a saturated pool denies at once and the D-Bus
      service stays responsive.
    - Python cannot cancel a thread blocked inside a C call. A timed-out check
      keeps its thread and its slot until the call returns. The thread is not
      killed, and no result from it is ever used.
    - Each request has its own state. The caller marks it abandoned on
      timeout, and the worker discards any result that arrives after that.
      A late "authorized" therefore cannot authorize a request that already
      returned a denial.
    """
    if timeout is None:
        timeout = POLKIT_CHECK_TIMEOUT_SECONDS

    if not _POLKIT_SLOTS.acquire(blocking=False):
        return False, (
            f"Polkit authorization busy (too many checks in flight); denied {action_id}"
        )

    lock = threading.Lock()
    req = {"status": "pending", "result": None, "error": None, "stage": None}

    def _settle(**fields):
        # Store the outcome only if the caller has not already given up.
        with lock:
            if req["status"] != "pending":
                return False
            req.update(fields)
            req["status"] = "done"
            return True

    def _worker():
        try:
            try:
                authority = Polkit.Authority.get_sync(None)
            except Exception as e:
                _settle(stage="authority", error=e)
                return
            try:
                subject = Polkit.UnixProcess.new(pid)
                result = authority.check_authorization_sync(
                    subject,
                    action_id,
                    None,
                    Polkit.CheckAuthorizationFlags.ALLOW_USER_INTERACTION,
                    None,
                )
            except Exception as e:
                _settle(stage="check", error=e)
                return
            _settle(result=result)
        finally:
            _POLKIT_SLOTS.release()

    worker = threading.Thread(target=_worker, name="polkit-check", daemon=True)
    try:
        worker.start()
    except Exception:
        _POLKIT_SLOTS.release()
        return False, "Polkit check could not start; denied"
    worker.join(timeout)

    with lock:
        if req["status"] == "pending":
            req["status"] = "abandoned"  # any late result is now discarded
            timed_out = True
        else:
            timed_out = False
        snapshot = dict(req)

    if timed_out:
        return False, (
            f"Polkit check timed out after {timeout}s for {action_id}; denied"
        )
    if snapshot["error"] is not None:
        if snapshot["stage"] == "authority":
            return False, f"Polkit authority unavailable: {snapshot['error']}"
        return False, f"Polkit authorization check failed: {snapshot['error']}"

    result = snapshot["result"]
    try:
        authorized = result.get_is_authorized()
        challenge = result.get_is_challenge()
    except Exception as e:
        return False, f"Polkit returned an invalid response: {e}"

    if authorized is True:
        return True, "polkit authorized"
    if challenge is True:
        return False, "authentication required"
    if authorized is False:
        return False, "not authorized"
    return False, f"Polkit returned an invalid response: {authorized!r}"


def _check_authorization(sender, action_id: str, bus=None,
                         allow_same_user: bool = False) -> tuple:
    """Authorize a D-Bus method call.

    Authorization model (Phase 2.3 — FAIL-CLOSED for all state changes):
      0. No D-Bus (HAS_DBUS=False) or no bus object: DENY. There is no
         trusted in-process path; a caller whose identity cannot be verified
         is never authorized.
      1. Credentials must be obtainable (PID/UID) → fail closed otherwise.
      2. Root is always authorized.
      3. Same-UID check: caller UID must match service UID. Other local
         accounts cannot control this user's Android environment even if
         they can reach the session bus.
      4. Read-only methods (allow_same_user=True): same-user authorized
         WITHOUT Polkit. These do not change any state.
      5. State-changing methods (allow_same_user=False, the default):
         ALWAYS consult Polkit. There is NO same-user fallback when Polkit
         is unavailable or raises an exception — doing so would convert a
         Polkit failure into a successful authorization, which is the very
         failure mode "fail closed" is meant to prevent.
           - Polkit returns is_authorized=True → allow (active session or
             admin authenticated).
           - Polkit returns is_challenge=True → deny ("authentication required").
           - Polkit returns not-authorized → deny ("not authorized").
           - Polkit module unavailable → deny with a clear error.
           - Polkit authority lookup or check_authorization_sync raises →
             deny with a clear error. The error message identifies whether
             Polkit is unavailable vs an exception was raised.
         Admin vs session actions differ ONLY in what Polkit policy does:
         admin actions trigger an admin password prompt (auth_admin_keep),
         session actions auto-allow active local console (allow_active=yes)
         and challenge inactive sessions. The service treats both uniformly
         at this layer: Polkit's decision is final.

    Args:
        sender: D-Bus sender bus name (provided by dbus-python via
            sender_keyword="sender").
        action_id: Polkit action ID (one of the POLKIT_ACTION_* constants).
        bus: D-Bus connection object (self._bus inside the service class).
        allow_same_user: If True, same-user callers are authorized without
            Polkit consultation. USE ONLY FOR READ-ONLY METHODS. All
            state-changing methods must pass False so that Polkit is the
            sole authority.
    Returns:
        (allowed: bool, reason: str). reason is a short human-readable
        explanation intended for D-Bus error messages; it distinguishes:
          - "root caller"
          - "same-user authorized" (read-only only)
          - "polkit authorized"
          - "authentication required"  (challenge not completed)
          - "not authorized"           (Polkit denied)
          - "Polkit is unavailable: <detail>"
          - "Polkit error: <detail>"
          - "caller uid X does not match service uid Y"
          - "could not determine caller identity: <detail>"
    """
    ok, pid, uid, reason = _get_caller_credentials(sender, bus)
    if not ok:
        return False, reason

    # Root is always authorized. Polkit is not consulted for root, so record
    # root-authorized state changes for audit (read-only calls are not logged).
    if uid == 0:
        if not allow_same_user:
            logger.info("Root authorized state-changing action=%s (Polkit not consulted)",
                        action_id)
        return True, "root caller"

    # Same-user verification — other local accounts are denied
    if uid != SERVICE_UID:
        logger.warning(
            "Denied D-Bus caller uid=%d (service uid=%d) action=%s",
            uid, SERVICE_UID, action_id,
        )
        return False, (
            f"caller uid {uid} does not match service uid {SERVICE_UID}; "
            "other users cannot control this Android session"
        )

    # Read-only methods: same-user is sufficient. Do not consult Polkit.
    if allow_same_user:
        return True, "same-user authorized"

    # ---------------- State-changing path: POLKIT IS REQUIRED ----------------
    # All state-changing actions (admin AND session) require a Polkit
    # authorization result. There is no same-user bypass. If Polkit cannot be
    # reached or raises, we FAIL CLOSED. This is the Phase 2.3 hardening:
    # never convert a Polkit failure into a successful authorization.

    if not HAS_POLKIT:
        logger.warning(
            "Denied action=%s caller uid=%d: Polkit is unavailable; "
            "state-changing actions require Polkit authorization.",
            action_id, uid,
        )
        return False, (
            f"Polkit is unavailable; cannot verify authorization for {action_id}. "
            "State-changing operations require Polkit."
        )

    allowed, reason = _polkit_consult(action_id, pid, uid)
    if not allowed:
        logger.warning("Denied action=%s caller uid=%d: %s", action_id, uid, reason)
    return allowed, reason


# Backwards-compatible alias (old name); prefer _check_authorization in new code.
_check_polkit = _check_authorization


# ---------------------------------------------------------------------------
# Background worker for long-running operations
# ---------------------------------------------------------------------------
class BackgroundWorker:
    """Run operations on a background thread and emit status via signals."""
    def __init__(self, service):
        self.service = service
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _run(self, func, op_name: str, *args, **kwargs):
        try:
            def progress(msg: str):
                logger.info("[%s] %s", op_name, msg)
                if HAS_DBUS:
                    self.service.OperationProgress(op_name, msg)
            kwargs["progress_cb"] = progress
            func(*args, **kwargs)
            if HAS_DBUS:
                self.service.OperationComplete(op_name, True, "")
        except Exception as e:
            logger.error("[%s] failed: %s", op_name, e)
            if HAS_DBUS:
                self.service.OperationComplete(op_name, False, str(e))

    def start(self, func, op_name: str, *args, **kwargs):
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError(f"Another operation is in progress")
            self._thread = threading.Thread(
                target=self._run, args=(func, op_name) + args, kwargs=kwargs,
                daemon=True,
            )
            self._thread.start()


# ---------------------------------------------------------------------------
# D-Bus Service Object
# ---------------------------------------------------------------------------
if HAS_DBUS:
    class BrightAndroidService(dbus.service.Object):
        """D-Bus service object for Bright Android management."""

        def __init__(self, bus, loop=None):
            super().__init__(bus, OBJECT_PATH)
            self._bus = bus
            self._loop = loop
            self._worker = BackgroundWorker(self)
            logger.info("Bright Android D-Bus service initialized")

        @dbus.service.signal(INTERFACE, signature="ss")
        def OperationProgress(self, operation: str, message: str):
            pass

        @dbus.service.signal(INTERFACE, signature="ssb")
        def OperationComplete(self, operation: str, message: str, success: bool):
            pass

        @dbus.service.signal(INTERFACE, signature="sa{sv}")
        def AppInstalled(self, package: str, info: Dict[str, Any]):
            pass

        @dbus.service.signal(INTERFACE, signature="s")
        def AppRemoved(self, package: str):
            pass

        @dbus.service.signal(INTERFACE, signature="b")
        def RuntimeStateChanged(self, running: bool):
            pass

        # --- Informational methods (same-user allowed, no Polkit prompt) ---

        @method(INTERFACE, in_signature="", out_signature="s", sender_keyword="sender")
        def GetVersion(self, sender=None):
            ok, reason = _check_authorization(sender, POLKIT_ACTION_SYNC,
                                              bus=self._bus, allow_same_user=True)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Not authorized: {reason}"
                )
            from bright_android import __version__
            return __version__

        @method(INTERFACE, in_signature="", out_signature="a{sv}", sender_keyword="sender")
        def GetCompatibilityReport(self, sender=None):
            ok, reason = _check_authorization(sender, POLKIT_ACTION_SYNC,
                                              bus=self._bus, allow_same_user=True)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Not authorized: {reason}"
                )
            report = compatibility.run_full_check()
            # Flatten to dbus-compatible dict
            result = {}
            result["can_install"] = report["can_install"]
            result["can_run"] = report["can_run"]
            result["binder_available"] = report["binder"]["binder_available"]
            result["wayland_available"] = report["wayland"]["wayland_available"]
            result["ram_mb"] = report["ram"]["total_mb"]
            result["disk_gb"] = report["disk"]["available_gb"]
            result["waydroid_installed"] = report["packages"]["waydroid_installed"]
            result["initialized"] = report["initialized"]["initialized"]
            result["running"] = waydroid_manager.is_running() if report["packages"]["waydroid_installed"] else False
            result["issues"] = dbus.Array(report["issues"], signature="s")
            result["warnings"] = dbus.Array(report["warnings"], signature="s")
            return dbus.Dictionary(result, signature="sv")

        @method(INTERFACE, in_signature="", out_signature="a{sv}", sender_keyword="sender")
        def GetStatus(self, sender=None):
            ok, reason = _check_authorization(sender, POLKIT_ACTION_SYNC,
                                              bus=self._bus, allow_same_user=True)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Not authorized: {reason}"
                )
            if not waydroid_manager.is_installed():
                return dbus.Dictionary({
                    "installed": False,
                    "initialized": False,
                    "running": False,
                }, signature="sv")
            status = waydroid_manager.get_status()
            return dbus.Dictionary({
                "installed": True,
                "initialized": status["initialized"],
                "running": status["running"],
                "session": status.get("session", "UNKNOWN"),
                "version": status["details"].get("waydroid_version", ""),
            }, signature="sv")

        @method(INTERFACE, in_signature="", out_signature="a{sv}", sender_keyword="sender")
        def GetConfig(self, sender=None):
            ok, reason = _check_authorization(sender, POLKIT_ACTION_SYNC,
                                              bus=self._bus, allow_same_user=True)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Not authorized: {reason}"
                )
            cfg = ba_config.load_config()
            result = {}
            for section in cfg.sections():
                for key, value in cfg.items(section):
                    result[f"{section}/{key}"] = value
            return dbus.Dictionary(result, signature="sv")

        @method(INTERFACE, in_signature="ss", out_signature="", sender_keyword="sender")
        def SetConfig(self, key: str, value: str, sender=None):
            # Setting config requires admin auth
            ok, reason = _check_authorization(sender, POLKIT_ACTION_SET_CONFIG,
                                              bus=self._bus)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Cannot set config: {reason}"
                )
            if "/" not in key:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.InvalidArgument",
                    "Key must be in section/key format"
                )
            section, k = key.split("/", 1)
            ba_config.set_value(section, k, value)

        @method(INTERFACE, in_signature="", out_signature="aa{sv}", sender_keyword="sender")
        def ListApps(self, sender=None):
            ok, reason = _check_authorization(sender, POLKIT_ACTION_SYNC,
                                              bus=self._bus, allow_same_user=True)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Not authorized: {reason}"
                )
            if not waydroid_manager.is_installed() or not waydroid_manager.is_initialized():
                return dbus.Array([], signature="a{sv}")
            try:
                apps = waydroid_manager.list_apps()
                result = []
                for a in apps:
                    result.append(dbus.Dictionary({
                        "package": a["package"],
                        "name": a["name"],
                        "launch_activity": a.get("launch_activity", ""),
                    }, signature="sv"))
                return dbus.Array(result, signature="a{sv}")
            except Exception as e:
                logger.warning("ListApps failed: %s", e)
                return dbus.Array([], signature="a{sv}")

        @method(INTERFACE, in_signature="s", out_signature="a{sv}", sender_keyword="sender")
        def ValidateApk(self, path: str, sender=None):
            ok, reason = _check_authorization(sender, POLKIT_ACTION_SYNC,
                                              bus=self._bus, allow_same_user=True)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Not authorized: {reason}"
                )
            err = apk_validator.validate_apk_path(path)
            if err:
                return dbus.Dictionary({
                    "valid": False,
                    "reason": err,
                    "compatible": False,
                }, signature="sv")
            compat = apk_validator.is_compatible_x86_64(path)
            info = apk_validator.get_app_info(path)
            return dbus.Dictionary({
                "valid": True,
                "compatible": compat["compatible"],
                "architectures": dbus.Array(compat["architectures"], signature="s"),
                "reason": compat["reason"],
                "package_name": info.get("package_name", ""),
                "label": info.get("label", ""),
                "size_bytes": info["size_bytes"],
            }, signature="sv")

        @method(INTERFACE, in_signature="", out_signature="s", sender_keyword="sender")
        def GetDiagnostics(self, sender=None):
            ok, reason = _check_authorization(sender, POLKIT_ACTION_SYNC,
                                              bus=self._bus, allow_same_user=True)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Not authorized: {reason}"
                )
            if not waydroid_manager.is_installed():
                return "Waydroid not installed"
            diag = waydroid_manager.diagnose()
            lines = [f"Waydroid version: {diag.get('waydroid_version', 'unknown')}"]
            lines.append(f"Initialized: {diag['initialized']}")
            lines.append(f"Running: {diag['running']}")
            if "data_size_mb" in diag:
                lines.append(f"Data size: {diag['data_size_mb']} MB")
            for issue in diag.get("issues", []):
                lines.append(f"Issue: {issue}")
            for sug in diag.get("suggestions", []):
                lines.append(f"Suggestion: {sug}")
            return "\n".join(lines)

        # --- Privileged operations (require Polkit auth) ---

        @method(INTERFACE, in_signature="", out_signature="", sender_keyword="sender")
        def InitializeRuntime(self, sender=None):
            ok, reason = _check_authorization(sender, POLKIT_ACTION_INIT,
                                              bus=self._bus)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Initialization requires admin auth: {reason}"
                )
            self._worker.start(waydroid_manager.init, "init", mode="auto")

        @method(INTERFACE, in_signature="", out_signature="", sender_keyword="sender")
        def StartRuntime(self, sender=None):
            # Session action: Polkit enforces active-session (allow_active=yes
            # auto-allows local console; SSH/inactive sessions are challenged).
            ok, reason = _check_authorization(sender, POLKIT_ACTION_START,
                                              bus=self._bus)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Start requires auth: {reason}"
                )
            try:
                waydroid_manager.start_session()
                launcher_integration.sync_apps(waydroid_manager.list_apps())
                self.RuntimeStateChanged(True)
            except Exception as e:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.StartFailed", str(e)
                )

        @method(INTERFACE, in_signature="", out_signature="", sender_keyword="sender")
        def StopRuntime(self, sender=None):
            # Session action: consult Polkit for active-session verification.
            ok, reason = _check_authorization(sender, POLKIT_ACTION_STOP,
                                              bus=self._bus)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Stop requires auth: {reason}"
                )
            try:
                waydroid_manager.stop_session()
                self.RuntimeStateChanged(False)
            except Exception as e:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.StopFailed", str(e)
                )

        @method(INTERFACE, in_signature="s", out_signature="", sender_keyword="sender")
        def InstallApk(self, path: str, sender=None):
            ok, reason = _check_authorization(sender, POLKIT_ACTION_INSTALL,
                                              bus=self._bus)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"APK install requires auth: {reason}"
                )
            try:
                result = waydroid_manager.install_apk(path)
                launcher_integration.sync_apps(waydroid_manager.list_apps())
                self.AppInstalled(result["package"], dbus.Dictionary({
                    "label": result.get("label", ""),
                    "path": result.get("path", ""),
                }, signature="sv"))
            except Exception as e:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.InstallFailed", str(e)
                )

        @method(INTERFACE, in_signature="s", out_signature="", sender_keyword="sender")
        def UninstallApp(self, package: str, sender=None):
            # Session action: consult Polkit for active-session verification.
            ok, reason = _check_authorization(sender, POLKIT_ACTION_UNINSTALL,
                                              bus=self._bus)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Uninstall requires auth: {reason}"
                )
            try:
                waydroid_manager.uninstall_app(package)
                launcher_integration.remove_app_desktop_entry(package)
                self.AppRemoved(package)
            except Exception as e:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.UninstallFailed", str(e)
                )

        @method(INTERFACE, in_signature="s", out_signature="b", sender_keyword="sender")
        def LaunchApp(self, package: str, sender=None):
            # Session action: Polkit's allow_active=yes auto-authorizes active
            # console sessions without prompting.
            ok, reason = _check_authorization(sender, POLKIT_ACTION_LAUNCH,
                                              bus=self._bus)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Launch not authorized: {reason}"
                )
            try:
                waydroid_manager.launch_app(package)
                return True
            except Exception as e:
                logger.error("Launch failed: %s", e)
                return False

        @method(INTERFACE, in_signature="", out_signature="", sender_keyword="sender")
        def SyncAppList(self, sender=None):
            """Refresh launcher integration (session action; Polkit verifies active)."""
            ok, reason = _check_authorization(sender, POLKIT_ACTION_SYNC,
                                              bus=self._bus)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Sync not authorized: {reason}"
                )
            if waydroid_manager.is_running():
                apps = waydroid_manager.list_apps()
                launcher_integration.sync_apps(apps)
            else:
                launcher_integration.remove_all_android_entries()

else:
    # Stub for headless/non-D-Bus operation
    class BrightAndroidService:
        def __init__(self, bus=None, loop=None):
            logger.warning("D-Bus not available; running in headless mode")
            self._loop = loop


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main():
    """Entry point for bright-android-service."""
    import argparse
    parser = argparse.ArgumentParser(description="Bright Android D-Bus service")
    parser.add_argument("--session", action="store_true",
                        help="Use session bus instead of system bus")
    parser.add_argument("--foreground", action="store_true",
                        help="Run in foreground (don't daemonize)")
    parser.add_argument("--version", action="store_true",
                        help="Print version and exit")
    args = parser.parse_args()

    from bright_android import __version__
    if args.version:
        print(f"bright-android-service {__version__}")
        return 0

    ba_config.create_default_config_file()

    if not HAS_DBUS:
        logger.error(
            "python3-dbus not available; cannot start D-Bus service.\n"
            "Install python3-dbus and python3-gi for full functionality."
        )
        return 1

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    if args.session:
        bus = dbus.SessionBus()
    else:
        bus = dbus.SystemBus()

    bus_name = dbus.service.BusName(BUS_NAME, bus)
    service = BrightAndroidService(bus)

    loop = GLib.MainLoop()
    service._loop = loop

    # Handle signals
    def handle_sigterm(sig, frame):
        logger.info("Received signal %s; shutting down", sig)
        if loop.is_running():
            loop.quit()

    import signal as sig_mod
    sig_mod.signal(sig_mod.SIGTERM, handle_sigterm)
    sig_mod.signal(sig_mod.SIGINT, handle_sigterm)

    logger.info(
        "Bright Android service started (bus=%s, name=%s)",
        "session" if args.session else "system", BUS_NAME,
    )

    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Bright Android service stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
