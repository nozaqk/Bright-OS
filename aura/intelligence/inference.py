"""Inference Engine — the central coordinator for AURA AI.

Responsibilities:
  - Select the right provider based on current mode and request type.
  - Enforce resource-manager load decisions before loading a model.
  - Route inference requests, with lazy loading on first request.
  - Cancel in-flight requests and ensure providers release resources on
    error (so AI crashes leave AURA Core running).
  - Track active conversations via the ConversationManager.
  - Never load a large model at boot (lazy_load=True by default).
  - Emit state-change callbacks for the D-Bus API layer.
"""
import logging
import threading
import time
import uuid
from typing import Callable, Dict, List, Optional

from .conversation import Conversation, ConversationManager
from .hardware import HardwareProfile
from .health import HealthMonitor
from .mode_manager import AIMode, ModeManager
from .model_info import ModelInfo
from .model_manager import ModelManager
from .provider import (
    InferenceRequest,
    InferenceResult,
    Provider,
    ProviderState,
)
from .resource_manager import ResourceManager
from .secure_store import get_api_key
from .providers import CloudProvider, LlamaCppProvider, OllamaProvider

logger = logging.getLogger("aura.intelligence.inference")


class InferenceError(RuntimeError):
    pass


class InferenceEngine:
    def __init__(self, config=None):
        self._config = config
        self._lock = threading.RLock()
        self._mode_manager = ModeManager("local")
        self._model_manager: Optional[ModelManager] = None
        self._resource_manager: Optional[ResourceManager] = None
        self._conversation_manager = ConversationManager(persist=False)
        self._health_monitor = HealthMonitor(check_interval=30)
        self._providers: Dict[str, Provider] = {}
        self._active_provider_name: Optional[str] = None
        self._loaded_model_id: Optional[str] = None
        self._cloud_provider: Optional[CloudProvider] = None
        self._listeners: List[Callable[[str, dict], None]] = []
        self._default_model_id: str = ""
        self._auto_load: bool = False
        self._lazy_load: bool = True
        self._request_lock = threading.Lock()
        self._active_requests: Dict[str, str] = {}  # req_id -> provider name
        self._cancel_events: Dict[str, threading.Event] = {}

        # Set up providers. CLI/executable presence is probed lazily.
        self._register_default_providers()

        if config is not None:
            self.configure(config)

        # Register providers with resource manager and health monitor
        if self._resource_manager:
            for p in self._providers.values():
                self._resource_manager.register_provider(p)
                self._health_monitor.register(p)

    # -- Setup --------------------------------------------------------------
    def _register_default_providers(self):
        llama = LlamaCppProvider()
        self._providers[llama.name] = llama
        ollama = OllamaProvider()
        if ollama.check_available():
            self._providers[ollama.name] = ollama
        # Cloud provider is registered but starts unavailable/disabled
        self._cloud_provider = CloudProvider()
        self._providers[self._cloud_provider.name] = self._cloud_provider

    def configure(self, config):
        """(Re)apply configuration from an AuraConfig instance."""
        model_dir = "/var/lib/aura/models"
        try:
            model_dir = config.get("intelligence", "model_dir") or model_dir
        except Exception:
            pass
        # Default model
        try:
            self._default_model_id = config.get("intelligence", "default_model") or ""
        except Exception:
            pass
        try:
            self._auto_load = config.getboolean("intelligence", "auto_load_at_boot")
        except Exception:
            self._auto_load = False
        try:
            self._lazy_load = config.getboolean("intelligence", "lazy_load")
        except Exception:
            self._lazy_load = True

        # Mode
        try:
            mode = config.get("intelligence", "mode") or "local"
            self._mode_manager.set_mode(mode)
        except Exception:
            pass

        # Cloud: load API key via secure store, NOT from plaintext config
        endpoint = ""
        key_cmd = ""
        key_file = ""
        allow_default = False
        require_consent = True
        try:
            endpoint = config.get("intelligence", "cloud_endpoint") or ""
        except Exception:
            pass
        try:
            key_cmd = config.get("intelligence", "cloud_api_key_command") or ""
        except Exception:
            pass
        try:
            key_file = config.get("intelligence", "cloud_api_key_file") or ""
        except Exception:
            pass
        try:
            allow_default = config.getboolean("intelligence", "allow_cloud_default")
        except Exception:
            pass
        try:
            require_consent = config.getboolean("intelligence", "require_consent")
        except Exception:
            require_consent = True

        api_key = None
        if endpoint:
            api_key = get_api_key(command=key_cmd, key_file=key_file)

        # Configure cloud: disabled unless user opted in, no consent given yet
        if self._cloud_provider:
            self._cloud_provider.configure(
                endpoint=endpoint,
                api_key=api_key or "",
                model_name=self._default_model_id or "gpt-4o-mini",
                enabled=bool(api_key) and bool(endpoint) and allow_default,
                consent_given=False,  # consent is per-session/request
            )

        # Build resource and model managers
        self._model_manager = ModelManager(model_dir=model_dir)
        self._resource_manager = ResourceManager(config=config)
        for p in self._providers.values():
            self._resource_manager.register_provider(p)
            self._health_monitor.register(p)

    # -- Public API ---------------------------------------------------------
    def start(self):
        if self._resource_manager:
            self._resource_manager.start()
        self._health_monitor.start()
        # IMPORTANT: do NOT load models at boot. Models are loaded lazily on
        # first inference request or by an explicit load_model() call.
        if self._auto_load and self._default_model_id:
            logger.warning("auto_load_at_boot=true is set, but large models "
                           "should not load at boot; ignoring. Unload them if "
                           "loaded by previous sessions.")
            self.unload_model()
        logger.info("Inference engine started (mode=%s)",
                    self._mode_manager.mode.value)

    def stop(self):
        self._health_monitor.stop()
        if self._resource_manager:
            self._resource_manager.stop()
        # Cancel all active requests and unload all models
        self.cancel_all()
        for p in self._providers.values():
            try:
                p.unload_model()
            except Exception as e:
                logger.debug("Error unloading provider %s: %s", p.name, e)
        logger.info("Inference engine stopped")

    def add_listener(self, cb: Callable[[str, dict], None]):
        self._listeners.append(cb)

    def _emit(self, event: str, details: dict):
        for cb in list(self._listeners):
            try:
                cb(event, details)
            except Exception as e:
                logger.debug("Listener error: %s", e)

    # -- Mode ---------------------------------------------------------------
    @property
    def mode(self) -> AIMode:
        return self._mode_manager.mode

    def set_mode(self, mode: str):
        old = self._mode_manager.mode
        new = self._mode_manager.set_mode(mode)
        if new != old:
            # When leaving HYBRID, cancel any in-flight cloud requests
            if new in (AIMode.LOCAL, AIMode.OFFLINE) and self._cloud_provider:
                self._cloud_provider.cancel_all()
                self._cloud_provider.unload_model()
            self._emit("mode_changed", {"mode": new.value})

    def set_cloud_consent_callback(self, cb: Callable[[str], bool]):
        self._mode_manager.set_consent_callback(cb)

    def grant_cloud_consent(self) -> bool:
        """Called after explicit user consent to enable cloud for this
        session. Persisted only until mode changes or service restarts."""
        if self._cloud_provider and self._cloud_provider._api_key:
            self._cloud_provider._consent_given = True
            self._cloud_provider._enabled = True
            if self._cloud_provider.check_available():
                self._cloud_provider._set_state(ProviderState.IDLE)
            return True
        return False

    def revoke_cloud_consent(self):
        if self._cloud_provider:
            self._cloud_provider._consent_given = False
            self._cloud_provider._enabled = False
            self._cloud_provider.cancel_all()
            self._cloud_provider._set_state(ProviderState.UNAVAILABLE,
                                            "consent revoked")

    # -- Provider / model queries ------------------------------------------
    def list_providers(self) -> List[Dict[str, object]]:
        out = []
        with self._lock:
            for name, p in self._providers.items():
                out.append({
                    "name": name,
                    "state": p.state.value,
                    "local": p.local,
                    "optional": p.optional,
                    "model": p.current_model.model_id if p.current_model else "",
                    "last_error": p.last_error or "",
                })
        return out

    def list_models(self) -> List[Dict[str, object]]:
        mm = self._model_manager
        if not mm:
            return []
        return [_model_info_dict(m) for m in mm.list_models()]

    def hardware_suitability(self, model_id: str) -> Dict[str, object]:
        mm = self._model_manager
        rm = self._resource_manager
        if not mm or not rm:
            return {"ok": False, "reason": "engine not configured"}
        model = mm.get_model(model_id)
        if not model:
            return {"ok": False, "reason": f"unknown model: {model_id}"}
        # Pick best local provider
        provider = self._select_local_provider_for(model)
        if not provider:
            return {"ok": False, "reason": "no compatible local provider"}
        decision = rm.assess_model(model, provider)
        return {
            "ok": decision.allowed,
            "reason": decision.reason,
            "recommended_threads": decision.recommended_threads,
            "max_ctx_tokens": decision.max_ctx_tokens,
            "required_memory_mb": provider.estimated_memory_for(model),
        }

    def active_provider(self) -> Optional[str]:
        return self._active_provider_name

    def loaded_model(self) -> Optional[str]:
        return self._loaded_model_id

    def resource_usage(self) -> Dict[str, object]:
        rm = self._resource_manager
        if not rm:
            return {}
        return rm.current_pressure()

    def inference_status(self) -> Dict[str, object]:
        with self._request_lock:
            return {
                "active_requests": len(self._active_requests),
                "active_provider": self._active_provider_name,
                "loaded_model": self._loaded_model_id,
            }

    # -- Model load/unload --------------------------------------------------
    def load_model(self, model_id: str) -> Dict[str, object]:
        mm = self._model_manager
        rm = self._resource_manager
        if not mm or not rm:
            return {"ok": False, "error": "engine not configured"}
        model = mm.get_model(model_id)
        if not model:
            return {"ok": False, "error": f"unknown model: {model_id}"}
        provider = self._select_local_provider_for(model)
        if not provider:
            return {"ok": False, "error": "no compatible local provider available"}
        decision = rm.assess_model(model, provider)
        if not decision.allowed:
            return {"ok": False, "error": decision.reason}
        # Configure provider threads
        if hasattr(provider, "configure"):
            provider.configure(cpu_threads=decision.recommended_threads,
                               ctx_size=decision.max_ctx_tokens)
        ok = provider.load_model(model,
                                 cpu_threads=decision.recommended_threads,
                                 ctx_size=decision.max_ctx_tokens)
        if ok:
            with self._lock:
                self._active_provider_name = provider.name
                self._loaded_model_id = model_id
            rm.note_inference(provider.name)
            self._emit("model_loaded", {"model": model_id, "provider": provider.name})
            return {"ok": True, "provider": provider.name,
                    "threads": decision.recommended_threads,
                    "ctx": decision.max_ctx_tokens}
        return {"ok": False, "error": provider.last_error or "load failed"}

    def unload_model(self):
        with self._lock:
            for p in self._providers.values():
                try:
                    p.unload_model()
                except Exception as e:
                    logger.debug("unload error on %s: %s", p.name, e)
            prev_model = self._loaded_model_id
            self._loaded_model_id = None
            self._active_provider_name = None
        if prev_model:
            self._emit("model_unloaded", {"model": prev_model})

    # -- Inference ----------------------------------------------------------
    def infer(self, prompt: str, *,
              conversation_id: Optional[str] = None,
              max_tokens: int = 512,
              temperature: float = 0.7,
              use_cloud: bool = False,
              model_id: Optional[str] = None,
              on_token: Optional[Callable[[str], None]] = None) -> InferenceResult:
        """Run inference. Lazy-loads a model if necessary. Routes to cloud
        only in HYBRID mode with consent."""
        request_id = str(uuid.uuid4())
        # Cloud routing
        if use_cloud:
            if not self._mode_manager.cloud_allowed(
                    f"cloud inference for request {request_id}"):
                return InferenceResult(
                    request_id=request_id, text="",
                    error="cloud not allowed (mode/consent)",
                )
            return self._do_infer(self._cloud_provider, request_id, prompt,
                                  conversation_id, max_tokens, temperature,
                                  on_token=on_token, model_id=model_id,
                                  is_cloud=True)

        # Local path
        if not self._lazy_load and self._loaded_model_id is None:
            # Auto-load not allowed and nothing loaded
            return InferenceResult(request_id=request_id, text="",
                                   error="no model loaded; call load_model() first")
        # Lazy load if needed
        if self._loaded_model_id is None:
            target = model_id or self._default_model_id
            if not target:
                return InferenceResult(request_id=request_id, text="",
                                       error="no model loaded and no default model set")
            result = self.load_model(target)
            if not result.get("ok"):
                return InferenceResult(
                    request_id=request_id, text="",
                    error=f"load failed: {result.get('error')}",
                )

        provider = None
        with self._lock:
            if self._active_provider_name:
                provider = self._providers.get(self._active_provider_name)
        if not provider:
            return InferenceResult(request_id=request_id, text="",
                                   error="no active provider")
        return self._do_infer(provider, request_id, prompt, conversation_id,
                              max_tokens, temperature, on_token=on_token,
                              model_id=model_id or self._loaded_model_id,
                              is_cloud=False)

    def _do_infer(self, provider: Provider, request_id: str, prompt: str,
                  conversation_id: Optional[str], max_tokens: int,
                  temperature: float, on_token, model_id: Optional[str],
                  is_cloud: bool) -> InferenceResult:
        # Conversation handling
        conv: Optional[Conversation] = None
        if conversation_id:
            conv = self._conversation_manager.get(conversation_id)
            if not conv:
                conv = self._conversation_manager.new_conversation(
                    conv_id=conversation_id)
        else:
            conv = self._conversation_manager.new_conversation()

        if conv is not None:
            self._conversation_manager.append_user(conv.id, prompt)
            full_prompt = conv.format_prompt(self._resource_manager._max_context_tokens
                                             if self._resource_manager else 4096)
        else:
            full_prompt = prompt

        cancel_evt = threading.Event()
        req = InferenceRequest(
            request_id=request_id,
            prompt=full_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            on_token=on_token,
            cancel=cancel_evt,
            metadata={"conversation_id": conv.id if conv else None,
                      "is_cloud": is_cloud},
        )

        with self._request_lock:
            self._active_requests[request_id] = provider.name
            self._cancel_events[request_id] = cancel_evt
        self._emit("inference_started", {"request_id": request_id,
                                          "provider": provider.name,
                                          "cloud": is_cloud})
        try:
            result = provider.generate(req)
        except Exception as e:
            logger.error("Provider %s raised during generate: %s",
                         provider.name, e)
            # Crash recovery: ensure provider releases resources
            try:
                provider.unload_model()
            except Exception:
                pass
            # Try to restore IDLE state so AURA keeps running
            provider._set_state(ProviderState.ERROR, str(e))
            result = InferenceResult(
                request_id=request_id, text="", error=str(e),
                provider=provider.name,
                model=model_id or (provider.current_model.model_id
                                   if provider.current_model else ""),
            )
        finally:
            with self._request_lock:
                self._active_requests.pop(request_id, None)
                self._cancel_events.pop(request_id, None)

        if self._resource_manager:
            self._resource_manager.note_inference(provider.name)

        if result.error:
            self._emit("inference_error",
                       {"request_id": request_id, "error": result.error})
        elif result.cancelled:
            self._emit("inference_cancelled", {"request_id": request_id})
        else:
            if conv is not None and not is_cloud:
                self._conversation_manager.append_assistant(conv.id, result.text)
            self._emit("inference_done",
                       {"request_id": request_id,
                        "tokens_out": result.tokens_out})
        return result

    def cancel(self, request_id: str) -> bool:
        with self._request_lock:
            evt = self._cancel_events.get(request_id)
            pname = self._active_requests.get(request_id)
            provider = self._providers.get(pname) if pname else None
        if evt:
            evt.set()
        if provider:
            try:
                provider.cancel(request_id)
            except Exception:
                pass
            return True
        return evt is not None

    def cancel_all(self):
        with self._request_lock:
            items = list(self._active_requests.items())
            evts = list(self._cancel_events.items())
        for rid, evt in evts:
            evt.set()
        for rid, pname in items:
            p = self._providers.get(pname)
            if p:
                try:
                    p.cancel(rid)
                except Exception:
                    pass

    # -- Helpers ------------------------------------------------------------
    def _select_local_provider_for(self, model: ModelInfo) -> Optional[Provider]:
        """Pick the best available local provider for a model. Prefers
        llama.cpp (CPU-safe, robust subprocess isolation)."""
        # Preference order
        for name in ("llamacpp", "ollama"):
            p = self._providers.get(name)
            if p and p.check_available() and p.is_model_compatible(model):
                return p
        return None


def _model_info_dict(m: ModelInfo) -> Dict[str, object]:
    return {
        "model_id": m.model_id,
        "path": m.path,
        "format": m.format.value,
        "size_bytes": m.size_bytes,
        "size_mb": m.size_bytes // (1024 * 1024),
        "quant_type": m.quant_type,
        "param_count_b": m.param_count_b,
        "context_window": m.context_window,
        "friendly_name": m.friendly_name,
        "estimated_memory_mb": m.estimated_memory_mb(),
    }
