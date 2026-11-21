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
        """Mark component as disabled (e.g. prerequisites not met).

        Note: call this BEFORE start_all() if you want the state change
        to be observed. The component manager's _start_component will not
        override DISABLED back to RUNNING.
        """
        self.state = ComponentState.DISABLED


class ComponentManager:
    """Manages lifecycle of all AURA components."""

    def __init__(self, restart_limit: int = 5, restart_delay: int = 3,
                 watchdog_interval: float = 5.0,
                 state_change_callback: Optional[Callable] = None):
        self._components: Dict[str, Component] = {}
        self._lock = threading.Lock()
        self._restart_limit = restart_limit
        self._restart_delay = restart_delay
        self._watchdog_interval = watchdog_interval
        self._watchdog_thread: Optional[threading.Thread] = None
        self._running = False
        # Optional callback: fn(component_name, new_state_value, details_dict)
        self._state_change_callback = state_change_callback

    def _notify_state(self, comp: Component, details: Optional[dict] = None):
        if self._state_change_callback is not None:
            try:
                self._state_change_callback(comp.name, comp.state.value,
                                            details or {"restart_count": comp.restart_count})
            except Exception as e:
                logger.debug("State change callback error for %s: %s", comp.name, e)

    def _set_state(self, comp: Component, new_state: ComponentState,
                   details: Optional[dict] = None):
        comp.state = new_state
        self._notify_state(comp, details)

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
                # Defensive: ensure state is STOPPED even if subclass forgets
                if comp.state != ComponentState.DISABLED:
                    comp.state = ComponentState.STOPPED
                self._notify_state(comp)
                logger.info("Stopped component: %s", name)
            except Exception as e:
                logger.error("Error stopping component %s: %s", name, e)
                comp.state = ComponentState.FAILED
                comp.last_error = str(e)
                self._notify_state(comp)

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
        prev_state = comp.state
        try:
            comp.state = ComponentState.STARTING
            self._notify_state(comp)
            comp.start()
            # Only set RUNNING if start() didn't change the state to something
            # else (e.g. DISABLED when prerequisites are unmet, or FAILED).
            if comp.state == ComponentState.STARTING:
                comp.state = ComponentState.RUNNING
            comp.last_error = None
            logger.info("Started component: %s (state=%s)", comp.name, comp.state.value)
            self._notify_state(comp)
        except Exception as e:
            comp.state = ComponentState.FAILED
            comp.last_error = str(e)
            logger.error("Failed to start component %s: %s", comp.name, e)
            self._notify_state(comp, {"error": str(e)})

    def _watchdog_pass(self):
        """Run one monitoring pass over all components (testable, no sleeps)."""
        for name, comp in list(self._components.items()):
            if not self._running:
                break

            # Skip DISABLED/STOPPED components — intentionally down
            if comp.state in (ComponentState.DISABLED, ComponentState.STOPPED):
                continue

            if comp.state == ComponentState.RUNNING:
                try:
                    if not comp.health_check():
                        raise RuntimeError("Health check failed")
                    # Sustained health: reset restart counter so a future crash
                    # gets a fresh budget (don't reset immediately on start() —
                    # that would let crash-looping components restart forever).
                    if comp.restart_count > 0:
                        comp.restart_count = 0
                except Exception as e:
                    logger.warning("Component %s unhealthy: %s", name, e)
                    comp.state = ComponentState.FAILED
                    comp.last_error = str(e)
                    self._notify_state(comp, {"error": str(e), "reason": "health_check_failed"})

            if comp.state == ComponentState.FAILED:
                if comp.restart_count < self._restart_limit:
                    comp.restart_count += 1
                    logger.warning("Restarting component %s (attempt %d/%d)",
                                   name, comp.restart_count, self._restart_limit)
                    if self._running:
                        self._start_component(comp)
                elif comp.restart_count == self._restart_limit:
                    comp.restart_count += 1
                    logger.error("Component %s exceeded restart limit (%d); "
                                 "entering permanent failed state",
                                 name, self._restart_limit)
                    self._notify_state(comp, {"permanent_failure": True})

    def _watchdog_loop(self):
        """Monitor components and restart failed ones up to the limit."""
        while self._running:
            time.sleep(self._watchdog_interval)
            if not self._running:
                break
            self._watchdog_pass()
