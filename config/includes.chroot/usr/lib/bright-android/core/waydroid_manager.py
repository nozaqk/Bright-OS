"""Waydroid runtime manager for Bright Android.

Provides safe, async-friendly wrappers around the waydroid CLI. All subprocess
calls use argument lists (no shell=True). Handles missing binaries, timeouts,
and reports actionable errors without silently claiming success.

Waydroid CLI reference (Waydroid 1.4+ on Debian Trixie):
  waydroid status                 # Show container + session status
  waydroid init [-s VANILLA|GAPPS] [-f]  # Download/initialize images (root)
  waydroid session start          # Start user session
  waydroid session stop           # Stop session
  waydroid container start        # Start the LXC container (usually done by session)
  waydroid container stop         # Stop container
  waydroid app install <path>     # Install APK into running container
  waydroid app remove <package>   # Uninstall app
  waydroid app list               # List installed apps
  waydroid app launch <package>   # Launch an app
  waydroid shell <cmd...>         # Run a shell command inside Android
  waydroid log                    # Show logs
  waydroid prop get <prop>        # Get Android property
  waydroid --version              # Print version

Privilege model:
- `waydroid init` writes to /var/lib/waydroid and /etc/waydroid → needs root (pkexec)
- `waydroid session start` initially needs root to set up the container, then
  runs a user-level Wayland client. We try as user first, then pkexec.
- `waydroid app install/remove/launch` work without root when the session is up.
- `waydroid app list` and `waydroid status` work without root.
"""
import os
import shutil
import subprocess
import logging
import shlex
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Tuple
from functools import wraps

logger = logging.getLogger("bright_android.waydroid")

WAYDROID_BIN = "waydroid"
WAYDROID_DATA = "/var/lib/waydroid"
WAYDROID_IMAGES = ["system.img", "vendor.img"]
WAYDROID_PROP = "/var/lib/waydroid/waydroid_base.prop"
WAYDROID_CONFIG = "/etc/waydroid/waydroid.cfg"

# Valid init options
VALID_MODES = ["auto", "regular", "vanilla", "gapps"]  # gapps is NOT default
DEFAULT_MODE = "vanilla"  # VANILLA — no Google services by default

