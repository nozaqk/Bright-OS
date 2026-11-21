"""Optional Ollama provider.

Ollama is NOT required. We only talk to a loopback Ollama instance; the
host cannot be pointed at arbitrary remote servers via the environment
variable — any non-loopback host configured at runtime is rejected.

We communicate via the local HTTP API at http://127.0.0.1:11434. No shell
commands with user input are executed.
"""
import json
import logging
import os
import shutil
import threading
import time
from typing import Optional
from urllib.parse import urlparse

from ..model_info import ModelInfo
from ..networking import _is_loopback_host, is_loopback_ip
from ..provider import (
    InferenceRequest,
    InferenceResult,
    Provider,
    ProviderState,
)

logger = logging.getLogger("aura.intelligence.providers.ollama")

# Default local Ollama endpoint. We intentionally do NOT honour arbitrary
# OLLAMA_HOST values — only loopback is permitted.
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024  # 32 MiB cap on API responses


class OllamaProvider(Provider):
    name = "ollama"
    local = True
    requires_consent = False
    optional = True

    def __init__(self, host: str = DEFAULT_OLLAMA_HOST):
        super().__init__()
        self._host = self._normalise_loopback(host)
        self._model_tag = ""
        if self._host and self.check_available():
            self._set_state(ProviderState.IDLE)
        else:
            self._set_state(ProviderState.UNAVAILABLE, "Ollama not detected")

    @staticmethod
    def _normalise_loopback(host: str) -> str:
        """Ensure the Ollama host is a loopback endpoint."""
        host = (host or "").rstrip("/")
        if not host:
            return DEFAULT_OLLAMA_HOST
        try:
            p = urlparse(host)
            if p.scheme != "http":
                return ""
            hostname = p.hostname or ""
            # Accept only explicit loopback IPs or "localhost"
            if hostname in ("localhost", "127.0.0.1", "::1"):
                return host
            try:
                if is_loopback_ip(hostname) or _is_loopback_host(hostname):
                    return host
            except Exception:
                pass
        except Exception:
            pass
        logger.warning("Refusing non-loopback Ollama host: %s", host)
        return ""

    def _api(self, path: str, data: Optional[dict] = None,
             timeout: float = 10.0,
             cancel_event: Optional[threading.Event] = None) -> Optional[dict]:
        if not self._host:
            raise RuntimeError("ollama not configured for loopback access")
        url = f"{self._host}{path}"
        try:
            from ..networking import open_loopback_url, read_limited_response
            if data is None:
                resp = open_loopback_url(url, timeout=timeout, method="GET")
            else:
                resp = open_loopback_url(
                    url, timeout=timeout,
                    data=json.dumps(data).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST")
            with resp:
                raw = read_limited_response(resp, MAX_RESPONSE_BYTES)
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"ollama API error: {e}") from e

    def check_available(self) -> bool:
        if not self._host:
            return False
        if not shutil.which("ollama"):
            return False
        try:
            self._api("/api/tags", timeout=2.0)
            return True
        except Exception:
            return False

    def is_model_compatible(self, model: ModelInfo) -> bool:
        return True

    def load_model(self, model: ModelInfo, **kwargs) -> bool:
        if not self.check_available():
            self._set_state(ProviderState.UNAVAILABLE, "ollama not reachable")
            return False
        self._model_tag = model.model_id
        self.current_model = model
        self._set_state(ProviderState.READY)
        return True

    def unload_model(self):
        self.cancel_all()
        self.current_model = None
        self._model_tag = ""
        if self.check_available():
            self._set_state(ProviderState.IDLE)

    def generate(self, request: InferenceRequest) -> InferenceResult:
        start = time.monotonic()
        if not self._model_tag:
            return InferenceResult(request_id=request.request_id, text="",
                                   error="no model loaded", provider=self.name)
        cancel = request.cancel or threading.Event()
        self._cancel_events[request.request_id] = cancel

        self._set_state(ProviderState.GENERATING)
        try:
            if cancel.is_set():
                return InferenceResult(request_id=request.request_id, text="",
                                       cancelled=True, provider=self.name,
                                       model=self._model_tag,
                                       duration_ms=int((time.monotonic() - start) * 1000))
            payload = {
                "model": self._model_tag,
                "prompt": request.prompt,
                "stream": False,
                "options": {
                    "num_predict": request.max_tokens,
                    "temperature": request.temperature,
                    "stop": request.stop or [],
                },
            }
            timeout = min(300.0, float(request.max_tokens) * 0.5 + 60)
            data = self._api("/api/generate", data=payload, timeout=timeout,
                             cancel_event=cancel)
            if data is None:
                raise RuntimeError("no response")
            text = data.get("response", "")
            return InferenceResult(
                request_id=request.request_id, text=text,
                provider=self.name, model=self._model_tag,
                tokens_in=data.get("prompt_eval_count", 0),
                tokens_out=data.get("eval_count", 0),
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            self._set_state(ProviderState.ERROR, str(e)[:500])
            return InferenceResult(request_id=request.request_id, text="",
                                   error=str(e)[:500], provider=self.name,
                                   model=self._model_tag,
                                   duration_ms=int((time.monotonic() - start) * 1000))
        finally:
            self._cancel_events.pop(request.request_id, None)
            if self.current_model and self.check_available():
                self._set_state(ProviderState.READY)
