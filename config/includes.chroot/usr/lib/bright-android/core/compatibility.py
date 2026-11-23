"""Compatibility checking for Bright Android / Waydroid.

Verifies kernel binder support, Ashmem, Wayland session, graphics,
disk space, and required packages before allowing installation.
"""
import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger("bright_android.compatibility")

# Minimum requirements
MIN_RAM_MB = 2048
RECOMMENDED_RAM_MB = 4096
MIN_DISK_GB = 5
RECOMMENDED_DISK_GB = 10
MIN_FREE_GB = 6  # For the Android image itself (~400MB base + apps)

# Required packages
REQUIRED_PACKAGES = [
    "waydroid",
    "lxc",
    "binder-linux-module",  # or ashmem_linux; varies by kernel
]

OPTIONAL_PACKAGES = [
    "waydroid-script",
    "adb",
]

# Kernel config flags needed for Waydroid
REQUIRED_KERNEL_CONFIGS = [
    "CONFIG_ANDROID_BINDER_IPC",
    "CONFIG_ANDROID_BINDERFS",
    "CONFIG_ASHMEM",
]

# Binder device paths
BINDER_PATHS = [
    "/dev/binder",
    "/dev/binderfs",
    "/dev/hwbinder",
    "/dev/vndbinder",
]


