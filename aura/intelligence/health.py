"""Provider health monitoring.

Runs a periodic lightweight health check on each registered provider and
emits state transitions. Useful for detecting crashed llama.cpp subprocesses
or a stopped local Ollama service.

Phase 2.2.3 lifecycle hardening
-------------------------------
The monitor uses an explicit STOPPED/STARTING/RUNNING/STOPPING state machine
guarded by a Condition variable, with a per-generation stop Event and an
explicit stop-owner field.

Lifecycle transitions:
  STOPPED -> STARTING -> RUNNING -> STOPPING -> STOPPED

Key guarantees:
  * start() blocks until the monitor is RUNNING. It creates a fresh stop
    Event for the new generation so a new start() cannot accidentally
    clear or signal the previous generation's cancellation. start()
    refuses to create a new monitor thread while a previous generation's
    thread is still alive (defensive live-thread check).
  * stop() uses a _stop_owner field (threading.Thread or None) guarded
    by _cv. At most one caller owns the join at any time. Waiters
    encountering STOPPING re-evaluate after every notify_all(): if
    _stop_owner is None (either because the previous owner finished
    successfully — state is STOPPED — or because it timed out and
    released ownership) a new caller can claim ownership and join the
    existing monitor thread.
  * When a join times out (stuck health_check), the owner releases
    _stop_owner (sets it to None), leaves _state=STOPPING with
    _thread/_stop_event retained, logs a warning, and returns. A
    subsequent stop() retries the join; stop() never falsely reports
    STOPPED while the thread is alive.
  * A loop's finally block transitions state to STOPPED only if it
    still owns the lifecycle (matching generation AND self._thread
    identity match). This prevents a stale finally from clobbering a
    newer generation.
  * Callback-triggered stop() from the monitor thread signals without
    self-joining (avoids deadlock); the loop's own finally finishes
    the transition.
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
    # Join timeout/poll defaults. Exposed as class attributes so tests
    # can override for fast deterministic scenarios without sleeping 30s.
    JOIN_TOTAL_TIMEOUT: float = 30.0
    JOIN_POLL_INTERVAL: float = 1.0

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
        # Set to the generation id when _loop successfully enters
        # RUNNING. Used by start() to distinguish "our generation
        # reached RUNNING and was then stopped" (success) from "our
        # generation was cancelled before ever reaching RUNNING"
        # (retry).
        self._running_generation: int = 0

        # Stop-owner tracking. Only the thread that is currently
        # performing a join (i.e., owns the STOPPING transition) is
        # stored here. None means nobody currently owns the stop; in
        # state STOPPING with _stop_owner=None, a new caller may claim
        # ownership and retry the join.
        self._stop_owner: Optional[threading.Thread] = None

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
        generation. If a racing stop cancels our attempt before the loop
        reaches RUNNING, we retry automatically so the caller always
        observes RUNNING on return. Safe to call concurrently and
        idempotent.
        """
        # Outer retry loop: if a racing stop beats us to cancelling the
        # generation we started, loop back and start a fresh one.
        while True:
            t_to_start: Optional[threading.Thread] = None
            my_stop_event: Optional[threading.Event] = None
            my_gen = 0

            with self._cv:
                while True:
                    if self._state == _State.RUNNING:
                        return
                    if self._state in (_State.STARTING, _State.STOPPING):
                        self._cv.wait()
                        continue
                    assert self._state == _State.STOPPED, (
                        f"unexpected state before start: {self._state}")
                    # Refuse to start if a monitor thread is still alive.
                    if self._thread is not None and self._thread.is_alive():
                        self._cv.wait()
                        continue
                    break

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
                # Notify waiters that state has changed to STARTING so
                # they re-evaluate (e.g. other start() callers that
                # might otherwise miss the transition).
                self._cv.notify_all()

            assert t_to_start is not None
            t_to_start.start()

            # Wait until we know the outcome of our start attempt:
            #  * RUNNING observed (for our gen or newer) → success.
            #  * STOPPED observed and _running_generation >= my_gen →
            #    success (our gen or a newer one reached RUNNING before
            #    being stopped; from the caller's perspective the start
            #    happened).
            #  * STOPPED observed and _running_generation < my_gen →
            #    our gen was cancelled before it ever reached RUNNING
            #    (racing stop beat us); retry outer loop.
            with self._cv:
                while True:
                    if self._state == _State.RUNNING:
                        return
                    if self._state == _State.STOPPED:
                        if self._running_generation >= my_gen:
                            return  # ran (us or newer) then stopped
                        # Our gen was cancelled before RUNNING; retry.
                        break
                    self._cv.wait()

    def stop(self):
        """Stop the monitor.

        Blocks until the monitoring loop has fully exited and the thread
        has been joined, or until JOIN_TOTAL_TIMEOUT elapses — in which
        case state remains STOPPING, stop-ownership is released, and the
        caller may call stop() again to retry joining.

        STOPPED vs STOPPING:
          * STOPPED means the monitor thread is dead and the monitor is
            ready for start().
          * STOPPING means someone has requested shutdown; the monitor
            thread may or may not still be alive. If stop() returned due
            to timeout, the thread is still alive and _stop_owner is
            None so another stop() can claim ownership and retry.

        When called from the monitor thread itself (e.g. from a health-
        change listener), signals the loop and returns immediately
        without self-joining; the loop's own finally finishes shutdown.

        Concurrent stop() calls: at most one caller performs the join
        (sets _stop_owner to itself). Other callers wait on the
        Condition and re-evaluate; they do not mark STOPPED themselves.
        """
        me = threading.current_thread()

        while True:
            join_thread: Optional[threading.Thread] = None
            join_gen: int = -1
            i_am_owner = False

            with self._cv:
                # Fast path: already STOPPED.
                if self._state == _State.STOPPED:
                    return

                # Always signal the current generation's stop event;
                # harmless to set repeatedly.
                if self._stop_event is not None:
                    self._stop_event.set()

                # Self-stop (from listener callback on the monitor thread):
                # signal but never self-join.
                if self._thread is not None and self._thread is me:
                    if self._state in (_State.STARTING, _State.RUNNING):
                        self._state = _State.STOPPING
                        self._stop_owner = None  # nobody is joining
                    self._cv.notify_all()
                    return

                if self._state == _State.STARTING:
                    # start() is still bringing the thread up; wait.
                    self._cv.wait()
                    continue

                if self._state == _State.STOPPING:
                    owner_alive = (self._stop_owner is not None
                                   and self._stop_owner.is_alive()
                                   and self._stop_owner is not me)
                    if owner_alive:
                        # Another live thread is performing the join;
                        # wait for it to finish (either it succeeds —
                        # state becomes STOPPED — or it times out and
                        # releases ownership — _stop_owner becomes None
                        # and we loop back to claim it).
                        self._cv.wait()
                        continue
                    else:
                        # Either no owner (previous caller timed out
                        # and released ownership) or owner is dead
                        # (shouldn't happen normally, but defensive).
                        # We can claim ownership and join the existing
                        # _thread.
                        pass

                elif self._state == _State.RUNNING:
                    # We are the first to initiate stop.
                    pass
                else:  # pragma: no cover - defensive
                    self._cv.wait()
                    continue

                # Claim ownership. Capture the generation we are
                # stopping so post-join cleanup never clobbers a newer
                # generation that a concurrent start() may create.
                assert self._thread is not None, (
                    f"cannot claim stop with no _thread (state={self._state})")
                self._state = _State.STOPPING
                self._stop_owner = me
                join_thread = self._thread
                join_gen = self._generation
                i_am_owner = True
                self._cv.notify_all()

            # --- Join OUTSIDE the lock ---
            assert join_thread is not None
            deadline = time.monotonic() + self.JOIN_TOTAL_TIMEOUT
            timed_out = False

            # Note: even if we're not the owner (shouldn't happen after
            # the claim above, but in a pathological re-entry), guard
            # against self-join.
            if join_thread is me:
                # Callback re-entry; shouldn't reach here because we
                # return early above, but be safe.
                pass
            else:
                while True:
                    if not join_thread.is_alive():
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        break
                    try:
                        join_thread.join(
                            timeout=min(self.JOIN_POLL_INTERVAL, remaining))
                    except RuntimeError:
                        # "cannot join before it is started"
                        time.sleep(0.001)

            with self._cv:
                if not i_am_owner:
                    self._cv.notify_all()
                    return

                if timed_out:
                    # Release ownership but DO NOT clear _thread/_state.
                    # The monitor thread is still alive; its finally
                    # will run when it eventually exits and will do
                    # the cleanup (identity check still works because
                    # we leave _thread pointing at it).
                    self._stop_owner = None
                    logger.warning(
                        "HealthMonitor thread did not exit within %.1fs "
                        "(provider health_check likely stuck); state "
                        "remains STOPPING and ownership has been "
                        "released. Call stop() again to retry.",
                        self.JOIN_TOTAL_TIMEOUT)
                    self._cv.notify_all()
                    return

                # Thread is dead (we observed join() returning). Release
                # ownership and yield _cv briefly so the loop's finally
                # can run its cleanup. Crucially, we only wait/cleanup
                # for the GENERATION we were stopping — if a concurrent
                # start() already created a newer generation (advanced
                # self._generation past join_gen), we must not touch
                # state/_thread because that new gen owns them.
                self._stop_owner = None
                self._cv.notify_all()
                if self._generation == join_gen:
                    # Give the finally a fair chance to acquire _cv and
                    # transition this generation to STOPPED.
                    waited = 0.0
                    while waited < 0.25 and (self._state != _State.STOPPED
                                             or self._thread is not None):
                        self._cv.wait(timeout=0.02)
                        waited += 0.02
                    # Defensive: if finally hasn't cleaned up (killed
                    # thread, unexpected exception), finalize this
                    # generation ourselves.
                    if (self._generation == join_gen
                            and (self._state != _State.STOPPED
                                 or self._thread is not None)):
                        self._state = _State.STOPPED
                        self._thread = None
                        self._stop_event = None
                # else: new generation already started; its lifecycle
                # is no longer ours to touch. The dead thread's finally
                # will still run but will correctly skip cleanup
                # because self._generation != generation (its gen) and
                # self._thread is not current_thread() (it points at
                # the new gen's Thread).
                self._cv.notify_all()
                return

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
                self._running_generation = generation
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
                    self._stop_owner = None
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
