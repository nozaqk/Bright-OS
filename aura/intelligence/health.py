"""Provider health monitoring.

Runs a periodic lightweight health check on each registered provider and
emits state transitions. Useful for detecting crashed llama.cpp subprocesses
or a stopped local Ollama service.
"""
import logging
import threading
import time
from typing import Callable, Dict, List, Optional

from .provider import Provider, ProviderState

logger = logging.getLogger("aura.intelligence.health")


class HealthMonitor:
    def __init__(self, check_interval: float = 30.0):
        self._providers: Dict[str, Provider] = {}
        self._lock = threading.Lock()
        self._interval = check_interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state_snapshots: Dict[str, ProviderState] = {}
        self._listeners: List[Callable[[str, ProviderState, ProviderState, Optional[str]], None]] = []

    def register(self, provider: Provider):
        with self._lock:
            self._providers[provider.name] = provider
            self._state_snapshots[provider.name] = provider.state

    def unregister(self, name: str):
        with self._lock:
            self._providers.pop(name, None)
            self._state_snapshots.pop(name, None)

    def add_listener(self, cb: Callable[[str, ProviderState, ProviderState, Optional[str]], None]):
        self._listeners.append(cb)

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            t = threading.Thread(target=self._loop, name="aura-provider-health",
                                 daemon=True)
            self._thread = t
        t.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            t = self._thread
            self._thread = None
        if t is not None:
            t.join(timeout=max(5, self._interval + 2))

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._check_all()
            except Exception as e:
                logger.debug("Health monitor error: %s", e)
            self._stop.wait(self._interval)

    def _check_all(self):
        with self._lock:
            providers = list(self._providers.items())
        for name, provider in providers:
            prev = provider.state
            try:
                healthy = provider.health_check()
            except Exception as e:
                healthy = False
                logger.warning("Provider %s health_check raised: %s", name, e)
            if not healthy and prev not in (ProviderState.ERROR, ProviderState.UNAVAILABLE):
                # Transition: provider went unhealthy
                provider._set_state(ProviderState.ERROR,
                                    error=provider.last_error or "health check failed")
            new_state = provider.state
            old_snapshot = self._state_snapshots.get(name, prev)
            if new_state != old_snapshot:
                with self._lock:
                    self._state_snapshots[name] = new_state
                for cb in list(self._listeners):
                    try:
                        cb(name, old_snapshot, new_state, provider.last_error)
                    except Exception as e:
                        logger.debug("Health listener error: %s", e)

    def snapshot(self) -> Dict[str, Dict[str, str]]:
        with self._lock:
            out = {}
            for name, p in self._providers.items():
                out[name] = {
                    "state": p.state.value,
                    "last_error": p.last_error or "",
                    "model": p.current_model.model_id if p.current_model else "",
                }
            return out
