"""llama.cpp provider — preferred local inference backend.

Runs `llama-cli` as a per-request subprocess. This keeps AI isolated from
the AURA Core daemon — a crash in llama.cpp doesn't take AURA down, and
the OS reclaims memory when the process exits.

Hardening fixes (Phase 2.1):
  * stdout/stderr are drained concurrently (stderr to DEVNULL) to prevent
    pipe-buffer deadlock.
  * Only one generate() runs at a time (serialised via a lock); concurrent
    calls are queued safely.
  * Cancellation reliably terminates the child: SIGTERM → SIGKILL escalation.
  * Process is always waited on (no zombies), even on exceptions.
  * Exit code is checked and surfaced as an error.
  * Per-request wall-time timeout.
  * The model path is passed via a temporary prompt file to avoid ARG_MAX
    limits with large context.
  * Output sanitisation strips common llama.cpp banner lines.
  * Multiple conflicting model processes cannot be spawned (an existing
    proc is killed before starting a new one).
  * Unload reliably kills any running process before clearing state.
"""
import logging
import os
import shutil
import subprocess
import tempfile
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

LLAMA_CLI_CANDIDATES = ["llama-cli", "llama.cpp-cli", "main", "llama"]

# Lines that llama.cpp may emit to stdout that are not model output.
_BANNER_PREFIXES = (
    "llama_build",
    "llama: ",
    "system_info:",
    "build:",
    "main: ",
    "load:",
    "llama_load",
    "llama_new_context",
    "sampling:",
    "prompt:",
    "number of tokens",
    "generation:",
    "eval time",
    "load time",
    "total time",
    "mem per token",
    "cache: ",
    "{" ,  # JSON stats lines
)


