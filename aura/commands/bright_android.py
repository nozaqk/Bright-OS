"""AURA command handlers for Bright Android integration.

Allows AURA AI to respond to user requests about Android apps
by communicating with the org.bright_os.BrightAndroid D-Bus service.

AURA may:
  - Check Android runtime status
  - List installed Android apps
  - Launch an already-installed app (after user confirmation)
  - Diagnose Android issues
  - Recommend installation

AURA must request user confirmation before:
  - Installing the Android runtime
  - Installing APKs
  - Uninstalling apps
  - Removing data
"""
import logging
import subprocess
import shutil
from typing import Dict, List, Optional, Any

logger = logging.getLogger("aura.commands.bright_android")

ANDROID_BUS_NAME = "org.bright_os.BrightAndroid"
ANDROID_OBJECT_PATH = "/org/bright_os/BrightAndroid"
ANDROID_INTERFACE = "org.bright_os.BrightAndroid"


def _bright_android_available() -> bool:
    """Check if the bright-android D-Bus service is running."""
    try:
        import dbus
        bus = dbus.SessionBus()
        bus.get_object(ANDROID_BUS_NAME, ANDROID_OBJECT_PATH)
        return True
    except Exception:
        return False


def _call_android_method(method_name: str, *args, **kwargs) -> Any:
    """Call a Bright Android D-Bus method. Returns result or raises."""
    import dbus
    bus = dbus.SessionBus()
    obj = bus.get_object(ANDROID_BUS_NAME, ANDROID_OBJECT_PATH)
    method = obj.get_dbus_method(method_name, ANDROID_INTERFACE)
    return method(*args, **kwargs)


def is_android_runtime_installed() -> bool:
    """Check if waydroid/Android runtime is installed."""
    return shutil.which("waydroid") is not None


def get_android_status() -> Dict[str, Any]:
    """Get Android runtime status for AURA responses."""
    status = {
        "available": False,
        "installed": is_android_runtime_installed(),
        "running": False,
        "initialized": False,
        "app_count": 0,
        "apps": [],
    }
    if is_android_runtime_installed():
        try:
            from bright_android.core import waydroid_manager
            status["initialized"] = waydroid_manager.is_initialized()
            status["running"] = waydroid_manager.is_running()
            if status["running"]:
                apps = waydroid_manager.list_apps()
                status["apps"] = apps
                status["app_count"] = len(apps)
            status["available"] = True
        except Exception as e:
            logger.warning("Could not get Android status: %s", e)
    return status


def list_android_apps() -> List[Dict[str, str]]:
    """List installed Android apps for AURA responses."""
    status = get_android_status()
    return status.get("apps", [])


def launch_android_app(package_name: str) -> Dict[str, Any]:
    """Launch an Android app. AURA must confirm with user first."""
    if not is_android_runtime_installed():
        return {"success": False, "message": "Android runtime is not installed"}
    try:
        from bright_android.core import waydroid_manager
        if not waydroid_manager.is_running():
            return {"success": False, "message":
                    "Android is not running. Start it first via Bright Android."}
        waydroid_manager.launch_app(package_name)
        return {"success": True, "message": f"Launched {package_name}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def get_install_recommendation() -> str:
    """Return a human-readable recommendation about installing Android."""
    if is_android_runtime_installed():
        return "Bright Android is already installed."
    return (
        "Android support can be installed via Bright Android settings. "
        "You can open Bright Android from the application launcher to set it up. "
        "This requires downloading the Android system image (~400-700 MB) "
        "and administrator privileges."
    )


def requires_confirmation(action: str) -> bool:
    """Check if an action requires explicit user confirmation before AURA executes it."""
    privileged_actions = {
        "install_runtime", "init_runtime", "install_apk",
        "uninstall_app", "remove_data", "stop_runtime",
    }
    return action in privileged_actions
