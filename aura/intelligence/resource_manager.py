"""Adaptive Resource Manager for AURA Intelligence.

Central policy module that decides:
  - Whether a given model can be loaded right now (RAM/CPU/GPU/storage/battery).
  - What CPU thread count to pass the provider (always leaves headroom).
  - When to unload an idle model to free RAM (NEVER while generating).
  - When to cancel an in-flight inference due to memory pressure.
  - How to adjust policy when on battery (conservative mode).
"""
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .hardware import HardwareProfile, detect_hardware
from .model_info import ModelInfo
from .provider import Provider, ProviderState

logger = logging.getLogger("aura.intelligence.resources")

# psutil is preferred; fall back to /proc/meminfo
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

MIN_RESERVE_RAM_MB = 1024
MIN_RESERVE_RAM_LOW_MB = 512
# Always leave at least this many logical CPUs for the desktop/system
DESKTOP_HEADROOM_CPU = 1
# Never allocate more than this fraction of total logical CPUs even if
# the admin overrides cpu_threads.
MAX_CPU_FRACTION = 0.875
# Wall-time between hardware re-probes inside the monitor loop
PRESSURE_CHECK_INTERVAL_SEC = 5.0
IDLE_CHECK_INTERVAL_SEC = 30


@dataclass
class LoadDecision:
    allowed: bool
    reason: str
    recommended_threads: int = 0
    max_ctx_tokens: int = 4096


