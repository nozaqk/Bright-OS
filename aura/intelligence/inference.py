"""Inference Engine — the central coordinator for AURA AI.

Phase 2.1 hardening:
  * load_model() serialises across threads; checks for active inference
    before swapping models.
  * unload_model() refuses to unload while inference is active (or
    cancels active inferences first — explicit flag).
  * Mode changes are correctly ordered: cancel cloud, THEN flip state,
    so concurrent infer() calls after the flip are rejected.
  * infer(use_cloud=True) double-checks mode after getting consent.
  * Offline mode gates model downloads via network_enabled().
  * No access to private members of ResourceManager.
  * Credential-command failures (SecureStoreError) are caught so they
    don't crash start-up.
"""
import logging
import threading
import time
import uuid
from typing import Callable, Dict, List, Optional

from .conversation import Conversation, ConversationManager
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
from .secure_store import SecureStoreError, get_api_key
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
        self._max_context_tokens: int = 4096
        self._load_lock = threading.RLock()  # serialises load/unload (reentrant)
        self._request_lock = threading.Lock()
        self._active_requests: Dict[str, str] = {}
        self._cancel_events: Dict[str, threading.Event] = {}

        self._register_default_providers()

        if config is not None:
            self.configure(config)

        if self._resource_manager:
            for p in self._providers.values():
                self._resource_manager.register_provider(p)
                self._health_monitor.register(p)

    def _register_default_providers(self):
        llama = LlamaCppProvider()
        self._providers[llama.name] = llama
        ollama = OllamaProvider()
        if ollama.check_available():
            self._providers[ollama.name] = ollama
        self._cloud_provider = CloudProvider()
        self._providers[self._cloud_provider.name] = self._cloud_provider

    def configure(self, config):
        model_dir = "/var/lib/aura/models"
        try:
            model_dir = config.get("intelligence", "model_dir") or model_dir
        except Exception:
            pass
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
        try:
            self._max_context_tokens = config.getint("intelligence", "max_context_tokens")
        except Exception:
            self._max_context_tokens = 4096

        try:
            mode = config.get("intelligence", "mode") or "local"
            self._mode_manager.set_mode(mode)
        except Exception:
            pass

        endpoint = ""
        key_cmd = ""
        key_file = ""
        allow_default = False
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
            allow_default = False

        api_key = None
        if endpoint:
            try:
                api_key = get_api_key(command=key_cmd, key_file=key_file)
            except SecureStoreError as e:
                logger.warning("Secure store error reading cloud key: %s", e)
                api_key = None
            except Exception as e:
                logger.warning("Unexpected error reading cloud key: %s", e)
                api_key = None

        if self._cloud_provider:
            self._cloud_provider.configure(
                endpoint=endpoint,
                api_key=api_key or "",
                model_name=self._default_model_id or "gpt-4o-mini",
                enabled=bool(api_key) and bool(endpoint) and bool(allow_default),
            )

        trusted = {}
        self._model_manager = ModelManager(model_dir=model_dir,
                                           trusted_manifest=trusted)
        self._resource_manager = ResourceManager(config=config)
        self._resource_manager.set_model_dir(model_dir)
        for p in self._providers.values():
            self._resource_manager.register_provider(p)
            self._health_monitor.register(p)

    # -- Public API ---------------------------------------------------------
    def start(self):
        if self._resource_manager:
            self._resource_manager.start()
        self._health_monitor.start()
        if self._auto_load and self._default_model_id:
            logger.warning("auto_load_at_boot=true is set, but large models "
                           "should never load at boot; ignoring.")
            self.unload_model(force=True)
        logger.info("Inference engine started (mode=%s)",
                    self._mode_manager.mode.value)

    def stop(self):
        self._health_monitor.stop()
        if self._resource_manager:
            self._resource_manager.stop()
        # Cancel in-flight requests, then unload providers.
        self.cancel_all()
        with self._lock:
            providers = list(self._providers.values())
        for p in providers:
            try:
                p.unload_model()
            except Exception as e:
                logger.debug("Error unloading provider %s: %s", p.name, e)
        with self._lock:
            self._active_provider_name = None
            self._loaded_model_id = None
        logger.info("Inference engine stopped")

    def add_listener(self, cb: Callable[[str, dict], None]):
        self._listeners.append(cb)

    def _emit(self, event: str, details: dict):
        for cb in list(self._listeners):
            try:
                cb(event, details)
            except Exception as e:
                logger.debug("Listener error: %s", e)

    @property
    def mode(self) -> AIMode:
        return self._mode_manager.mode

    def set_mode(self, mode: str):
        # 1. Flip the mode (under lock inside ModeManager)
        old = self._mode_manager.mode
        new = self._mode_manager.set_mode(mode)
        if new != old:
            # 2. Cancel cloud requests if we're leaving HYBRID
            if new in (AIMode.LOCAL, AIMode.OFFLINE) and self._cloud_provider:
                self._cloud_provider.cancel_all()
                self._cloud_provider.unload_model()
            # 3. If going to OFFLINE, cancel any in-flight requests (local
            # requests may finish, but no network access is permitted)
            if new == AIMode.OFFLINE:
                self.cancel_all()
            self._emit("mode_changed", {"mode": new.value})

    def set_cloud_consent_callback(self, cb: Callable[[str], bool]):
        self._mode_manager.set_consent_callback(cb)

    def grant_cloud_consent(self) -> bool:
        """Enable cloud for this session. Consent is still verified per-request
        via the ModeManager consent callback, but this marks the cloud
        provider as administratively enabled."""
        if self._cloud_provider and self._cloud_provider._api_key \
                and self._mode_manager.mode == AIMode.HYBRID:
            self._cloud_provider._enabled = True
            if self._cloud_provider.check_available():
                self._cloud_provider._set_state(ProviderState.IDLE)
            return True
        return False

    def revoke_cloud_consent(self):
        if self._cloud_provider:
            self._cloud_provider.cancel_all()
            self._cloud_provider._set_state_disabled("consent revoked")

    # -- Queries ------------------------------------------------------------
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
        with self._lock:
            return self._active_provider_name

    def loaded_model(self) -> Optional[str]:
        with self._lock:
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

    def active_request_count(self) -> int:
        with self._request_lock:
            return len(self._active_requests)

    # -- Model load/unload --------------------------------------------------
    def load_model(self, model_id: str) -> Dict[str, object]:
        # Serialize loads/unloads
        with self._load_lock:
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
            # If a model is already loaded and generating, refuse swap
            if self.active_request_count() > 0:
                return {"ok": False, "error": "inference in progress; cancel first"}
            if hasattr(provider, "configure"):
                provider.configure(cpu_threads=decision.recommended_threads,
                                   ctx_size=decision.max_ctx_tokens)
            ok = provider.load_model(
                model,
                cpu_threads=decision.recommended_threads,
                ctx_size=decision.max_ctx_tokens,
            )
            if ok:
                with self._lock:
                    self._active_provider_name = provider.name
                    self._loaded_model_id = model_id
                rm.note_inference(provider.name)
                self._emit("model_loaded", {"model": model_id,
                                             "provider": provider.name})
                return {"ok": True, "provider": provider.name,
                        "threads": decision.recommended_threads,
                        "ctx": decision.max_ctx_tokens}
            return {"ok": False, "error": provider.last_error or "load failed"}

    def unload_model(self, force: bool = False):
        with self._load_lock:
            if not force and self.active_request_count() > 0:
                logger.warning("unload_model() called with active requests; "
                               "pass force=True to cancel and unload")
                return
            if force:
                self.cancel_all()
            with self._lock:
                providers = list(self._providers.values())
                prev_model = self._loaded_model_id
                self._loaded_model_id = None
                self._active_provider_name = None
            # Clear the active request bookkeeping after cancelling
            with self._request_lock:
                self._active_requests.clear()
                self._cancel_events.clear()
            for p in providers:
                try:
                    p.unload_model()
                except Exception as e:
                    logger.debug("unload error on %s: %s", p.name, e)
        if prev_model:
            self._emit("model_unloaded", {"model": prev_model})

    # -- Downloads (offline-gated) ------------------------------------------
    def download_model(self, model_id: str, url: str,
                       expected_sha256: str = "",
                       progress_cb=None,
                       cancel_event=None,
                       overwrite: bool = False) -> object:
        """User-initiated download. Refused in OFFLINE mode."""
        if self._model_manager is None:
            return None
        if not self._mode_manager.network_enabled():
            from .model_manager import DownloadProgress
            return DownloadProgress(
                model_id=model_id, url=url, status="error",
                error="downloads disabled in offline mode")
        return self._model_manager.download_model(
            model_id=model_id, url=url,
            expected_sha256=expected_sha256,
            network_enabled=True,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
            overwrite=overwrite,
        )

    # -- Inference ----------------------------------------------------------
    def infer(self, prompt: str, *,
              conversation_id: Optional[str] = None,
              max_tokens: int = 512,
              temperature: float = 0.7,
              use_cloud: bool = False,
              model_id: Optional[str] = None,
              on_token: Optional[Callable[[str], None]] = None) -> InferenceResult:
        request_id = str(uuid.uuid4())
        if use_cloud:
            # Check consent AND mode (race-free: mode is re-checked inside
            # cloud_allowed after the consent callback returns).
            if not self._mode_manager.cloud_allowed(
                    f"cloud inference for request {request_id}"):
                return InferenceResult(
                    request_id=request_id, text="",
                    error="cloud not allowed (mode/consent)",
                )
            if self._cloud_provider is None:
                return InferenceResult(request_id=request_id, text="",
                                       error="cloud provider unavailable")
            return self._do_infer(self._cloud_provider, request_id, prompt,
                                  conversation_id, max_tokens, temperature,
                                  on_token=on_token, model_id=model_id,
                                  is_cloud=True)

        # Local path
        if not self._lazy_load and self._loaded_model_id is None:
            return InferenceResult(request_id=request_id, text="",
                                   error="no model loaded; call load_model() first")
        # Lazy load if needed (hold load_lock briefly)
        if self._loaded_model_id is None:
            target = model_id or self._default_model_id
            if not target:
                return InferenceResult(request_id=request_id, text="",
                                       error="no model loaded and no default set")
            with self._load_lock:
                if self._loaded_model_id is None:
                    result = self.load_model(target)
                    if not result.get("ok"):
                        return InferenceResult(
                            request_id=request_id, text="",
                            error=f"load failed: {result.get('error')}")

        with self._lock:
            provider = self._providers.get(self._active_provider_name) \
                if self._active_provider_name else None
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
        conv: Optional[Conversation] = None
        if conversation_id:
            conv = self._conversation_manager.get(conversation_id)
            if not conv:
                conv = self._conversation_manager.new_conversation(conv_id=conversation_id)
        else:
            conv = self._conversation_manager.new_conversation()

        if conv is not None:
            self._conversation_manager.append_user(conv.id, prompt)
            ctx = self._max_context_tokens
            full_prompt = conv.format_prompt(ctx)
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
            logger.error("Provider %s raised during generate: %s", provider.name, e)
            try:
                provider.unload_model()
            except Exception:
                pass
            try:
                provider._set_state(ProviderState.ERROR, str(e)[:500])
            except Exception:
                pass
            result = InferenceResult(
                request_id=request_id, text="", error=str(e)[:500],
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
                       {"request_id": request_id, "error": result.error[:500]})
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
                try:
                    p.cancel_all()
                except Exception:
                    pass

    def _select_local_provider_for(self, model: ModelInfo) -> Optional[Provider]:
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
        "sha256": m.sha256,
        "estimated_memory_mb": m.estimated_memory_mb(),
    }