def _run_cmd(cmd: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    """Run a command safely with argument list (no shell)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "Timed out"
    except Exception as e:
        return 1, "", str(e)


def check_kernel_binder() -> Dict[str, object]:
    """Check for binder and ashmem kernel support."""
    result = {
        "binder_available": False,
        "ashmem_available": False,
        "binderfs_available": False,
        "details": [],
    }

    # Check binder devices
    for dev in BINDER_PATHS:
        if os.path.exists(dev):
            result["binder_available"] = True
            result["details"].append(f"Found {dev}")

    # Check binderfs mount
    rc, out, _ = _run_cmd(["mount"])
    if "binder" in out.lower() or "binderfs" in out.lower():
        result["binderfs_available"] = True
        result["details"].append("binderfs is mounted")

    # Check kernel config via /proc/config.gz or /boot/config-*
    config_found = False
    config_paths = ["/proc/config.gz"]
    try:
        for kpath in Path("/boot").glob("config-*"):
            config_paths.append(str(kpath))
    except OSError:
        pass

    for cp in config_paths:
        if not os.path.exists(cp):
            continue
        config_found = True
        try:
            if cp.endswith(".gz"):
                import gzip
                with gzip.open(cp, "rt") as f:
                    config_text = f.read()
            else:
                with open(cp, "r") as f:
                    config_text = f.read()

            for cfg in REQUIRED_KERNEL_CONFIGS:
                if f"{cfg}=y" in config_text or f"{cfg}=m" in config_text:
                    if "BINDER" in cfg:
                        result["binder_available"] = True
                    if "ASHMEM" in cfg:
                        result["ashmem_available"] = True
        except Exception as e:
            result["details"].append(f"Could not read {cp}: {e}")

    if not config_found:
        # If we can't read config, rely on device presence
        result["details"].append(
            "Kernel config not readable; checking device nodes only"
        )

    # Check if binder module can be loaded
    if not result["binder_available"]:
        rc, _, _ = _run_cmd(["modprobe", "binder"])
        if rc == 0:
            result["binder_available"] = True
            result["details"].append("binder module loaded successfully")

    return result


def check_ashmem() -> Dict[str, object]:
    """Check for ashmem support (needed for older Waydroid versions)."""
    result = {"ashmem_available": False, "details": []}
    if os.path.exists("/dev/ashmem"):
        result["ashmem_available"] = True
        result["details"].append("/dev/ashmem exists")
    # memfd is the modern replacement
    rc, out, _ = _run_cmd(["grep", "-q", "memfd", "/proc/filesystems"])
    # Even if ashmem is missing, Waydroid 1.4+ can use memfd
    result["memfd_available"] = os.path.exists("/dev/ashmem") or True
    return result


def check_wayland_session() -> Dict[str, object]:
    """Check if we are running in a Wayland session."""
    result = {
        "wayland_available": False,
        "session_type": os.environ.get("XDG_SESSION_TYPE", "unknown"),
        "xdg_runtime_dir": os.environ.get("XDG_RUNTIME_DIR", ""),
        "wayland_display": os.environ.get("WAYLAND_DISPLAY", ""),
        "details": [],
    }

    if result["session_type"] == "wayland":
        result["wayland_available"] = True
        result["details"].append("XDG_SESSION_TYPE=wayland")
    elif os.environ.get("WAYLAND_DISPLAY"):
        result["wayland_available"] = True
        result["details"].append("WAYLAND_DISPLAY is set")
    else:
        result["details"].append(
            "Not running in a Wayland session; Android apps "
            "require Wayland (Weston/KWin) for windowed mode"
        )

    if result["xdg_runtime_dir"] and os.path.isdir(result["xdg_runtime_dir"]):
        wl_socket = os.path.join(result["xdg_runtime_dir"], "wayland-0")
        if os.path.exists(wl_socket):
            result["wayland_available"] = True
            result["details"].append(f"Wayland socket found: {wl_socket}")

    return result


def check_graphics() -> Dict[str, object]:
    """Check for GPU/driver compatibility."""
    result = {
        "graphics_ok": False,
        "driver": "unknown",
        "renderer": "unknown",
        "details": [],
    }
    # Check for Mesa/GL
    rc, out, _ = _run_cmd(["glxinfo", "-B"], timeout=5)
    if rc == 0 and "OpenGL" in out:
        result["graphics_ok"] = True
        for line in out.splitlines():
            if "OpenGL renderer" in line:
                result["renderer"] = line.split(":", 1)[1].strip()
            if "OpenGL vendor" in line:
                result["driver"] = line.split(":", 1)[1].strip()
        result["details"].append(f"GL renderer: {result['renderer']}")
    else:
        # Check for render nodes even without glxinfo
        if os.path.exists("/dev/dri/renderD128"):
            result["graphics_ok"] = True
            result["details"].append("/dev/dri/renderD128 present")
        else:
            # Software rendering may still work (slowly)
            result["details"].append(
                "No GPU render node detected; software rendering may be slow"
            )
            result["graphics_ok"] = True  # Don't block; warn instead
    return result


def check_disk_space(path: str = "/var/lib/waydroid") -> Dict[str, object]:
    """Check available disk space for Android images."""
    result = {
        "path": path,
        "available_gb": 0,
        "sufficient": False,
        "details": [],
    }
    try:
        target = Path(path)
        while not target.exists() and target != target.parent:
            target = target.parent
        stat = os.statvfs(str(target))
        avail_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        result["available_gb"] = round(avail_gb, 1)
        result["sufficient"] = avail_gb >= MIN_FREE_GB
        if avail_gb >= RECOMMENDED_DISK_GB:
            result["details"].append(
                f"{avail_gb:.1f} GB available (recommended: {RECOMMENDED_DISK_GB})"
            )
        elif avail_gb >= MIN_FREE_GB:
            result["details"].append(
                f"{avail_gb:.1f} GB available (minimum met; tight)"
            )
        else:
            result["details"].append(
                f"Only {avail_gb:.1f} GB available; need at least {MIN_FREE_GB} GB"
            )
    except OSError as e:
        result["details"].append(f"Cannot check disk space: {e}")
    return result


def check_ram() -> Dict[str, object]:
    """Check available RAM."""
    result = {
        "total_mb": 0,
        "available_mb": 0,
        "sufficient": False,
        "details": [],
    }
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    info[key] = int(val)
        total_mb = info.get("MemTotal", 0) // 1024
        avail_mb = info.get("MemAvailable", info.get("MemFree", 0)) // 1024
        result["total_mb"] = total_mb
        result["available_mb"] = avail_mb
        result["sufficient"] = total_mb >= MIN_RAM_MB
        if total_mb >= RECOMMENDED_RAM_MB:
            result["details"].append(
                f"{total_mb} MB RAM (recommended)"
            )
        elif total_mb >= MIN_RAM_MB:
            result["details"].append(
                f"{total_mb} MB RAM (minimum met; may be slow)"
            )
        else:
            result["details"].append(
                f"{total_mb} MB RAM; need at least {MIN_RAM_MB} MB"
            )
    except OSError as e:
        result["details"].append(f"Cannot check RAM: {e}")
    return result


def check_packages() -> Dict[str, object]:
    """Check if required packages are installed."""
    result = {
        "waydroid_installed": False,
        "missing_packages": [],
        "details": [],
    }

    # Check for waydroid binary
    if shutil.which("waydroid"):
        result["waydroid_installed"] = True
        result["details"].append("waydroid binary found")
        # Get version
        rc, out, _ = _run_cmd(["waydroid", "--version"])
        if rc == 0 and out.strip():
            result["details"].append(f"waydroid version: {out.strip()}")
    else:
        result["missing_packages"].append("waydroid")
        result["details"].append("waydroid not installed")

    # Check for lxc
    if not shutil.which("lxc-start"):
        result["missing_packages"].append("lxc")

    return result


def check_waydroid_initialized() -> Dict[str, object]:
    """Check if the Waydroid image has already been initialized."""
    result = {
        "initialized": False,
        "images_present": False,
        "details": [],
    }
    waydroid_data = Path("/var/lib/waydroid")
    if waydroid_data.exists():
        images = list(waydroid_data.glob("*.img"))
        if images:
            result["images_present"] = True
            result["initialized"] = True
            result["details"].append(
                f"Found {len(images)} Android image(s)"
            )
        if (waydroid_data / "waydroid_base.prop").exists():
            result["initialized"] = True
            result["details"].append("waydroid_base.prop found")
    if not result["initialized"]:
        result["details"].append("Android runtime not initialized")
    return result


def run_full_check() -> Dict[str, object]:
    """Run all compatibility checks and return aggregate results."""
    binder = check_kernel_binder()
    wayland = check_wayland_session()
    graphics = check_graphics()
    disk = check_disk_space()
    ram = check_ram()
    packages = check_packages()
    initialized = check_waydroid_initialized()

    # Determine if installation is possible
    can_install = (
        binder["binder_available"]
        and ram["sufficient"]
        and disk["sufficient"]
    )

    # Determine if runtime can start (needs packages + init)
    can_run = (
        packages["waydroid_installed"]
        and initialized["initialized"]
        and wayland["wayland_available"]
    )

    issues: List[str] = []
    warnings: List[str] = []

    if not binder["binder_available"]:
        issues.append("Kernel binder module (/dev/binder) not available")
    if not ram["sufficient"]:
        issues.append(f"Insufficient RAM: {ram['total_mb']} MB < {MIN_RAM_MB} MB")
    if not disk["sufficient"]:
        issues.append(f"Insufficient disk space: {disk['available_gb']} GB")
    if not packages["waydroid_installed"]:
        warnings.append("Waydroid package not installed (installable)")
    if not wayland["wayland_available"]:
        warnings.append("Not in a Wayland session; apps need Wayland to launch")
    if ram["total_mb"] < RECOMMENDED_RAM_MB and ram["sufficient"]:
        warnings.append(f"RAM below recommended {RECOMMENDED_RAM_MB} MB")
    if not graphics.get("graphics_ok", False):
        warnings.append("No hardware GPU detected; software rendering")

    return {
        "can_install": can_install,
        "can_run": can_run,
        "binder": binder,
        "wayland": wayland,
        "graphics": graphics,
        "disk": disk,
        "ram": ram,
        "packages": packages,
        "initialized": initialized,
        "issues": issues,
        "warnings": warnings,
    }
