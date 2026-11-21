"""Provider health monitoring.

Runs a periodic lightweight health check on each registered provider and
emits state transitions. Useful for detecting crashed llama.cpp subprocesses
or a stopped local Ollama service.

Phase 2.2.1 lifecycle hardening
-------------------------------
The monitor has four explicit states (STOPPED, STARTING, RUNNING, STOPPING)
and transitions them under a Condition variable. Thread creation, start(),
and stop() are fully serialized:

  * start() cannot return until the monitoring loop is RUNNING (or another
    concurrent start brought it to RUNNING). This means a stop() that
    arrives immediately after start() returns will actually join the real
    live thread, not a not-yet-started Thread object.
  * stop() cannot return until the loop has exited and the thread has been
    joined (or, if called from a health-listener callback on the monitor's
    own thread, signals and returns without self-joining).
  * A new start() that arrives while an old thread is still exiting waits
    for STOPPED before creating a new thread.
  * When a loop thread exits it only clears state if it still owns the
    lifecycle (generation counter), so a trailing finally-block from a
    stale thread can never clobber a newer thread's state.
"""
import enum
import logging
import threading
import time
from typing import Callable, Dict, List, Optional

from .provider import Provider, ProviderState

logger = logging.getLogger("aura.intelligence.health")


class _State(enum.Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"


class HealthMonitor:
    def __init__(self, check_interval: float = 30.0):
        self._providers: Dict[str, Provider] = {}
        self._data_lock = threading.Lock()  # protects providers/snapshots/listeners
        self._interval = check_interval
        self._state = _State.STOPPED
        self._cv = threading.Condition(threading.Lock())  # lifecycle lock
        self._stop = threading.Event()
        # _thread is only written under _cv; readers must also hold _cv.
        self._thread: Optional[threading.Thread] = None
        # _generation increments every start() so that a stale loop exit
        # can detect it no longer owns the lifecycle.
        self._generation = 0
        self._state_snapshots: Dict[str, ProviderState] = {}
        self._listeners: List[Callable[[str, ProviderState, ProviderState, Optional[str]], None]] = []

    # -- Provider management -------------------------------------------------
    def register(self, provider: Provider):
        with self._data_lock:
            self._providers[provider.name] = provider
            self._state_snapshots[provider.name] = provider.state

    def unregister(self, name: str):
        with self._data_lock:
            self._providers.pop(name, None)
            self._state_snapshots.pop(name, None)

    def add_listener(self, cb: Callable[[str, ProviderState, ProviderState, Optional[str]], None]):
        with self._data_lock:
            self._listeners.append(cb)

    # -- Lifecycle -----------------------------------------------------------
    def start(self):
        """Start the monitor.

        Blocks until the monitoring loop is RUNNING. Idempotent: calling
        start() when already RUNNING returns immediately. Safe to call
        concurrently from any thread.
        """
        # Phase 1: under the cv, wait until the monitor is STOPPED (or
        # already RUNNING, in which case we return), then transition it
        # to STARTING. Prepare the Thread object but don't start it
        # under the lock.
        t_to_start: Optional[threading.Thread] = None
        my_gen = 0
        with self._cv:
            while True:
                if self._state == _State.RUNNING:
                    return
                if self._state in (_State.STARTING, _State.STOPPING):
                    self._cv.wait()
                    continue
                # state is STOPPED
                break
            self._state = _State.STARTING
            self._stop.clear()
            self._generation += 1
            my_gen = self._generation
            t = threading.Thread(
                target=self._loop, args=(my_gen,),
                name="aura-provider-health", daemon=True)
            self._thread = t
            t_to_start = t

        # Phase 2: start the thread OUTSIDE the lock so we don't hold
        # _cv across Thread.start() (which could otherwise be intercepted
        # by tests or, in general, we don't want to hold a lock while
        # calling foreign code).
        assert t_to_start is not None
        t_to_start.start()

        # Phase 3: wait under the cv for the loop to transition itself
        # to RUNNING. If it fails immediately it will land in STOPPED;
        # if a racing stop ran and moved us to STOPPING/STOPPED we
        # observe that too. We return when we're no longer in STARTING.
        with self._cv:
            while self._state == _State.STARTING:
                self._cv.wait()

    def stop(self):
        """Stop the monitor and join the thread.

        Blocks until the monitoring loop has fully exited and the thread
        has been joined (unless stop() is called from the monitor's own
        thread, e.g. from a listener callback, in which case it signals
        stop and returns immediately to avoid self-deadlock). Idempotent.
        """
        join_thread = None
        with self._cv:
            if self._state == _State.STOPPED:
                return
            self._stop.set()
            me = threading.current_thread()
            if self._thread is not None and self._thread is me:
                # Called from within the monitor thread itself (e.g. a
                # listener callback). Signal stop but do NOT self-join.
                if self._state in (_State.STARTING, _State.RUNNING):
                    self._state = _State.STOPPING
                self._cv.notify_all()
                return
            # Wait until the thread has left STARTING (i.e. has either
            # begun running or been torn down by another stop).
            while self._state == _State.STARTING:
                self._cv.wait()
            if self._state == _State.STOPPED:
                return
            # Claim ownership of the stop: move to STOPPING and grab the
            # thread we need to join. We clear _thread NOW so that any
            # racing start() that wakes after this point will create a
            # new Thread object rather than thinking it can reuse ours.
            self._state = _State.STOPPING
            join_thread = self._thread
            self._thread = None
        # Join OUTSIDE the lock so concurrent start()s can proceed
        # without blocking on us (and without us blocking on them).
        if join_thread is not None and join_thread.is_alive() \
                and join_thread is not threading.current_thread():
            join_thread.join(timeout=max(5, self._interval + 2))
        # After join returns, the thread has exited (or timed out).
        # Defensively transition to STOPPED under the lock. If a newer
        # generation already started (a racing start() created a new
        # thread after we cleared self._thread), we detect that via a
        # non-None self._thread and leave its state alone — the new
        # generation owns the lifecycle now.
        with self._cv:
            if self._thread is None and self._state == _State.STOPPING:
                self._state = _State.STOPPED
                self._cv.notify_all()

    def _loop(self, generation: int):
        """Monitoring loop body. `generation` identifies which start()
        this loop belongs to, so an old thread exiting after a newer
        start+stop cycle can't clobber current state."""
        # Transition STARTING -> RUNNING under the cv. If a racing
        # stop() or newer start() has already changed state, bail out
        # immediately via the finally block (which cleans up state).
        entered_running = False
        with self._cv:
            if self._generation == generation and self._state == _State.STARTING:
                self._state = _State.RUNNING
                entered_running = True
                self._cv.notify_all()
        try:
            if not entered_running:
                # We didn't take ownership (racing stop/newer start);
                # don't run the loop body. The finally block will do
                # cleanup for our generation.
                return
            while not self._stop.is_set():
                try:
                    self._check_all()
                except Exception as e:
                    logger.debug("Health monitor error: %s", e)
                # Wait in small slices so we notice stop() promptly even
                # though the check interval may be long.
                self._stop.wait(self._interval)
        finally:
            with self._cv:
                # Only clean up state if this thread's generation is
                # still the current generation (i.e., no newer start()
                # has taken over). If a newer generation exists, it
                # owns the lifecycle and we must not touch its state.
                if self._generation == generation:
                    self._state = _State.STOPPED
                    self._thread = None
                    self._cv.notify_all()

    def _check_all(self):
        with self._data_lock:
            providers = list(self._providers.items())
        for name, provider in providers:
            prev = provider.state
            try:
                healthy = provider.health_check()
            except Exception as e:
                healthy = False
                logger.warning("Provider %s health_check raised: %s", name, e)
            if not healthy and prev not in (ProviderState.ERROR, ProviderState.UNAVAILABLE):
                provider._set_state(ProviderState.ERROR,
                                    error=provider.last_error or "health check failed")
            new_state = provider.state
            with self._data_lock:
                old_snapshot = self._state_snapshots.get(name, prev)
                if new_state != old_snapshot:
                    self._state_snapshots[name] = new_state
                    cbs = list(self._listeners)
                else:
                    cbs = []
            for cb in cbs:
                try:
                    cb(name, old_snapshot, new_state, provider.last_error)
                except Exception as e:
                    logger.debug("Health listener error: %s", e)

    def snapshot(self) -> Dict[str, Dict[str, str]]:
        with self._data_lock:
            out = {}
            for name, p in self._providers.items():
                out[name] = {
                    "state": p.state.value,
                    "last_error": p.last_error or "",
                    "model": p.current_model.model_id if p.current_model else "",
                }
            return out
