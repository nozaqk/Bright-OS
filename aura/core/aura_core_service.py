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

# Polkit is used for authorization checks on privileged methods. If the
# Polkit GObject introspection bindings aren't available we still start but
# refuse privileged operations for non-root callers (fail closed).
try:
    from gi.repository import Polkit
    HAS_POLKIT = True
except ImportError:
    HAS_POLKIT = False
    logger.info("Polkit gir bindings unavailable; privileged methods require root")


def _check_polkit(sender, action_id, bus=None):
    """Check whether `sender` is authorized for `action_id`.

    Returns (allowed, reason). If Polkit is unavailable, falls back to
    root-only (UID 0 on the bus). Fail closed if caller identity cannot
    be obtained or verified.
    """
    if not HAS_DBUS or bus is None:
        # Headless/test mode with no D-Bus — only local code can call us,
        # so allow. In any real service path bus is always set.
        return True, ""
    if sender is None:
        return False, "no sender identity"
    try:
        pid = bus.get_connection_unix_process_id(sender)
        uid = bus.get_unix_user(sender)
    except (dbus.DBusException, AttributeError) as e:
        logger.warning("Polkit: could not determine caller identity: %s", e)
        return False, f"could not determine caller identity: {e}"

    # Validate PID/UID before using them.
    if not isinstance(pid, int) or pid <= 0:
        return False, "invalid caller pid"
    if not isinstance(uid, int) or uid < 0:
        return False, "invalid caller uid"

    # Root (UID 0) is always authorized for any action.
    if uid == 0:
        return True, ""

    if not HAS_POLKIT:
        return False, "polkit unavailable; only root may perform this action"

    try:
        authority = Polkit.Authority.get()
        # Polkit.UnixProcess.new(pid) takes a single int PID. Polkit
        # internally reads /proc/<pid>/status to verify the UID, so a
        # stale/reused PID would not be confused with another user's
        # process (the UID mismatch causes authorization to fail).
        subject = Polkit.UnixProcess.new(pid)
        result = authority.check_authorization_sync(
            subject, action_id, None,
            Polkit.CheckAuthorizationFlags.ALLOW_USER_INTERACTION, None)
        if result.get_is_authorized():
            return True, ""
        if result.get_is_challenge():
            return False, "authentication required"
        return False, "not authorized"
    except Exception as e:
        logger.warning("Polkit check failed for %s pid=%d uid=%d: %s",
                       action_id, pid, uid, e)
        return False, f"polkit error: {e}"


class AuraStarterComponent(Component):
    """Placeholder components that represent subsystems not yet implemented."""

    def __init__(self, name: str, available: bool = True, note: str = ""):
        super().__init__(name)
        self._available = available
        self._note = note

    def start(self):
        if self._available:
            self.state = ComponentState.RUNNING
            logger.info("Component %s ready (placeholder): %s",
                        self.name, self._note or "stub")
        else:
            self.state = ComponentState.DISABLED
            logger.info("Component %s disabled: %s", self.name, self._note)


class IntelligenceComponent(Component):
    """Wraps the Phase 2 Intelligence Engine as a Component that can be
    started/stopped by the component manager and whose lifecycle faults
    are handled (watchdog will restart it up to the limit; on permanent
    failure AURA keeps running without AI)."""

    def __init__(self, name: str, config):
        super().__init__(name)
        self._config = config
        self._engine = None

    @property
    def engine(self):
        return self._engine

    def start(self):
        # Import lazily so core can start even if the intelligence package
        # has import issues on minimal systems (it will just be DISABLED).
        try:
            from aura.intelligence import InferenceEngine
        except Exception as e:
            logger.error("Intelligence package unavailable: %s", e)
            self.state = ComponentState.DISABLED
            return
        try:
            self._engine = InferenceEngine(config=self._config)
            self._engine.start()
            self.state = ComponentState.RUNNING
            logger.info("Intelligence engine started (mode=%s)",
                        self._engine.mode.value)
        except Exception as e:
            logger.error("Failed to start intelligence engine: %s", e)
            self.state = ComponentState.FAILED
            self.last_error = str(e)

    def stop(self):
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception as e:
                logger.error("Error stopping intelligence engine: %s", e)
            self._engine = None

    def health_check(self) -> bool:
        if self._engine is None:
            return False
        # Basic liveness: if any provider is in ERROR state, still healthy
        # as long as we have an engine object. Deeper checks via providers.
        return True


