"""Compatibility and hardware-readiness checking for Bright Android / Waydroid.

Verifies kernel binder support, memfd (modern ashmem replacement), Wayland
session, graphics capabilities, disk space, RAM, swap, CPU architecture,
and required packages before allowing installation.

Waydroid (as of 1.4+) requirements:
- Linux kernel with CONFIG_ANDROID_BINDER_IPC (binder_linux module on Debian)
- memfd_create(2) syscall (available on all kernels >= 3.17, replaces ashmem)
- Wayland session (Weston, KWin, Sway, etc.)
- LXC
- ~4 GB disk for images + room for apps
- 2 GB RAM minimum, 4 GB recommended

Binder and binderfs are loaded via the binder_linux DKMS package on Debian
(`binder-linux-module-dkms`) or via the kernel's built-in
CONFIG_ANDROID_BINDER_IPC=y on custom kernels.
"""
import os
import re
import shutil
import platform
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("bright_android.compatibility")

# ---------------------------------------------------------------------------
# Minimum / recommended thresholds
# ---------------------------------------------------------------------------
MIN_RAM_MB = 2048
RECOMMENDED_RAM_MB = 4096
MIN_FREE_GB = 6        # For the Android image (~400-700 MB base + apps)
RECOMMENDED_FREE_GB = 10
MIN_RAM_MB_LOW_RES = 4096  # Below this, warn about resource contention
RECOMMENDED_GPU_MEMORY_MB = 512

# Binder device paths (binderfs is the modern API)
BINDER_PATHS = [
    "/dev/binder",
    "/dev/hwbinder",
    "/dev/vndbinder",
]
BINDERFS_PATH = "/dev/binderfs"
BINDERFS_MOUNT = "/dev/binderfs/binder"
ASHMEM_PATH = "/dev/ashmem"

# Kernel config flags that indicate binder support
REQUIRED_KERNEL_CONFIGS = [
    "CONFIG_ANDROID_BINDER_IPC",
    "CONFIG_ANDROID_BINDERFS",
]
OPTIONAL_KERNEL_CONFIGS = [
    "CONFIG_ASHMEM",           # legacy, not needed if memfd works
    "CONFIG_ANDROID_BINDER_DEVICES",
]

STATUS_SUPPORTED = "supported"
STATUS_LIMITED = "supported_with_limitations"
STATUS_UNSUPPORTED = "unsupported"


