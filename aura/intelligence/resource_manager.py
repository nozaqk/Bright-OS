"""Adaptive Resource Manager for AURA Intelligence.

Central policy module that decides:
  - Whether a given model can be loaded right now (considering free RAM,
    CPU count, GPU availability, battery state, storage).
  - What CPU thread count to pass the provider (leaves headroom for the
    desktop).
  - When to unload an idle model to free RAM.
  - When to cancel an in-flight inference due to memory pressure.
  - How to adjust policy when on battery (conservative mode).

Design goals (from PRD):
  - Never load a large model at boot. (auto_load_at_boot=false is enforced
    upstream; here we also reject loads when free RAM is below a floor.)
  - Never keep an unused model in RAM indefinitely (idle unload timer).
  - Desktop responsiveness is prioritized: always leave headroom for the
    user session.
  - Battery-aware: switch to conservative policy on low battery.
  - Resource-aware scheduling: queue requests instead of overcommitting.
  - Profiles based on DETECTED hardware, not just RAM (CPU, GPU, storage).
"""
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .hardware import HardwareProfile, detect_hardware
from .model_info import ModelInfo
from .provider import Provider, ProviderState

logger = logging.getLogger("aura.intelligence.resources")

# psutil is preferred but fall back to /proc/meminfo if unavailable
try:
    import psutil  # type: ignore
except ImportError:
    class _FakeVmem:
        def __init__(self):
            try:
                total = avail = 0
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            total = int(line.split()[1])
                        elif line.startswith("MemAvailable:"):
                            avail = int(line.split()[1])
                self.total = total * 1024
                self.available = avail * 1024
                self.percent = 100 - (avail * 100.0 / total if total else 0)
            except OSError:
                self.total = 0
                self.available = 0
                self.percent = 0

    class _FakePsutil:
        @staticmethod
        def virtual_memory():
            return _FakeVmem()
    psutil = _FakePsutil()

# Minimum free RAM that must remain after model load (MB).
# We keep a desktop-responsive buffer at all times.
MIN_RESERVE_RAM_MB = 1024
MIN_RESERVE_RAM_LOW_MB = 512   # on low-memory systems, smaller buffer
DESKTOP_HEADROOM_CPU = 1       # always leave at least one core unused
IDLE_CHECK_INTERVAL_SEC = 30   # how often to check for idle models


@dataclass
class LoadDecision:
    allowed: bool
    reason: str
    recommended_threads: int = 0
    max_ctx_tokens: int = 4096


