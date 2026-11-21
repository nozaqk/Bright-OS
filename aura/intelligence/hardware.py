"""Hardware detection and resource profiling for AURA.

Detects total RAM, available RAM, CPU cores, GPU presence, free storage,
and battery state. Results are used by the ResourceManager to decide which
models can be loaded and what thread/RAM limits to enforce.

Detection is best-effort: on systems where a sensor is unavailable we fall
back to safe conservative defaults rather than raising.
"""
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("aura.intelligence.hardware")


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
    # Derived rough tier: "low", "medium", "high"
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
    """Return (total_kb, available_kb) from /proc/meminfo."""
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
    return total, avail


def _cpu_info() -> Tuple[int, int]:
    """Return (physical_cores, logical_threads)."""
    try:
        logical = os.cpu_count() or 1
    except Exception:
        logical = 1
    # Physical cores via lscpu if available
    physical = logical
    try:
        out = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=2)
        for line in out.stdout.splitlines():
            if line.startswith("Core(s) per socket:"):
                cores_per_socket = int(line.split(":")[1].strip())
            elif line.startswith("Socket(s):"):
                sockets = int(line.split(":")[1].strip())
                physical = cores_per_socket * sockets
                break
    except Exception:
        pass
    return max(1, physical), max(1, logical)


def _detect_gpus() -> List[str]:
    """Best-effort GPU detection. Returns a list of descriptive strings."""
    gpus: List[str] = []
    # Look for NVIDIA via nvidia-smi
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
    # Look for /dev/dri/renderD* for any DRM GPU (Intel/AMD/other)
    try:
        for entry in os.listdir("/dev/dri"):
            if entry.startswith("renderD"):
                path = f"/dev/dri/{entry}"
                # Try to read device vendor via sysfs
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
                    on_battery = status != "Charging" and status != "Full"
                    return on_battery, pct
                except OSError:
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


def detect_hardware(model_dir: str = "/var/lib/aura/models") -> HardwareProfile:
    """Produce a HardwareProfile snapshot. Safe to call repeatedly."""
    total_kb, avail_kb = _read_meminfo()
    phys_cores, threads = _cpu_info()
    total_mb = total_kb // 1024
    avail_mb = avail_kb // 1024
    on_batt, batt_pct = _detect_battery()
    gpus = _detect_gpus()

    # Determine tier based on multiple factors, not just RAM
    # low: <4 GB RAM or <2 cores
    # high: >=16 GB RAM AND >=4 cores AND (GPU present OR >=8 threads)
    # medium: everything else
    if total_mb < 3800 or phys_cores < 2:
        tier = "low"
    elif total_mb >= 16000 and phys_cores >= 4 and (gpus or threads >= 8):
        tier = "high"
    else:
        tier = "medium"

    # Try to ensure model_dir exists for disk check, but tolerate
    # permission errors (e.g. when running unit tests as non-aura user).
    model_dir_free = 0
    try:
        os.makedirs(model_dir, exist_ok=True)
        model_dir_free = _free_space_mb(model_dir)
    except OSError:
        model_dir_free = _free_space_mb(os.path.dirname(model_dir) or "/")

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
