"""AURA structured logging configuration.

Logs go to syslog (via systemd journal) and optionally to /var/log/aura/aura.log.
Uses structured key=value pairs for easy parsing by security tooling.
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from . import AURA_LOG_DIR


def setup_logging(level_name: str = "info") -> logging.Logger:
    """Configure structured logging for the AURA service."""
    root = logging.getLogger("aura")
    root.setLevel(_level(level_name))

    # Avoid duplicate handlers on re-init
    if root.handlers:
        return root

    formatter = logging.Formatter(
        "aura component=%(name)s level=%(levelname)s msg=\"%(message)s\"",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    # Syslog (systemd journal) handler — always available
    try:
        syslog_handler = logging.handlers.SysLogHandler(address="/dev/log")
        syslog_handler.setFormatter(formatter)
        root.addHandler(syslog_handler)
    except (OSError, FileNotFoundError):
        pass  # syslog not available (e.g. in tests); fall back to stderr

    # Stderr handler for foreground/debug runs
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    # File handler if log directory is writable
    try:
        log_dir = Path(AURA_LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "aura.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except (OSError, PermissionError):
        root.debug("Cannot write to %s (running unprivileged?); skipping file log",
                   AURA_LOG_DIR)

    return root


def _level(name: str) -> int:
    return {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "warn": logging.WARNING,
        "error": logging.ERROR,
    }.get(name.lower(), logging.INFO)
