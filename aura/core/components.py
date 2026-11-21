"""AURA component lifecycle manager.

Each AURA subsystem (intelligence, commands, security, memory, recovery) is
a component that can be started, stopped, restarted, and queried for health.
The component manager tracks component state, handles failures gracefully,
and ensures a single component crash does not bring down the whole service.
"""
import logging
import threading
import time
from enum import Enum
from typing import Callable, Dict, Optional

logger = logging.getLogger("aura.components")


class ComponentState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"
    DISABLED = "disabled"


class ComponentStatus:
    """Read-only status snapshot of a component."""

    def __init__(self, name: str, state: ComponentState,
                 last_error: Optional[str] = None,
                 restart_count: int = 0):
        self.name = name
        self.state = state
        self.last_error = last_error
        self.restart_count = restart_count

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "last_error": self.last_error,
            "restart_count": self.restart_count,
        }


class Component:
    """Base class for AURA components.

    Subclasses implement start() and stop(). They should not block in start()
    indefinitely; any long-running work should use threads or async.
    """

    def __init__(self, name: str):
        self.name = name
        self.state = ComponentState.STOPPED
        self.last_error: Optional[str] = None
        self.restart_count = 0

    def start(self):
        """Start the component. Override in subclasses."""
        self.state = ComponentState.RUNNING

    def stop(self):
        """Stop the component. Override in subclasses."""
        self.state = ComponentState.STOPPED

    def health_check(self) -> bool:
        """Return True if the component is healthy. Override if needed."""
        return self.state == ComponentState.RUNNING

    def disable(self):
        """Mark component as disabled (e.g. prerequisites not met)."""
        self.state = ComponentState.DISABLED


class ComponentManager:
    """Manages lifecycle of all AURA components."""

    def __init__(self, restart_limit: int = 5, restart_delay: int = 3):
        self._components: Dict[str, Component] = {}
        self._lock = threading.Lock()
        self._restart_limit = restart_limit
        self._restart_delay = restart_delay
        self._watchdog_thread: Optional[threading.Thread] = None
        self._running = False

    def register(self, component: Component):
        """Register a component (before start)."""
        with self._lock:
            self._components[component.name] = component
            logger.info("Registered component: %s", component.name)

    def start_all(self):
        """Start all registered components."""
        self._running = True
        for name, comp in self._components.items():
            self._start_component(comp)

        # Start watchdog thread to monitor components
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="aura-watchdog", daemon=True
        )
        self._watchdog_thread.start()
        logger.info("Component manager started all components; watchdog active")

    def stop_all(self):
        """Stop all registered components (reverse order)."""
        self._running = False
        for name in reversed(list(self._components.keys())):
            comp = self._components[name]
            try:
                comp.stop()
                logger.info("Stopped component: %s", name)
            except Exception as e:
                logger.error("Error stopping component %s: %s", name, e)

    def get_status(self, name: str) -> Optional[ComponentStatus]:
        with self._lock:
            comp = self._components.get(name)
            if not comp:
                return None
            return ComponentStatus(comp.name, comp.state, comp.last_error,
                                   comp.restart_count)

    def get_all_status(self) -> Dict[str, ComponentStatus]:
        with self._lock:
            return {
                name: ComponentStatus(c.name, c.state, c.last_error, c.restart_count)
                for name, c in self._components.items()
            }

    def _start_component(self, comp: Component):
        try:
            comp.state = ComponentState.STARTING
            comp.start()
            comp.state = ComponentState.RUNNING
            comp.last_error = None
            logger.info("Started component: %s", comp.name)
        except Exception as e:
            comp.state = ComponentState.FAILED
            comp.last_error = str(e)
            logger.error("Failed to start component %s: %s", comp.name, e)

    def _watchdog_loop(self):
        """Monitor components and restart failed ones up to the limit."""
        while self._running:
            time.sleep(5)
            for name, comp in list(self._components.items()):
                if not self._running:
                    break
                if comp.state == ComponentState.RUNNING:
                    try:
                        if not comp.health_check():
                            raise RuntimeError("Health check failed")
                    except Exception as e:
                        logger.warning("Component %s unhealthy: %s", name, e)
                        comp.state = ComponentState.FAILED
                        comp.last_error = str(e)

                if comp.state == ComponentState.FAILED:
                    if comp.restart_count < self._restart_limit:
                        comp.restart_count += 1
                        logger.warning("Restarting component %s (attempt %d/%d)",
                                       name, comp.restart_count, self._restart_limit)
                        time.sleep(self._restart_delay)
                        self._start_component(comp)
                    else:
                        logger.error("Component %s exceeded restart limit (%d); "
                                     "entering failed state", name, self._restart_limit)
