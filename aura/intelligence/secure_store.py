"""Secure API-key storage for cloud providers.

Design constraints (from PRD):
  - API keys MUST NOT be stored in plaintext in aura.conf
  - We prefer invoking an external command (`cloud_api_key_command`) that
    the admin configures (e.g. `pass show aura/openai`, a secret-tool lookup).
  - As a fallback we read a file (`cloud_api_key_file`) that must be mode 0600
    and owned by the aura user (or root with 0600).
  - We NEVER log the key.
  - We do NOT shell out to arbitrary user input: only the exact command the
    admin configured in aura.conf is executed (with no shell interpolation).
"""
import logging
import os
import stat
import subprocess
from typing import Optional

logger = logging.getLogger("aura.intelligence.secure_store")


class SecureStoreError(RuntimeError):
    pass


def _file_perms_ok(path: str) -> bool:
    """Return True if the file has mode 0600 (owner-only read/write)."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    mode = stat.S_IMODE(st.st_mode)
    # Reject group/other access
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        return False
    return True


def get_api_key(command: str = "", key_file: str = "") -> Optional[str]:
    """Retrieve a cloud API key via the configured mechanism.

    Resolution order:
      1. If `command` is set, execute it (no shell) and strip stdout.
      2. Else if `key_file` is set, read it if permissions are 0600.
      3. Else return None.
    """
    command = (command or "").strip()
    key_file = (key_file or "").strip()

    if command:
        return _from_command(command)
    if key_file:
        return _from_file(key_file)
    return None


def _from_command(command: str) -> Optional[str]:
    # Split command without shell to avoid injection. Only allow single
    # executable with args, no pipes/redirection.
    import shlex
    try:
        args = shlex.split(command)
    except ValueError as e:
        raise SecureStoreError(f"Invalid api key command: {e}") from e
    if not args:
        return None
    exe = args[0]
    if not os.path.isabs(exe) and not os.path.exists(exe):
        # Resolve via PATH
        import shutil
        resolved = shutil.which(exe)
        if not resolved:
            raise SecureStoreError(f"api key command not found: {exe}")
        args[0] = resolved
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=10, shell=False)
    except subprocess.TimeoutExpired:
        logger.error("API key command timed out")
        return None
    except OSError as e:
        logger.error("API key command failed: %s", e)
        return None
    if result.returncode != 0:
        logger.error("API key command exited %d: %s",
                     result.returncode, result.stderr.strip())
        return None
    key = result.stdout.strip()
    if not key:
        return None
    logger.info("API key retrieved via command (length=%d)", len(key))
    return key


def _from_file(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        logger.error("API key file does not exist: %s", path)
        return None
    if not _file_perms_ok(path):
        logger.error("Refusing to read API key file %s: permissions must be 0600 "
                     "(no group/world access)", path)
        return None
    try:
        with open(path, "r") as f:
            key = f.read().strip()
        if key:
            logger.info("API key read from file %s (length=%d)", path, len(key))
            return key
        return None
    except OSError as e:
        logger.error("Cannot read API key file %s: %s", path, e)
        return None
