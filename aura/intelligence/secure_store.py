"""Secure API-key storage for cloud providers.

Design constraints:
  - API keys MUST NOT be stored in plaintext in aura.conf.
  - Preferred: invoke an external admin-configured command (e.g.
    `secret-tool lookup ...`, `pass show aura/openai`). The command is
    executed WITHOUT a shell, with a fixed argv; the binary is resolved
    via PATH but NOT invoked through shell interpolation.
  - Fallback: read a file (`cloud_api_key_file`) that must be:
      * a regular file (not a symlink),
      * mode 0600 (no group/other access),
      * owned by root or the invoking (aura) user.
  - Keys are NEVER logged (only length is logged at info level).
  - Missing credential providers return None safely — never raise into
    the service start path.
"""
import logging
import os
import shlex
import shutil
import stat
import subprocess
from typing import Optional

logger = logging.getLogger("aura.intelligence.secure_store")


class SecureStoreError(RuntimeError):
    pass


def _file_perms_ok(path: str) -> bool:
    """Return True only if `path` is a regular file (not symlink), mode
    0600 or tighter, owned by root or the current uid."""
    try:
        # Use lstat to NOT follow symlinks (prevents symlink race)
        st = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        logger.error("API key path is not a regular file: %s", path)
        return False
    mode = stat.S_IMODE(st.st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.error("Refusing API key file %s: mode %o grants group/world access",
                     path, mode)
        return False
    # Ownership: only allow root or the current user
    my_uid = os.geteuid()
    if st.st_uid != 0 and st.st_uid != my_uid:
        logger.error("Refusing API key file %s: owned by uid %d (expected 0 or %d)",
                     path, st.st_uid, my_uid)
        return False
    return True


def get_api_key(command: str = "", key_file: str = "") -> Optional[str]:
    """Retrieve a cloud API key via the configured mechanism.

    Resolution order:
      1. If `command` is set, execute it (no shell) and return its stdout.
      2. Else if `key_file` is set, read it if perms/ownership pass.
      3. Else return None.

    Returns None on any failure (logged). Raises SecureStoreError only for
    syntactically invalid command configuration (caller should catch it).
    """
    command = (command or "").strip()
    key_file = (key_file or "").strip()

    if command:
        return _from_command(command)
    if key_file:
        return _from_file(key_file)
    return None


def _from_command(command: str) -> Optional[str]:
    """Execute a credential command without a shell."""
    try:
        args = shlex.split(command)
    except ValueError as e:
        raise SecureStoreError(f"Invalid api key command: {e}") from e
    if not args:
        return None
    exe = args[0]
    if not os.path.isabs(exe):
        resolved = shutil.which(exe)
        if not resolved:
            logger.error("API key command not found on PATH: %s", exe)
            return None
        args[0] = resolved
    # Refuse to run a world-writable binary
    try:
        st = os.stat(args[0])
        if stat.S_IMODE(st.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
            logger.error("Refusing to run world/group-writable credential "
                         "command: %s", args[0])
            return None
    except OSError as e:
        logger.error("Cannot stat credential command %s: %s", args[0], e)
        return None
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
        # Stderr may contain sensitive output; log only returncode + length
        logger.error("API key command exited %d (stderr len=%d)",
                     result.returncode, len(result.stderr or ""))
        return None
    key = (result.stdout or "").strip()
    if not key:
        return None
    logger.info("API key retrieved via command (length=%d)", len(key))
    return key


def _read_file_nofollow(path: str) -> Optional[str]:
    """Read a file without following symlinks."""
    flags = os.O_RDONLY
    # O_NOFOLLOW is POSIX.1-2008 and supported on Linux
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0)
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.error("Cannot open API key file %s (symlink?): %s", path, e)
        return None
    try:
        with os.fdopen(fd, "r") as f:
            return f.read().strip()
    except OSError as e:
        logger.error("Cannot read API key file %s: %s", path, e)
        return None


def _from_file(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        logger.error("API key file does not exist: %s", path)
        return None
    if not _file_perms_ok(path):
        return None
    key = _read_file_nofollow(path)
    if key:
        logger.info("API key read from file %s (length=%d)", path, len(key))
        return key
    return None
