"""Cloud inference provider (disabled by default).

Used in HYBRID mode only after explicit user consent. We:
  - Validate the endpoint against an allowlist (no SSRF/arbitrary endpoints
    beyond the configured host).
  - Send only the prompt (no PII scrubbed here; caller is responsible, but
    we never log prompt contents).
  - Require a valid API key (loaded via secure_store, never from plaintext
    config).
  - Support OpenAI-compatible /v1/chat/completions APIs (one widely used
    shape covers OpenAI, Groq, Together, OpenRouter, etc.).
"""
import json
import logging
import socket
import urllib.error
import urllib.request
from typing import List, Optional
from urllib.parse import urlparse

from ..model_info import ModelInfo
from ..provider import (
    InferenceRequest,
    InferenceResult,
    Provider,
    ProviderState,
)

logger = logging.getLogger("aura.intelligence.providers.cloud")

# Only these schemes/hosts are considered safe to talk to. We block private
# IP ranges and non-https by default.
ALLOWED_SCHEMES = {"https"}
RESERVED_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1", ""}


def _endpoint_safe(endpoint: str) -> bool:
    try:
        p = urlparse(endpoint)
    except Exception:
        return False
    if p.scheme not in ALLOWED_SCHEMES:
        return False
    host = (p.hostname or "").lower()
    if host in RESERVED_HOSTNAMES:
        return False
    # Disallow IPs in private ranges (very basic SSRF guard)
    try:
        ip = socket.getaddrinfo(host, None)
        for fam, typ, proto, canon, sockaddr in ip:
            addr = sockaddr[0]
            if addr.startswith(("10.", "192.168.", "172.16.", "172.17.",
                                "172.18.", "172.19.", "172.2", "172.30.",
                                "127.", "0.", "169.254.", "::1", "fe80:",
                                "fc", "fd")):
                return False
    except Exception:
        # If we can't resolve it we can't validate; refuse
        return False
    return True


class CloudProvider(Provider):
    name = "cloud"
    local = False
    requires_consent = True
    optional = False  # Always available for hybrid mode; but disabled by default

    def __init__(self, endpoint: str = "", api_key: str = "",
                 model_name: str = "gpt-4o-mini"):
        super().__init__()
        self._endpoint = endpoint
        self._api_key = api_key
        self._model_name = model_name
        self._enabled = False
        self._consent_given = False
        if endpoint and api_key and _endpoint_safe(endpoint):
            self._set_state(ProviderState.IDLE)
        else:
            # Not an error; just unavailable until configured
            self._set_state(ProviderState.UNAVAILABLE,
                            "cloud not configured or endpoint unsafe")

    def configure(self, endpoint: str, api_key: str, model_name: str = "",
                  enabled: bool = False, consent_given: bool = False):
        self._endpoint = endpoint
        self._api_key = api_key
        if model_name:
            self._model_name = model_name
        self._enabled = enabled
        self._consent_given = consent_given
        if enabled and consent_given and endpoint and api_key \
                and _endpoint_safe(endpoint):
            self._set_state(ProviderState.IDLE)
        else:
            self._set_state(ProviderState.UNAVAILABLE,
                            "cloud disabled (no consent or invalid config)")

    @property
    def consent_required(self) -> bool:
        return True

    def can_infer(self) -> bool:
        return (self._enabled and self._consent_given and bool(self._api_key)
                and _endpoint_safe(self._endpoint))

    def check_available(self) -> bool:
        return self.can_infer()

    def is_model_compatible(self, model: ModelInfo) -> bool:
        # Cloud provider accepts any logical model by name; we don't manage
        # local files for it.
        return True

    def load_model(self, model: ModelInfo, **kwargs) -> bool:
        # "Loading" for cloud means noting the model name; no local weight load
        if not self.can_infer():
            self._set_state(ProviderState.UNAVAILABLE,
                            "cloud not enabled/consented")
            return False
        self._model_name = model.model_id
        self.current_model = model
        self._set_state(ProviderState.READY)
        return True

    def unload_model(self):
        self.cancel_all()
        self.current_model = None
        if self.can_infer():
            self._set_state(ProviderState.IDLE)

    def generate(self, request: InferenceRequest) -> InferenceResult:
        import time
        start = time.monotonic()
        if not self.can_infer():
            return InferenceResult(
                request_id=request.request_id, text="",
                error="cloud not available (disabled or no consent)",
                provider=self.name,
            )
        self._set_state(ProviderState.GENERATING)
        cancel = request.cancel or __import__("threading").Event()
        self._cancel_events[request.request_id] = cancel

        # OpenAI-compatible chat completion
        messages = [{"role": "user", "content": request.prompt}]
        payload = {
            "model": self._model_name,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": False,
        }
        if request.stop:
            payload["stop"] = request.stop

        try:
            req = urllib.request.Request(
                self._endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            # Network timeout. Note: we do not block on cancel since HTTP
            # requests aren't trivially interruptible; we just close early.
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = ""
            try:
                text = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError):
                text = ""
            return InferenceResult(
                request_id=request.request_id, text=text,
                provider=self.name, model=self._model_name,
                tokens_in=data.get("usage", {}).get("prompt_tokens", 0),
                tokens_out=data.get("usage", {}).get("completion_tokens", 0),
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            self._set_state(ProviderState.ERROR, str(e))
            return InferenceResult(
                request_id=request.request_id, text="",
                error=str(e), provider=self.name, model=self._model_name,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        finally:
            self._cancel_events.pop(request.request_id, None)
            if self.can_infer():
                self._set_state(ProviderState.READY)
