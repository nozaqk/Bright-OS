"""Bright Android configuration management.

Stores user preferences for Bright Android: auto-start, notifications,
clipboard sharing, shared folders, etc.

Config location: ~/.config/bright-android/config.ini
System defaults: /usr/share/bright-android/config.ini.default
"""
import configparser
import os
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("bright_android.config")

CONFIG_DIR = os.path.expanduser("~/.config/bright-android")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.ini")

SYSTEM_CONFIG = "/etc/bright-android/config.ini"
DEFAULT_CONFIG = "/usr/share/bright-android/config.ini.default"

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "runtime": {
        "auto_start": "false",
        "start_on_demand": "true",
        "stop_on_idle": "false",
        "idle_timeout_minutes": "30",
        "suspend_when_inactive": "true",
    },
    "integration": {
        "clipboard_share": "true",
        "notification_forward": "true",
        "shared_clipboard_bidirectional": "true",
        "app_integration": "true",  # Create .desktop files for Android apps
        "window_integration": "true",  # Multi-window mode (Waydroid 1.4+)
    },
    "storage": {
        "shared_downloads": "true",
        "shared_documents": "false",
        "shared_pictures": "false",
        "shared_music": "false",
        "shared_videos": "false",
        "data_path": "/var/lib/waydroid",
    },
    "developer": {
        "adb_enabled": "false",
        "adb_port": "5555",
        "show_logs": "false",
        "debug_mode": "false",
        "nogpu_mode": "false",
    },
    "appearance": {
        "force_landscape": "false",
        "dpi": "0",  # 0 = auto
        "freeform_windows": "true",
    },
}


def _ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def _merge_defaults(parser: configparser.ConfigParser):
    """Populate parser with defaults if sections are missing."""
    for section, options in DEFAULTS.items():
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in options.items():
            if not parser.has_option(section, key):
                parser.set(section, key, str(value))


def load_config() -> configparser.ConfigParser:
    """Load config, creating defaults if needed."""
    parser = configparser.ConfigParser()
    _merge_defaults(parser)

    # Load system config first
    if os.path.exists(SYSTEM_CONFIG):
        try:
            parser.read(SYSTEM_CONFIG)
        except Exception as e:
            logger.warning("Could not read system config: %s", e)

    # Load user config (overrides)
    if os.path.exists(CONFIG_FILE):
        try:
            parser.read(CONFIG_FILE)
        except Exception as e:
            logger.warning("Could not read user config: %s", e)

    return parser


def save_config(parser: configparser.ConfigParser):
    """Save user configuration."""
    _ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        parser.write(f)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass
    logger.info("Configuration saved to %s", CONFIG_FILE)


def get_value(section: str, key: str, fallback: Any = None) -> str:
    """Get a single config value."""
    cfg = load_config()
    try:
        return cfg.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError):
        if fallback is not None:
            return str(fallback)
        return str(DEFAULTS.get(section, {}).get(key, ""))


def set_value(section: str, key: str, value: Any):
    """Set and persist a single config value."""
    cfg = load_config()
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, str(value))
    save_config(cfg)


def get_bool(section: str, key: str, fallback: bool = False) -> bool:
    val = get_value(section, key, str(fallback))
    return val.lower() in ("true", "yes", "1", "on")


def set_bool(section: str, key: str, value: bool):
    set_value(section, key, "true" if value else "false")


def get_int(section: str, key: str, fallback: int = 0) -> int:
    try:
        return int(get_value(section, key, str(fallback)))
    except (ValueError, TypeError):
        return fallback


def create_default_config_file():
    """Write the default config file template."""
    _ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        return
    parser = configparser.ConfigParser()
    _merge_defaults(parser)
    with open(CONFIG_FILE, "w") as f:
        f.write("# Bright Android configuration\n")
        f.write("# Edit via bright-android settings GUI\n\n")
        parser.write(f)
    os.chmod(CONFIG_FILE, 0o600)