class ResourceManager:
    def __init__(self, config=None,
                 hardware: Optional[HardwareProfile] = None,
                 idle_check_interval: float = IDLE_CHECK_INTERVAL_SEC):
        self._config = config
        self._hw: HardwareProfile = hardware or detect_hardware()
        self._hw_lock = threading.Lock()
        self._idle_unload_seconds = 600
        self._max_memory_percent = 50
        self._max_memory_mb = 0          # hard cap, 0 = use percent
        self._cpu_threads_config = 0     # 0 = auto
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
        self._pressure_emitted_for: Dict[str, float] = {}

        if config is not None:
            self.apply_config(config)

    def apply_config(self, config):
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
            self._max_memory_mb = config.getint(
                "intelligence", "max_memory_mb")
        except Exception:
            self._max_memory_mb = 0
        try:
            self._cpu_threads_config = config.getint(
                "intelligence", "cpu_threads")
        except Exception:
            self._cpu_threads_config = 0
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
        # Clamp config to sane ranges
        if self._max_memory_percent <= 0 or self._max_memory_percent > 90:
            self._max_memory_percent = min(90, max(10, self._max_memory_percent))
        if self._idle_unload_seconds < 0:
            self._idle_unload_seconds = -1  # sentinel for "disabled"

    def register_provider(self, provider: Provider):
        with self._lock:
            self._providers[provider.name] = provider

    def providers(self) -> Dict[str, Provider]:
        with self._lock:
            return dict(self._providers)

    def refresh_hardware(self, force: bool = False) -> HardwareProfile:
        new_hw = detect_hardware(force_refresh=force)
        with self._hw_lock:
            self._hw = new_hw
        return new_hw

    def current_hardware(self) -> HardwareProfile:
        with self._hw_lock:
            return self._hw

    def current_pressure(self) -> Dict[str, object]:
        """Return a snapshot of current memory/CPU/battery state.

        Uses the cached hardware snapshot (hardware detect is cheap but
        not free; it has its own TTL of ~30s). Memory is always read
        live because it changes constantly.
        """
        hw = self.current_hardware()
        try:
            vmem = psutil.virtual_memory()
        except Exception:
            vmem = None
        avail_mb = vmem.available // (1024 * 1024) if vmem else hw.available_ram_mb
        total_mb = vmem.total // (1024 * 1024) if vmem else hw.total_ram_mb
        used_pct = vmem.percent if vmem else (
            100 - (avail_mb * 100.0 / total_mb) if total_mb else 0)
        load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
        on_battery = hw.on_battery
        battery_low = (hw.battery_percent is not None
                       and hw.battery_percent <= self._battery_low_threshold)
        return {
            "total_ram_mb": total_mb,
            "available_ram_mb": avail_mb,
            "used_ram_percent": used_pct,
            "load_avg_1m": load,
            "cpu_threads": hw.cpu_threads,
            "on_battery": on_battery,
            "battery_low": bool(battery_low and on_battery),
            "tier": hw.tier,
        }

    def assess_model(self, model: ModelInfo, provider: Provider,
                     pressure: Optional[Dict[str, object]] = None) -> LoadDecision:
        """Decide whether `model` may be loaded on `provider` right now.
        Re-reads current pressure unless a fresh snapshot is passed in."""
        if pressure is None:
            # Re-read immediately before load (not cached); this is the
            # final gate before spawning the inference process.
            pressure = self.current_pressure()
        free_mb = int(pressure["available_ram_mb"])
        total_mb = int(pressure["total_ram_mb"])
        required_mb = int(provider.estimated_memory_for(model))
        battery_low = bool(pressure["battery_low"])
        cpu_threads = int(pressure["cpu_threads"])

        if total_mb <= 0 or free_mb <= 0:
            return LoadDecision(allowed=False, reason="cannot read system memory")

        # RAM cap: min of (percent cap, hard cap, free-reserve)
        percent_cap = int(total_mb * (self._max_memory_percent / 100.0))
        if self._max_memory_mb > 0:
            percent_cap = min(percent_cap, self._max_memory_mb)
        reserve = MIN_RESERVE_RAM_MB if pressure["tier"] != "low" else MIN_RESERVE_RAM_LOW_MB
        if battery_low:
            percent_cap = percent_cap // 2
            reserve = reserve * 2

        usable_mb = max(0, min(free_mb - reserve, percent_cap))

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

        # Storage: re-stat the model directory immediately (do not use
        # a cached snapshot which could be stale).
        from .hardware import _free_space_mb
        try:
            model_dir_free = _free_space_mb(
                getattr(provider, "_model_dir", None)
                or getattr(self, "_last_model_dir", "/var/lib/aura/models"))
        except Exception:
            model_dir_free = 0
        if model.path and not os.path.exists(model.path):
            needed_mb = model.size_bytes // (1024 * 1024) + 256
            if model_dir_free < needed_mb:
                return LoadDecision(
                    allowed=False,
                    reason=(f"insufficient storage in model dir "
                            f"(~{model_dir_free}MB free, need ~{needed_mb}MB)"),
                )

        threads = self._recommend_threads(battery_low, cpu_threads)
        ctx = self._recommend_ctx(required_mb, total_mb)
        return LoadDecision(
            allowed=True, reason="ok",
            recommended_threads=threads,
            max_ctx_tokens=min(ctx, self._max_context_tokens),
        )

    def _recommend_threads(self, battery_low: bool, cpu_threads: int) -> int:
        """Return a CPU thread count that ALWAYS leaves headroom for the
        desktop. If the admin set cpu_threads explicitly, we CLAMP that
        value to the safe maximum (we never honour "use all threads" since
        that starves the desktop)."""
        # Compute the absolute maximum we'll ever allocate
        absolute_max = max(1, int(cpu_threads * MAX_CPU_FRACTION))
        absolute_max = max(1, min(absolute_max, cpu_threads - DESKTOP_HEADROOM_CPU))
        absolute_max = max(1, absolute_max)

        if self._cpu_threads_config > 0:
            return max(1, min(self._cpu_threads_config, absolute_max))

        avail = max(1, cpu_threads - DESKTOP_HEADROOM_CPU)
        if battery_low:
            avail = max(1, avail // 2)
        return max(1, min(avail, absolute_max))

    def _recommend_ctx(self, model_mb: int, total_mb: int) -> int:
        ratio = model_mb / max(1, total_mb)
        if ratio > 0.4:
            return 2048
        if ratio > 0.25:
            return 4096
        return 8192

    def note_inference(self, provider_name: str):
        with self._lock:
            self._last_inference_time[provider_name] = time.monotonic()

    def seconds_idle(self, provider_name: str) -> float:
        with self._lock:
            last = self._last_inference_time.get(provider_name)
            if last is None:
                return float("inf")
            return time.monotonic() - last

    # -- Monitor ------------------------------------------------------------
    def start(self):
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
        t = self._monitor_thread
        if t is not None:
            t.join(timeout=max(5, self._idle_check_interval + 2))
        self._monitor_thread = None
        # During shutdown, proactively unload models so children are reaped
        with self._lock:
            providers = list(self._providers.values())
        for p in providers:
            try:
                p.unload_model()
            except Exception as e:
                logger.debug("Error unloading %s during stop: %s", p.name, e)

    def _monitor_loop(self):
        next_pressure = 0.0
        next_idle = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            try:
                if now >= next_pressure:
                    self._check_pressure()
                    next_pressure = now + PRESSURE_CHECK_INTERVAL_SEC
                if now >= next_idle:
                    self._check_idle_unload()
                    next_idle = now + self._idle_check_interval
            except Exception as e:
                logger.debug("Resource monitor error: %s", e)
            self._stop_event.wait(min(1.0, self._idle_check_interval))

    def _check_idle_unload(self):
        if self._idle_unload_seconds < 0:
            return
        threshold = self._idle_unload_seconds
        with self._lock:
            providers = list(self._providers.items())
        for name, provider in providers:
            # NEVER unload a provider that is actively generating
            if provider.state == ProviderState.GENERATING:
                continue
            if provider.state != ProviderState.READY:
                continue
            idle = self.seconds_idle(name)
            if idle >= threshold:
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
        try:
            vmem = psutil.virtual_memory()
            free_mb = vmem.available // (1024 * 1024)
        except Exception:
            return
        with self._hw_lock:
            tier = self._hw.tier
            battery_low = False
        # Also check battery state from cached profile
        hw = self.current_hardware()
        battery_low = (hw.battery_percent is not None
                       and hw.battery_percent <= self._battery_low_threshold
                       and hw.on_battery)
        reserve = MIN_RESERVE_RAM_MB if tier != "low" else MIN_RESERVE_RAM_LOW_MB
        if battery_low:
            reserve = reserve * 2
        if free_mb < reserve // 2:
            with self._lock:
                providers = list(self._providers.values())
            for p in providers:
                if p.state == ProviderState.GENERATING:
                    # Rate-limit: don't spam cancellation for the same provider
                    last = self._pressure_emitted_for.get(p.name, 0)
                    if time.monotonic() - last < 10:
                        continue
                    self._pressure_emitted_for[p.name] = time.monotonic()
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
        else:
            # Clean up stale entries once we have headroom again
            with self._lock:
                self._pressure_emitted_for.clear()

    def set_model_dir(self, model_dir: str):
        """Called by InferenceEngine so storage checks look at the right path."""
        self._last_model_dir = model_dir

    def add_pressure_callback(self, cb):
        self._pressure_callbacks.append(cb)

    def add_idle_callback(self, cb):
        self._idle_callbacks.append(cb)
