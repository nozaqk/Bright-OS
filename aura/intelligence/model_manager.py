"""Model Manager — discovers, indexes, and (on user request) downloads
models. Model weights are NEVER included in the ISO and never downloaded
automatically at boot.

Downloads are user-initiated, validated (sha256 + format magic) before
loading, and stored under the configured model directory.
"""
import json
import logging
import os
import shutil
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import model_info
from .model_info import (
    ModelFormat,
    ModelInfo,
    build_model_info,
    scan_model_directory,
    validate_model_file,
)

logger = logging.getLogger("aura.intelligence.model_manager")

# A small, curated recommended-models registry. This is NOT a downloader
# manifest; it just provides metadata for `list_available_models()` so the
# UI can show what the user might want. Actual downloads are initiated by
# explicit user action with a full URL.
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
    status: str = "pending"  # pending | downloading | validating | done | error
    error: str = ""


class ModelManager:
    def __init__(self, model_dir: str = "/var/lib/aura/models",
                 manifest_path: Optional[str] = None):
        self._model_dir = model_dir
        self._manifest_path = manifest_path or os.path.join(model_dir, "manifest.json")
        self._models: Dict[str, ModelInfo] = {}
        self._lock = threading.RLock()
        self._downloads: Dict[str, DownloadProgress] = {}
        self._download_lock = threading.Lock()
        self._refresh_models()

    # -- Discovery ----------------------------------------------------------
    def _refresh_models(self):
        try:
            os.makedirs(self._model_dir, exist_ok=True)
        except OSError:
            pass
        with self._lock:
            self._models.clear()
            for m in scan_model_directory(self._model_dir):
                self._models[m.model_id] = m
            # Also load manifest entries for models not found by scan
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
                info = build_model_info(path, model_id=mid)
                if info:
                    info.quant_type = entry.get("quant_type", info.quant_type)
                    info.param_count_b = entry.get("param_count_b", info.param_count_b)
                    info.context_window = entry.get("context_window", info.context_window)
                    self._models[mid] = info
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read model manifest: %s", e)

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

    # -- Recommended catalogue (for UI) -------------------------------------
    def list_recommended(self, tier: str = "medium") -> List[Dict[str, object]]:
        return [m for m in RECOMMENDED_MODELS if tier in m.get("suitable_tiers", [])]

    # -- Import a user-placed model -----------------------------------------
    def import_model_file(self, path: str, model_id: Optional[str] = None) -> Optional[ModelInfo]:
        """Register a model file already on disk (no download)."""
        ok, reason = validate_model_file(path)
        if not ok:
            logger.error("Refusing to import %s: %s", path, reason)
            return None
        # If file is outside model_dir, copy it in.
        dest = path
        if os.path.abspath(os.path.dirname(path)) != os.path.abspath(self._model_dir):
            try:
                os.makedirs(self._model_dir, exist_ok=True)
                dest = os.path.join(self._model_dir, os.path.basename(path))
                shutil.copy2(path, dest)
                logger.info("Copied model %s -> %s", path, dest)
            except OSError as e:
                logger.error("Failed to copy model to model dir: %s", e)
                return None
        info = build_model_info(dest, model_id=model_id)
        if info:
            with self._lock:
                self._models[info.model_id] = info
            self._save_manifest()
        return info

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
                    })
            tmp = self._manifest_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._manifest_path)
        except OSError as e:
            logger.warning("Failed to save model manifest: %s", e)

    # -- User-initiated download --------------------------------------------
    def download_model(self, model_id: str, url: str,
                       progress_cb: Optional[Callable[[DownloadProgress], None]] = None) -> DownloadProgress:
        """Start a download (synchronous; call from a thread).

        Returns the final DownloadProgress. The caller is responsible for
        running this in a thread if they want async behavior.
        """
        if not url.startswith(("https://", "http://", "file://")):
            dp = DownloadProgress(model_id=model_id, url=url,
                                  status="error", error="invalid URL scheme")
            return dp
        if not url.startswith("https://"):
            # Only warn; allow http/file for local mirrors but log.
            logger.warning("Model download is not using https: %s", url)

        try:
            os.makedirs(self._model_dir, exist_ok=True)
        except OSError as e:
            return DownloadProgress(model_id=model_id, url=url,
                                    status="error", error=f"mkdir failed: {e}")

        dest = os.path.join(self._model_dir, f"{model_id}.gguf")
        if os.path.exists(dest):
            # Don't overwrite silently; caller must remove first
            return DownloadProgress(model_id=model_id, url=url,
                                    status="error",
                                    error="destination exists; remove first")

        dp = DownloadProgress(model_id=model_id, url=url, status="downloading")
        with self._download_lock:
            self._downloads[model_id] = dp

        tmp = dest + ".part"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                dp.total_bytes = total
                with open(tmp, "wb") as f:
                    downloaded = 0
                    chunk = 64 * 1024
                    while True:
                        buf = resp.read(chunk)
                        if not buf:
                            break
                        f.write(buf)
                        downloaded += len(buf)
                        dp.bytes_downloaded = downloaded
                        if progress_cb:
                            try:
                                progress_cb(dp)
                            except Exception:
                                pass
            # Validate
            dp.status = "validating"
            if progress_cb:
                try:
                    progress_cb(dp)
                except Exception:
                    pass
            os.replace(tmp, dest)
            ok, reason = validate_model_file(dest)
            if not ok:
                os.unlink(dest)
                dp.status = "error"
                dp.error = f"validation failed: {reason}"
                return dp
            info = build_model_info(dest, model_id=model_id)
            if not info:
                dp.status = "error"
                dp.error = "failed to build model info"
                return dp
            with self._lock:
                self._models[model_id] = info
            self._save_manifest()
            dp.status = "done"
            return dp
        except (urllib.error.URLError, OSError) as e:
            dp.status = "error"
            dp.error = str(e)
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            return dp
        finally:
            if progress_cb:
                try:
                    progress_cb(dp)
                except Exception:
                    pass

    def download_status(self, model_id: str) -> Optional[DownloadProgress]:
        with self._download_lock:
            return self._downloads.get(model_id)
