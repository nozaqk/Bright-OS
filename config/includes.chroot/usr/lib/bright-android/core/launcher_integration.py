"""Launcher integration for Bright Android.

Creates and manages .desktop files for installed Android applications in
~/.local/share/applications/ so they appear in the Bright OS launcher
alongside native Linux applications.
"""
import os
import logging
import shutil
from pathlib import Path
from typing import List, Dict, Optional
import configparser
import time

logger = logging.getLogger("bright_android.launcher")

APP_DIR = os.path.expanduser("~/.local/share/applications")
ICON_DIR = os.path.expanduser("~/.local/share/icons/bright-android")
DESKTOP_PREFIX = "bright-android-app-"
ANDROID_ICON_CACHE = os.path.expanduser("~/.cache/bright-android/icons")


def _ensure_dirs():
    os.makedirs(APP_DIR, exist_ok=True)
    os.makedirs(ICON_DIR, exist_ok=True)
    os.makedirs(ANDROID_ICON_CACHE, exist_ok=True)


def _desktop_filename(package_name: str) -> str:
    safe_name = package_name.replace("/", "-").replace(" ", "-")
    return f"{DESKTOP_PREFIX}{safe_name}.desktop"


def _desktop_path(package_name: str) -> Path:
    return Path(APP_DIR) / _desktop_filename(package_name)


def _get_app_icon(package_name: str) -> str:
    """Attempt to get an icon path for an Android app.

    Falls back to the generic Bright Android icon if we can't extract
    the app-specific icon.
    """
    # Check cached icon first
    cached = Path(ANDROID_ICON_CACHE) / f"{package_name}.png"
    if cached.exists():
        return str(cached)

    # Generic icon
    return "bright-android"  # Named icon from icon theme


def create_app_desktop_entry(app: Dict[str, str]) -> Path:
    """Create a .desktop file for an Android application."""
    _ensure_dirs()

    package = app.get("package", "")
    name = app.get("name", package)
    launch_activity = app.get("launch_activity", "")

    if not package:
        raise ValueError("Package name required")

    entry = configparser.ConfigParser()
    entry.optionxform = str  # Preserve case
    entry.add_section("Desktop Entry")
    entry.set("Desktop Entry", "Type", "Application")
    entry.set("Desktop Entry", "Name", name)
    entry.set("Desktop Entry", "Comment", f"Android application: {name}")
    entry.set("Desktop Entry", "Exec", f"bright-android --launch {package}")
    entry.set("Desktop Entry", "Icon", _get_app_icon(package))
    entry.set("Desktop Entry", "Terminal", "false")
    entry.set("Desktop Entry", "Categories", "Android;")
    entry.set("Desktop Entry", "Keywords", f"android;{name.lower()};")
    entry.set("Desktop Entry", "X-Bright-Android-Package", package)
    entry.set("Desktop Entry", "X-Bright-Android", "true")
    if launch_activity:
        entry.set("Desktop Entry", "X-Bright-Android-Activity", launch_activity)

    path = _desktop_path(package)
    with open(path, "w") as f:
        entry.write(f)

    # Make executable? Not required for .desktop files, but nice
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass

    logger.debug("Created desktop entry: %s", path)
    return path


def remove_app_desktop_entry(package_name: str) -> bool:
    """Remove the .desktop file for an Android app."""
    path = _desktop_path(package_name)
    if path.exists():
        path.unlink()
        logger.debug("Removed desktop entry: %s", path)
        return True
    return False


def remove_all_android_entries() -> int:
    """Remove ALL bright-android generated .desktop files. Returns count."""
    count = 0
    app_dir = Path(APP_DIR)
    if not app_dir.exists():
        return 0
    for f in app_dir.glob(f"{DESKTOP_PREFIX}*.desktop"):
        try:
            f.unlink()
            count += 1
        except OSError:
            pass
    logger.info("Removed %d Android desktop entries", count)
    return count


def sync_apps(apps: List[Dict[str, str]]) -> int:
    """Sync launcher entries with the list of installed Android apps.

    Creates entries for new apps, removes entries for uninstalled apps.
    Returns the number of entries created/updated.
    """
    _ensure_dirs()

    current_packages = {a.get("package") for a in apps if a.get("package")}

    # Remove stale entries
    app_dir = Path(APP_DIR)
    if app_dir.exists():
        for f in app_dir.glob(f"{DESKTOP_PREFIX}*.desktop"):
            try:
                entry = configparser.ConfigParser()
                entry.read(f)
                pkg = entry.get("Desktop Entry", "X-Bright-Android-Package",
                              fallback="")
                if pkg and pkg not in current_packages:
                    f.unlink()
                    logger.debug("Removed stale entry: %s", f.name)
            except Exception as e:
                logger.warning("Error reading %s: %s", f, e)

    # Create/update entries
    count = 0
    for app in apps:
        if app.get("package"):
            create_app_desktop_entry(app)
            count += 1

    # Update desktop database
    _update_desktop_database()

    return count


def _update_desktop_database():
    """Tell the desktop environment to refresh its application database."""
    if shutil.which("update-desktop-database"):
        try:
            import subprocess
            subprocess.run(
                ["update-desktop-database", APP_DIR],
                capture_output=True, timeout=10
            )
        except Exception:
            pass


def list_android_desktop_entries() -> List[Dict[str, str]]:
    """List all Android .desktop entries currently on disk."""
    entries = []
    app_dir = Path(APP_DIR)
    if not app_dir.exists():
        return entries
    for f in app_dir.glob(f"{DESKTOP_PREFIX}*.desktop"):
        try:
            entry = configparser.ConfigParser()
            entry.read(f)
            if entry.has_section("Desktop Entry"):
                entries.append({
                    "file": str(f),
                    "name": entry.get("Desktop Entry", "Name", fallback=""),
                    "package": entry.get("Desktop Entry", "X-Bright-Android-Package",
                                          fallback=""),
                    "icon": entry.get("Desktop Entry", "Icon", fallback=""),
                })
        except Exception:
            pass
    return entries
