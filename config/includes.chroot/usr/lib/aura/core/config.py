"""AURA Core configuration management.

Reads configuration from /etc/bright-os/aura/aura.conf. All settings have
safe defaults so that AURA operates correctly even without a config file.
"""
import configparser
import logging
import os
from pathlib import Path
from typing import Any, Dict

from . import AURA_CONFIG_DIR

logger = logging.getLogger("aura.config")

# Default configuration — AURA is fully functional with these defaults
DEFAULTS: Dict[str, Dict[str, Any]] = {
    "core": {
        "log_level": "info",           # debug, info, warning, error
        "component_restart_limit": 5,  # Max restart attempts per component
        "component_restart_delay": 3,  # Seconds between restart attempts
    },
    "intelligence": {
        "mode": "local",               # local, hybrid, offline
        "provider": "auto",            # auto, qwen, llama.cpp, ollama, none
        "model_path": "",              # Path to local model file
        "max_memory_mb": "2048",       # Max RAM for model inference
        "cloud_endpoint": "",          # Cloud API URL (hybrid mode only)
        "cloud_api_key": "",           # Cloud API key (hybrid mode only)
        "require_consent": "true",     # Require consent before cloud calls
    },
    "security": {
        "enabled": "true",
        "file_integrity_check": "true",
        "process_monitoring": "true",
        "network_monitoring": "true",
        "auto_isolate": "false",       # Autonomous containment (default off)
        "audit_log": "true",
    },
    "memory": {
        "enabled": "true",
        "max_entries": "10000",
        "retention_days": "90",
    },
    "recovery": {
        "enabled": "true",
        "backup_dir": "/var/lib/aura/backups",
        "max_backups": "10",
    },
}


class AuraConfig:
    """Loads and provides access to AURA configuration."""

    def __init__(self, config_dir: str = AURA_CONFIG_DIR):
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "aura.conf"
        self._parser = configparser.ConfigParser()
        self._load_defaults()
        self._load_file()

    def _load_defaults(self):
        for section, values in DEFAULTS.items():
            self._parser.add_section(section)
            for key, value in values.items():
                self._parser.set(section, key, str(value))

    def _load_file(self):
        if self.config_file.exists():
            try:
                self._parser.read(self.config_file)
                logger.info("Loaded configuration from %s", self.config_file)
            except Exception as e:
                logger.error("Failed to parse %s: %s — using defaults",
                             self.config_file, e)
        else:
            logger.info("No config file at %s — using defaults", self.config_file)

    def get(self, section: str, key: str) -> str:
        return self._parser.get(section, key)

    def getboolean(self, section: str, key: str) -> bool:
        return self._parser.getboolean(section, key)

    def getint(self, section: str, key: str) -> int:
        return self._parser.getint(section, key)

    def set(self, section: str, key: str, value: str):
        if not self._parser.has_section(section):
            self._parser.add_section(section)
        self._parser.set(section, key, value)

    def save(self):
        """Save current configuration to file (requires write permission)."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            self._parser.write(f)
        logger.info("Configuration saved to %s", self.config_file)

    def sections(self):
        return self._parser.sections()