if HAS_DBUS:
    class AURAService(dbus.service.Object):
        """D-Bus object exposing AURA's management + Intelligence API."""

        def __init__(self, bus, component_manager: ComponentManager, config: AuraConfig,
                     intelligence_component: "IntelligenceComponent" = None,
                     mainloop=None):
            super().__init__(bus, AURA_OBJECT_PATH)
            self._bus = bus
            self._components = component_manager
            self._config = config
            self._intel = intelligence_component
            self._mainloop = mainloop
            self._start_time = time.time()

        def _engine(self):
            if self._intel is None:
                return None
            return self._intel.engine

        # --- Core methods ---------------------------------------------------
        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="s")
        def GetVersion(self):
            return AURA_VERSION

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="s")
        def GetStatus(self):
            return "running"

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="a{sv}")
        def GetServiceInfo(self):
            return {
                "version": AURA_VERSION,
                "uptime_seconds": dbus.Int64(int(time.time() - self._start_time)),
                "pid": dbus.UInt32(os.getpid()),
                "user": os.environ.get("USER", "unknown"),
            }

        @dbus.service.method(AURA_INTERFACE, in_signature="s", out_signature="a{sv}")
        def GetComponentStatus(self, name: str):
            status = self._components.get_status(name)
            if not status:
                return {"error": f"Component '{name}' not found"}
            return dbus.Dictionary(status.to_dict(), signature="sv")

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="a{sa{sv}}")
        def GetAllComponentStatus(self):
            result = dbus.Dictionary({}, signature="sa{sv}")
            for name, status in self._components.get_all_status().items():
                result[name] = dbus.Dictionary(status.to_dict(), signature="sv")
            return result

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="as")
        def ListComponents(self):
            return list(self._components.get_all_status().keys())

        @dbus.service.method(AURA_INTERFACE, in_signature="s", out_signature="b")
        def IsComponentHealthy(self, name: str):
            status = self._components.get_status(name)
            return bool(status and status.state == ComponentState.RUNNING)

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="",
                             sender_keyword="sender")
        def Shutdown(self, sender=None):
            ok, reason = _check_polkit(
                sender, "org.bright_os.AURA.shutdown",
                bus=self._bus if hasattr(self, "_bus") else None)
            if not ok:
                logger.warning("Shutdown denied for %s: %s", sender, reason)
                raise dbus.exceptions.DBusException(
                    "org.bright_os.AURA.NotAuthorized",
                    f"Shutdown not authorized: {reason}")
            logger.info("Shutdown requested via D-Bus by %s", sender)
            self._components.stop_all()
            if self._mainloop is not None:
                GLib.idle_add(self._mainloop.quit)
            else:
                logger.warning("Shutdown called but no main loop reference")

        # --- Intelligence API (backward-compatible additions) --------------
        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="s")
        def GetAIMode(self):
            eng = self._engine()
            if eng:
                return eng.mode.value
            return self._config.get("intelligence", "mode")

        @dbus.service.method(AURA_INTERFACE, in_signature="s", out_signature="b")
        def SetAIMode(self, mode: str):
            """Set AI mode: 'local', 'hybrid', or 'offline'."""
            eng = self._engine()
            if not eng:
                return False
            try:
                eng.set_mode(mode)
                # Persist to config
                self._config.set("intelligence", "mode", eng.mode.value)
                try:
                    self._config.save()
                except Exception as e:
                    logger.warning("Could not persist mode change: %s", e)
                return True
            except Exception as e:
                logger.warning("SetAIMode failed: %s", e)
                return False

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="aa{sv}")
        def ListAIModels(self):
            """List locally available models."""
            eng = self._engine()
            if not eng:
                return []
            return [dbus.Dictionary(m, signature="sv") for m in eng.list_models()]

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="aa{sv}")
        def ListAIProviders(self):
            eng = self._engine()
            if not eng:
                return []
            return [dbus.Dictionary(p, signature="sv") for p in eng.list_providers()]

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="s")
        def GetActiveAIProvider(self):
            eng = self._engine()
            if not eng:
                return ""
            return eng.active_provider() or ""

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="s")
        def GetLoadedModel(self):
            eng = self._engine()
            if not eng:
                return ""
            return eng.loaded_model() or ""

        @dbus.service.method(AURA_INTERFACE, in_signature="s", out_signature="b")
        def LoadAIModel(self, model_id: str):
            eng = self._engine()
            if not eng:
                return False
            result = eng.load_model(model_id)
            return bool(result.get("ok"))

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="")
        def UnloadAIModel(self):
            eng = self._engine()
            if eng:
                eng.unload_model()

        @dbus.service.method(AURA_INTERFACE, in_signature="s", out_signature="a{sv}")
        def GetHardwareSuitability(self, model_id: str):
            eng = self._engine()
            if not eng:
                return {"ok": False, "reason": "intelligence engine not ready"}
            return dbus.Dictionary(eng.hardware_suitability(model_id), signature="sv")

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="a{sv}")
        def GetResourceUsage(self):
            eng = self._engine()
            if not eng:
                return {}
            usage = eng.resource_usage()
            return dbus.Dictionary({k: _dbus_safe(v) for k, v in usage.items()},
                                   signature="sv")

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="a{sv}")
        def GetInferenceStatus(self):
            eng = self._engine()
            if not eng:
                return {}
            st = eng.inference_status()
            return dbus.Dictionary({k: _dbus_safe(v) for k, v in st.items()},
                                   signature="sv")

        @dbus.service.method(AURA_INTERFACE, in_signature="s", out_signature="b")
        def CancelInference(self, request_id: str):
            eng = self._engine()
            if not eng:
                return False
            return eng.cancel(request_id)

        @dbus.service.method(AURA_INTERFACE, in_signature="", out_signature="")
        def CancelAllInference(self):
            eng = self._engine()
            if eng:
                eng.cancel_all()

        @dbus.service.method(AURA_INTERFACE, in_signature="b", out_signature="b",
                             sender_keyword="sender")
        def GrantCloudConsent(self, granted: bool, sender=None):
            # Granting consent is a privileged action (allows cloud traffic);
            # revoking consent is allowed for any caller (fail-safe).
            if granted:
                ok, reason = _check_polkit(
                    sender, "org.bright_os.AURA.grant-cloud-consent",
                    bus=self._bus if hasattr(self, "_bus") else None)
                if not ok:
                    logger.warning("GrantCloudConsent denied for %s: %s",
                                   sender, reason)
                    raise dbus.exceptions.DBusException(
                        "org.bright_os.AURA.NotAuthorized",
                        f"Cloud consent not authorized: {reason}")
            eng = self._engine()
            if not eng:
                return False
            if granted:
                return eng.grant_cloud_consent()
            else:
                eng.revoke_cloud_consent()
                return True

        # --- Signals --------------------------------------------------------
        @dbus.service.signal(AURA_INTERFACE, signature="ssa{sv}")
        def ComponentStateChanged(self, component_name, new_state, details):
            pass

        @dbus.service.signal(AURA_INTERFACE, signature="sa{sv}")
        def SecurityAlert(self, alert_type, details):
            pass

        @dbus.service.signal(AURA_INTERFACE, signature="sa{sv}")
        def AIEvent(self, event_type, details):
            """Emitted for intelligence events: model_loaded, model_unloaded,
            inference_started, inference_done, inference_cancelled,
            inference_error, mode_changed."""
            pass


