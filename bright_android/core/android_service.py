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
# Polkit authorization
# ---------------------------------------------------------------------------
POLKIT_ACTION_INIT = "org.bright_os.BrightAndroid.init"
POLKIT_ACTION_START = "org.bright_os.BrightAndroid.start"
POLKIT_ACTION_STOP = "org.bright_os.BrightAndroid.stop"
POLKIT_ACTION_INSTALL = "org.bright_os.BrightAndroid.install-apk"
POLKIT_ACTION_UNINSTALL = "org.bright_os.BrightAndroid.uninstall-app"
POLKIT_ACTION_REMOVE_DATA = "org.bright_os.BrightAndroid.remove-data"


def _check_polkit(sender, action_id: str, bus=None) -> tuple:
    """Check Polkit authorization.

    Returns (allowed: bool, reason: str).
    - If Polkit is unavailable and sender is root, allow.
    - If Polkit is unavailable and sender is not root, deny (fail closed).
    - If Polkit is available, query authority.
    """
    if sender is None:
        return False, "No sender"

    # Get PID of caller
    pid = None
    uid = None
    if bus is not None and HAS_DBUS:
        try:
            dbus_info = bus.get_unix_process_id(sender)
            pid = dbus_info.get("pid") if isinstance(dbus_info, dict) else None
            uid_info = bus.get_unix_user_id(sender)
            uid = uid_info.get("uid") if isinstance(uid_info, dict) else None
        except Exception:
            pass

    # Validate pid/uid
    if not isinstance(pid, int) or pid <= 0:
        return False, "Invalid or missing PID"
    if not isinstance(uid, int) or uid < 0:
        return False, "Invalid or missing UID"

    # Root is always allowed (for system services)
    if uid == 0:
        return True, "root"

    if not HAS_POLKIT:
        # Polkit unavailable: only root can do privileged ops (fail closed)
        return False, "Polkit unavailable; operation requires root"

    try:
        authority = Polkit.Authority.get_sync(None)
        subject = Polkit.UnixProcess.new(pid)
        result = authority.check_authorization_sync(
            subject, action_id, None,
            Polkit.CheckAuthorizationFlags.ALLOW_USER_INTERACTION,
            None,
        )
        if result.get_is_authorized():
            return True, "authorized"
        elif result.get_is_challenge():
            return False, "authentication required"
        else:
            return False, "not authorized"
    except Exception as e:
        logger.warning("Polkit check failed for %s: %s", action_id, e)
        return False, f"Polkit error: {e}"


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

        # --- Informational methods (no auth required) ---

        @method(INTERFACE, in_signature="", out_signature="s")
        def GetVersion(self):
            from bright_android import __version__
            return __version__

        @method(INTERFACE, in_signature="", out_signature="a{sv}")
        def GetCompatibilityReport(self):
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

        @method(INTERFACE, in_signature="", out_signature="a{sv}")
        def GetStatus(self):
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

        @method(INTERFACE, in_signature="", out_signature="a{sv}")
        def GetConfig(self):
            cfg = ba_config.load_config()
            result = {}
            for section in cfg.sections():
                for key, value in cfg.items(section):
                    result[f"{section}/{key}"] = value
            return dbus.Dictionary(result, signature="sv")

        @method(INTERFACE, in_signature="ss", out_signature="", sender_keyword="sender")
        def SetConfig(self, key: str, value: str, sender=None):
            # Setting config requires auth
            ok, reason = _check_polkit(sender, POLKIT_ACTION_START,
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

        @method(INTERFACE, in_signature="", out_signature="aa{sv}")
        def ListApps(self):
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

        @method(INTERFACE, in_signature="s", out_signature="a{sv}")
        def ValidateApk(self, path: str):
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

        @method(INTERFACE, in_signature="", out_signature="s")
        def GetDiagnostics(self):
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
            ok, reason = _check_polkit(sender, POLKIT_ACTION_INIT,
                                      bus=self._bus)
            if not ok:
                raise dbus.exceptions.DBusException(
                    "org.bright_os.BrightAndroid.NotAuthorized",
                    f"Initialization requires admin auth: {reason}"
                )
            self._worker.start(waydroid_manager.init, "init", mode="auto")

        @method(INTERFACE, in_signature="", out_signature="", sender_keyword="sender")
        def StartRuntime(self, sender=None):
            ok, reason = _check_polkit(sender, POLKIT_ACTION_START,
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
            ok, reason = _check_polkit(sender, POLKIT_ACTION_STOP,
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
            ok, reason = _check_polkit(sender, POLKIT_ACTION_INSTALL,
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
            ok, reason = _check_polkit(sender, POLKIT_ACTION_UNINSTALL,
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
            # Launching doesn't require admin auth (user action)
            # But sender must be the console user — allow without polkit for now
            # (AURA must request confirmation before calling this)
            try:
                waydroid_manager.launch_app(package)
                return True
            except Exception as e:
                logger.error("Launch failed: %s", e)
                return False

        @method(INTERFACE, in_signature="", out_signature="", sender_keyword="sender")
        def SyncAppList(self, sender=None):
            """Refresh launcher integration (no auth required)."""
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