# Status cache (avoid hammering waydroid on every GUI refresh)
_status_cache: Dict[str, Any] = {}
_status_cache_lock = threading.Lock()
_STATUS_CACHE_TTL = 3.0  # seconds


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
                "Waydroid is not installed. Install it with:\n"
                "  sudo apt install waydroid",
                exit_code=127,
            )
        return func(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def is_installed() -> bool:
    """Check if waydroid binary is available."""
    return shutil.which(WAYDROID_BIN) is not None


def is_initialized() -> bool:
    """Check if the Android image has been downloaded/initialized."""
    data = Path(WAYDROID_DATA)
    if not data.exists():
        return False
    has_images = any((data / img).exists() for img in WAYDROID_IMAGES)
    has_prop = (data / "waydroid_base.prop").exists()
    return has_images and has_prop


def _invalidate_status_cache():
    with _status_cache_lock:
        _status_cache.clear()


def _run(args: List[str], timeout: int = 60, as_root: bool = False,
         input_text: Optional[str] = None) -> Tuple[int, str, str]:
    """Run a waydroid subcommand safely with argv lists (never shell=True).

    Args:
        args: waydroid subcommand + args (NOT including 'waydroid')
        timeout: max seconds
        as_root: prepend pkexec to run as root via Polkit
        input_text: optional stdin
    Returns:
        (exit_code, stdout, stderr)
    """
    if as_root:
        cmd = ["pkexec", WAYDROID_BIN] + args
    else:
        cmd = [WAYDROID_BIN] + args

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
        _invalidate_status_cache()
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"Timed out after {timeout}s"
    except PermissionError as e:
        return 1, "", f"Permission denied: {e}"
    except Exception as e:
        return 1, "", str(e)


# ---------------------------------------------------------------------------
# Status detection (parses real `waydroid status` output)
# ---------------------------------------------------------------------------

def _parse_status_output(out: str) -> Dict[str, Any]:
    """Parse the output of `waydroid status`.

    Typical output (Waydroid 1.4):
      Session:       RUNNING
      Container:     RUNNING
      Vendor type:   MAINLINE
      ...
    Or stopped:
      Session:       STOPPED
      Container:     STOPPED
    """
    info: Dict[str, str] = {}
    for line in out.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            key_norm = key.strip().lower().replace(" ", "_")
            info[key_norm] = val.strip()
    session = info.get("session", "STOPPED").upper()
    container = info.get("container", "STOPPED").upper()
    return {
        "session": session,
        "container": container,
        "details": info,
    }


@_require_waydroid
def get_status(force_refresh: bool = False) -> Dict[str, Any]:
    """Get current Waydroid runtime status, with short-lived caching.

    Returns:
        {installed, initialized, running, starting, stopping, session,
         container, session_user, details}
    """
    now = time.monotonic()
    with _status_cache_lock:
        if not force_refresh and _status_cache.get("ts", 0) > now - _STATUS_CACHE_TTL:
            return dict(_status_cache["data"])

    status: Dict[str, Any] = {
        "installed": True,
        "initialized": is_initialized(),
        "running": False,
        "starting": False,
        "stopping": False,
        "session": "STOPPED",
        "container": "STOPPED",
        "details": {},
    }

    if not status["initialized"]:
        with _status_cache_lock:
            _status_cache["data"] = dict(status)
            _status_cache["ts"] = now
        return status

    rc, out, err = _run(["status"], timeout=10)
    if rc == 0 and out:
        parsed = _parse_status_output(out)
        status["session"] = parsed["session"]
        status["container"] = parsed["container"]
        status["details"] = parsed["details"]
        status["running"] = (
            parsed["session"] == "RUNNING" and parsed["container"] in ("RUNNING", "FROZEN")
        )
        status["starting"] = parsed["session"] in ("STARTING", "INITIALIZING")
        status["stopping"] = "STOP" in parsed["session"]
    else:
        # If `waydroid status` fails, check lxc-info directly
        rc2, out2, _ = _run(["shell", "echo", "bright-android-probe"], timeout=8)
        if rc2 == 0 and "bright-android-probe" in out2:
            status["running"] = True
            status["session"] = "RUNNING"
            status["container"] = "RUNNING"
        else:
            logger.debug("waydroid status rc=%d err=%s", rc, (err or out).strip()[:200])

    with _status_cache_lock:
        _status_cache["data"] = dict(status)
        _status_cache["ts"] = now
    return status


def is_running() -> bool:
    """Convenience: check if the Waydroid session+container are up."""
    if not is_installed() or not is_initialized():
        return False
    return get_status().get("running", False)


# ---------------------------------------------------------------------------
# Runtime lifecycle
# ---------------------------------------------------------------------------

@_require_waydroid
def init(mode: str = DEFAULT_MODE, progress_cb: Optional[Callable[[str], None]] = None) -> bool:
    """Initialize the Waydroid installation (download Android images).

    Long-running operation (downloads ~400-700 MB). Call from a background
    thread. Requires root (pkexec) to write to /var/lib/waydroid and
    /etc/waydroid.

    Args:
        mode: 'vanilla'/'auto'/'regular' = VANILLA image.
              'gapps' requires explicit user opt-in (not default).
    Returns:
        True on success
    Raises:
        WaydroidError on failure
    """
    if mode == "auto" or mode == "regular":
        mode = "vanilla"
    if mode not in VALID_MODES:
        raise WaydroidError(f"Invalid init mode: {mode}")

    if is_initialized():
        logger.info("Waydroid already initialized")
        if progress_cb:
            progress_cb("Already initialized")
        return True

    def _emit(msg: str):
        if progress_cb:
            progress_cb(msg)
        logger.info(msg)

    _emit("Downloading and setting up Android images (this may take several minutes)...")

    # 'waydroid init' must run as root — writes /var/lib/waydroid and /etc/waydroid
    args = ["init", "-f"]
    if mode == "gapps":
        args.extend(["-s", "GAPPS"])
    else:
        args.extend(["-s", "VANILLA"])

    rc, out, err = _run(args, timeout=900, as_root=True)

    if rc != 0:
        err_msg = (err or out or "").strip()
        _emit(f"Init failed: {err_msg}")
        raise WaydroidError(
            f"Waydroid initialization failed (exit {rc}): {err_msg}",
            exit_code=rc,
            stderr=err_msg,
        )

    _emit("Android images installed successfully")
    _invalidate_status_cache()
    return True


@_require_waydroid
def start_session(progress_cb: Optional[Callable[[str], None]] = None) -> bool:
    """Start the Waydroid session (container + Wayland client).

    Tries without root first (the session runs as the user for Wayland
    integration). First-time start may need root to set up the LXC
    container, so we fall back to pkexec with a clear Polkit prompt.
    """
    if is_running():
        logger.info("Waydroid already running")
        return True

    def _emit(msg: str):
        if progress_cb:
            progress_cb(msg)
        logger.info(msg)

    _emit("Starting Android runtime...")

    # Try user-level start first (works when container already exists)
    rc, out, err = _run(["session", "start"], timeout=60, as_root=False)
    if rc != 0:
        _emit("Requesting administrator privileges to start container...")
        rc, out, err = _run(["session", "start"], timeout=120, as_root=True)
        if rc != 0:
            err_msg = (err or out or "").strip()
            # Provide actionable messages
            if "binder" in err_msg.lower():
                raise WaydroidError(
                    f"Binder kernel module not available. Load it with:\n"
                    f"  pkexec modprobe binder_linux\n\nDetails: {err_msg}",
                    exit_code=rc, stderr=err_msg,
                )
            if "wayland" in err_msg.lower():
                raise WaydroidError(
                    f"Wayland session not detected. Start Android from a "
                    f"Wayland session (KWin/Weston).\n\nDetails: {err_msg}",
                    exit_code=rc, stderr=err_msg,
                )
            raise WaydroidError(
                f"Failed to start Waydroid session (exit {rc}): {err_msg}",
                exit_code=rc, stderr=err_msg,
            )

    # Wait for the session to come up (poll with short timeouts)
    _emit("Waiting for Android to start...")
    for attempt in range(45):
        status = get_status(force_refresh=True)
        if status["running"]:
            _emit("Android runtime is running")
            return True
        if status["stopping"]:
            raise WaydroidError("Android failed during startup (stopping state)")
        time.sleep(1)

    # One last check via shell probe
    rc, out, err = _run(["shell", "echo", "probe"], timeout=10)
    if rc == 0 and "probe" in out:
        _emit("Android runtime is running (shell probe OK)")
        return True

    raise WaydroidError(
        "Android runtime did not start within 45 seconds. Check logs "
        "with: waydroid log"
    )


@_require_waydroid
def stop_session(progress_cb: Optional[Callable[[str], None]] = None) -> bool:
    """Stop the Waydroid session."""
    if not is_initialized():
        return True
    status = get_status(force_refresh=True)
    if not (status["running"] or status["stopping"]):
        return True

    def _emit(msg: str):
        if progress_cb:
            progress_cb(msg)
        logger.info(msg)

    _emit("Stopping Android runtime...")

    # Try session stop as user first, fall back to pkexec
    rc, out, err = _run(["session", "stop"], timeout=30, as_root=False)
    if rc != 0:
        rc, out, err = _run(["session", "stop"], timeout=30, as_root=True)
        if rc != 0:
            # As last resort, stop container directly
            rc2, out2, err2 = _run(["container", "stop"], timeout=30, as_root=True)
            if rc2 != 0:
                raise WaydroidError(
                    f"Failed to stop Waydroid session (exit {rc}): "
                    f"{(err or out or '').strip()}",
                    exit_code=rc, stderr=(err or out or "").strip(),
                )

    # Wait for it to actually stop
    for _ in range(20):
        if not is_running():
            _emit("Android runtime stopped")
            return True
        time.sleep(1)

    _emit("Stop command sent; Android may take a moment to shut down")
    return True


# ---------------------------------------------------------------------------
# APK operations
# ---------------------------------------------------------------------------

@_require_waydroid
def install_apk(apk_path: str, progress_cb: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Install an APK file into the running Android container.

    Args:
        apk_path: validated .apk path
    Returns:
        Dict with 'success', 'package', 'label', 'message'
    """
    from .apk_validator import validate_apk_path, is_compatible_x86_64, get_app_info

    err = validate_apk_path(apk_path)
    if err:
        raise WaydroidError(f"Invalid APK: {err}")

    compat = is_compatible_x86_64(apk_path)
    if not compat["compatible"]:
        # Do NOT block install on suspected incompatibility — let the user decide
        # after seeing the warning in the GUI. Log a warning for diagnostics.
        logger.warning("APK may not be compatible: %s", compat["reason"])

    if not is_running():
        raise WaydroidError(
            "Android runtime is not running. Start it before installing apps."
        )

    if progress_cb:
        progress_cb(f"Installing {os.path.basename(apk_path)}...")

    rc, out, err = _run(["app", "install", apk_path], timeout=180)
    if rc != 0:
        err_msg = (err or out or "").strip()
        if "INSTALL_FAILED" in err_msg:
            raise WaydroidError(
                f"Android package install failed: {err_msg}",
                exit_code=rc, stderr=err_msg,
            )
        raise WaydroidError(
            f"APK installation failed (exit {rc}): {err_msg}",
            exit_code=rc, stderr=err_msg,
        )

    info = get_app_info(apk_path)
    pkg = info.get("package_name", "")
    label = info.get("label", os.path.basename(apk_path))
    logger.info("APK installed: %s (%s)", label, pkg or apk_path)
    _invalidate_status_cache()

    return {
        "success": True,
        "package": pkg,
        "label": label,
        "path": apk_path,
        "message": f"Installed: {label}",
    }


@_require_waydroid
def uninstall_app(package_name: str) -> Dict[str, Any]:
    """Uninstall an Android app by package name.

    Validates package name to avoid shell injection via argument list
    (we use argv lists anyway, but a valid package name is also a sanity check).
    """
    if not package_name:
        raise WaydroidError("No package name specified")
    # Package names must be Java-style identifiers: alphanumeric + dots + underscores
    import re
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", package_name):
        raise WaydroidError(f"Invalid package name: {package_name}")

    if not is_running():
        raise WaydroidError("Android runtime is not running")

    rc, out, err = _run(["app", "remove", package_name], timeout=60)
    if rc != 0:
        err_msg = (err or out or "").strip()
        if "not found" in err_msg.lower() or "Unknown package" in err_msg:
            raise WaydroidError(
                f"Package '{package_name}' is not installed",
                exit_code=rc, stderr=err_msg,
            )
        raise WaydroidError(
            f"Failed to uninstall {package_name} (exit {rc}): {err_msg}",
            exit_code=rc, stderr=err_msg,
        )

    logger.info("Uninstalled app: %s", package_name)
    _invalidate_status_cache()
    return {"success": True, "package": package_name}


@_require_waydroid
def list_apps() -> List[Dict[str, str]]:
    """List installed Android applications.

    Returns list of dicts with: name, package, launch_activity.
    """
    apps: List[Dict[str, str]] = []
    if not is_initialized():
        return apps
    if not is_running():
        return apps

    rc, out, err = _run(["app", "list"], timeout=30)
    if rc != 0:
        logger.warning("Could not list apps (rc=%d): %s", rc, (err or out)[:200])
        return apps

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pkg = ""
        launch_activity = ""
        for part in line.split():
            if part.startswith("package:"):
                pkg = part[len("package:"):]
            elif part.startswith("launcher:"):
                launch_activity = part[len("launcher:"):]
        if pkg:
            apps.append({
                "package": pkg,
                "name": _app_name_from_package(pkg),
                "launch_activity": launch_activity,
            })
    return apps


def _app_name_from_package(pkg: str) -> str:
    """Guess a human-readable name from a package name."""
    parts = pkg.split(".")
    if parts:
        name = parts[-1].replace("_", " ").replace("-", " ")
        return name.title() if name else pkg
    return pkg


@_require_waydroid
def launch_app(package_name: str) -> bool:
    """Launch an Android application by package name."""
    # Same rule as uninstall_app: a package name must be a Java-style identifier.
    # Rejecting here stops a value such as "--help" from being parsed as an option.
    import re
    if not package_name or not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", package_name):
        raise WaydroidError(f"Invalid package name: {package_name!r}")
    if not is_running():
        raise WaydroidError(
            "Android runtime is not running. Start it first."
        )

    rc, out, err = _run(["app", "launch", package_name], timeout=20)
    if rc != 0:
        # Fall back to am start (package/.MainActivity or similar)
        rc2, out2, err2 = _run(
            ["shell", "am", "start", "-n", f"{package_name}/.MainActivity"],
            timeout=15,
        )
        if rc2 != 0:
            raise WaydroidError(
                f"Failed to launch {package_name}: {(err or out or '').strip()}",
                exit_code=rc, stderr=(err or out or "").strip(),
            )
    logger.info("Launched app: %s", package_name)
    return True


@_require_waydroid
def get_logs(lines: int = 100) -> str:
    """Get Android/container logs."""
    rc, out, err = _run(["log"], timeout=10)
    if rc == 0:
        log_lines = out.splitlines()
        return "\n".join(log_lines[-lines:])
    return (err or out or "")


@_require_waydroid
def diagnose() -> Dict[str, Any]:
    """Run diagnostic checks and return a status report."""
    report: Dict[str, Any] = {
        "waydroid_installed": True,
        "waydroid_version": "",
        "initialized": is_initialized(),
        "running": False,
        "issues": [],
        "suggestions": [],
    }

    rc, out, _ = _run(["--version"], timeout=5)
    if rc == 0:
        report["waydroid_version"] = out.strip()

    if not report["initialized"]:
        report["issues"].append("Android image not initialized")
        report["suggestions"].append(
            "Run 'Initialize Android' to download the VANILLA system image"
        )
        return report

    status = get_status(force_refresh=True)
    report["running"] = status["running"]
    report["session"] = status["session"]
    report["container"] = status["container"]

    if not status["running"]:
        if status["session"] == "STOPPED":
            report["issues"].append("Android runtime is stopped")
            report["suggestions"].append("Click 'Start Android' to launch the runtime")

    # Check for binder availability
    from . import compatibility
    binder = compatibility.check_binder()
    if not binder["binder_available"]:
        report["issues"].append("Binder devices not available")
        report["suggestions"].append(
            "Load binder module: pkexec modprobe binder_linux"
        )

    # Data path size
    data_path = Path(WAYDROID_DATA)
    if data_path.exists():
        total_size = 0
        for f in data_path.rglob("*"):
            try:
                if f.is_file():
                    total_size += f.stat().st_size
            except OSError:
                pass
        report["data_size_mb"] = round(total_size / (1024 * 1024))

    return report
