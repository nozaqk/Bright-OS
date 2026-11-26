"""Allowlist for configuration changes requested over D-Bus (SetConfig).

Only the settings listed in RUNTIME_WRITABLE may be changed at runtime. Every
other key is rejected, including keys that exist in config defaults but are
never read by the code, so nothing is writable by accident.

Keys were taken from the GUI (`gui.py`), which is the only code that reads or
writes configuration. The 11 other keys in config.DEFAULTS are not used by any
code path and are therefore not runtime-writable.
"""
import re

from . import config as ba_config

# section -> {key: value type}. Every key here is a boolean used by the GUI.
RUNTIME_WRITABLE = {
    "runtime": {"auto_start": "bool", "start_on_demand": "bool"},
    "integration": {
        "clipboard_share": "bool",
        "notification_forward": "bool",
        "app_integration": "bool",
    },
    "storage": {
        "shared_downloads": "bool",
        "shared_documents": "bool",
        "shared_pictures": "bool",
    },
    "developer": {
        "adb_enabled": "bool",
        "show_logs": "bool",
        "nogpu_mode": "bool",
    },
    "appearance": {"freeform_windows": "bool"},
}

# Settings that must never be changed through D-Bus, even if they were added to
# RUNTIME_WRITABLE later. data_path selects where Android data is stored.
PROTECTED = frozenset({("storage", "data_path")})

MAX_PATH_LEN = 64      # "section/key"
MAX_VALUE_LEN = 16     # longest allowed value is "false" (5 characters)
_NAME_RE = re.compile(r"^[a-z][a-z_]*$")
_BOOL_VALUES = ("true", "false")


class ConfigPolicyError(ValueError):
    """Raised when a configuration change is not permitted."""


def validate_setting(path: str, value: str) -> tuple:
    """Return (section, key, value) if the change is permitted, else raise.

    `path` must be "section/key". `value` must be a str.
    """
    if not isinstance(path, str) or not isinstance(value, str):
        raise ConfigPolicyError("key and value must be strings")
    if len(path) > MAX_PATH_LEN:
        raise ConfigPolicyError("key is too long")
    if path.count("/") != 1:
        raise ConfigPolicyError("key must be in section/key format")
    section, key = path.split("/", 1)
    if not _NAME_RE.match(section) or not _NAME_RE.match(key):
        raise ConfigPolicyError("section and key may only contain lowercase letters and underscores")
    if (section, key) in PROTECTED:
        raise ConfigPolicyError(f"{section}/{key} is a protected setting")
    if section not in RUNTIME_WRITABLE:
        raise ConfigPolicyError(f"unknown section: {section}")
    kinds = RUNTIME_WRITABLE[section]
    if key not in kinds:
        raise ConfigPolicyError(f"{section}/{key} is not a runtime-writable setting")
    if len(value) > MAX_VALUE_LEN:
        raise ConfigPolicyError("value is too long")
    if kinds[key] == "bool" and value not in _BOOL_VALUES:
        raise ConfigPolicyError(f"{section}/{key} must be 'true' or 'false'")
    return section, key, value


def set_setting(path: str, value: str) -> None:
    """Validate a change and write it. Nothing is written if validation fails."""
    section, key, value = validate_setting(path, value)
    ba_config.set_value(section, key, value)
