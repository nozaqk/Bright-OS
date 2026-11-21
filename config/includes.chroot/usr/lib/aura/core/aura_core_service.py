#!/usr/bin/env python3
"""AURA Core D-Bus service.

Exposes the org.bright_os.AURA D-Bus interface for desktop components,
security tools, and user-facing apps to interact with AURA.

This service runs as the 'aura' user (not root). Privileged operations
are mediated through Polkit and restricted helper programs.

Usage:
    aura-core-service [--foreground] [--config-dir DIR]
"""
import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

# Ensure the aura package is importable when running from source tree
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aura.core import AURA_SERVICE_NAME, AURA_OBJECT_PATH, AURA_INTERFACE, AURA_VERSION
from aura.core.config import AuraConfig
from aura.core.logger import setup_logging
from aura.core.components import (
    ComponentManager, Component, ComponentState,
)

logger = logging.getLogger("aura.core")

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False
    logger.warning("python3-dbus not available; running in headless/test mode")


class AuraStarterComponent(Component):
    """Placeholder components that represent subsystems not yet implemented.

    In Phase 1 these are stubs; later phases will replace them with real
    implementations. They register as STARTING → DISABLED when their
    prerequisites aren't met, allowing the core to stay up.
    """

    def __init__(self, name: str, available: bool = True, note: str = ""):
        super().__init__(name)
        self._available = available
        self._note = note

    def start(self):
        if self._available:
            self.state = ComponentState.RUNNING
            logger.info("Component %s ready (placeholder): %s",
                        self.name, self._note or "phase-1 stub")
        else:
            self.state = ComponentState.DISABLED
            logger.info("Component %s disabled: %s", self.name, self._note)


if HAS_DBUS:
    class AURAService(dbus.service.Object):
        """D-Bus object exposing AURA's management interface."""

        def __init__(self, bus, component_manager: ComponentManager, config: AuraConfig):
            super().__init__(bus, AURA_OBJECT_PATH)
            self._components = component_manager
            self._config = config
            self._start_time = time.time()

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="s")
        def GetVersion(self):
            return AURA_VERSION

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="s")
        def GetStatus(self):
            """Return overall service status as a string."""
            return "running"

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="a{sv}")
        def GetServiceInfo(self):
            """Return service metadata."""
            return {
                "version": AURA_VERSION,
                "uptime_seconds": dbus.Int64(int(time.time() - self._start_time)),
                "pid": dbus.UInt32(os.getpid()),
                "user": os.environ.get("USER", "unknown"),
            }

        @dbus.service.method(AURA_INTERFACE, in_signature="s", out_signature="a{sv}")
        def GetComponentStatus(self, name: str):
            """Get status of a specific component."""
            status = self._components.get_status(name)
            if not status:
                return {"error": f"Component '{name}' not found"}
            return dbus.Dictionary(status.to_dict(), signature="sv")

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="a{sa{sv}}")
        def GetAllComponentStatus(self):
            """Get status of all components."""
            result = dbus.Dictionary({}, signature="sa{sv}")
            for name, status in self._components.get_all_status().items():
                result[name] = dbus.Dictionary(status.to_dict(), signature="sv")
            return result

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="as")
        def ListComponents(self):
            """List all registered component names."""
            return list(self._components.get_all_status().keys())

        @dbus.service.method(AURA_INTERFACE, in_signature="s", out_signature="b")
        def IsComponentHealthy(self, name: str):
            status = self._components.get_status(name)
            return bool(status and status.state == ComponentState.RUNNING)

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="s")
        def GetAIMode(self):
            return self._config.get("intelligence", "mode")

        @dbus.service.method(AURA_INTERFACE, in_signature="b", out_signature="")
        def Shutdown(self):
            """Request clean shutdown of the AURA service."""
            logger.info("Shutdown requested via D-Bus")
            self._components.stop_all()
            GLib.MainLoop().quit()

        @dbus.service.signal(AURA_INTERFACE, signature="ssa{sv}")
        def ComponentStateChanged(self, component_name, new_state, details):
            """Emitted when a component changes state."""
            pass

        @dbus.service.signal(AURA_INTERFACE, signature="sa{sv}")
        def SecurityAlert(self, alert_type, details):
            """Emitted when the security engine detects a threat."""
            pass


def parse_args():
    parser = argparse.ArgumentParser(description="AURA Core service")
    parser.add_argument("--foreground", "-f", action="store_true",
                        help="Run in foreground (don't daemonize)")
    parser.add_argument("--config-dir", default="/etc/bright-os/aura",
                        help="Configuration directory")
    return parser.parse_args()


def main():
    args = parse_args()

    # Load config before logging so we can get the log level
    config = AuraConfig(config_dir=args.config_dir)
    log = setup_logging(config.get("core", "log_level"))

    log.info("=" * 60)
    log.info("AURA Core v%s starting", AURA_VERSION)
    log.info("PID: %d, User: %s", os.getpid(), os.environ.get("USER", "unknown"))
    log.info("Config dir: %s", args.config_dir)
    log.info("=" * 60)

    # Initialize component manager
    restart_limit = config.getint("core", "component_restart_limit")
    restart_delay = config.getint("core", "component_restart_delay")
    component_mgr = ComponentManager(
        restart_limit=restart_limit,
        restart_delay=restart_delay,
    )

    # Register Phase 1 placeholders. Each subsystem will replace these with
    # real implementations in subsequent phases.
    component_mgr.register(AuraStarterComponent(
        "intelligence",
        note="Phase 2: AI provider architecture (local/hybrid/offline)",
    ))
    component_mgr.register(AuraStarterComponent(
        "commands",
        available=False,
        note="Phase 3: Task planning and restricted execution",
    ))
    component_mgr.register(AuraStarterComponent(
        "security",
        note="Phase 4: Security monitoring and controlled protection",
    ))
    component_mgr.register(AuraStarterComponent(
        "memory",
        note="Phase 5: User-controlled local memory",
    ))
    component_mgr.register(AuraStarterComponent(
        "recovery",
        note="Phase 5: Configuration backup and recovery",
    ))

    # Start all components
    component_mgr.start_all()

    # Set up signal handlers
    def handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name
        log.info("Received %s — shutting down", sig_name)
        component_mgr.stop_all()
        if HAS_DBUS:
            try:
                GLib.MainLoop().quit()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    if not HAS_DBUS:
        log.warning("D-Bus not available; AURA running in headless mode.")
        log.warning("Install python3-dbus and python3-gi for full functionality.")
        # Keep running in foreground for testing
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            component_mgr.stop_all()
        return 0

    # Start D-Bus service
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    try:
        bus = dbus.SystemBus()
        name = dbus.service.BusName(AURA_SERVICE_NAME, bus)
        service = AURAService(bus, component_mgr, config)
        log.info("D-Bus service registered: %s", AURA_SERVICE_NAME)
    except Exception as e:
        log.error("Failed to register D-Bus service: %s", e)
        log.error("Is another AURA instance running, or do you lack D-Bus permissions?")
        component_mgr.stop_all()
        return 1

    log.info("AURA Core is ready.")

    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down")
    finally:
        component_mgr.stop_all()

    return 0


if __name__ == "__main__":
    sys.exit(main())
