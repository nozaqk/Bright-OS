"""Optional Ollama provider.

Ollama is NOT required. We detect it by looking for the `ollama` CLI and
attempting to reach its local API. If unavailable, this provider stays in
UNAVAILABLE and the InferenceEngine falls back to llama.cpp.

We communicate via the local HTTP API (http://127.0.0.1:11434) which is the
officially supported interface. No shell commands with user input are run.
"""
import json
import logging
import os
import shutil
import socket
import urllib.error
import urllib.request
from typing import Optional

from ..model_info import ModelFormat, ModelInfo
from ..provider import (
    InferenceRequest,
    InferenceResult,
    Provider,
    ProviderState,
)

logger = logging.getLogger("aura.intelligence.providers.ollama")

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")


class OllamaProvider(Provider):
    name = "ollama"
    local = True
    requires_consent = False
    optional = True  # Never required

    def __init__(self, host: str = OLLAMA_HOST):
        super().__init__()
        self._host = host.rstrip("/")
        self._model_tag = ""
        if self.check_available():
            self._set_state(ProviderState.IDLE)
        else:
            self._set_state(ProviderState.UNAVAILABLE, "Ollama not detected")

    def _api(self, path: str, data: Optional[dict] = None, timeout: float = 10.0):
        url = f"{self._host}{path}"
        try:
            if data is None:
                req = urllib.request.Request(url, method="GET")
            else:
                req = urllib.request.Request(
                    url, data=json.dumps(data).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, socket.timeout, ConnectionError,
                json.JSONDecodeError) as e:
            raise RuntimeError(f"ollama API error: {e}") from e

    def check_available(self) -> bool:
        if not shutil.which("ollama"):
            return False
        try:
            self._api("/api/tags", timeout=2.0)
            return True
        except Exception:
            return False

    def is_model_compatible(self, model: ModelInfo) -> bool:
        # Ollama manages its own model store; any GGUF or pulled model works
        # if it has been `ollama pull`ed. We accept any format since ollama
        # converts, but mark GGUF/native as preferred.
        return True

    def load_model(self, model: ModelInfo, **kwargs) -> bool:
        if not self.check_available():
            self._set_state(ProviderState.UNAVAILABLE, "ollama not reachable")
            return False
        # We use the model_id as the Ollama tag (e.g. "qwen2.5:3b")
        self._model_tag = model.model_id
        self.current_model = model
        # Don't actually pull here (pulls can be huge; user initiates download)
        self._set_state(ProviderState.READY)
        return True

    def unload_model(self):
        # Ollama will unload on its own idle timer; we can't force it via API
        # in older versions, but we drop our reference.
        self.cancel_all()
        self.current_model = None
        self._model_tag = ""
        if self.check_available():
            self._set_state(ProviderState.IDLE)

    def generate(self, request: InferenceRequest) -> InferenceResult:
        import time
        start = time.monotonic()
        if not self._model_tag:
            return InferenceResult(request_id=request.request_id, text="",
                                   error="no model loaded", provider=self.name)
        cancel = request.cancel
        self._cancel_events[request.request_id] = cancel or __import__("threading").Event()

        self._set_state(ProviderState.GENERATING)
        try:
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
            data = self._api("/api/generate", data=payload,
                             timeout=float(request.max_tokens) * 0.5 + 60)
            text = data.get("response", "")
            return InferenceResult(
                request_id=request.request_id, text=text,
                provider=self.name, model=self._model_tag,
                tokens_in=data.get("prompt_eval_count", 0),
                tokens_out=data.get("eval_count", 0),
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            self._set_state(ProviderState.ERROR, str(e))
            return InferenceResult(request_id=request.request_id, text="",
                                   error=str(e), provider=self.name,
                                   model=self._model_tag,
                                   duration_ms=int((time.monotonic() - start) * 1000))
        finally:
            self._cancel_events.pop(request.request_id, None)
            if self.current_model:
                self._set_state(ProviderState.READY)
