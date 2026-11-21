#!/usr/bin/env python3
"""Regression tests for aura.core.components.

These tests cover the Phase 1 bugs fixed on the Phase 2 branch:

1. DISABLED -> RUNNING race: _start_component must not override a state that
   Component.start() set (e.g. DISABLED when prerequisites are missing).
2. Watchdog must not restart DISABLED or STOPPED components.
3. Permanent-fail components (restart_limit exceeded) must not spam logs.
4. State-change callback must fire on all transitions.
"""
import os
import sys
import threading
import time
import unittest

# Ensure the project root is on sys.path so `aura.core` imports work when tests
# are executed directly.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "..", ".."))

from aura.core.components import Component, ComponentManager, ComponentState


class _FakeComponent(Component):
    """Configurable fake component for tests."""

    def __init__(self, name: str, start_fail=False, health_fail=False,
                 disable_on_start=False, start_sleep=0.0):
        super().__init__(name)
        self.start_fail = start_fail
        self.health_fail = health_fail
        self.disable_on_start = disable_on_start
        self.start_sleep = start_sleep
        self.start_count = 0
        self.stop_count = 0
        self.health_count = 0

    def start(self):
        self.start_count += 1
        if self.start_sleep:
            time.sleep(self.start_sleep)
        if self.disable_on_start:
            self.state = ComponentState.DISABLED
        if self.start_fail:
            raise RuntimeError(f"fake start failure for {self.name}")

    def stop(self):
        self.stop_count += 1

    def health_check(self):
        self.health_count += 1
        if self.health_fail:
            raise RuntimeError(f"fake health failure for {self.name}")
        return True


class ComponentStateRegressionTests(unittest.TestCase):
    """Regression tests for DISABLED state handling."""

    def test_disabled_remains_disabled_after_start_all(self):
        """Bug: Component.start() setting DISABLED was overwritten to RUNNING.
        Verify a component that self-disables in start() stays DISABLED."""
        mgr = ComponentManager(restart_limit=2)
        comp = _FakeComponent("self-disabling", disable_on_start=True)
        mgr.register(comp)
        # Simulate what start_all does without running watchdog (single start)
        mgr._running = True
        mgr._start_component(comp)
        self.assertEqual(comp.state, ComponentState.DISABLED,
                         f"expected DISABLED, got {comp.state}")

    def test_watchdog_does_not_restart_disabled_component(self):
        """Bug: watchdog would re-enter _start_component for DISABLED components.
        Verify a DISABLED component is not restarted by the watchdog."""
        mgr = ComponentManager(restart_limit=5)
        comp = _FakeComponent("disabled-comp")
        mgr.register(comp)
        comp.state = ComponentState.DISABLED
        mgr._running = True
        mgr._watchdog_pass()
        self.assertEqual(comp.start_count, 0,
                         "watchdog must not start a DISABLED component")
        self.assertEqual(comp.state, ComponentState.DISABLED)

    def test_watchdog_does_not_restart_stopped_component(self):
        comp = _FakeComponent("stopped-comp")
        mgr = ComponentManager(restart_limit=5)
        mgr.register(comp)
        comp.state = ComponentState.STOPPED
        mgr._running = True
        mgr._watchdog_pass()
        self.assertEqual(comp.start_count, 0,
                         "watchdog must not start a STOPPED component")
        self.assertEqual(comp.state, ComponentState.STOPPED)

    def test_permanent_failure_stops_log_spam(self):
        """Bug: FAILED components beyond restart_limit were logged every pass.
        Verify the 'bump to restart_limit+1' guard prevents repeated starts."""
        comp = _FakeComponent("failing", start_fail=True)
        mgr = ComponentManager(restart_limit=2)
        mgr.register(comp)
        mgr._running = True

        # Initial start fails -> FAILED
        mgr._start_component(comp)
        self.assertEqual(comp.state, ComponentState.FAILED)
        self.assertEqual(comp.start_count, 1)

        # Drive watchdog passes manually (more than the limit)
        for _ in range(5):
            mgr._watchdog_pass()

        # start_count = 1 (initial) + restart_limit (2) = 3 maximum
        self.assertLessEqual(comp.start_count, 3,
                             "permanent-fail component must not be restarted forever")
        self.assertGreaterEqual(comp.restart_count, mgr._restart_limit + 1,
                                "restart_count should be marked as exhausted")

    def test_failed_component_restarts_within_limit(self):
        """Health-check failures should trigger restarts up to the limit."""
        comp = _FakeComponent("flaky", health_fail=True)
        mgr = ComponentManager(restart_limit=2)
        mgr.register(comp)
        mgr._running = True
        # Get to RUNNING first (component doesn't fail on start, only on health)
        mgr._start_component(comp)
        self.assertEqual(comp.state, ComponentState.RUNNING)
        self.assertEqual(comp.start_count, 1)
        # Health check will now fail -> triggers restarts
        for _ in range(3):
            mgr._watchdog_pass()
        self.assertGreaterEqual(comp.health_count, 1)
        self.assertLessEqual(comp.start_count, 1 + mgr._restart_limit)


class StateChangeCallbackTests(unittest.TestCase):
    """Verify the optional state-change callback fires correctly."""

    def test_callback_receives_state_changes(self):
        events = []

        def cb(name, state_value, details):
            events.append((name, state_value, details))

        mgr = ComponentManager(restart_limit=1, state_change_callback=cb)
        comp = _FakeComponent("ok")
        mgr.register(comp)
        mgr._running = True
        mgr._start_component(comp)
        # Expect STARTING and RUNNING callbacks
        states = [e[1] for e in events]
        self.assertIn("starting", states)
        self.assertIn("running", states)
        mgr.stop_all()
        states_after = [e[1] for e in events]
        self.assertIn("stopped", states_after)


if __name__ == "__main__":
    unittest.main()
