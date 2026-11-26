"""Model metadata, format detection, and memory-requirement estimation.

Model weights are NEVER bundled in the ISO. Users download GGUF files via
user-initiated actions, and we validate size/hash/format before loading.

We primarily target GGUF (llama.cpp) which works well on CPU. Qwen-family
models are supported as long as they are available in GGUF.
"""
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("aura.intelligence.models")

# Model file extensions we recognize
GGUF_EXTENSIONS = {".gguf"}
SAFETENSORS_EXTENSIONS = {".safetensors", ".bin"}
MODEL_EXTENSIONS = GGUF_EXTENSIONS | SAFETENSORS_EXTENSIONS


class ModelFormat(Enum):
    GGUF = "gguf"
    SAFETENSORS = "safetensors"
    UNKNOWN = "unknown"


@dataclass
class ModelInfo:
    """Metadata about a discovered local model."""
    model_id: str             # stable identifier, e.g. "qwen2.5-3b-instruct"
    path: str                 # absolute path to file (or dir for safetensors)
    format: ModelFormat
    size_bytes: int = 0
    quant_type: str = ""      # e.g. "Q4_K_M", "Q8_0"
    param_count_b: float = 0  # billions of parameters (best guess)
    context_window: int = 4096
    requires_gpu: bool = False
    sha256: str = ""
    friendly_name: str = ""

    def estimated_memory_mb(self) -> int:
        """Estimate runtime RAM usage (weights + KV cache overhead).

        Uses rough per-quantization bytes-per-parameter multipliers and adds
        a KV-cache + runtime overhead estimate. These are conservative upper
        bounds so the resource manager doesn't overcommit.
        """
        bytes_per_param = _quant_to_bpp(self.quant_type)
        if self.param_count_b <= 0:
            # Fall back to file size * 1.2 (rough overhead)
            return int(self.size_bytes * 1.2 // (1024 * 1024))
        weights_mb = int(self.param_count_b * 1e9 * bytes_per_param // (1024 * 1024))
        # KV cache + activation overhead: ~30% for small contexts, capped
        overhead_mb = max(256, int(weights_mb * 0.30))
        return weights_mb + overhead_mb


# ---- Quantization table ----------------------------------------------------
# Map of common GGUF quant suffixes to approximate bytes per parameter.
_QUANT_BPP: Dict[str, float] = {
    "Q2_K": 0.28, "Q2_K_S": 0.28, "IQ2_XXS": 0.25, "IQ2_XS": 0.26,
    "Q3_K_S": 0.33, "Q3_K_M": 0.37, "Q3_K_L": 0.40, "IQ3_XS": 0.32,
    "Q4_0": 0.47, "Q4_K_S": 0.49, "Q4_K_M": 0.51,
    "Q5_K_S": 0.58, "Q5_K_M": 0.60,
    "Q6_K": 0.68,
    "Q8_0": 1.00, "F16": 2.00, "F32": 4.00, "FP16": 2.00,
}


def _quant_to_bpp(quant_type: str) -> float:
    q = quant_type.upper().replace("-", "_")
    # exact match first
    if q in _QUANT_BPP:
        return _QUANT_BPP[q]
    # prefix match
    for k, v in _QUANT_BPP.items():
        if q.startswith(k):
            return v
    # Unknown quant: assume Q4 equivalent to be safe
    logger.warning("Unknown quantization %s; assuming Q4-equivalent memory", quant_type)
    return 0.55


_PARAM_PATTERNS = [
    (re.compile(r"(\d+(?:\.\d+)?)b", re.IGNORECASE), 1.0),   # 7b, 1.5b
    (re.compile(r"(\d+(?:\.\d+)?)m", re.IGNORECASE), 0.001), # 360m
]


def estimate_params_from_name(name: str) -> float:
    """Guess parameter count (billions) from filename."""
    for rx, mult in _PARAM_PATTERNS:
        m = rx.search(name)
        if m:
            try:
                return float(m.group(1)) * mult
            except ValueError:
                pass
    return 0.0


def detect_quant_from_name(name: str) -> str:
    """Try to extract quantization type from filename."""
    upper = name.upper().replace("-", "_")
    # Check longer prefixes first
    for q in sorted(_QUANT_BPP.keys(), key=len, reverse=True):
        if q in upper:
            return q
    return ""


def _has_gguf_magic(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"GGUF"
    except OSError:
        return False


def detect_format(path: str) -> ModelFormat:
    ext = os.path.splitext(path)[1].lower()
    # If the extension matches, trust it
    if ext in GGUF_EXTENSIONS:
        return ModelFormat.GGUF
    if ext in SAFETENSORS_EXTENSIONS:
        return ModelFormat.SAFETENSORS
    # Fall back to content sniffing so temp files without proper extensions
    # can still be validated.
    if _has_gguf_magic(path):
        return ModelFormat.GGUF
    return ModelFormat.UNKNOWN


def validate_model_file(path: str) -> Tuple[bool, str]:
    """Run lightweight validation on a model file before loading.

    Returns (ok, reason).
    """
    if not os.path.exists(path):
        return False, f"path does not exist: {path}"
    if not os.access(path, os.R_OK):
        return False, f"path not readable: {path}"
    size = os.path.getsize(path)
    if size < 1024 * 1024:  # smaller than 1MB is not a model
        return False, f"file too small to be a model ({size} bytes)"
    fmt = detect_format(path)
    if fmt == ModelFormat.UNKNOWN:
        return False, f"unrecognized model format: {path}"
    if fmt == ModelFormat.GGUF:
        # Minimal GGUF magic check: "GGUF" at offset 0
        try:
            with open(path, "rb") as f:
                magic = f.read(4)
            if magic != b"GGUF":
                return False, "file has .gguf extension but no GGUF magic number"
        except OSError as e:
            return False, f"cannot read file: {e}"
    return True, "ok"


def sha256_file(path: str, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(chunk), b""):
                h.update(block)
        return h.hexdigest()
    except OSError as e:
        logger.error("Failed to hash %s: %s", path, e)
        return ""


def build_model_info(path: str, model_id: Optional[str] = None) -> Optional[ModelInfo]:
    """Construct a ModelInfo from a path. Returns None if invalid."""
    ok, reason = validate_model_file(path)
    if not ok:
        logger.warning("Refusing to index %s: %s", path, reason)
        return None
    fname = os.path.basename(path)
    fmt = detect_format(path)
    size = os.path.getsize(path)
    quant = detect_quant_from_name(fname)
    params = estimate_params_from_name(fname)
    if model_id is None:
        # Use filename without extension as id
        model_id = os.path.splitext(fname)[0]
    return ModelInfo(
        model_id=model_id,
        path=path,
        format=fmt,
        size_bytes=size,
        quant_type=quant,
        param_count_b=params,
        friendly_name=fname,
    )


def scan_model_directory(directory: str) -> List[ModelInfo]:
    """Scan a directory for valid model files. Non-recursive by default to
    avoid walking into huggingface cache trees accidentally."""
    models: List[ModelInfo] = []
    if not os.path.isdir(directory):
        return models
    try:
        for entry in os.listdir(directory):
            full = os.path.join(directory, entry)
            if not os.path.isfile(full):
                continue
            if os.path.splitext(entry)[1].lower() not in MODEL_EXTENSIONS:
                continue
            info = build_model_info(full)
            if info:
                models.append(info)
    except OSError as e:
        logger.error("Failed to scan %s: %s", directory, e)
    return models
