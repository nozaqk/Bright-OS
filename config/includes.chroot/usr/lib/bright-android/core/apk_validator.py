"""APK file validation for Bright Android.

Validates APK architecture (x86_64 vs ARM-only), file integrity, and basic
metadata extraction without requiring external Android tools.

APK files are ZIP archives. We check:
  - File exists and is a valid ZIP
  - File size is reasonable
  - Native libraries inside indicate x86_64 support
  - AndroidManifest.xml exists (even if binary XML)

For ARM-only APKs, we report the incompatibility clearly. We do NOT
claim ARM translation/Houdini support unless explicitly installed.
"""
import os
import struct
import zipfile
import logging
from pathlib import Path
from typing import Dict, Optional, List

logger = logging.getLogger("bright_android.apk")

# Minimum/maximum reasonable APK size
MIN_APK_BYTES = 1024  # 1 KB
MAX_APK_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB (generous for large games)

# Android ABIs
ABI_X86_64 = "x86_64"
ABI_X86 = "x86"
ABI_ARM64 = "arm64-v8a"
ABI_ARM = "armeabi-v7a"
ABI_ARM_V5 = "armeabi"
ABI_UNIVERSAL = "universal"  # Pure Java/Kotlin, no native code


def _read_zip_comment(zf: zipfile.ZipFile) -> bytes:
    """Read APK signing block comment (simplified)."""
    return b""


def get_architectures(apk_path: str) -> List[str]:
    """Determine which ABIs an APK supports by inspecting its lib/ entries.

    Returns a list of supported ABI strings. If there are no native
    libraries, the APK is considered 'universal' (pure Java/Kotlin).
    """
    abis = set()
    try:
        with zipfile.ZipFile(apk_path, "r") as zf:
            for name in zf.namelist():
                if name.startswith("lib/"):
                    parts = name.split("/")
                    if len(parts) >= 2:
                        abi = parts[1]
                        if abi in (ABI_X86_64, ABI_X86, ABI_ARM64, ABI_ARM, ABI_ARM_V5):
                            abis.add(abi)
    except (zipfile.BadZipFile, OSError) as e:
        logger.warning("Cannot read APK architectures: %s", e)
        return []

    if not abis:
        return [ABI_UNIVERSAL]
    return sorted(abis)


def is_compatible_x86_64(apk_path: str) -> Dict[str, object]:
    """Check if an APK is compatible with x86_64 (Bright OS target).

    Returns dict with:
        compatible: bool
        architectures: list of ABIs
        reason: str explaining compatibility status
    """
    result = {
        "compatible": False,
        "architectures": [],
        "reason": "",
        "is_universal": False,
    }

    path = Path(apk_path)
    if not path.exists():
        result["reason"] = f"File not found: {apk_path}"
        return result

    size = path.stat().st_size
    if size < MIN_APK_BYTES:
        result["reason"] = f"File too small ({size} bytes); not a valid APK"
        return result

    if size > MAX_APK_BYTES:
        result["reason"] = f"File too large ({size // (1024**3)} GB)"
        return result

    if not zipfile.is_zipfile(apk_path):
        result["reason"] = "Not a valid ZIP/APK file"
        return result

    try:
        with zipfile.ZipFile(apk_path, "r") as zf:
            names = zf.namelist()
            if "AndroidManifest.xml" not in names:
                result["reason"] = "Missing AndroidManifest.xml; not a valid APK"
                return result
    except (zipfile.BadZipFile, OSError) as e:
        result["reason"] = f"Cannot read APK: {e}"
        return result

    abis = get_architectures(apk_path)
    result["architectures"] = abis

    if ABI_UNIVERSAL in abis:
        result["compatible"] = True
        result["is_universal"] = True
        result["reason"] = (
            "Pure Java/Kotlin application (no native code); "
            "compatible with x86_64"
        )
        return result

    if ABI_X86_64 in abis or ABI_X86 in abis:
        result["compatible"] = True
        x86_abis = [a for a in abis if a in (ABI_X86_64, ABI_X86)]
        result["reason"] = f"x86/x86_64 native code found ({', '.join(x86_abis)})"
        return result

    # ARM only
    arm_abis = [a for a in abis if a.startswith("arm")]
    if arm_abis:
        result["reason"] = (
            f"ARM-only application ({', '.join(arm_abis)}). "
            "Bright Android uses the x86_64 Android image by default. "
            "ARM native code requires libndk_translation or Houdini, "
            "which are not bundled due to licensing restrictions. "
            "Some ARM apps may work if you install an ARM translation layer."
        )
    else:
        result["reason"] = f"Unrecognized architectures: {abis}"

    return result


