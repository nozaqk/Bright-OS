"""Model Manager — discovers, indexes, and (on user request) downloads models.

Model weights are NEVER included in the ISO and NEVER downloaded
automatically at boot. Downloads are user-initiated.

Security guarantees:
  * Remote downloads require HTTPS. HTTP and file:// are refused for
    remote download. Importing local files remains possible for admin-
    placed models.
  * Downloaded files are validated before being moved into place:
      - SHA-256 is compared against an expected hash (if supplied).
      - GGUF magic-number validation runs on the TEMPORARY file (never
        on the live path).
      - Only after validation passes is the file atomically renamed.
  * Path traversal in model IDs is rejected; the destination filename
    is sanitized to a safe basename.
  * Download cancellation is supported (partial files removed).
  * Existing model files are never overwritten without an explicit
    `overwrite=True` flag.
  * Model files are written with mode 0640 owned by the aura user/group.
  * A size cap (default 50 GB) prevents malicious servers from streaming
    infinite data.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from . import model_info
from .model_info import (
    ModelFormat,
    ModelInfo,
    build_model_info,
    scan_model_directory,
    validate_model_file,
)
from .networking import open_safe_url, read_limited_response

logger = logging.getLogger("aura.intelligence.model_manager")

# Maximum model download size (50 GB is plenty for any realistic GGUF).
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024 * 1024
# Chunk size for streaming reads
DOWNLOAD_CHUNK = 256 * 1024
# Fs-friendly model ID pattern
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# Hash pattern (sha256 hex)
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")

RECOMMENDED_MODELS: List[Dict[str, object]] = [
    {
        "model_id": "qwen2.5-1.5b-instruct-q4",
        "name": "Qwen 2.5 1.5B Instruct (Q4_K_M)",
        "size_mb": 1100,
        "ram_required_mb": 1400,
        "format": "gguf",
        "suitable_tiers": ["low", "medium", "high"],
        "description": "Small fast model for low-memory systems.",
    },
    {
        "model_id": "qwen2.5-3b-instruct-q4",
        "name": "Qwen 2.5 3B Instruct (Q4_K_M)",
        "size_mb": 2000,
        "ram_required_mb": 2600,
        "format": "gguf",
        "suitable_tiers": ["medium", "high"],
        "description": "Balanced quality/size for 4 GB+ RAM systems.",
    },
    {
        "model_id": "qwen2.5-7b-instruct-q4",
        "name": "Qwen 2.5 7B Instruct (Q4_K_M)",
        "size_mb": 4400,
        "ram_required_mb": 5700,
        "format": "gguf",
        "suitable_tiers": ["high"],
        "description": "High-quality model for 8 GB+ RAM.",
    },
]


@dataclass
class DownloadProgress:
    model_id: str
    url: str
    bytes_downloaded: int = 0
    total_bytes: int = 0
    status: str = "pending"  # pending | downloading | validating | done | error | cancelled
    error: str = ""
    expected_sha256: str = ""


def _sanitize_filename(model_id: str) -> Optional[str]:
    """Return a safe filename for a model_id, or None if it is unsafe."""
    if not model_id or not _SAFE_ID_RE.match(model_id):
        return None
    if model_id in (".", ".."):
        return None
    return model_id


class ModelManager:
    def __init__(self, model_dir: str = "/var/lib/aura/models",
                 manifest_path: Optional[str] = None,
                 trusted_manifest: Optional[Dict[str, str]] = None):
        self._model_dir = model_dir
        self._manifest_path = manifest_path or os.path.join(model_dir, "manifest.json")
        self._models: Dict[str, ModelInfo] = {}
        self._lock = threading.RLock()
        self._downloads: Dict[str, DownloadProgress] = {}
        self._download_lock = threading.Lock()
        # trusted_manifest maps model_id -> expected sha256 hex
        self._trusted_hashes: Dict[str, str] = dict(trusted_manifest or {})
        self._refresh_models()

    def register_trusted_hash(self, model_id: str, sha256_hex: str):
        if not _SHA256_RE.match(sha256_hex):
            raise ValueError("invalid sha256")
        with self._lock:
            self._trusted_hashes[model_id] = sha256_hex.lower()

    # -- Discovery ----------------------------------------------------------
    def _refresh_models(self):
        try:
            os.makedirs(self._model_dir, exist_ok=True)
            try:
                os.chmod(self._model_dir, 0o750)
            except OSError:
                pass
        except OSError:
            pass
        with self._lock:
            self._models.clear()
            for m in scan_model_directory(self._model_dir):
                # Set secure permissions on any existing model files
                try:
                    os.chmod(m.path, 0o640)
                except OSError:
                    pass
                self._models[m.model_id] = m
            self._merge_manifest()

    def _merge_manifest(self):
        if not os.path.isfile(self._manifest_path):
            return
        try:
            with open(self._manifest_path) as f:
                data = json.load(f)
            for entry in data.get("models", []):
                mid = entry.get("model_id")
                if not mid or mid in self._models:
                    continue
                path = entry.get("path")
                if not path or not os.path.exists(path):
                    continue
                if not self._is_within_model_dir(path):
                    logger.warning("Manifest entry %s escapes model dir; ignoring", mid)
                    continue
                info = build_model_info(path, model_id=mid)
                if info:
                    info.quant_type = entry.get("quant_type", info.quant_type)
                    info.param_count_b = entry.get("param_count_b", info.param_count_b)
                    info.context_window = entry.get("context_window", info.context_window)
                    info.sha256 = entry.get("sha256", info.sha256)
                    self._models[mid] = info
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read model manifest: %s", e)

    def _is_within_model_dir(self, path: str) -> bool:
        model_dir = os.path.realpath(self._model_dir)
        try:
            real = os.path.realpath(path)
        except OSError:
            return False
        return os.path.commonpath([real, model_dir]) == model_dir

    def list_models(self) -> List[ModelInfo]:
        with self._lock:
            return list(self._models.values())

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        with self._lock:
            return self._models.get(model_id)

    def rescan(self):
        self._refresh_models()

    def model_dir(self) -> str:
        return self._model_dir

    def list_recommended(self, tier: str = "medium") -> List[Dict[str, object]]:
        return [m for m in RECOMMENDED_MODELS if tier in m.get("suitable_tiers", [])]

    # -- Import a user-placed file ------------------------------------------
    def import_model_file(self, path: str, model_id: Optional[str] = None,
                          expected_sha256: str = "") -> Optional[ModelInfo]:
        ok, reason = validate_model_file(path)
        if not ok:
            logger.error("Refusing to import %s: %s", path, reason)
            return None
        # Ensure source file is a regular file within an expected location
        try:
            st = os.stat(path)
            if not stat.S_ISREG(st.st_mode):
                logger.error("Refusing to import non-regular file: %s", path)
                return None
        except OSError as e:
            logger.error("Cannot stat import source %s: %s", path, e)
            return None

        try:
            os.makedirs(self._model_dir, exist_ok=True)
        except OSError as e:
            logger.error("Cannot create model dir: %s", e)
            return None

        if model_id is None:
            model_id = os.path.splitext(os.path.basename(path))[0]
        safe_id = _sanitize_filename(model_id)
        if safe_id is None:
            logger.error("Unsafe model_id: %r", model_id)
            return None

        dest = os.path.join(self._model_dir, f"{safe_id}.gguf")
        if os.path.abspath(os.path.realpath(path)) != os.path.abspath(dest):
            if os.path.exists(dest):
                logger.error("Destination already exists; remove or use overwrite flag")
                return None
            tmp = dest + ".import-tmp"
            try:
                shutil.copy2(path, tmp)
                if not self._validate_and_promote(tmp, dest, expected_sha256):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    return None
            except OSError as e:
                logger.error("Failed to copy model: %s", e)
                return None
        info = build_model_info(dest, model_id=safe_id)
        if info:
            if expected_sha256 and _SHA256_RE.match(expected_sha256):
                info.sha256 = expected_sha256.lower()
            with self._lock:
                self._models[safe_id] = info
            self._save_manifest()
        return info

    def _validate_and_promote(self, tmp_path: str, dest_path: str,
                              expected_sha256: str = "") -> bool:
        """Validate the file at tmp_path; if ok, atomically rename to dest_path.
        Returns True on success; on failure leaves dest_path untouched."""
        # Compute hash BEFORE replacing dest
        actual_hash = ""
        if expected_sha256 and _SHA256_RE.match(expected_sha256):
            actual_hash = _hash_file(tmp_path)
            if actual_hash.lower() != expected_sha256.lower():
                logger.error("Hash mismatch for %s: expected %s, got %s",
                             dest_path, expected_sha256[:16], actual_hash[:16])
                return False
        ok, reason = validate_model_file(tmp_path)
        if not ok:
            logger.error("Validation failed for %s: %s", tmp_path, reason)
            return False
        # Set restrictive permissions before moving into place
        try:
            os.chmod(tmp_path, 0o640)
        except OSError:
            pass
        try:
            os.replace(tmp_path, dest_path)
        except OSError as e:
            logger.error("Failed to place model at %s: %s", dest_path, e)
            return False
        return True

    def _save_manifest(self):
        try:
            os.makedirs(os.path.dirname(self._manifest_path), exist_ok=True)
            data = {"models": []}
            with self._lock:
                for mid, m in self._models.items():
                    data["models"].append({
                        "model_id": mid,
                        "path": m.path,
                        "quant_type": m.quant_type,
                        "param_count_b": m.param_count_b,
                        "context_window": m.context_window,
                        "sha256": m.sha256,
                    })
            tmp = self._manifest_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._manifest_path)
            try:
                os.chmod(self._manifest_path, 0o640)
            except OSError:
                pass
        except OSError as e:
            logger.warning("Failed to save model manifest: %s", e)

    # -- User-initiated download --------------------------------------------
    def download_model(self, model_id: str, url: str,
                       expected_sha256: str = "",
                       network_enabled: bool = True,
                       progress_cb: Optional[Callable[[DownloadProgress], None]] = None,
                       cancel_event: Optional[threading.Event] = None,
                       overwrite: bool = False) -> DownloadProgress:
        """Download a model (synchronous; call from a thread).

        Args:
          model_id:        sanitize-checked model identifier
          url:             HTTPS URL to fetch
          expected_sha256: optional hex sha256 to verify (recommended)
          network_enabled: when False (offline mode), aborts immediately
          progress_cb:     callback(DownloadProgress) invoked during download
          cancel_event:    threading.Event; when set, aborts the download
          overwrite:       True to replace an existing file with same id
        """
        safe_id = _sanitize_filename(model_id)
        if safe_id is None:
            return DownloadProgress(model_id=model_id, url=url, status="error",
                                    error="invalid model_id")
        if not network_enabled:
            return DownloadProgress(model_id=safe_id, url=url, status="error",
                                    error="network disabled (offline mode)")

        # Determine expected hash: explicit arg > trusted manifest
        hash_expected = expected_sha256 or self._trusted_hashes.get(safe_id, "")
        if hash_expected and not _SHA256_RE.match(hash_expected):
            return DownloadProgress(model_id=safe_id, url=url, status="error",
                                    error="invalid expected_sha256")

        try:
            os.makedirs(self._model_dir, exist_ok=True)
        except OSError as e:
            return DownloadProgress(model_id=safe_id, url=url, status="error",
                                    error=f"mkdir failed: {e}")

        dest = os.path.join(self._model_dir, f"{safe_id}.gguf")
        # Defense-in-depth: confirm dest is inside model_dir
        if not self._is_within_model_dir(dest):
            return DownloadProgress(model_id=safe_id, url=url, status="error",
                                    error="path escapes model directory")

        if os.path.exists(dest) and not overwrite:
            return DownloadProgress(model_id=safe_id, url=url, status="error",
                                    error="destination exists; set overwrite=True to replace")

        dp = DownloadProgress(model_id=safe_id, url=url,
                              status="downloading",
                              expected_sha256=hash_expected)
        with self._download_lock:
            self._downloads[safe_id] = dp

        tmp = dest + ".part"
        # Clean any stale partial file
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass

        try:
            if cancel_event and cancel_event.is_set():
                dp.status = "cancelled"
                return dp

            # Validate the URL BEFORE opening a connection
            from .networking import validate_remote_url
            if not validate_remote_url(url, https_only=True):
                dp.status = "error"
                dp.error = "URL failed safety validation (must be https, public IP)"
                return dp

            resp = open_safe_url(url, timeout=60.0, https_only=True,
                                 allow_redirects=True, method="GET")
            try:
                content_length = 0
                try:
                    content_length = int(resp.headers.get("Content-Length", 0))
                except (TypeError, ValueError):
                    content_length = 0
                dp.total_bytes = content_length

                hasher = hashlib.sha256() if hash_expected else None
                downloaded = 0
                with open(tmp, "wb") as f:
                    while True:
                        if cancel_event and cancel_event.is_set():
                            dp.status = "cancelled"
                            return dp
                        chunk = resp.read(DOWNLOAD_CHUNK)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > MAX_DOWNLOAD_BYTES:
                            dp.status = "error"
                            dp.error = f"download exceeded size cap ({MAX_DOWNLOAD_BYTES} bytes)"
                            return dp
                        f.write(chunk)
                        if hasher is not None:
                            hasher.update(chunk)
                        dp.bytes_downloaded = downloaded
                        if progress_cb:
                            try:
                                progress_cb(dp)
                            except Exception:
                                pass
            finally:
                resp.close()

            # Validate hash BEFORE promoting
            if hasher is not None:
                actual = hasher.hexdigest()
                if actual.lower() != hash_expected.lower():
                    dp.status = "error"
                    dp.error = f"sha256 mismatch (expected {hash_expected[:16]}..., got {actual[:16]}...)"
                    return dp

            dp.status = "validating"
            if progress_cb:
                try:
                    progress_cb(dp)
                except Exception:
                    pass

            # Remove existing dest if overwriting
            if overwrite and os.path.exists(dest):
                try:
                    os.unlink(dest)
                except OSError as e:
                    dp.status = "error"
                    dp.error = f"cannot remove existing file: {e}"
                    return dp

            if not self._validate_and_promote(tmp, dest, hash_expected):
                dp.status = "error"
                dp.error = "validation failed; refusing to load model"
                return dp

            info = build_model_info(dest, model_id=safe_id)
            if not info:
                dp.status = "error"
                dp.error = "failed to build model info"
                return dp
            if hash_expected:
                info.sha256 = hash_expected.lower()
            with self._lock:
                self._models[safe_id] = info
            self._save_manifest()
            dp.status = "done"
            return dp
        except (urllib.error.URLError, OSError, ValueError) as e:
            dp.status = "error"
            dp.error = str(e)[:500]
            return dp
        finally:
            # Clean up temp file unless we succeeded
            if dp.status in ("error", "cancelled"):
                try:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                except OSError:
                    pass
            if progress_cb:
                try:
                    progress_cb(dp)
                except Exception:
                    pass

    def download_status(self, model_id: str) -> Optional[DownloadProgress]:
        with self._download_lock:
            return self._downloads.get(model_id)

    def remove_model(self, model_id: str) -> bool:
        """Delete a model from disk (user-initiated)."""
        with self._lock:
            info = self._models.get(model_id)
        if not info:
            return False
        if not self._is_within_model_dir(info.path):
            logger.error("Refusing to remove model outside model dir: %s", info.path)
            return False
        try:
            os.unlink(info.path)
        except OSError as e:
            logger.error("Failed to remove %s: %s", info.path, e)
            return False
        with self._lock:
            self._models.pop(model_id, None)
        self._save_manifest()
        return True


def _hash_file(path: str, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(chunk), b""):
                h.update(block)
        return h.hexdigest()
    except OSError as e:
        logger.error("Failed to hash %s: %s", path, e)
        return ""
