"""Hardware detection and resource profiling for AURA.

Detects total RAM, available RAM, CPU cores, GPU presence, free storage,
and battery state. Results are used by the ResourceManager to decide which
models can be loaded and what thread/RAM limits to enforce.

Detection is best-effort: on systems where a sensor is unavailable we fall
back to safe CONSERVATIVE defaults (assume low-end hardware) rather than
raising. Detection results are cached with a short TTL so repeated queries
do not spawn unnecessary subprocesses.
"""
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("aura.intelligence.hardware")

# Cache hardware detection so monitor loops don't constantly fork lscpu etc.
_HW_CACHE_TTL_SEC = 30.0
_hw_cache_lock = threading.Lock()
_hw_cache: Optional[Tuple[float, "HardwareProfile"]] = None


@dataclass
class HardwareProfile:
    """Snapshot of system hardware at a point in time."""
    total_ram_mb: int = 0
    available_ram_mb: int = 0
    cpu_cores: int = 0
    cpu_threads: int = 0
    gpus: List[str] = field(default_factory=list)
    free_storage_mb: int = 0
    model_dir_free_mb: int = 0
    on_battery: bool = False
    battery_percent: Optional[int] = None
    tier: str = "low"

    def summary(self) -> Dict[str, object]:
        return {
            "total_ram_mb": self.total_ram_mb,
            "available_ram_mb": self.available_ram_mb,
            "cpu_cores": self.cpu_cores,
            "cpu_threads": self.cpu_threads,
            "gpus": self.gpus,
            "free_storage_mb": self.free_storage_mb,
            "model_dir_free_mb": self.model_dir_free_mb,
            "on_battery": self.on_battery,
            "battery_percent": self.battery_percent,
            "tier": self.tier,
        }


def _read_meminfo() -> Tuple[int, int]:
    """Return (total_kb, available_kb) from /proc/meminfo. Conservative
    fallback of (1GB total, 256MB available) when unreadable."""
    total = avail = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1])
                if total and avail:
                    break
    except OSError as e:
        logger.warning("Could not read /proc/meminfo: %s", e)
    if total <= 0 or avail <= 0:
        logger.warning("Unable to read memory info; using conservative defaults")
        total = total or 1024 * 1024   # 1 GB
        avail = avail or 256 * 1024    # 256 MB
    return total, avail


def _cpu_info() -> Tuple[int, int]:
    """Return (physical_cores, logical_threads). Conservative fallback of
    (1, 1) when detection fails."""
    try:
        logical = os.cpu_count() or 1
    except Exception:
        logical = 1
    physical = logical
    try:
        out = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=2)
        cores_per_socket = None
        sockets = None
        for line in out.stdout.splitlines():
            if line.startswith("Core(s) per socket:"):
                try:
                    cores_per_socket = int(line.split(":")[1].strip())
                except ValueError:
                    pass
            elif line.startswith("Socket(s):"):
                try:
                    sockets = int(line.split(":")[1].strip())
                except ValueError:
                    pass
            if cores_per_socket is not None and sockets is not None:
                physical = cores_per_socket * sockets
                break
    except Exception:
        pass
    physical = max(1, min(physical, logical))
    return physical, max(1, logical)


def _detect_gpus() -> List[str]:
    """Best-effort GPU detection. Only reports GPUs that have an actual
    render node and appear to have a real (non-software) driver bound."""
    gpus: List[str] = []
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "-L"], capture_output=True,
                                 text=True, timeout=3)
            for line in out.stdout.splitlines():
                line = line.strip()
                if line:
                    gpus.append(line)
        except Exception as e:
            logger.debug("nvidia-smi failed: %s", e)
    try:
        if not os.path.isdir("/dev/dri"):
            return gpus
        found = False
        drm_dir = "/sys/class/drm"
        if os.path.isdir(drm_dir):
            software_drivers = {"bochs-drm", "virtio-gpu", "simpledrm", "vesafb"}
            for dev in sorted(os.listdir(drm_dir)):
                if not dev.startswith("card") or "-" not in dev:
                    continue
                driver_link = os.path.join(drm_dir, dev, "device/driver")
                try:
                    if os.path.exists(driver_link):
                        driver = os.path.basename(os.path.realpath(driver_link))
                        if driver not in software_drivers:
                            gpus.append(f"DRM GPU ({driver})")
                            found = True
                            break
                except OSError:
                    continue
        if not found:
            for entry in sorted(os.listdir("/dev/dri")):
                if entry.startswith("renderD"):
                    gpus.append(f"DRM GPU ({entry})")
                    break
    except OSError:
        pass
    return gpus


def _detect_battery() -> Tuple[bool, Optional[int]]:
    """Return (on_battery, battery_percent) if any battery is present."""
    try:
        for name in os.listdir("/sys/class/power_supply"):
            if name.startswith("BAT"):
                base = f"/sys/class/power_supply/{name}"
                try:
                    with open(f"{base}/status") as f:
                        status = f.read().strip()
                    with open(f"{base}/capacity") as f:
                        pct = int(f.read().strip())
                    on_battery = status not in ("Charging", "Full", "Not charging")
                    return on_battery, max(0, min(100, pct))
                except (OSError, ValueError):
                    continue
    except OSError:
        pass
    return False, None


def _free_space_mb(path: str) -> int:
    try:
        usage = shutil.disk_usage(path)
        return usage.free // (1024 * 1024)
    except OSError:
        return 0


def _detect_hardware_uncached(model_dir: str) -> HardwareProfile:
    total_kb, avail_kb = _read_meminfo()
    phys_cores, threads = _cpu_info()
    total_mb = total_kb // 1024
    avail_mb = avail_kb // 1024
    on_batt, batt_pct = _detect_battery()
    gpus = _detect_gpus()

    if total_mb < 3800 or phys_cores < 2:
        tier = "low"
    elif total_mb >= 16000 and phys_cores >= 4 and (gpus or threads >= 8):
        tier = "high"
    else:
        tier = "medium"

    # Don't create directories during detection (side effects); stat existing
    # dir or fall back to parent or root.
    model_dir_free = 0
    try:
        if os.path.isdir(model_dir):
            model_dir_free = _free_space_mb(model_dir)
        else:
            parent = os.path.dirname(model_dir) or "/"
            model_dir_free = _free_space_mb(parent)
    except OSError:
        model_dir_free = _free_space_mb("/")

    profile = HardwareProfile(
        total_ram_mb=total_mb,
        available_ram_mb=avail_mb,
        cpu_cores=phys_cores,
        cpu_threads=threads,
        gpus=gpus,
        free_storage_mb=_free_space_mb("/"),
        model_dir_free_mb=model_dir_free,
        on_battery=on_batt,
        battery_percent=batt_pct,
        tier=tier,
    )
    logger.info("Hardware profile: %s", profile.summary())
    return profile


def detect_hardware(model_dir: str = "/var/lib/aura/models",
                    force_refresh: bool = False) -> HardwareProfile:
    """Produce a HardwareProfile snapshot.

    Results are cached for _HW_CACHE_TTL_SEC so polling callers (e.g. the
    resource monitor) don't repeatedly fork lscpu/nvidia-smi.
    """
    global _hw_cache
    now = time.monotonic()
    with _hw_cache_lock:
        if not force_refresh and _hw_cache is not None:
            ts, prof = _hw_cache
            if now - ts < _HW_CACHE_TTL_SEC:
                return prof
        profile = _detect_hardware_uncached(model_dir)
        _hw_cache = (now, profile)
        return profile


def invalidate_hardware_cache():
    global _hw_cache
    with _hw_cache_lock:
        _hw_cache = None
