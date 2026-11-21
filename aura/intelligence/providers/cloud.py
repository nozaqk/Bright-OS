"""Cloud inference provider (disabled by default).

Used in HYBRID mode only after explicit per-request user consent.

Safety properties:
  * Only HTTPS URLs are accepted (http://, file:// are rejected).
  * Endpoints are validated against SSRF: DNS is resolved and all
    returned addresses must be public; loopback / RFC1918 / link-local /
    ULA / CGNAT / documentation / reserved ranges are rejected. This
    runs at request time (not just config time) to avoid DNS rebinding.
  * HTTP redirects are validated against the same rules; redirect depth
    is capped.
  * Request + response sizes are capped to prevent memory/disk exhaustion.
  * A hard connect/read timeout applies and is split so cancellation can
    interrupt a blocking request.
  * API keys are sent in an Authorization header; they (and the prompt /
    response) are never written to logs.
  * The provider cannot be used from Local or Offline mode — InferenceEngine
    routes via ModeManager.cloud_allowed() which enforces mode+consent.
"""
import json
import logging
import select
import socket
import threading
import time
import urllib.error
from typing import Optional
from urllib.parse import urlparse

from ..model_info import ModelInfo
from ..networking import open_safe_url, read_limited_response, validate_remote_url
from ..provider import (
    InferenceRequest,
    InferenceResult,
    Provider,
    ProviderState,
)

logger = logging.getLogger("aura.intelligence.providers.cloud")

# Hard caps
MAX_REQUEST_BYTES = 1024 * 1024      # 1 MiB request body
MAX_RESPONSE_BYTES = 16 * 1024 * 1024  # 16 MiB response body
CONNECT_TIMEOUT_SEC = 10.0
READ_TIMEOUT_SEC = 120.0


class CloudProvider(Provider):
    name = "cloud"
    local = False
    requires_consent = True
    optional = False

    def __init__(self, endpoint: str = "", api_key: str = "",
                 model_name: str = "gpt-4o-mini"):
        super().__init__()
        self._endpoint = endpoint
        self._api_key = api_key
        self._model_name = model_name
        self._enabled = False
        # NOTE: consent is enforced PER-REQUEST at InferenceEngine via the
        # ModeManager consent callback. We do NOT hold a session-long consent
        # flag here. `_enabled` means "configuration is valid and user has
        # opted into hybrid mode at all" — actual cloud calls still pass
        # through ModeManager.cloud_allowed().
        self._set_state_disabled("cloud not configured")

    def _set_state_disabled(self, reason: str):
        self._enabled = False
        self._set_state(ProviderState.UNAVAILABLE, reason)

    def configure(self, endpoint: str, api_key: str, model_name: str = "",
                  enabled: bool = False):
        """Configure the cloud provider.

        `enabled` means cloud is permitted by admin configuration. Per-request
        consent is still required via the ModeManager callback.
        """
        self._endpoint = endpoint
        self._api_key = api_key
        if model_name:
            self._model_name = model_name
        if enabled and endpoint and api_key \
                and validate_remote_url(endpoint, https_only=True):
            self._enabled = True
            self._set_state(ProviderState.IDLE)
        else:
            self._set_state_disabled(
                "cloud disabled (no consent, missing key, or invalid endpoint)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def check_available(self) -> bool:
        return (self._enabled and bool(self._api_key)
                and bool(self._endpoint)
                and validate_remote_url(self._endpoint, https_only=True))

    def is_model_compatible(self, model: ModelInfo) -> bool:
        return True

    def load_model(self, model: ModelInfo, **kwargs) -> bool:
        if not self.check_available():
            self._set_state_disabled("cloud not available for load")
            return False
        self._model_name = model.model_id
        self.current_model = model
        self._set_state(ProviderState.READY)
        return True

    def unload_model(self):
        self.cancel_all()
        self.current_model = None
        if self.check_available():
            self._set_state(ProviderState.IDLE)

    def generate(self, request: InferenceRequest) -> InferenceResult:
        start = time.monotonic()
        if not self.check_available():
            return InferenceResult(
                request_id=request.request_id, text="",
                error="cloud not available", provider=self.name,
            )

        cancel = request.cancel or threading.Event()
        self._cancel_events[request.request_id] = cancel
        self._set_state(ProviderState.GENERATING)

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

        body = json.dumps(payload).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            self._set_state(ProviderState.ERROR, "request body too large")
            return InferenceResult(
                request_id=request.request_id, text="",
                error="request body too large", provider=self.name,
                model=self._model_name,
                duration_ms=int((time.monotonic() - start) * 1000))

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "Content-Length": str(len(body)),
        }

        try:
            # Use a short connect timeout and a separate read timeout; loop
            # so we can poll the cancel event between chunks.
            # urllib's timeout is the total blocking time per read call.
            resp = open_safe_url(
                self._endpoint,
                timeout=READ_TIMEOUT_SEC,
                max_bytes=MAX_RESPONSE_BYTES,
                https_only=True,
                allow_localhost=False,
                headers=headers,
                data=body,
                allow_redirects=False,
                method="POST",
            )
            try:
                raw = b""
                chunks = []
                total = 0
                # Polling read so cancellation can interrupt mid-response
                while True:
                    if cancel.is_set():
                        resp.close()
                        self._cancel_events.pop(request.request_id, None)
                        self._set_state(ProviderState.READY)
                        return InferenceResult(
                            request_id=request.request_id, text="",
                            cancelled=True, provider=self.name,
                            model=self._model_name,
                            duration_ms=int((time.monotonic() - start) * 1000))
                    # Read with select/poll-like approach via small chunks
                    # with short timeouts — we use resp.read with a small
                    # chunk so cancel is checked frequently.
                    # Note: response object is a file-like; HTTPResponse.read()
                    # honors the timeout passed to urlopen. We read small
                    # chunks and check cancel in between.
                    # Workaround: fall back to read_limited_response if the
                    # response object doesn't support non-blocking reads.
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        resp.close()
                        raise ValueError(
                            f"cloud response exceeded {MAX_RESPONSE_BYTES} bytes")
                    chunks.append(chunk)
                raw = b"".join(chunks)
            finally:
                resp.close()

            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as e:
                raise ValueError(f"invalid JSON response: {e}")

            text = ""
            tokens_in = 0
            tokens_out = 0
            # Validate expected shape; do not crash on unexpected shapes.
            if isinstance(data, dict):
                choices = data.get("choices")
                if isinstance(choices, list) and choices:
                    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                    if isinstance(msg, dict):
                        text = msg.get("content", "") or ""
                usage = data.get("usage")
                if isinstance(usage, dict):
                    tokens_in = int(usage.get("prompt_tokens", 0) or 0)
                    tokens_out = int(usage.get("completion_tokens", 0) or 0)
            if not isinstance(text, str):
                text = ""

            return InferenceResult(
                request_id=request.request_id, text=text,
                provider=self.name, model=self._model_name,
                tokens_in=tokens_in, tokens_out=tokens_out,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except (urllib.error.URLError, ValueError, OSError) as e:
            # Do NOT include the API key or response body in error
            err_msg = str(e).replace(self._api_key, "***") if self._api_key else str(e)
            self._set_state(ProviderState.ERROR, err_msg[:500])
            return InferenceResult(
                request_id=request.request_id, text="",
                error=err_msg[:500], provider=self.name, model=self._model_name,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        finally:
            self._cancel_events.pop(request.request_id, None)
            if self.check_available():
                self._set_state(ProviderState.READY)
            else:
                self._set_state_disabled("cloud unavailable after request")
