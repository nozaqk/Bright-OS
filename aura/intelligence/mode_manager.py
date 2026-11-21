"""AI Mode manager.

Three modes (no reinstall required to change):
  - LOCAL:   All inference runs on local models. Cloud calls are disabled
             even if a key is configured.
  - HYBRID:  Local inference is the default. Cloud calls require explicit
             per-request consent AND a configured API key.
  - OFFLINE: All network calls disabled. Local models only; any attempt to
             reach the internet is blocked at the provider level.

Mode changes at runtime must:
  - Cancel any in-flight cloud requests when switching OFFLINE/LOCAL.
  - Preserve loaded local models where possible.
  - Emit a D-Bus signal (handled at the service layer).
"""
import enum
import logging
import threading
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("aura.intelligence.modes")


class AIMode(enum.Enum):
    LOCAL = "local"
    HYBRID = "hybrid"
    OFFLINE = "offline"


VALID_MODES = {m.value for m in AIMode}


class ModeError(RuntimeError):
    pass


class ModeManager:
    def __init__(self, initial_mode: str = "local"):
        self._mode = AIMode(initial_mode) if initial_mode in VALID_MODES else AIMode.LOCAL
        self._lock = threading.RLock()
        self._consent_cb: Optional[Callable[[str], bool]] = None
        self._change_listeners: List[Callable[[AIMode, AIMode], None]] = []
        # Pending-consent tracking
        self._cloud_consent_pending: Dict[str, bool] = {}

    @property
    def mode(self) -> AIMode:
        with self._lock:
            return self._mode

    def set_mode(self, new_mode: str) -> AIMode:
        if new_mode not in VALID_MODES:
            raise ModeError(f"invalid mode '{new_mode}' (must be one of "
                            f"{sorted(VALID_MODES)})")
        with self._lock:
            nm = AIMode(new_mode)
            old = self._mode
            if nm == old:
                return nm
            self._mode = nm
            # Cancel pending consents when leaving HYBRID
            if nm != AIMode.HYBRID:
                self._cloud_consent_pending.clear()
            logger.info("AI mode changed: %s -> %s", old.value, nm.value)
        for cb in list(self._change_listeners):
            try:
                cb(old, nm)
            except Exception as e:
                logger.debug("Mode change listener error: %s", e)
        return nm

    def add_change_listener(self, cb: Callable[[AIMode, AIMode], None]):
        self._change_listeners.append(cb)

    def set_consent_callback(self, cb: Callable[[str], bool]):
        """Set a function `fn(reason) -> bool` that prompts the user for
        consent to use the cloud. Returns True if granted."""
        self._consent_cb = cb

    def cloud_allowed(self, reason: str = "") -> bool:
        """Return True if a cloud call may proceed in the current mode.

        In LOCAL and OFFLINE: always False.
        In HYBRID: requires an interactive consent check via the consent
        callback. Mode is re-checked AFTER the consent callback returns
        to avoid a race where the user switches mode mid-prompt.
        """
        with self._lock:
            if self._mode != AIMode.HYBRID:
                return False
            if self._consent_cb is None:
                logger.warning("Hybrid mode active but no consent callback "
                               "registered; denying cloud call")
                return False
            cb = self._consent_cb
        # Call callback outside the lock (it may open a UI dialog)
        try:
            granted = bool(cb(reason))
        except Exception as e:
            logger.error("Consent callback failed: %s", e)
            granted = False
        # Double-check mode after callback: user could have switched to OFFLINE
        # while the dialog was open.
        with self._lock:
            if self._mode != AIMode.HYBRID:
                logger.info("Mode changed during consent prompt; denying cloud")
                return False
        if not granted:
            logger.info("User denied cloud consent for: %s", reason[:80])
        return granted

    def network_enabled(self) -> bool:
        """OFFLINE disables all network (even downloads)."""
        with self._lock:
            return self._mode != AIMode.OFFLINE