def _strip_banner_lines(text: str) -> str:
    """Remove llama.cpp diagnostic lines that start with a known prefix."""
    out_lines: List[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        low = stripped.lower()
        skip = False
        for prefix in _BANNER_PREFIXES:
            if low.startswith(prefix.lower()):
                skip = True
                break
        if not skip and stripped:
            out_lines.append(line)
    return "\n".join(out_lines)


class LlamaCppProvider(Provider):
    name = "llamacpp"
    local = True
    requires_consent = False
    optional = False

    def __init__(self, cli_path: Optional[str] = None):
        super().__init__()
        self._cli_path = cli_path or self._find_cli()
        self._proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.RLock()
        self._generate_lock = threading.Lock()
        self._cpu_threads = 0
        self._ctx_size = 4096
        self._gpu_layers = 0
        if self.check_available():
            self._set_state(ProviderState.IDLE)
        else:
            self._set_state(ProviderState.UNAVAILABLE,
                            "llama.cpp CLI not found (install llama-cli package)")

    @staticmethod
    def _find_cli() -> Optional[str]:
        for name in LLAMA_CLI_CANDIDATES:
            p = shutil.which(name)
            if p:
                return p
        for cand in ("/usr/lib/aura/third_party/llama.cpp/llama-cli",
                     "/usr/local/bin/llama-cli"):
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
        return None

    def check_available(self) -> bool:
        return self._cli_path is not None and os.path.isfile(self._cli_path)

    def is_model_compatible(self, model: ModelInfo) -> bool:
        return model.format == ModelFormat.GGUF

    def configure(self, cpu_threads: int = 0, ctx_size: int = 4096,
                  gpu_layers: int = 0):
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
        # Kill any existing process before switching models
        self.unload_model()
        self._set_state(ProviderState.LOADING)
        threads = int(kwargs.get("cpu_threads", self._cpu_threads) or
                      max(1, (os.cpu_count() or 2) - 1))
        ctx = int(kwargs.get("ctx_size", self._ctx_size))
        ngl = int(kwargs.get("gpu_layers", self._gpu_layers))
        self.current_model = model
        self._threads = threads
        self._ctx = ctx
        self._ngl = ngl
        # Llama.cpp lazy-loads weights on first inference; just mark READY.
        self._set_state(ProviderState.READY)
        logger.info("llama.cpp ready for %s (threads=%d, ctx=%d, ngl=%d)",
                    model.friendly_name, threads, ctx, ngl)
        return True

    def unload_model(self):
        with self._proc_lock:
            self._kill_proc_locked()
        self.cancel_all()
        self.current_model = None
        if self.check_available():
            self._set_state(ProviderState.IDLE)

    def _kill_proc_locked(self):
        """Must be called under self._proc_lock. Kills and reaps the child."""
        p = self._proc
        self._proc = None
        if p is None:
            return
        try:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        p.kill()
                        p.wait(timeout=2)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("Error killing llama.cpp process: %s", e)
        # Ensure we don't leak pipes (Popen will gc them, but be explicit).
        for stream_name in ("stdout", "stderr", "stdin"):
            stream = getattr(p, stream_name, None)
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

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

        # Serialize generate() calls so we never have two concurrent
        # llama-cli processes fighting over the same model.
        if not self._generate_lock.acquire(timeout=60):
            return InferenceResult(
                request_id=request.request_id, text="",
                error="could not acquire generation lock",
                provider=self.name, model=model.model_id)
        try:
            return self._generate_locked(request, model, cancel, start)
        finally:
            self._generate_lock.release()

    def _generate_locked(self, request: InferenceRequest, model: ModelInfo,
                         cancel: threading.Event,
                         start: float) -> InferenceResult:
        threads = int(getattr(self, "_threads", 0) or
                      max(1, (os.cpu_count() or 2) - 1))
        ctx = int(getattr(self, "_ctx", self._ctx_size))
        ngl = int(getattr(self, "_ngl", self._gpu_layers))

        # Kill any stale process before starting a new one
        with self._proc_lock:
            self._kill_proc_locked()

        # Write the prompt to a temp file to avoid ARG_MAX issues for long
        # conversations.
        prompt_file = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", prefix="aura-prompt-",
                    delete=False, encoding="utf-8") as pf:
                pf.write(request.prompt)
                prompt_file = pf.name
        except OSError as e:
            return InferenceResult(
                request_id=request.request_id, text="",
                error=f"cannot write prompt temp file: {e}",
                provider=self.name, model=model.model_id,
                duration_ms=int((time.monotonic() - start) * 1000))

        args: List[str] = [
            self._cli_path,
            "-m", model.path,
            "-f", prompt_file,
            "-n", str(request.max_tokens),
            "--temp", str(request.temperature),
            "-t", str(threads),
            "-c", str(ctx),
            "-ngl", str(ngl),
            "--no-display-prompt",
            "--no-penalize-nl",
            "-r", "",   # no reverse prompt by default
        ]
        if request.stop:
            args = args[:-2]  # drop empty -r
            for s in request.stop:
                args += ["-r", s]

        self._set_state(ProviderState.GENERATING)
        proc = None
        stdout_thread: Optional[threading.Thread] = None
        output_parts: List[str] = []
        stdout_data: List[str] = []
        proc_error: Optional[str] = None
        try:
            with self._proc_lock:
                self._proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,  # Drain to /dev/null to avoid deadlock
                    stdin=subprocess.DEVNULL,
                    text=True, bufsize=1,
                )
                proc = self._proc

            assert proc.stdout is not None

            # Read stdout in a thread so cancellation is responsive; also
            # avoids blocking if the process writes a lot (we aren't PIPE-draining
            # stderr anymore so deadlock is already avoided, but this makes
            # cancel responsive even while reading).
            def _read_stdout():
                assert proc is not None and proc.stdout is not None
                try:
                    for line in proc.stdout:
                        if cancel.is_set():
                            return
                        stdout_data.append(line)
                except Exception as e:
                    logger.debug("stdout reader error: %s", e)

            stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
            stdout_thread.start()

            # Wait for process with periodic cancel checks
            idle_wait = max(0.5, float(request.max_tokens) * 0.05)
            max_wait = float(request.max_tokens) * 2 + 60  # generous wall cap
            wait_start = time.monotonic()
            while True:
                if cancel.is_set():
                    with self._proc_lock:
                        self._kill_proc_locked()
                    break
                if proc.poll() is not None:
                    break
                if time.monotonic() - wait_start > max_wait:
                    logger.warning("llama.cpp wall-time limit reached; killing")
                    with self._proc_lock:
                        self._kill_proc_locked()
                    proc_error = "wall-time limit exceeded"
                    break
                time.sleep(0.1)

            if stdout_thread is not None:
                stdout_thread.join(timeout=2)

            rc = proc.returncode
            if rc is not None and rc != 0 and not cancel.is_set():
                proc_error = f"llama-cli exited with code {rc}"
                logger.warning(proc_error)
        except subprocess.TimeoutExpired:
            proc_error = "subprocess timeout"
        except Exception as e:
            proc_error = str(e)
            logger.error("llama.cpp generation error: %s", e)
        finally:
            # Always clean up the process
            with self._proc_lock:
                if self._proc is proc:
                    self._kill_proc_locked()
                else:
                    # Someone else killed it
                    self._kill_proc_locked()
            self._cancel_events.pop(request.request_id, None)
            # Remove the prompt temp file
            if prompt_file:
                try:
                    os.unlink(prompt_file)
                except OSError:
                    pass
            # Transition state
            if self.current_model:
                self._set_state(ProviderState.READY)
            else:
                self._set_state(ProviderState.IDLE)

        duration_ms = int((time.monotonic() - start) * 1000)
        output_parts = stdout_data
        text = "".join(output_parts)
        text = _strip_banner_lines(text)

        if cancel.is_set():
            return InferenceResult(
                request_id=request.request_id,
                text=text,
                cancelled=True,
                provider=self.name, model=model.model_id,
                duration_ms=duration_ms,
            )
        if proc_error:
            return InferenceResult(
                request_id=request.request_id, text=text,
                error=proc_error, provider=self.name,
                model=model.model_id, duration_ms=duration_ms,
            )
        return InferenceResult(
            request_id=request.request_id,
            text=text,
            provider=self.name, model=model.model_id,
            duration_ms=duration_ms,
        )
