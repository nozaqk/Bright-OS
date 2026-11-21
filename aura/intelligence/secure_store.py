"""Secure API-key storage for cloud providers.

Design constraints (Phase 2.2 hardened):
  - API keys MUST NOT be stored in plaintext in aura.conf.
  - Key files are opened with O_NOFOLLOW and O_CLOEXEC.
  - ALL security decisions (regular file? permissions? ownership?) are made
    on the fstat() of the opened file descriptor, not on a separate
    lstat()/isfile() call. This eliminates TOCTOU races where an attacker
    replaces a safe file with a symlink or world-readable file between the
    permission check and the open.
  - External credential commands must be non-world/group-writable files
    and are executed WITHOUT a shell.
  - Keys are NEVER logged (only their length at info level).
  - Stderr from credential commands is never logged (may contain output).
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


def _fd_perms_ok(fd: int, path_hint: str = "") -> bool:
    """Given an opened file descriptor, fstat() it and verify it's a
    regular file owned by root or the current uid, with mode 0600 or
    tighter. Returns True if safe, False otherwise (and logs why)."""
    try:
        st = os.fstat(fd)
    except OSError as e:
        logger.error("Cannot fstat key file: %s", e)
        return False
    if not stat.S_ISREG(st.st_mode):
        logger.error("Key file is not a regular file (mode %o): %s",
                     stat.S_IFMT(st.st_mode), path_hint)
        return False
    mode = stat.S_IMODE(st.st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.error("Refusing key file %s: mode %o grants group/world access",
                     path_hint, mode)
        return False
    my_uid = os.geteuid()
    if st.st_uid != 0 and st.st_uid != my_uid:
        logger.error("Refusing key file %s: owned by uid %d (expected 0 or %d)",
                     path_hint, st.st_uid, my_uid)
        return False
    return True


def get_api_key(command: str = "", key_file: str = "") -> Optional[str]:
    command = (command or "").strip()
    key_file = (key_file or "").strip()
    if command:
        return _from_command(command)
    if key_file:
        return _from_file(key_file)
    return None


def _from_command(command: str) -> Optional[str]:
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
        # Never log stderr; it may contain a key
        logger.error("API key command exited %d (stderr_len=%d)",
                     result.returncode, len(result.stderr or ""))
        return None
    key = (result.stdout or "").strip()
    if not key:
        return None
    logger.info("API key retrieved via command (length=%d)", len(key))
    return key


def _from_file(path: str) -> Optional[str]:
    """Open the file with O_NOFOLLOW|O_CLOEXEC, then verify via fstat."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = None
    try:
        try:
            fd = os.open(path, flags, 0)
        except FileNotFoundError:
            logger.error("API key file does not exist: %s", path)
            return None
        except OSError as e:
            logger.error("Cannot open API key file %s: %s", path, e)
            return None
        if not _fd_perms_ok(fd, path_hint=path):
            return None
        with os.fdopen(fd, "r") as f:
            fd = None  # fdopen takes ownership
            key = f.read().strip()
        if not key:
            return None
        logger.info("API key read from file %s (length=%d)", path, len(key))
        return key
    except OSError as e:
        logger.error("Cannot read API key file %s: %s", path, e)
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


# Backwards-compatible helper used by tests; now implemented in terms of
# fstat-on-open, not a separate lstat.
def _file_perms_ok(path: str) -> bool:
    """Legacy helper retained for compatibility/tests. Performs a racy
    check via stat — DO NOT rely on this for the actual security decision;
    _from_file uses fstat() on the opened fd."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = None
    try:
        fd = os.open(path, flags, 0)
        ok = _fd_perms_ok(fd, path_hint=path)
        return ok
    except OSError:
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
