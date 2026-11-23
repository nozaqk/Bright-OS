"""Waydroid runtime manager for Bright Android.

Provides safe, asynchronous-friendly wrappers around waydroid CLI commands.
All subprocess calls use argument lists (no shell=True). Handles missing
binaries, timeouts, and error reporting without silently claiming success.
"""
import os
import shutil
import subprocess
import logging
import shlex
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Tuple
from functools import wraps

logger = logging.getLogger("bright_android.waydroid")

WAYDROID_BIN = "waydroid"
WAYDROID_DATA = "/var/lib/waydroid"
WAYDROID_IMAGES = ["system.img", "vendor.img"]
WAYDROID_PROP = "/var/lib/waydroid/waydroid_base.prop"
APP_DESKTOP_DIR = os.path.expanduser("~/.local/share/applications")
ANDROID_APP_PREFIX = "bright-android-app-"

# Valid init options
VALID_MODES = ["auto", "regular", "gapps"]  # gapps is NOT default; requires user action


class WaydroidError(Exception):
    """Raised when a waydroid operation fails."""
    def __init__(self, message: str, exit_code: int = -1, stderr: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


def _require_waydroid(func):
    """Decorator that checks waydroid is installed before calling."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_installed():
            raise WaydroidError(
                "Waydroid is not installed. Install it first via the "
                "Bright Android setup wizard.",
                exit_code=127,
            )
        return func(*args, **kwargs)
    return wrapper


def is_installed() -> bool:
    """Check if waydroid binary is available."""
    return shutil.which(WAYDROID_BIN) is not None


def is_initialized() -> bool:
    """Check if the Android image has been downloaded/initialized."""
    data = Path(WAYDROID_DATA)
    if not data.exists():
        return False
    has_images = any(
        (data / img).exists() for img in WAYDROID_IMAGES
    )
    has_prop = (data / "waydroid_base.prop").exists()
    return has_images and has_prop


def is_running() -> bool:
    """Check if the Waydroid container is currently running."""
    rc, out, err = _run(["status"], timeout=10)
    if rc != 0:
        return False
    return "RUNNING" in out.upper() or "Session:\tRUNNING" in out


def _run(args: List[str], timeout: int = 60, as_root: bool = False,
         input_text: Optional[str] = None) -> Tuple[int, str, str]:
    """Run a waydroid subcommand safely.

    Args:
        args: waydroid subcommand + arguments (NOT including 'waydroid' itself)
        timeout: maximum seconds
        as_root: prepend pkexec for privilege escalation
        input_text: optional stdin text
    Returns:
        (exit_code, stdout, stderr)
    """
    cmd = [WAYDROID_BIN] + args
    if as_root:
        cmd = ["pkexec", WAYDROID_BIN] + args

    logger.debug("Running: %s", " ".join(shlex.quote(c) for c in cmd))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
            env={**os.environ, "LC_ALL": "C"},
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"Timed out after {timeout}s"
    except Exception as e:
        return 1, "", str(e)


@_require_waydroid
def init(mode: str = "auto", progress_cb: Optional[Callable[[str], None]] = None) -> bool:
    """Initialize the Waydroid installation (download images).

    This is a long-running operation. Call from a background thread.

    Args:
        mode: 'auto' (vanilla) or 'regular' (vanilla). 'gapps' is not
              offered as a default due to Google licensing and is
              intentionally NOT called unless the user explicitly opts in.
        progress_cb: optional callback receiving status lines
    Returns:
        True on success
    Raises:
        WaydroidError on failure
    """
    if mode not in VALID_MODES:
        raise WaydroidError(f"Invalid init mode: {mode}")

    if is_initialized():
        logger.info("Waydroid already initialized")
        return True

    def _emit(msg: str):
        if progress_cb:
            progress_cb(msg)
        logger.info(msg)

    _emit("Initializing Waydroid (downloading Android images, may take a while)...")

    # 'waydroid init' must run as root (to write to /var/lib/waydroid and /etc/waydroid)
    args = ["init", "-f"]
    if mode in ("regular", "auto"):
        args.extend(["-s", "VANILLA"])

    rc, out, err = _run(args, timeout=600, as_root=True)

    if rc != 0:
        _emit(f"Init failed: {err or out}")
        raise WaydroidError(
            f"Waydroid initialization failed (exit {rc})",
            exit_code=rc,
            stderr=err or out,
        )

    _emit("Waydroid initialized successfully")
    return True


@_require_waydroid
def get_status() -> Dict[str, Any]:
    """Get current Waydroid runtime status."""
    status = {
        "installed": True,
        "initialized": is_initialized(),
        "running": False,
        "session": "UNKNOWN",
        "details": {},
    }

    if not is_initialized():
        return status

    rc, out, err = _run(["status"], timeout=10)
    if rc == 0:
        for line in out.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip().lower().replace(" ", "_")
                val = val.strip()
                status["details"][key] = val
                if "session" in key:
                    status["session"] = val
                    if val.upper() == "RUNNING":
                        status["running"] = True

    # Check for waydroid container via lxc-info
    rc, out, err = _run(["shell", "echo", "Android alive"], timeout=10)
    if rc == 0 and "Android alive" in out:
        status["running"] = True
        status["session"] = "RUNNING"

    return status


@_require_waydroid
def start_session() -> bool:
    """Start the Waydroid session.

    Launches the waydroid session (Wayland client). Does NOT require root
    for the user session part, but initial container start does.
    """
    if is_running():
        logger.info("Waydroid already running")
        return True

    logger.info("Starting Waydroid session...")
    rc, out, err = _run(["session", "start"], timeout=60, as_root=False)
    if rc != 0:
        # Try with pkexec (needed first time to set up LXC container)
        rc, out, err = _run(["session", "start"], timeout=120, as_root=True)
        if rc != 0:
            raise WaydroidError(
                f"Failed to start Waydroid session: {err or out}",
                exit_code=rc, stderr=err or out
            )

    # Wait for session to come up
    for _ in range(30):
        if is_running():
            logger.info("Waydroid session started")
            return True
        time.sleep(1)

    raise WaydroidError("Waydroid session did not start within 30 seconds")


@_require_waydroid
def stop_session() -> bool:
    """Stop the Waydroid session."""
    if not is_running():
        return True

    logger.info("Stopping Waydroid session...")
    rc, out, err = _run(["session", "stop"], timeout=30, as_root=True)
    if rc != 0:
        # Try non-root session stop
        rc, out, err = _run(["session", "stop"], timeout=30, as_root=False)
        if rc != 0:
            raise WaydroidError(
                f"Failed to stop Waydroid session: {err or out}",
                exit_code=rc, stderr=err or out
            )
    logger.info("Waydroid session stopped")
    return True


@_require_waydroid
def install_apk(apk_path: str, progress_cb: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Install an APK file into the running Android container.

    Args:
        apk_path: path to .apk file (must be validated first)
    Returns:
        Dict with 'success', 'package', 'message'
    """
    from .apk_validator import validate_apk_path, is_compatible_x86_64, get_app_info

    err = validate_apk_path(apk_path)
    if err:
        raise WaydroidError(f"Invalid APK: {err}")

    compat = is_compatible_x86_64(apk_path)
    if not compat["compatible"]:
        # We still allow attempting the install, but warn
        logger.warning("APK may not be compatible: %s", compat["reason"])

    if not is_running():
        raise WaydroidError("Android runtime is not running. Start it first.")

    if progress_cb:
        progress_cb(f"Installing {os.path.basename(apk_path)}...")

    # waydroid app install <path>
    rc, out, err = _run(["app", "install", apk_path], timeout=120)
    if rc != 0:
        raise WaydroidError(
            f"APK installation failed: {err or out}",
            exit_code=rc, stderr=err or out,
        )

    info = get_app_info(apk_path)
    logger.info("APK installed: %s", info.get("package_name") or apk_path)

    return {
        "success": True,
        "package": info.get("package_name", ""),
        "label": info.get("label", os.path.basename(apk_path)),
        "path": apk_path,
        "message": f"Installed: {info.get('label', os.path.basename(apk_path))}",
    }


@_require_waydroid
def uninstall_app(package_name: str) -> Dict[str, Any]:
    """Uninstall an Android app by package name."""
    if not package_name or not package_name.replace(".", "").replace("_", "").isalnum():
        raise WaydroidError(f"Invalid package name: {package_name}")

    if not is_running():
        raise WaydroidError("Android runtime is not running")

    rc, out, err = _run(["app", "remove", package_name], timeout=60)
    if rc != 0:
        raise WaydroidError(
            f"Failed to uninstall {package_name}: {err or out}",
            exit_code=rc, stderr=err or out,
        )

    logger.info("Uninstalled app: %s", package_name)
    return {"success": True, "package": package_name}


@_require_waydroid
def list_apps() -> List[Dict[str, str]]:
    """List installed Android applications.

    Returns a list of dicts with: name, package, intent (for launching).
    """
    apps = []
    if not is_initialized():
        return apps

    # 'waydroid app list' returns lines like:
    # package:com.example.app  launcher:com.example/.MainActivity
    rc, out, err = _run(["app", "list"], timeout=30)
    if rc != 0:
        logger.warning("Could not list apps: %s", err)
        return apps

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pkg = ""
        launch_activity = ""
        for part in line.split():
            if part.startswith("package:"):
                pkg = part[8:]
            elif part.startswith("launcher:"):
                launch_activity = part[9:]
        if pkg:
            apps.append({
                "package": pkg,
                "name": _app_name_from_package(pkg),
                "launch_activity": launch_activity,
            })
    return apps


def _app_name_from_package(pkg: str) -> str:
    """Guess a human-readable name from package name."""
    parts = pkg.split(".")
    if parts:
        name = parts[-1].replace("_", " ").replace("-", " ")
        return name.title() if name else pkg
    return pkg


@_require_waydroid
def launch_app(package_name: str) -> bool:
    """Launch an Android application by package name."""
    if not is_running():
        raise WaydroidError("Android runtime is not running. Start it first.")

    # 'waydroid app launch <package>'
    rc, out, err = _run(["app", "launch", package_name], timeout=15)
    if rc != 0:
        # Try with intent
        rc, out, err = _run(["shell", "am", "start", "-n",
                             f"{package_name}/.MainActivity"], timeout=15)
        if rc != 0:
            raise WaydroidError(
                f"Failed to launch {package_name}: {err or out}",
                exit_code=rc, stderr=err or out,
            )
    logger.info("Launched app: %s", package_name)
    return True


@_require_waydroid
def get_logs(lines: int = 100) -> str:
    """Get Android/container logs (for developer tools)."""
    # waydroid log
    rc, out, err = _run(["log"], timeout=10)
    if rc == 0:
        log_lines = out.splitlines()
        return "\n".join(log_lines[-lines:])
    return err or out


@_require_waydroid
def diagnose() -> Dict[str, Any]:
    """Run diagnostic checks and return status report."""
    report = {
        "waydroid_installed": True,
        "waydroid_version": "",
        "initialized": is_initialized(),
        "running": is_running(),
        "issues": [],
        "suggestions": [],
    }

    rc, out, _ = _run(["--version"], timeout=5)
    if rc == 0:
        report["waydroid_version"] = out.strip()

    if not is_initialized():
        report["issues"].append("Android image not initialized")
        report["suggestions"].append("Run 'Initialize Android' to download images")
    elif not is_running():
        report["issues"].append("Android runtime is stopped")
        report["suggestions"].append("Start the Android runtime")

    # Check data path size
    data_path = Path(WAYDROID_DATA)
    if data_path.exists():
        total_size = 0
        for f in data_path.rglob("*"):
            if f.is_file():
                try:
                    total_size += f.stat().st_size
                except OSError:
                    pass
        report["data_size_mb"] = round(total_size / (1024 * 1024))

    return report