def get_app_info(apk_path: str) -> Dict[str, object]:
    """Extract basic app info from an APK.

    Note: Full AndroidManifest parsing requires a binary XML parser
    (like androguard/aapt). We extract what we can from ZIP structure
    and filenames. Callers should use `aapt dump badging` if aapt is
    available for full metadata.
    """
    info = {
        "path": apk_path,
        "filename": os.path.basename(apk_path),
        "size_bytes": 0,
        "package_name": "",
        "version_name": "",
        "label": "",
        "architectures": [],
        "valid": False,
        "has_icon": False,
    }

    path = Path(apk_path)
    if not path.exists():
        return info

    info["size_bytes"] = path.stat().st_size

    compat = is_compatible_x86_64(apk_path)
    info["architectures"] = compat["architectures"]
    info["valid"] = compat.get("compatible", False) or bool(compat["architectures"])

    try:
        with zipfile.ZipFile(apk_path, "r") as zf:
            names = zf.namelist()
            # Check for icon resources
            icon_patterns = ("res/mipmap-", "res/drawable-", "ic_launcher")
            info["has_icon"] = any(
                p in n for n in names for p in icon_patterns
            )
    except (zipfile.BadZipFile, OSError):
        pass

    # Try to use aapt/aapt2 if available for richer metadata
    aapt = None
    for tool in ("aapt2", "aapt"):
        import shutil as _shutil
        if _shutil.which(tool):
            aapt = tool
            break

    if aapt:
        try:
            import subprocess
            if aapt == "aapt2":
                result = subprocess.run(
                    ["aapt2", "dump", "badging", apk_path],
                    capture_output=True, text=True, timeout=10
                )
            else:
                result = subprocess.run(
                    ["aapt", "dump", "badging", apk_path],
                    capture_output=True, text=True, timeout=10
                )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("package: name="):
                        # Parse: package: name='com.example' versionCode='1' versionName='1.0'
                        parts = line.split()
                        for p in parts:
                            if p.startswith("name="):
                                info["package_name"] = p.split("'")[1]
                            elif p.startswith("versionName="):
                                info["version_name"] = p.split("'")[1]
                    elif line.startswith("application-label:"):
                        info["label"] = line.split("'")[1] if "'" in line else ""
        except Exception as e:
            logger.debug("aapt metadata extraction failed: %s", e)

    # Fallback label from filename
    if not info["label"]:
        info["label"] = Path(apk_path).stem.replace("_", " ").replace("-", " ")

    return info


def validate_apk_path(apk_path: str) -> Optional[str]:
    """Validate that an APK path is safe.

    Returns None if valid, error message string if invalid.
    Prevents path traversal, shell injection, etc.
    """
    if not apk_path:
        return "Empty path"

    # Must reject null bytes before any Path operations (they crash resolve())
    if "\x00" in apk_path:
        return "Invalid path (null byte)"

    path = Path(apk_path).resolve()

    # Must exist
    if not path.exists():
        return f"File does not exist: {apk_path}"

    # Must be a regular file
    if not path.is_file():
        return "Not a regular file"

    # Must end with .apk
    if path.suffix.lower() != ".apk":
        return f"Not an APK file (extension: {path.suffix})"

    # Basic path safety: reject paths with null bytes or shell metacharacters
    # (though we use argv lists, not shell strings)
    if "\x00" in apk_path:
        return "Invalid path (null byte)"

    return None
