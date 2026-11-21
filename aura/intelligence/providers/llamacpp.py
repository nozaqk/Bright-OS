"""llama.cpp provider — preferred local inference backend.

Runs `llama-cli` (or equivalent) as a subprocess, streaming output via
stdout. Communicates using the CLI's interactive/command-line interface so
we don't need any Python bindings. This is robust and keeps the AI process
isolated from the AURA Core daemon (no in-process crashes take AURA down).
"""
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import List, Optional

from ..model_info import ModelFormat, ModelInfo
from ..provider import (
    InferenceRequest,
    InferenceResult,
    Provider,
    ProviderState,
)

logger = logging.getLogger("aura.intelligence.providers.llamacpp")

# Candidate binary names; Debian may package llama.cpp as 'llama-cli'
LLAMA_CLI_CANDIDATES = ["llama-cli", "llama.cpp-cli", "main", "llama"]


class LlamaCppProvider(Provider):
    """Local llama.cpp inference via subprocess."""

    name = "llamacpp"
    local = True
    requires_consent = False
    optional = False  # Preferred backend, but binary may be missing (IDLE)

    def __init__(self, cli_path: Optional[str] = None):
        super().__init__()
        self._cli_path = cli_path or self._find_cli()
        self._proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._cpu_threads = 0       # 0 = auto
        self._ctx_size = 4096
        self._gpu_layers = 0        # 0 = CPU-only (safe default)
        if self._cli_path:
            self._set_state(ProviderState.IDLE)
        else:
            self._set_state(ProviderState.UNAVAILABLE,
                            "llama.cpp CLI not found (install llama-cli package)")

    # -- Binary discovery ---------------------------------------------------
    @staticmethod
    def _find_cli() -> Optional[str]:
        for name in LLAMA_CLI_CANDIDATES:
            p = shutil.which(name)
            if p:
                return p
        # Also check /usr/lib/aura/third_party if we ever bundle it
        for cand in ("/usr/lib/aura/third_party/llama.cpp/llama-cli",
                     "/usr/local/bin/llama-cli"):
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
        return None

    # -- Provider interface -------------------------------------------------
    def check_available(self) -> bool:
        return self._cli_path is not None and os.path.isfile(self._cli_path)

    def is_model_compatible(self, model: ModelInfo) -> bool:
        return model.format == ModelFormat.GGUF

    def configure(self, cpu_threads: int = 0, ctx_size: int = 4096,
                  gpu_layers: int = 0):
        """Runtime tuning; applied on next load."""
        self._cpu_threads = cpu_threads
        self._ctx_size = ctx_size
        self._gpu_layers = gpu_layers

    def load_model(self, model: ModelInfo, **kwargs) -> bool:
        if not self.check_available():
            self._set_state(ProviderState.ERROR, "llama.cpp CLI not available")
            return False
        if not self.is_model_compatible(model):
            self._set_state(ProviderState.ERROR, f"incompatible format: {model.format}")
            return False
        # Unload any existing model first
        self.unload_model()

        self._set_state(ProviderState.LOADING)
        threads = kwargs.get("cpu_threads", self._cpu_threads) or max(1, (os.cpu_count() or 2) - 1)
        ctx = kwargs.get("ctx_size", self._ctx_size)
        ngl = kwargs.get("gpu_layers", self._gpu_layers)

        # We use the `-i` (interactive) mode-less single-prompt invocation
        # per-request rather than keeping a long-running server, which keeps
        # resource accounting simple: when generate() returns, process exits.
        # For load_model we just do a very fast dry run to validate the file
        # parses (--help would not load weights). We just mark ready and defer
        # actual load to the first generate() call (lazy loading).
        self.current_model = model
        self._threads = threads
        self._ctx = ctx
        self._ngl = ngl
        self._set_state(ProviderState.READY)
        logger.info("llama.cpp ready for %s (threads=%d, ctx=%d, ngl=%d)",
                    model.friendly_name, threads, ctx, ngl)
        return True

    def unload_model(self):
        with self._proc_lock:
            if self._proc is not None:
                self._kill_proc_locked()
        self.cancel_all()
        self.current_model = None
        if self.check_available():
            self._set_state(ProviderState.IDLE)

    def _kill_proc_locked(self):
        p = self._proc
        self._proc = None
        if p is None:
            return
        try:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=2)
        except Exception as e:
            logger.debug("Error killing llama.cpp process: %s", e)

    def generate(self, request: InferenceRequest) -> InferenceResult:
        start = time.monotonic()
        model = self.current_model
        if model is None:
            return InferenceResult(
                request_id=request.request_id, text="",
                error="no model loaded", provider=self.name,
            )
        cancel = request.cancel or threading.Event()
        self._cancel_events[request.request_id] = cancel

        threads = getattr(self, "_threads", 0) or max(1, (os.cpu_count() or 2) - 1)
        ctx = getattr(self, "_ctx", self._ctx_size)
        ngl = getattr(self, "_ngl", self._gpu_layers)

        args: List[str] = [
            self._cli_path,
            "-m", model.path,
            "-p", request.prompt,
            "-n", str(request.max_tokens),
            "--temp", str(request.temperature),
            "-t", str(threads),
            "-c", str(ctx),
            "-ngl", str(ngl),
            "--no-display-prompt",
        ]
        if request.stop:
            for s in request.stop:
                args += ["-r", s]

        self._set_state(ProviderState.GENERATING)
        proc = None
        output_parts: List[str] = []
        try:
            with self._proc_lock:
                self._proc = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, bufsize=1,
                )
                proc = self._proc

            assert proc.stdout is not None
            # Read streaming output line/char by char
            # llama-cli prints tokens progressively; we collect all.
            for line in proc.stdout:
                if cancel.is_set():
                    proc.terminate()
                    break
                text = line.rstrip("\n")
                if text:
                    output_parts.append(text)
                    if request.on_token:
                        try:
                            request.on_token(text)
                        except Exception as e:
                            logger.debug("on_token callback error: %s", e)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
        except Exception as e:
            logger.error("llama.cpp generation error: %s", e)
            return InferenceResult(
                request_id=request.request_id, text="", error=str(e),
                provider=self.name, model=model.model_id,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        finally:
            with self._proc_lock:
                if self._proc is proc:
                    self._proc = None
            self._cancel_events.pop(request.request_id, None)
            if self.current_model:
                self._set_state(ProviderState.READY)
            else:
                self._set_state(ProviderState.IDLE)

        duration_ms = int((time.monotonic() - start) * 1000)
        if cancel.is_set():
            return InferenceResult(
                request_id=request.request_id,
                text="".join(output_parts),
                cancelled=True,
                provider=self.name, model=model.model_id,
                duration_ms=duration_ms,
            )
        return InferenceResult(
            request_id=request.request_id,
            text="".join(output_parts),
            provider=self.name, model=model.model_id,
            duration_ms=duration_ms,
        )