class ResourceManager:
    """Adaptive policy engine. All methods are thread-safe."""

    def __init__(self, config=None,
                 hardware: Optional[HardwareProfile] = None,
                 idle_check_interval: float = IDLE_CHECK_INTERVAL_SEC):
        self._config = config
        self._hw: HardwareProfile = hardware or detect_hardware()
        self._hw_lock = threading.Lock()
        self._idle_unload_seconds = 600
        self._max_memory_percent = 50
        self._cpu_threads_config = 0  # 0 = auto
        self._max_context_tokens = 8192
        self._battery_low_threshold = 20
        self._auto_load = False
        self._last_inference_time: Dict[str, float] = {}
        self._providers: Dict[str, Provider] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._pressure_callbacks: List[callable] = []
        self._idle_callbacks: List[callable] = []
        self._idle_check_interval = idle_check_interval

        if config is not None:
            self.apply_config(config)

    # -- Configuration ------------------------------------------------------
    def apply_config(self, config):
        """Read relevant settings from an AuraConfig instance."""
        try:
            self._idle_unload_seconds = config.getint(
                "intelligence", "unload_idle_seconds")
        except Exception:
            pass
        try:
            self._max_memory_percent = config.getint(
                "intelligence", "max_memory_percent")
        except Exception:
            pass
        try:
            self._cpu_threads_config = config.getint(
                "intelligence", "cpu_threads")
        except Exception:
            pass
        try:
            self._max_context_tokens = config.getint(
                "intelligence", "max_context_tokens")
        except Exception:
            pass
        try:
            self._battery_low_threshold = config.getint(
                "intelligence", "battery_low_threshold")
        except Exception:
            pass
        try:
            self._auto_load = config.getboolean(
                "intelligence", "auto_load_at_boot")
        except Exception:
            self._auto_load = False

    # -- Provider tracking --------------------------------------------------
    def register_provider(self, provider: Provider):
        with self._lock:
            self._providers[provider.name] = provider

    def providers(self) -> Dict[str, Provider]:
        with self._lock:
            return dict(self._providers)

    # -- Hardware / pressure ------------------------------------------------
    def refresh_hardware(self) -> HardwareProfile:
        """Re-detect hardware and update snapshot."""
        new_hw = detect_hardware()
        with self._hw_lock:
            self._hw = new_hw
        return new_hw

    def current_hardware(self) -> HardwareProfile:
        with self._hw_lock:
            return self._hw

    def current_pressure(self) -> Dict[str, object]:
        """Return a snapshot of current memory/CPU/battery state."""
        hw = self.refresh_hardware()
        vmem = psutil.virtual_memory()
        load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
        on_battery = hw.on_battery
        battery_low = (hw.battery_percent is not None
                       and hw.battery_percent <= self._battery_low_threshold)
        return {
            "total_ram_mb": hw.total_ram_mb,
            "available_ram_mb": hw.available_ram_mb,
            "used_ram_percent": vmem.percent,
            "load_avg_1m": load,
            "cpu_threads": hw.cpu_threads,
            "on_battery": on_battery,
            "battery_low": battery_low and on_battery,
            "tier": hw.tier,
        }

    # -- Load decision ------------------------------------------------------
    def assess_model(self, model: ModelInfo, provider: Provider) -> LoadDecision:
        """Decide whether `model` may be loaded on `provider` right now."""
        pressure = self.current_pressure()
        free_mb = int(pressure["available_ram_mb"])
        total_mb = int(pressure["total_ram_mb"])
        required_mb = provider.estimated_memory_for(model)
        battery_low = bool(pressure["battery_low"])

        # Cap RAM by configured percent
        cap_mb = int(total_mb * (self._max_memory_percent / 100.0))
        reserve = MIN_RESERVE_RAM_MB if self._hw.tier != "low" else MIN_RESERVE_RAM_LOW_MB
        if battery_low:
            # On low battery, use half the cap and double the reserve
            cap_mb = cap_mb // 2
            reserve = reserve * 2

        usable_mb = max(0, min(free_mb - reserve, cap_mb))

        if required_mb > usable_mb:
            return LoadDecision(
                allowed=False,
                reason=(f"insufficient memory (model ~{required_mb}MB, "
                        f"usable ~{usable_mb}MB, free ~{free_mb}MB)"),
            )
        if required_mb > total_mb:
            return LoadDecision(
                allowed=False,
                reason=f"model ({required_mb}MB) exceeds total RAM ({total_mb}MB)",
            )

        # Check storage for model dir
        model_dir_free = self._hw.model_dir_free_mb
        # Only check if model file is not already on disk
        if model.path and not os.path.exists(model.path):
            needed_mb = model.size_bytes // (1024 * 1024) + 256
            if model_dir_free < needed_mb:
                return LoadDecision(
                    allowed=False,
                    reason=(f"insufficient storage in model dir "
                            f"(~{model_dir_free}MB free, need ~{needed_mb}MB)"),
                )

        # Thread recommendation
        threads = self._recommend_threads(battery_low)
        ctx = self._recommend_ctx(required_mb, total_mb)
        return LoadDecision(
            allowed=True,
            reason="ok",
            recommended_threads=threads,
            max_ctx_tokens=min(ctx, self._max_context_tokens),
        )

    def _recommend_threads(self, battery_low: bool) -> int:
        if self._cpu_threads_config > 0:
            return max(1, self._cpu_threads_config)
        hw = self.current_hardware()
        avail = max(1, hw.cpu_threads - DESKTOP_HEADROOM_CPU)
        if battery_low:
            avail = max(1, avail // 2)
        return avail

    def _recommend_ctx(self, model_mb: int, total_mb: int) -> int:
        """Smaller context window on tighter RAM."""
        ratio = model_mb / max(1, total_mb)
        if ratio > 0.4:
            return 2048
        if ratio > 0.25:
            return 4096
        return 8192

    # -- Activity tracking --------------------------------------------------
    def note_inference(self, provider_name: str):
        with self._lock:
            self._last_inference_time[provider_name] = time.monotonic()

    def seconds_idle(self, provider_name: str) -> float:
        with self._lock:
            last = self._last_inference_time.get(provider_name)
            if last is None:
                # Never used; idle since "forever"
                return float("inf")
            return time.monotonic() - last

    # -- Idle monitor -------------------------------------------------------
    def start(self):
        """Start the background monitoring thread."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, name="aura-resource-monitor",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info("Resource manager started (idle_unload=%ds)",
                    self._idle_unload_seconds)

    def stop(self):
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        self._monitor_thread = None

    def _monitor_loop(self):
        while not self._stop_event.is_set():
            try:
                self._check_idle_unload()
                self._check_pressure()
            except Exception as e:
                logger.debug("Resource monitor error: %s", e)
            self._stop_event.wait(self._idle_check_interval)

    def _check_idle_unload(self):
        # Negative value disables idle unload; 0 means "unload immediately"
        if self._idle_unload_seconds < 0:
            return
        threshold = self._idle_unload_seconds
        with self._lock:
            providers = list(self._providers.items())
        for name, provider in providers:
            if provider.state not in (ProviderState.READY, ProviderState.GENERATING):
                continue
            idle = self.seconds_idle(name)
            if idle >= threshold or (threshold == 0 and idle > 0.05):
                logger.info("Idle unload: provider %s idle for %.0fs, unloading",
                            name, idle)
                try:
                    provider.unload_model()
                    for cb in self._idle_callbacks:
                        try:
                            cb(name)
                        except Exception as e:
                            logger.debug("Idle callback error: %s", e)
                except Exception as e:
                    logger.error("Error during idle unload of %s: %s", name, e)

    def _check_pressure(self):
        """If available RAM drops under reserve while a model is generating,
        request graceful cancellation of the current request to free memory."""
        try:
            vmem = psutil.virtual_memory()
            free_mb = vmem.available // (1024 * 1024)
        except Exception:
            return
        reserve = MIN_RESERVE_RAM_MB if self._hw.tier != "low" else MIN_RESERVE_RAM_LOW_MB
        if free_mb < reserve // 2:
            # Critical pressure: ask generating providers to cancel
            with self._lock:
                providers = list(self._providers.values())
            for p in providers:
                if p.state == ProviderState.GENERATING:
                    logger.warning("Memory pressure critical (%dMB free), "
                                   "cancelling in-flight request on %s",
                                   free_mb, p.name)
                    try:
                        p.cancel_all()
                        for cb in self._pressure_callbacks:
                            try:
                                cb(p.name, free_mb)
                            except Exception as e:
                                logger.debug("Pressure callback error: %s", e)
                    except Exception as e:
                        logger.debug("Cancel error: %s", e)

    def add_pressure_callback(self, cb):
        self._pressure_callbacks.append(cb)

    def add_idle_callback(self, cb):
        self._idle_callbacks.append(cb)



