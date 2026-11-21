"""Provider health monitoring.

Runs a periodic lightweight health check on each registered provider and
emits state transitions. Useful for detecting crashed llama.cpp subprocesses
or a stopped local Ollama service.

Phase 2.2.2 lifecycle hardening
-------------------------------
The monitor uses an explicit STOPPED/STARTING/RUNNING/STOPPING state machine
guarded by a Condition variable, with a generation counter that identifies
each start/stop cycle:

  * start() blocks until the monitoring loop is RUNNING. It creates a
    per-generation stop Event so that a new start() cannot accidentally
    clear or signal the previous generation's cancellation.
  * stop() uses generation-scoped ownership: only one caller performs the
    actual join; other concurrent stop() callers wait on the Condition
    for STOPPED. stop() never transitions to STOPPED while the thread is
    still alive — STOPPED is set exclusively by the loop body's finally
    block as the thread exits.
  * If join() times out (e.g. a provider health_check blocks longer than
    the join timeout), state remains STOPPING and the thread reference is
    retained. A subsequent stop() will resume the join; a subsequent
    start() cannot create a new thread until state is STOPPED. stop()
    never falsely reports successful shutdown.
  * A loop's finally block only transitions state to STOPPED if the loop
    still owns the lifecycle (its generation matches _generation and the
    current _thread is itself). This prevents a stale finally from
    clobbering a newer generation.
  * Callback-triggered stop() from a listener never self-joins.
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


# Total upper bound (seconds) a single stop() call will spend trying to
# join a monitor thread that is stuck in a provider health_check. After
# this, stop() returns with state still STOPPING and logs an error, so
# the caller (or a subsequent stop() call) can retry without having been
# lied to about successful shutdown.
_JOIN_TOTAL_TIMEOUT = 30.0
_JOIN_POLL_INTERVAL = 1.0


class HealthMonitor:
    def __init__(self, check_interval: float = 30.0):
        self._providers: Dict[str, Provider] = {}
        self._data_lock = threading.Lock()  # protects providers/snapshots/listeners
        self._interval = check_interval
        self._state = _State.STOPPED
        self._cv = threading.Condition(threading.Lock())  # lifecycle lock

        # Generation-scoped state. Each start() allocates a fresh stop
        # Event and a fresh Thread. Older threads hold their own
        # references locally (passed via args) so a new start() cannot
        # mutate the old generation's cancellation signal.
        self._generation = 0
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None

        self._state_snapshots: Dict[str, ProviderState] = {}
        self._listeners: List[
            Callable[[str, ProviderState, ProviderState, Optional[str]], None]
        ] = []

    # -- Provider management -------------------------------------------------
    def register(self, provider: Provider):
        with self._data_lock:
            self._providers[provider.name] = provider
            self._state_snapshots[provider.name] = provider.state

    def unregister(self, name: str):
        with self._data_lock:
            self._providers.pop(name, None)
            self._state_snapshots.pop(name, None)

    def add_listener(
        self,
        cb: Callable[[str, ProviderState, ProviderState, Optional[str]], None],
    ):
        with self._data_lock:
            self._listeners.append(cb)

    # -- Lifecycle -----------------------------------------------------------
    def start(self):
        """Start the monitor.

        Blocks until the monitoring loop is RUNNING (or another concurrent
        start() has already brought it to RUNNING). If a stop is in
        progress (STOPPING), waits for the previous thread to actually
        exit (state == STOPPED and no live thread) before creating a new
        generation. Safe to call concurrently and idempotent.
        """
        t_to_start: Optional[threading.Thread] = None
        my_stop_event: Optional[threading.Event] = None
        my_gen = 0

        with self._cv:
            while True:
                if self._state == _State.RUNNING:
                    # Already running; nothing to do.
                    return
                if self._state in (_State.STARTING, _State.STOPPING):
                    # Wait for any in-progress transition to quiesce.
                    self._cv.wait()
                    continue
                assert self._state == _State.STOPPED, (
                    f"unexpected state before start: {self._state}")
                # Defensive: refuse to start if a monitor thread is still
                # alive (shouldn't happen if state is STOPPED, but guard
                # against any future bug that leaves a live thread).
                if self._thread is not None and self._thread.is_alive():
                    self._cv.wait()
                    continue
                break

            # We own the STARTING transition.
            self._state = _State.STARTING
            self._generation += 1
            my_gen = self._generation
            my_stop_event = threading.Event()
            self._stop_event = my_stop_event
            t = threading.Thread(
                target=self._loop,
                args=(my_gen, my_stop_event),
                name="aura-provider-health",
                daemon=True,
            )
            self._thread = t
            t_to_start = t

        assert t_to_start is not None
        assert my_stop_event is not None
        t_to_start.start()

        with self._cv:
            while self._state == _State.STARTING:
                self._cv.wait()

    def stop(self):
        """Stop the monitor.

        Blocks until the monitoring loop has fully exited and the thread
        has been joined, or until _JOIN_TOTAL_TIMEOUT elapses (in which
        case state remains STOPPING and the caller may retry).

        When called from the monitor thread itself (e.g. from a health-
        change listener), signals the loop to stop and returns immediately
        without self-joining; the loop's own finally block will complete
        the transition to STOPPED.

        Concurrent stop() calls serialize: only one transitions the
        state to STOPPING; the others wait on the Condition for STOPPED.
        We deliberately do NOT clear self._thread here; the loop's
        finally block is the only place that clears it, so the loop can
        always identify itself as owner when it exits.
        """
        join_thread: Optional[threading.Thread] = None

        with self._cv:
            while True:
                if self._state == _State.STOPPED:
                    return

                if self._stop_event is not None:
                    self._stop_event.set()

                me = threading.current_thread()
                if self._thread is not None and self._thread is me:
                    # Listener-callback stop from the monitor thread.
                    if self._state in (_State.STARTING, _State.RUNNING):
                        self._state = _State.STOPPING
                    self._cv.notify_all()
                    return

                if self._state == _State.STOPPING:
                    # Another caller owns this stop; wait for STOPPED.
                    while self._state == _State.STOPPING:
                        self._cv.wait()
                    # After waiting: either STOPPED (done), or a newer
                    # generation started (RUNNING/STARTING) — loop back
                    # to top.
                    continue
                if self._state == _State.STARTING:
                    # start() has assigned a Thread but the loop hasn't
                    # entered RUNNING yet. Wait for it to resolve.
                    self._cv.wait()
                    continue
                # state is RUNNING — we own the STOPPING transition.
                assert self._state == _State.RUNNING, (
                    f"unexpected state in stop: {self._state}")
                assert self._thread is not None, "RUNNING without _thread"
                self._state = _State.STOPPING
                join_thread = self._thread
                self._cv.notify_all()
                break

        # Join OUTSIDE the lock. Poll repeatedly so a health_check that
        # completes after the initial wakeup is observed.
        deadline = time.monotonic() + _JOIN_TOTAL_TIMEOUT
        timed_out = False
        if join_thread is not None and join_thread is not threading.current_thread():
            while True:
                if not join_thread.is_alive():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    join_thread.join(timeout=min(_JOIN_POLL_INTERVAL, remaining))
                except RuntimeError:
                    # "cannot join before started" — tight race with
                    # start() phase 2 calling t.start(); yield.
                    time.sleep(0.001)

        with self._cv:
            if timed_out:
                # Join timed out — thread is still alive. Leave state
                # as STOPPING, keep _thread pointing at the live thread,
                # so subsequent stop/start calls behave correctly.
                logger.warning(
                    "HealthMonitor thread did not exit within %.1fs "
                    "(provider health_check likely stuck); state remains "
                    "STOPPING. Call stop() again to retry.",
                    _JOIN_TOTAL_TIMEOUT)
                self._cv.notify_all()
                return
            # Thread is dead. The loop's finally block SHOULD have
            # transitioned state to STOPPED and cleared _thread/_stop_event.
            # If it hasn't yet (still running finally), wait briefly.
            if self._state != _State.STOPPED:
                # Fallback: if for any reason the loop's finally hasn't
                # run (e.g. it was killed before finally executed), do
                # the cleanup ourselves. This is defensive; in the
                # normal path the finally runs first.
                self._state = _State.STOPPED
                self._thread = None
                self._stop_event = None
                self._cv.notify_all()

    def _loop(self, generation: int, stop_event: threading.Event):
        """Monitoring loop body.

        Args:
          generation: monotonically increasing id from start(); used to
            detect whether this loop still owns the lifecycle.
          stop_event: per-generation Event; signalled by stop(). A new
            start() cannot affect this Event because it creates a fresh
            one for the new generation.
        """
        # Transition STARTING -> RUNNING under the cv.
        entered_running = False
        with self._cv:
            if (self._generation == generation
                    and self._state == _State.STARTING
                    and self._thread is threading.current_thread()):
                self._state = _State.RUNNING
                entered_running = True
                self._cv.notify_all()
        try:
            if not entered_running:
                return
            while not stop_event.is_set():
                try:
                    self._check_all()
                except Exception as e:
                    logger.debug("Health monitor error: %s", e)
                stop_event.wait(self._interval)
        finally:
            with self._cv:
                # Only finalize if we are still the registered thread
                # for our generation. If a newer generation has started
                # (different _generation, or _thread points at a
                # different Thread), we must not touch its state.
                if (self._generation == generation
                        and self._thread is threading.current_thread()
                        and self._state in (_State.STOPPING, _State.RUNNING, _State.STARTING)):
                    self._state = _State.STOPPED
                    self._thread = None
                    self._stop_event = None
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
            if not healthy and prev not in (
                ProviderState.ERROR,
                ProviderState.UNAVAILABLE,
            ):
                provider._set_state(
                    ProviderState.ERROR,
                    error=provider.last_error or "health check failed",
                )
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
