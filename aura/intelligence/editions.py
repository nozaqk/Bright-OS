"""Edition support for AURA Intelligence.

Bright OS ships in three editions; the AI stack behaves differently per
edition but the same binary code is used. Which edition is active is
determined at build time by writing /etc/bright-os/edition.

  - HOME:       Full local/hybrid/offline AI support.
  - DEVELOPER:  Full AI + extra dev config (debug endpoints, model tuning
                presets, provider dev modes).
  - LITE:       Lightweight, optional AI. AI defaults to OFF, smaller
                defaults, model dir on removable media is preferred.
"""
import logging
import os
from typing import Dict

logger = logging.getLogger("aura.intelligence.editions")

EDITION_FILE = "/etc/bright-os/edition"

VALID_EDITIONS = ("home", "developer", "lite")


def detect_edition() -> str:
    """Return the current edition, defaulting to 'home'."""
    try:
        with open(EDITION_FILE) as f:
            ed = f.read().strip().lower()
            if ed in VALID_EDITIONS:
                return ed
    except OSError:
        pass
    # Fallback: env var for testing
    env = os.environ.get("AURA_EDITION", "").lower()
    if env in VALID_EDITIONS:
        return env
    return "home"


def edition_defaults(edition: str) -> Dict[str, object]:
    """Return edition-specific default config overrides."""
    edition = edition.lower()
    base: Dict[str, object] = {
        "mode": "local",
        "auto_load_at_boot": False,
        "max_memory_percent": 50,
        "unload_idle_seconds": 600,
        "lazy_load": True,
        "cloud_available": True,
        "default_model_size": "medium",
    }
    if edition == "developer":
        base.update({
            "max_memory_percent": 70,
            "unload_idle_seconds": 1800,  # longer idle on dev machines
            "default_model_size": "large",
            "dev_tools_enabled": True,
        })
    elif edition == "lite":
        base.update({
            "mode": "offline",
            "max_memory_percent": 35,
            "unload_idle_seconds": 120,  # aggressive unload on lite
            "cloud_available": False,
            "default_model_size": "small",
            # Lite prefers model dir on removable storage; override via config
            "model_dir": "/var/lib/aura/models",
        })
    return base


def apply_edition_defaults(config_obj, edition: str = ""):
    """Apply edition defaults to a live AuraConfig instance (only for keys
    that are not already explicitly set in the config file)."""
    edition = edition or detect_edition()
    defaults = edition_defaults(edition)
    # Map internal keys to config section/key
    key_map = {
        "mode": ("intelligence", "mode"),
        "auto_load_at_boot": ("intelligence", "auto_load_at_boot"),
        "max_memory_percent": ("intelligence", "max_memory_percent"),
        "unload_idle_seconds": ("intelligence", "unload_idle_seconds"),
        "lazy_load": ("intelligence", "lazy_load"),
    }
    for k, v in defaults.items():
        if k not in key_map:
            continue
        section, key = key_map[k]
        # Only override if current value matches the hard-coded default
        # (meaning the admin didn't set it in aura.conf).
        try:
            current = config_obj.get(section, key)
        except Exception:
            current = None
        if current is None or current == "":
            config_obj.set(section, key, str(v).lower())
    return edition