def _dbus_safe(value):
    """Convert python values to dbus-compatible types."""
    if isinstance(value, bool):
        return dbus.Boolean(value)
    if isinstance(value, int):
        return dbus.Int64(value)
    if isinstance(value, float):
        return dbus.Double(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_dbus_safe(v) for v in value]
    if isinstance(value, dict):
        return dbus.Dictionary({str(k): _dbus_safe(v) for k, v in value.items()},
                               signature="sv")
    return str(value)


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

    # Real intelligence component (Phase 2); will self-disable if deps missing
    intel_component = IntelligenceComponent("intelligence", config)
    component_mgr.register(intel_component)

    # Other subsystems remain placeholders until later phases
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

    # These are set after D-Bus init for signal handlers and the service object
    loop = None
    service = None

    # Wire component state changes and AI events to D-Bus signal emission.
    # Service is set later once D-Bus is up.
    def _state_changed_cb(name, state_value, details):
        if service is not None:
            GLib.idle_add(service.ComponentStateChanged, name, state_value, details)
    component_mgr._state_change_callback = _state_changed_cb

    def _ai_event_cb(event_type, details):
        if service is not None:
            safe = {str(k): _dbus_safe(v) for k, v in details.items()}
            GLib.idle_add(service.AIEvent, event_type, safe)

    # Wire AI events after engine start. We hook this lazily once the
    # component is in RUNNING state.
    def _wire_ai_listeners():
        eng = intel_component.engine
        if eng is not None:
            eng.add_listener(_ai_event_cb)

    # Start all components
    component_mgr.start_all()

    # After start_all, the intelligence component has either reached RUNNING
    # or disabled itself; wire up its event listeners if it's up.
    _wire_ai_listeners()

    # Set up signal handlers (use a closure so we can reference 'loop' once set)
    def handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name
        log.info("Received %s — shutting down", sig_name)
        component_mgr.stop_all()
        if loop is not None and HAS_DBUS:
            GLib.idle_add(loop.quit)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    if not HAS_DBUS:
        log.warning("D-Bus not available; AURA running in headless mode.")
        log.warning("Install python3-dbus and python3-gi for full functionality.")
        # Keep running in foreground for testing
        _headless_running = True
        def _stop_headless(signum, frame):
            nonlocal _headless_running
            _headless_running = False
        signal.signal(signal.SIGTERM, _stop_headless)
        signal.signal(signal.SIGINT, _stop_headless)
        try:
            while _headless_running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        component_mgr.stop_all()
        return 0

    # Start D-Bus service
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    loop = GLib.MainLoop()

    try:
        bus = dbus.SystemBus()
        name = dbus.service.BusName(AURA_SERVICE_NAME, bus)
        service = AURAService(bus, component_mgr, config,
                              intelligence_component=intel_component,
                              mainloop=loop)
        log.info("D-Bus service registered: %s", AURA_SERVICE_NAME)
    except Exception as e:
        log.error("Failed to register D-Bus service: %s", e)
        log.error("Is another AURA instance running, or do you lack D-Bus permissions?")
        component_mgr.stop_all()
        return 1

    log.info("AURA Core is ready.")

    try:
        loop.run()
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down")
    finally:
        component_mgr.stop_all()

    return 0


if __name__ == "__main__":
    sys.exit(main())
