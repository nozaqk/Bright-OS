"""Abstract interface for AI inference providers.

Every backend (llama.cpp, Ollama, cloud) implements this interface so the
InferenceEngine and ResourceManager can treat them uniformly.
"""
import abc
import enum
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .model_info import ModelInfo

logger = logging.getLogger("aura.intelligence.provider")


class ProviderState(enum.Enum):
    UNAVAILABLE = "unavailable"   # binary/deps missing
    IDLE = "idle"                 # ready but no model loaded
    LOADING = "loading"           # loading weights
    READY = "ready"               # model loaded, ready to infer
    GENERATING = "generating"     # actively processing a request
    ERROR = "error"               # last operation failed


@dataclass
class InferenceRequest:
    """A single inference request."""
    request_id: str
    prompt: str
    max_tokens: int = 512
    temperature: float = 0.7
    stop: List[str] = field(default_factory=list)
    stream: bool = False
    # Optional callback invoked per token (only if stream=True)
    on_token: Optional[Callable[[str], None]] = None
    # Cancel event: set by caller to request graceful cancellation
    cancel: Optional[threading.Event] = None
    # Metadata (e.g. conversation id); not sent to providers
    metadata: Dict[str, Any] = field(default_factory=dict)
    submitted_at: float = field(default_factory=time.monotonic)


@dataclass
class InferenceResult:
    request_id: str
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    provider: str = ""
    model: str = ""
    error: Optional[str] = None
    cancelled: bool = False
    duration_ms: int = 0


class Provider(abc.ABC):
    """Abstract base class for AI inference backends."""

    name: str = "base"
    local: bool = True        # True = does not call the network
    requires_consent: bool = False
    # Set to True if this provider is optional (e.g. Ollama is not required)
    optional: bool = False

    def __init__(self):
        self.state = ProviderState.UNAVAILABLE
        self.state_lock = threading.Lock()
        self.last_error: Optional[str] = None
        self.current_model: Optional[ModelInfo] = None
        self._state_listeners: List[Callable[[ProviderState, ProviderState], None]] = []
        self._cancel_events: Dict[str, threading.Event] = {}

    # -- Lifecycle ----------------------------------------------------------
    @abc.abstractmethod
    def check_available(self) -> bool:
        """Return True if this provider's binary/deps are present."""

    @abc.abstractmethod
    def load_model(self, model: ModelInfo, **kwargs) -> bool:
        """Load a model. Returns True on success."""

    @abc.abstractmethod
    def unload_model(self):
        """Release model resources (must be safe to call repeatedly)."""

    @abc.abstractmethod
    def is_model_compatible(self, model: ModelInfo) -> bool:
        """Return True if this provider can load `model`."""

    @abc.abstractmethod
    def generate(self, request: InferenceRequest) -> InferenceResult:
        """Run inference. Must honor request.cancel when set."""

    # -- Optional overrides -------------------------------------------------
    def cancel(self, request_id: str) -> bool:
        evt = self._cancel_events.get(request_id)
        if evt:
            evt.set()
            return True
        return False

    def cancel_all(self):
        for evt in self._cancel_events.values():
            evt.set()

    def estimated_memory_for(self, model: ModelInfo) -> int:
        """Return estimated MB needed to load `model`. Defaults to
        model.estimated_memory_mb()."""
        return model.estimated_memory_mb()

    def current_memory_mb(self) -> int:
        """Approximate current memory held by the loaded model in MB.
        Default: 0 if idle, estimate if loaded."""
        if self.current_model and self.state in (ProviderState.READY,
                                                 ProviderState.GENERATING):
            return self.current_model.estimated_memory_mb()
        return 0

    def health_check(self) -> bool:
        """Return True if provider is healthy (process alive / reachable)."""
        return self.state != ProviderState.ERROR

    # -- Helpers for subclasses --------------------------------------------
    def _set_state(self, new_state: ProviderState, error: Optional[str] = None):
        with self.state_lock:
            old = self.state
            self.state = new_state
            if error is not None:
                self.last_error = error
        for cb in list(self._state_listeners):
            try:
                cb(old, new_state)
            except Exception as e:
                logger.debug("State listener error: %s", e)

    def add_state_listener(self, cb: Callable[[ProviderState, ProviderState], None]):
        self._state_listeners.append(cb)

    def remove_state_listener(self, cb):
        if cb in self._state_listeners:
            self._state_listeners.remove(cb)
