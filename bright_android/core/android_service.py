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
    """
    if not HAS_DBUS or bus is None:
        # Headless/test mode: no real D-Bus connection (either the dbus module
        # is unavailable, or this is a direct in-process call not through D-Bus).
        # In production, bus is always populated by dbus-python for every
        # D-Bus-dispatched method call. When bus is None we trust the call as
        # coming from our own process (e.g. internal signal handlers, unit tests
        # that construct the service directly). This path is NOT reachable from
        # a remote D-Bus caller because dbus-python always supplies a sender and
        # bus for actual D-Bus method invocations.
        return True, 0, SERVICE_UID, "in-process call (no D-Bus bus)"

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


def _check_authorization(sender, action_id: str, bus=None,
                         allow_same_user: bool = False) -> tuple:
    """Authorize a D-Bus method call.

    Authorization model (Phase 2.2):
      0. In-process calls (no bus, or HAS_DBUS=False): allow (trusted path).
         Not reachable from a remote D-Bus peer.
      1. Credentials must be obtainable (PID/UID) → fail closed otherwise.
      2. Root is always authorized.
      3. Same-UID check: caller UID must match service UID. Other local
         accounts cannot control this user's Android environment even if
         they can reach the session bus.
      4. For read-only methods (allow_same_user=True, no action_id needed):
         allow the same user without consulting Polkit.
      5. For state-changing methods (allow_same_user=False, the default):
         - Consult Polkit. For actions with allow_active=yes (start/stop/
           launch/sync/uninstall), Polkit automatically authorizes callers
           in the active local console session without prompting, but
           denies or challenges callers from inactive sessions (e.g. SSH).
           For admin actions (init/install-apk/remove-data/set-config),
           Polkit requires admin authentication.
         - If Polkit is unavailable (polkitd unreachable, no agent):
             * PRIVILEGED admin actions: FAIL CLOSED. These are destructive
               (init, install-apk, remove-data, set-config) and must not run
               without verified authorization.
             * USER session actions (start/stop/uninstall/launch/sync):
               allow the same user. These are user-scoped actions that
               control the caller's own session; a broken Polkit must not
               lock the user out of their own Android environment. This
               fallback only applies when uid == SERVICE_UID; other UIDs
               are already denied at step 3.

    Args:
        sender: D-Bus sender bus name (provided by dbus-python via
            sender_keyword="sender").
        action_id: Polkit action ID (one of the POLKIT_ACTION_* constants).
        bus: D-Bus connection object (self._bus inside the service class).
        allow_same_user: If True, same-user callers are authorized without
            Polkit consultation. Use ONLY for read-only methods that do
            not change any state. State-changing methods must pass False
            so Polkit can verify active-session status.
    Returns:
        (allowed: bool, reason: str)
    """
    ok, pid, uid, reason = _get_caller_credentials(sender, bus)
    if not ok:
        return False, reason

    # In-process / headless mode: _get_caller_credentials returned ok=True
    # with reason indicating this is not a real D-Bus call. Allow.
    if "in-process" in reason or "headless" in reason:
        return True, reason

    # Root is always authorized for any action
    if uid == 0:
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

    # Read-only methods: same-user is sufficient. Do not consult Polkit
    # (no state change; no active-session concern).
    if allow_same_user:
        return True, "same-user authorized"

    # Determine whether this is a privileged (admin) action or a user-session
    # action. Admin actions always require Polkit and fail closed when Polkit
    # is unavailable. User-session actions fall back to same-user allow when
    # Polkit is unreachable (don't brick the user's own session).
    admin_actions = {
        POLKIT_ACTION_INIT,
        POLKIT_ACTION_INSTALL,
        POLKIT_ACTION_REMOVE_DATA,
        POLKIT_ACTION_SET_CONFIG,
    }
    is_admin_action = action_id in admin_actions

    # For state-changing actions, query Polkit
    if not HAS_POLKIT:
        if is_admin_action:
            return False, (
                "Polkit is unavailable; cannot verify authorization for "
                f"{action_id}. Only root may perform this action."
            )
        else:
            # User-session action: same-user fallback. Log a warning so the
            # administrator can notice the Polkit outage.
            logger.warning(
                "Polkit unavailable; allowing same-user session action %s "
                "(uid=%d) because this is a non-destructive user-session action.",
                action_id, uid,
            )
            return True, "same-user authorized (Polkit unavailable, user session action)"

    try:
        authority = Polkit.Authority.get_sync(None)
        subject = Polkit.UnixProcess.new(pid)
        result = authority.check_authorization_sync(
            subject,
            action_id,
            None,
            Polkit.CheckAuthorizationFlags.ALLOW_USER_INTERACTION,
            None,
        )
        if result.get_is_authorized():
            return True, "polkit authorized"
        elif result.get_is_challenge():
            return False, "authentication required"
        else:
            return False, "not authorized"
    except Exception as e:
        logger.warning(
            "Polkit check failed for action=%s pid=%d uid=%d: %s",
            action_id, pid, uid, e,
        )
        if is_admin_action:
            return False, f"polkit error: {e}"
        else:
            # Same fallback as Polkit-unavailable for user-session actions.
            logger.warning(
                "Polkit error; allowing same-user session action %s.",
                action_id,
            )
            return True, "same-user authorized (Polkit error, user session action)"


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