def _run_cmd(cmd: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    """Run a command safely with argument list (no shell)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "Timed out"
    except Exception as e:
        return 1, "", str(e)


# ---------------------------------------------------------------------------
# Kernel / Binder
# ---------------------------------------------------------------------------

def _read_kernel_config() -> Dict[str, str]:
    """Read kernel config; returns dict of CONFIG_XXX -> 'y'/'m'/'n' or absent.

    Looks for /proc/config.gz first (requires CONFIG_IKCONFIG_PROC=y),
    then /boot/config-$(uname -r). Returns empty dict if neither is readable.
    """
    config: Dict[str, str] = {}

    def _parse(text: str):
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            config[key.strip()] = val.strip().strip('"')

    # /proc/config.gz
    proc_gz = Path("/proc/config.gz")
    if proc_gz.exists():
        try:
            import gzip
            with gzip.open(proc_gz, "rt", errors="replace") as f:
                _parse(f.read())
            return config
        except Exception:
            pass

    # /boot/config-*
    try:
        kver = os.uname().release
        for candidate in (Path("/boot") / f"config-{kver}",):
            if candidate.exists():
                try:
                    _parse(candidate.read_text(errors="replace"))
                    return config
                except Exception:
                    pass
        # Try any config-* file as fallback
        for candidate in sorted(Path("/boot").glob("config-*"), reverse=True):
            try:
                _parse(candidate.read_text(errors="replace"))
                return config
            except Exception:
                continue
    except OSError:
        pass

    return config


def check_binder() -> Dict[str, object]:
    """Check binder kernel support and device availability.

    This distinguishes three states:
      - kernel_supported: kernel config shows CONFIG_ANDROID_BINDER_IPC=y/m
      - devices_present: /dev/binder or binderfs is accessible
      - module_loadable: binder_linux module exists on disk (may need loading)

    We do NOT attempt to load the module ourselves — that requires root
    and must be done via pkexec/Polkit with user authorization.
    """
    result = {
        "binder_available": False,      # devices are present and usable
        "kernel_supported": False,      # kernel has binder built in or as module
        "devices_present": False,       # /dev/binder or binderfs exists
        "binderfs_mounted": False,
        "module_needs_loading": False,  # module exists but not loaded
        "module_installable": False,    # binder_linux package may be installable
        "details": [],
    }

    # 1) Check device nodes
    found_devs = [p for p in BINDER_PATHS if os.path.exists(p)]
    if found_devs:
        result["devices_present"] = True
        result["binder_available"] = True
        result["details"].append(f"Found binder devices: {', '.join(found_devs)}")

    # 2) Check binderfs
    if os.path.exists(BINDERFS_PATH):
        result["binderfs_mounted"] = True
        # binderfs is mounted; individual nodes may be created by the session
        result["details"].append("binderfs is mounted")
        if not result["devices_present"]:
            # binderfs mount present but nodes not created yet — waydroid
            # creates them at container start
            result["binder_available"] = True
            result["details"].append(
                "binderfs mounted; device nodes created at container start"
            )
    else:
        # Check mount table for binderfs
        rc, out, _ = _run_cmd(["findmnt", "-n", "-o", "SOURCE", "binderfs"], timeout=3)
        if rc == 0 and "binder" in out:
            result["binderfs_mounted"] = True
            result["binder_available"] = True
            result["details"].append("binderfs mount detected via findmnt")

    # 3) Check kernel config
    kcfg = _read_kernel_config()
    if kcfg:
        if kcfg.get("CONFIG_ANDROID_BINDER_IPC") in ("y", "m"):
            result["kernel_supported"] = True
            result["details"].append(
                f"Kernel has CONFIG_ANDROID_BINDER_IPC="
                f"{kcfg.get('CONFIG_ANDROID_BINDER_IPC')}"
            )
        if kcfg.get("CONFIG_ANDROID_BINDERFS") in ("y", "m"):
            result["details"].append("Kernel supports binderfs")

        # If kernel supports binder as module but no devices, module needs loading
        if (result["kernel_supported"]
                and not result["devices_present"]
                and not result["binderfs_mounted"]
                and kcfg.get("CONFIG_ANDROID_BINDER_IPC") == "m"):
            result["module_needs_loading"] = True
    else:
        result["details"].append(
            "Could not read kernel config; relying on device presence only"
        )

    # 4) Check if binder_linux module exists on disk (DKMS or in-tree)
    kver = os.uname().release
    dkms_mod = Path("/lib/modules") / kver / "updates/dkms/binder_linux.ko"
    in_tree_mod = Path("/lib/modules") / kver / "kernel/drivers/android/binder_linux.ko"
    if (dkms_mod.exists() if kver else False) or in_tree_mod.exists():
        result["module_installable"] = True
        if not result["binder_available"]:
            result["module_needs_loading"] = True
    elif shutil.which("modinfo"):
        rc, _, _ = _run_cmd(["modinfo", "-n", "binder_linux"], timeout=3)
        if rc == 0:
            result["module_installable"] = True
            result["details"].append("binder_linux module is installed but not loaded")
            if not result["binder_available"]:
                result["module_needs_loading"] = True

    # 5) Check for binder-linux-module package availability hint
    if not result["binder_available"] and not result["module_installable"]:
        # Provide clear remediation message
        result["details"].append(
            "Binder not available. Install 'binder-linux-module-dkms' "
            "and load with 'pkexec modprobe binder_linux'"
        )

    return result


def check_memfd() -> Dict[str, object]:
    """Check for memfd_create support (modern ashmem replacement).

    memfd_create is available on all Linux kernels >= 3.17 (2014). Waydroid
    1.4+ uses memfd and does NOT require ashmem. We detect it by trying to
    call memfd_create via ctypes, or by checking kernel version as a fallback.
    """
    result = {
        "memfd_available": False,
        "ashmem_available": False,
        "details": [],
    }

    # Check /dev/ashmem (legacy)
    if os.path.exists(ASHMEM_PATH):
        result["ashmem_available"] = True
        result["details"].append("/dev/ashmem present (legacy)")

    # Try to detect memfd via ctypes (real syscall test)
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        # memfd_create(const char *name, unsigned int flags)
        MFD_CLOEXEC = 0x0001
        fd = libc.syscall(319, b"bright-android-probe\0", MFD_CLOEXEC)  # SYS_memfd_create = 319 on x86_64
        if fd >= 0:
            os.close(fd)
            result["memfd_available"] = True
            result["details"].append("memfd_create syscall works")
            return result
    except Exception:
        pass

    # Fallback: check kernel version >= 3.17
    try:
        kver = os.uname().release
        m = re.match(r"(\d+)\.(\d+)", kver)
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            if major > 3 or (major == 3 and minor >= 17):
                result["memfd_available"] = True
                result["details"].append(
                    f"Kernel {kver} is >= 3.17; memfd_create expected"
                )
            else:
                result["details"].append(
                    f"Kernel {kver} < 3.17; memfd may not be available"
                )
    except Exception:
        pass

    # Fallback: check /proc/filesystems for tmpfs (memfd uses tmpfs shmem)
    if not result["memfd_available"]:
        try:
            with open("/proc/filesystems") as f:
                if "tmpfs" in f.read():
                    # tmpfs exists, which is a prerequisite; assume memfd works
                    # on any modern Debian kernel
                    result["memfd_available"] = True
                    result["details"].append(
                        "tmpfs available; memfd_create assumed working"
                    )
        except OSError:
            pass

    return result


# ---------------------------------------------------------------------------
# Session / Environment
# ---------------------------------------------------------------------------

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
    elif result["session_type"] == "x11":
        result["details"].append(
            "Running in an X11 session; Waydroid requires a Wayland "
            "compositor (Weston nested or switch to Wayland session)"
        )

    if result["wayland_display"]:
        result["wayland_available"] = True
        result["details"].append(f"WAYLAND_DISPLAY={result['wayland_display']}")

    if result["xdg_runtime_dir"] and os.path.isdir(result["xdg_runtime_dir"]):
        for sock in ("wayland-0", "wayland-1"):
            wl_socket = os.path.join(result["xdg_runtime_dir"], sock)
            if os.path.exists(wl_socket):
                result["wayland_available"] = True
                result["details"].append(f"Wayland socket: {wl_socket}")
                break

    if not result["wayland_available"]:
        result["details"].append(
            "Wayland socket not found; Android apps require Wayland"
        )

    return result


def check_graphics() -> Dict[str, object]:
    """Check GPU/driver/OpenGL capabilities."""
    result = {
        "graphics_ok": False,
        "driver": "unknown",
        "renderer": "unknown",
        "vendor": "unknown",
        "gl_version": "unknown",
        "gles": False,
        "software_rendering": False,
        "render_node": None,
        "details": [],
    }

    # Check for DRI render nodes
    for dev in ("/dev/dri/renderD128", "/dev/dri/renderD129"):
        if os.path.exists(dev):
            result["render_node"] = dev
            result["graphics_ok"] = True
            result["details"].append(f"GPU render node: {dev}")
            break

    # Try glxinfo for full GL info
    glxinfo = shutil.which("glxinfo")
    if glxinfo:
        rc, out, _ = _run_cmd([glxinfo, "-B"], timeout=5)
        if rc == 0:
            for line in out.splitlines():
                low = line.lower()
                if "opengl renderer string:" in low:
                    result["renderer"] = line.split(":", 1)[1].strip()
                elif "opengl vendor string:" in low:
                    result["vendor"] = line.split(":", 1)[1].strip()
                elif "opengl version string:" in low:
                    result["gl_version"] = line.split(":", 1)[1].strip()
                elif "opengl es" in low:
                    result["gles"] = True
            if result["renderer"] != "unknown":
                result["graphics_ok"] = True
                result["details"].append(f"GL renderer: {result['renderer']}")
                if any(s in result["renderer"].lower() for s in ("llvmpipe", "softpipe", "swrast")):
                    result["software_rendering"] = True
                    result["details"].append("Software rendering detected (will be slow)")

    # Try eglinfo for GLES info (Wayland native)
    eglinfo = shutil.which("eglinfo")
    if eglinfo and not result["gles"]:
        rc, out, _ = _run_cmd([eglinfo], timeout=5)
        if rc == 0 and "OpenGL ES" in out:
            result["gles"] = True
            result["details"].append("EGL/OpenGL ES available")

    if not result["graphics_ok"]:
        result["details"].append(
            "No GPU render node detected; software rendering only"
        )
        # Don't block install; software rendering may still work (slowly)
        result["graphics_ok"] = True
        result["software_rendering"] = True

    return result


def check_disk_space(path: str = "/var/lib/waydroid") -> Dict[str, object]:
    """Check available disk space for Android images."""
    result = {
        "path": path,
        "available_gb": 0.0,
        "total_gb": 0.0,
        "sufficient": False,
        "details": [],
    }
    try:
        target = Path(path)
        while not target.exists() and target != target.parent:
            target = target.parent
        stat = os.statvfs(str(target))
        avail_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        total_gb = (stat.f_blocks * stat.f_frsize) / (1024 ** 3)
        result["available_gb"] = round(avail_gb, 1)
        result["total_gb"] = round(total_gb, 1)
        result["sufficient"] = avail_gb >= MIN_FREE_GB
        if avail_gb >= RECOMMENDED_FREE_GB:
            result["details"].append(
                f"{avail_gb:.1f} GB available (of {total_gb:.1f} GB)"
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
    """Check total and available RAM."""
    result = {
        "total_mb": 0,
        "available_mb": 0,
        "sufficient": False,
        "recommended": False,
        "low_resource": False,
        "details": [],
    }
    try:
        with open("/proc/meminfo") as f:
            info: Dict[str, int] = {}
            for line in f:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    toks = parts[1].strip().split()
                    if toks:
                        try:
                            info[key] = int(toks[0])
                        except ValueError:
                            pass
        total_mb = info.get("MemTotal", 0) // 1024
        avail_mb = info.get("MemAvailable", info.get("MemFree", 0)) // 1024
        result["total_mb"] = total_mb
        result["available_mb"] = avail_mb
        result["sufficient"] = total_mb >= MIN_RAM_MB
        result["recommended"] = total_mb >= RECOMMENDED_RAM_MB
        result["low_resource"] = total_mb < MIN_RAM_MB_LOW_RES

        if total_mb >= RECOMMENDED_RAM_MB * 2:
            result["details"].append(f"{total_mb} MB RAM (plenty)")
        elif total_mb >= RECOMMENDED_RAM_MB:
            result["details"].append(f"{total_mb} MB RAM (recommended)")
        elif total_mb >= MIN_RAM_MB_LOW_RES:
            result["details"].append(
                f"{total_mb} MB RAM (meets minimum; Android + desktop may compete)"
            )
        elif total_mb >= MIN_RAM_MB:
            result["details"].append(
                f"{total_mb} MB RAM (minimum; may be slow with multiple apps)"
            )
        else:
            result["details"].append(
                f"{total_mb} MB RAM; need at least {MIN_RAM_MB} MB"
            )
    except OSError as e:
        result["details"].append(f"Cannot check RAM: {e}")
    return result


def check_swap() -> Dict[str, object]:
    """Check swap availability (helps prevent OOM kills on 8 GB systems)."""
    result = {
        "swap_total_mb": 0,
        "swap_free_mb": 0,
        "swap_available": False,
        "details": [],
    }
    try:
        with open("/proc/meminfo") as f:
            info: Dict[str, int] = {}
            for line in f:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    toks = parts[1].strip().split()
                    if toks:
                        try:
                            info[key] = int(toks[0])
                        except ValueError:
                            pass
        total = info.get("SwapTotal", 0) // 1024
        free = info.get("SwapFree", 0) // 1024
        result["swap_total_mb"] = total
        result["swap_free_mb"] = free
        result["swap_available"] = total > 0
        if total > 0:
            result["details"].append(f"Swap: {total} MB ({free} MB free)")
        else:
            result["details"].append("No swap configured; RAM pressure may cause issues")
    except OSError as e:
        result["details"].append(f"Cannot check swap: {e}")
    return result


def check_cpu() -> Dict[str, object]:
    """Check CPU architecture and core count."""
    result = {
        "arch": platform.machine(),
        "cores": os.cpu_count() or 0,
        "model": "",
        "compatible": False,
        "details": [],
    }

    result["compatible"] = result["arch"] in ("x86_64", "amd64")
    result["details"].append(f"Architecture: {result['arch']} ({result['cores']} cores)")

    if result["arch"] not in ("x86_64", "amd64"):
        result["details"].append(
            "Bright Android is only supported on x86_64/amd64"
        )

    # Try to get CPU model
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    result["model"] = line.split(":", 1)[1].strip()
                    result["details"].append(f"CPU: {result['model']}")
                    break
    except OSError:
        pass

    return result


def check_packages() -> Dict[str, object]:
    """Check if required packages are installed."""
    result = {
        "waydroid_installed": False,
        "waydroid_version": "",
        "lxc_installed": False,
        "missing_packages": [],
        "details": [],
    }

    if shutil.which("waydroid"):
        result["waydroid_installed"] = True
        rc, out, _ = _run_cmd(["waydroid", "--version"], timeout=5)
        if rc == 0 and out.strip():
            result["waydroid_version"] = out.strip()
            result["details"].append(f"waydroid {out.strip()}")
        else:
            result["details"].append("waydroid binary found")
    else:
        result["missing_packages"].append("waydroid")
        result["details"].append("waydroid not installed (install via apt)")

    if shutil.which("lxc-start"):
        result["lxc_installed"] = True
    else:
        result["missing_packages"].append("lxc")

    for opt in ("binderfs",):
        # binder module may be in a separate package
        pass

    return result


def check_waydroid_initialized() -> Dict[str, object]:
    """Check if the Waydroid image has already been initialized."""
    result = {
        "initialized": False,
        "images_present": False,
        "prop_present": False,
        "details": [],
    }
    waydroid_data = Path("/var/lib/waydroid")
    if waydroid_data.exists():
        images = [p for p in waydroid_data.glob("*.img") if p.is_file()]
        if images:
            result["images_present"] = True
            result["details"].append(f"Found {len(images)} Android image(s)")
        if (waydroid_data / "waydroid_base.prop").exists():
            result["prop_present"] = True
            result["details"].append("waydroid_base.prop found")
        if (waydroid_data / "data").exists():
            result["details"].append("Data directory present")
        result["initialized"] = result["images_present"] and result["prop_present"]
    else:
        result["details"].append("Android runtime not initialized (/var/lib/waydroid missing)")

    if not result["initialized"]:
        if result["images_present"] != result["prop_present"]:
            result["details"].append("Partial install detected; reinitialization recommended")

    return result


# ---------------------------------------------------------------------------
# Hardware readiness assessment
# ---------------------------------------------------------------------------

def assess_hardware_readiness(report: Optional[Dict] = None) -> Dict[str, object]:
    """Produce an overall hardware-readiness assessment.

    Returns:
        status: one of STATUS_SUPPORTED / STATUS_LIMITED / STATUS_UNSUPPORTED
        summary: human-readable one-line summary
        warnings: list of warnings about limitations
        blockers: list of issues that prevent installation/use
        recommendations: suggested actions
    """
    if report is None:
        report = run_full_check()

    warnings: List[str] = []
    blockers: List[str] = []
    recommendations: List[str] = []

    # CPU
    cpu = report["cpu"]
    if not cpu["compatible"]:
        blockers.append(f"CPU architecture '{cpu['arch']}' is not supported (x86_64 only)")

    # RAM
    ram = report["ram"]
    if not ram["sufficient"]:
        blockers.append(f"Insufficient RAM: {ram['total_mb']} MB (need {MIN_RAM_MB} MB)")
    elif ram["low_resource"]:
        warnings.append(
            f"System has {ram['total_mb']} MB RAM. Running Android applications "
            "alongside a full desktop environment may be resource-intensive. "
            "Close other applications before starting Android."
        )
        recommendations.append("Consider adding swap space if not already configured")

    # Swap (8 GB or less benefits from swap to avoid OOM kills)
    swap = report["swap"]
    if ram["total_mb"] <= 8192 and not swap["swap_available"]:
        warnings.append(
            "No swap space is configured. Adding swap (2-4 GB) is recommended "
            "to prevent out-of-memory kills when running Android apps."
        )
        recommendations.append("Set up swap: sudo apt install zram-tools")

    # Graphics
    gfx = report["graphics"]
    if gfx["software_rendering"]:
        warnings.append(
            "Software rendering detected. Android apps will run slowly "
            "without hardware GPU acceleration."
        )
    if "Radeon R6" in gfx.get("renderer", "") or "Carrizo" in gfx.get("renderer", ""):
        warnings.append(
            "AMD Radeon R6 (Carrizo) iGPU detected with ~1 GB VRAM. "
            "3D games and GPU-heavy apps may perform poorly."
        )

    # Binder
    binder = report["binder"]
    if not binder["binder_available"]:
        if binder["module_needs_loading"]:
            blockers.append(
                "Binder kernel module is not loaded. Run: pkexec modprobe binder_linux"
            )
            recommendations.append(
                "To load automatically at boot: "
                "echo 'binder_linux' | pkexec tee /etc/modules-load.d/binder.conf"
            )
        else:
            blockers.append(
                "Kernel binder support is not available. Install binder-linux-module-dkms "
                "or use a kernel with CONFIG_ANDROID_BINDER_IPC=y."
            )

    # Memfd
    if not report["memfd"]["memfd_available"]:
        blockers.append(
            "memfd_create is not available; Waydroid requires Linux >= 3.17"
        )

    # Wayland
    if not report["wayland"]["wayland_available"]:
        warnings.append(
            "Not running in a Wayland session. Switch to a Wayland session "
            "(log out → gear icon → 'Plasma (Wayland)') to use Android apps."
        )

    # Disk
    disk = report["disk"]
    if not disk["sufficient"]:
        blockers.append(
            f"Insufficient disk space: {disk['available_gb']:.1f} GB available "
            f"(need {MIN_FREE_GB} GB)"
        )

    # Determine overall status
    if blockers:
        status = STATUS_UNSUPPORTED
        summary = "System is not ready for Bright Android (see blockers below)"
    elif warnings:
        status = STATUS_LIMITED
        summary = "Bright Android will run with some limitations"
    else:
        status = STATUS_SUPPORTED
        summary = "System is ready for Bright Android"

    return {
        "status": status,
        "summary": summary,
        "warnings": warnings,
        "blockers": blockers,
        "recommendations": recommendations,
    }


def run_full_check() -> Dict[str, object]:
    """Run all compatibility checks and return aggregate results."""
    binder = check_binder()
    memfd = check_memfd()
    wayland = check_wayland_session()
    graphics = check_graphics()
    disk = check_disk_space()
    ram = check_ram()
    swap = check_swap()
    cpu = check_cpu()
    packages = check_packages()
    initialized = check_waydroid_initialized()

    # Can install if kernel supports it (binder available or loadable) and
    # hardware meets minimums. Missing packages are installable.
    can_install = (
        cpu["compatible"]
        and (binder["binder_available"] or binder["kernel_supported"] or binder["module_installable"])
        and ram["sufficient"]
        and disk["sufficient"]
        and memfd["memfd_available"]
    )

    # Can run right now (packages installed + initialized + wayland)
    can_run = False
    running = False
    if packages["waydroid_installed"]:
        # Lazy-import to avoid circular deps at module load time
        try:
            from . import waydroid_manager
            can_run = initialized["initialized"] and wayland["wayland_available"]
            if can_run or initialized["initialized"]:
                try:
                    running = waydroid_manager.is_running()
                except Exception:
                    running = False
        except Exception:
            pass

    issues: List[str] = []
    warnings: List[str] = []

    if not binder["binder_available"] and not binder["module_installable"] and not binder["kernel_supported"]:
        issues.append("Kernel binder (/dev/binder) not available")
    elif binder["module_needs_loading"]:
        issues.append("Binder module needs loading (pkexec modprobe binder_linux)")
    if not memfd["memfd_available"]:
        issues.append("memfd_create syscall not available")
    if not cpu["compatible"]:
        issues.append(f"Unsupported CPU architecture: {cpu['arch']}")
    if not ram["sufficient"]:
        issues.append(f"Insufficient RAM: {ram['total_mb']} MB < {MIN_RAM_MB} MB")
    elif ram["low_resource"]:
        warnings.append(
            f"{ram['total_mb']} MB RAM; running Android + desktop may be slow"
        )
    if not disk["sufficient"]:
        issues.append(f"Insufficient disk space: {disk['available_gb']:.1f} GB")
    if not packages["waydroid_installed"]:
        # Missing package is not an "issue" — it's installable
        warnings.append("Waydroid package not installed (install with apt)")
    if not wayland["wayland_available"]:
        warnings.append("Not in a Wayland session; apps require Wayland")
    if graphics.get("software_rendering"):
        warnings.append("Software rendering; Android apps will be slow")
    if not swap["swap_available"] and ram["total_mb"] < 8192:
        warnings.append("No swap configured; consider adding swap on this system")

    report = {
        "can_install": can_install,
        "can_run": can_run,
        "running": running,
        "binder": binder,
        "memfd": memfd,
        "wayland": wayland,
        "graphics": graphics,
        "disk": disk,
        "ram": ram,
        "swap": swap,
        "cpu": cpu,
        "packages": packages,
        "initialized": initialized,
        "issues": issues,
        "warnings": warnings,
    }

    # Add hardware readiness assessment
    report["hardware_readiness"] = assess_hardware_readiness(report)

    return report
