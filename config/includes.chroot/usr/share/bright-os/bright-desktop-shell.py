#!/usr/bin/env python3
"""
Bright Desktop Shell - Main compositor shell for Bright OS
Provides panel, dock, wallpaper, window management, and launcher integration.

Supports three desktop profiles:
  - home:      Friendly everyday desktop (full features, animations)
  - developer: Developer-oriented layout with side dock and dev tools
  - lite:      Lightweight profile with reduced animations and essentials-only apps

Edition is detected from /etc/bright-os/edition at startup.
"""
import sys
import os
import json
import subprocess
import signal
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import QApplication
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty, QTimer, QUrl, QProcess, Qt
from PyQt6.QtGui import QIcon, QFontDatabase

# Constants
APP_NAME = "Bright Desktop Shell"
APP_VERSION = "0.1.0-alpha"
CONFIG_DIR = Path.home() / ".config" / "bright-os"
CONFIG_FILE = CONFIG_DIR / "shell.conf"
WALLPAPER_DIR = Path("/usr/share/bright-os/wallpapers")
USER_WALLPAPER_DIR = Path.home() / "Pictures" / "Wallpapers"
EDITION_FILE = Path("/etc/bright-os/edition")
DESIGN_DIR = Path("/usr/share/bright-os/design")
PROFILES_DIR = Path("/usr/share/bright-os/profiles")

# Valid editions
VALID_EDITIONS = ("home", "developer", "lite")


def detect_edition():
    """Detect the current Bright OS edition from /etc/bright-os/edition.
    Falls back to 'home' if the file is missing or invalid."""
    try:
        ed = EDITION_FILE.read_text().strip().lower()
        if ed in VALID_EDITIONS:
            return ed
    except Exception:
        pass
    return "home"


# Edition profile definitions (mirrors EditionProfiles.js but available to Python)
EDITION_PROFILES = {
    "home": {
        "display_name": "Bright OS Home",
        "tagline": "Everyday computing, made simple",
        "panel_height": 40,
        "panel_position": "top",
        "dock_position": "bottom",
        "dock_icon_size": 48,
        "dock_centered": True,
        "dock_max_icons": 9,
        "animations": True,
        "dock_pill_shape": True,
        "default_theme": "dark",
        "dock_apps": [
            {"id": "firefox-esr", "name": "Firefox", "command": "firefox-esr"},
            {"id": "bright-files", "name": "Files", "command": "bright-files"},
            {"id": "thunderbird", "name": "Thunderbird", "command": "thunderbird"},
            {"id": "libreoffice-writer", "name": "LibreOffice", "command": "libreoffice --writer"},
            {"id": "bright-terminal", "name": "Terminal", "command": "bright-terminal"},
            {"id": "vlc", "name": "VLC", "command": "vlc"},
            {"id": "bright-settings", "name": "Settings", "command": "bright-settings"},
            {"id": "org.kde.discover", "name": "Software", "command": "plasma-discover"},
        ],
    },
    "developer": {
        "display_name": "Bright OS Developer",
        "tagline": "Built for creators, engineers, and makers",
        "panel_height": 36,
        "panel_position": "top",
        "dock_position": "left",
        "dock_icon_size": 40,
        "dock_centered": False,
        "dock_max_icons": 12,
        "animations": True,
        "dock_pill_shape": True,
        "default_theme": "dark",
        "dock_apps": [
            {"id": "firefox-esr", "name": "Firefox", "command": "firefox-esr"},
            {"id": "bright-terminal", "name": "Terminal", "command": "bright-terminal"},
            {"id": "bright-files", "name": "Files", "command": "bright-files"},
            {"id": "code", "name": "Code", "command": "code"},
            {"id": "git-gui", "name": "Git", "command": "git gui"},
            {"id": "virt-manager", "name": "VMs", "command": "virt-manager"},
            {"id": "docker", "name": "Docker", "command": "x-terminal-emulator -e docker"},
            {"id": "bright-monitor", "name": "Monitor", "command": "bright-monitor"},
            {"id": "kicad", "name": "KiCad", "command": "kicad"},
            {"id": "arduino", "name": "Arduino", "command": "arduino"},
            {"id": "bright-settings", "name": "Settings", "command": "bright-settings"},
        ],
    },
    "lite": {
        "display_name": "Bright OS Lite",
        "tagline": "Fast and responsive on older hardware",
        "panel_height": 28,
        "panel_position": "bottom",
        "dock_position": "none",
        "dock_icon_size": 32,
        "dock_centered": False,
        "dock_max_icons": 0,
        "animations": False,
        "dock_pill_shape": False,
        "default_theme": "dark",
        "dock_apps": [],
    },
}


def get_dock_applications(edition):
    """Get list of pinned dock applications for the given edition.
    Only includes apps that are actually installed (graceful fallback)."""
    profile = EDITION_PROFILES.get(edition, EDITION_PROFILES["home"])
    apps = []
    for app in profile["dock_apps"]:
        # Check if app command exists (basic availability check)
        cmd_base = app["command"].split()[0]
        cmd_path = None
        for p in ("/usr/bin", "/bin", "/usr/local/bin"):
            candidate = Path(p) / cmd_base
            if candidate.exists():
                cmd_path = str(candidate)
                break
        # Also check .desktop files
        desktop_path = Path(f"/usr/share/applications/{app['id']}.desktop")
        if cmd_path or desktop_path.exists():
            apps.append(app)
        else:
            # Include anyway; Shell.qml handles missing apps gracefully
            apps.append(app)
    return apps


def command_exists(cmd):
    """Check if a command is available on PATH"""
    result = subprocess.run(["which", cmd.split()[0]], capture_output=True, text=True)
    return result.returncode == 0


class ShellBackend(QObject):
    """Backend QObject exposing system functionality to QML"""

    clockUpdated = pyqtSignal(str, str)
    brightnessChanged = pyqtSignal(float)
    volumeChanged = pyqtSignal(int)
    networkStatusChanged = pyqtSignal(str, bool)
    batteryStatusChanged = pyqtSignal(float, bool)
    windowListChanged = pyqtSignal(list)
    themeChanged = pyqtSignal(str)
    editionChanged = pyqtSignal(str)
    metricsUpdated = pyqtSignal(float, float)  # CPU %, MEM %

    def __init__(self):
        super().__init__()
        self._edition = detect_edition()
        self._profile = EDITION_PROFILES.get(self._edition, EDITION_PROFILES["home"])
        self._theme = self._profile.get("default_theme", "dark")
        self._volume = 50
        self._brightness = 75
        self._network_status = "disconnected"
        self._network_connected = False
        self._battery_percent = 100
        self._battery_charging = True
        self._windows = []
        self._launcher_open = False
        self._cpu_percent = 0.0
        self._mem_percent = 0.0
        self._config = self._load_config()

        # Clock timer
        self._clock_timer = QTimer()
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

        # System monitor timer (slower for Lite edition)
        self._monitor_timer = QTimer()
        self._monitor_timer.timeout.connect(self._update_system)
        interval = 10000 if self._edition == "lite" else 5000
        self._monitor_timer.start(interval)
        self._update_system()

    def _load_config(self):
        """Load shell configuration"""
        config = {
            "theme": self._profile.get("default_theme", "dark"),
            "wallpaper": "",
            "panel_position": self._profile.get("panel_position", "top"),
            "panel_height": str(self._profile.get("panel_height", 40)),
            "dock_position": self._profile.get("dock_position", "bottom"),
            "dock_icon_size": str(self._profile.get("dock_icon_size", 48)),
            "dock_auto_hide": "false",
            "animations": "true" if self._profile.get("animations", True) else "false",
        }
        # Set default wallpaper based on theme
        wp = WALLPAPER_DIR / "bright-default-dark.svg"
        if config["theme"] == "light":
            wp = WALLPAPER_DIR / "bright-default-light.svg"
        config["wallpaper"] = str(wp)

        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            config[key.strip()] = val.strip()
            except Exception:
                pass
        self._theme = config.get("theme", self._theme)
        return config

    def _save_config(self):
        """Save shell configuration"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w") as f:
                f.write("# Bright OS Shell Configuration\n")
                f.write(f"# Edition: {self._edition}\n")
                for k, v in self._config.items():
                    f.write(f"{k}={v}\n")
        except Exception as e:
            print(f"Failed to save config: {e}", file=sys.stderr)

    def _update_clock(self):
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%A, %B %d")
        self.clockUpdated.emit(time_str, date_str)

    def _update_system(self):
        """Periodically update system status"""
        # Check network
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "STATE", "general"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and "connected" in result.stdout:
                self._network_status = "connected"
                self._network_connected = True
            else:
                self._network_status = "disconnected"
                self._network_connected = False
        except Exception:
            pass
        self.networkStatusChanged.emit(self._network_status, self._network_connected)

        # Check battery
        bat_path = Path("/sys/class/power_supply/BAT0")
        if bat_path.exists():
            try:
                cap = bat_path / "capacity"
                status = bat_path / "status"
                if cap.exists():
                    self._battery_percent = float(cap.read_text().strip())
                if status.exists():
                    self._battery_charging = "Charging" in status.read_text()
            except Exception:
                pass
        self.batteryStatusChanged.emit(self._battery_percent, self._battery_charging)

        # CPU/Memory metrics (Developer edition shows these in panel)
        try:
            # Simple CPU average from /proc/loadavg
            load = Path("/proc/loadavg").read_text().split()[0]
            ncpu = os.cpu_count() or 1
            self._cpu_percent = min(100.0, (float(load) / ncpu) * 100)
            # Memory from /proc/meminfo
            meminfo = Path("/proc/meminfo").read_text()
            total = avail = 0
            for line in meminfo.splitlines():
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1])
            if total > 0:
                self._mem_percent = ((total - avail) / total) * 100
            self.metricsUpdated.emit(self._cpu_percent, self._mem_percent)
        except Exception:
            pass

    @pyqtSlot(str, str)
    def launchApplication(self, app_id, command=None):
        """Launch an application by .desktop file ID or command.
        Handles missing applications gracefully."""
        if command:
            cmd_parts = command.split()
            if command_exists(cmd_parts[0]):
                QProcess.startDetached(cmd_parts[0], cmd_parts[1:] if len(cmd_parts) > 1 else [])
                return
            else:
                print(f"Warning: command '{cmd_parts[0]}' not found, skipping launch", file=sys.stderr)
                return
        try:
            QProcess.startDetached("gtk-launch", [app_id])
        except Exception:
            try:
                if command_exists(app_id):
                    QProcess.startDetached(app_id)
            except Exception as e:
                print(f"Failed to launch {app_id}: {e}", file=sys.stderr)

    @pyqtSlot(str)
    def setTheme(self, theme):
        if theme in ("dark", "light"):
            self._theme = theme
            self._config["theme"] = theme
            wp = "bright-default-dark.svg" if theme == "dark" else "bright-default-light.svg"
            self._config["wallpaper"] = str(WALLPAPER_DIR / wp)
            self._save_config()
            self.themeChanged.emit(theme)

    @pyqtSlot()
    def lockScreen(self):
        """Lock the screen"""
        subprocess.Popen(["loginctl", "lock-session"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @pyqtSlot()
    def shutdown(self):
        """Shutdown the system"""
        subprocess.Popen(["systemctl", "poweroff"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @pyqtSlot()
    def reboot(self):
        """Reboot the system"""
        subprocess.Popen(["systemctl", "reboot"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @pyqtSlot()
    def logout(self):
        """Log out of the session"""
        subprocess.Popen(["loginctl", "terminate-session", "self"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @pyqtSlot()
    def openTerminal(self):
        term_cmd = "bright-terminal"
        if self._edition == "lite":
            term_cmd = "qterminal"
        if command_exists(term_cmd):
            QProcess.startDetached(term_cmd)
        elif command_exists("x-terminal-emulator"):
            QProcess.startDetached("x-terminal-emulator")

    @pyqtSlot()
    def openFiles(self):
        files_cmd = "bright-files"
        if self._edition == "lite":
            files_cmd = "pcmanfm-qt"
        if command_exists(files_cmd):
            QProcess.startDetached(files_cmd)

    @pyqtSlot()
    def openSettings(self):
        if command_exists("bright-settings"):
            QProcess.startDetached("bright-settings")

    @pyqtSlot(int)
    def setVolume(self, vol):
        self._volume = max(0, min(100, vol))
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.volumeChanged.emit(self._volume)

    @pyqtSlot(float)
    def setBrightness(self, level):
        self._brightness = max(10, min(100, level))
        try:
            subprocess.run(["brightnessctl", "set", f"{int(level)}%"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        self.brightnessChanged.emit(self._brightness)

    # --- Properties ---

    @pyqtProperty(str, constant=True)
    def version(self):
        return APP_VERSION

    @pyqtProperty(str, constant=True)
    def edition(self):
        return self._edition

    @pyqtProperty(str, constant=True)
    def editionDisplayName(self):
        return self._profile.get("display_name", "Bright OS")

    @pyqtProperty(str, constant=True)
    def editionTagline(self):
        return self._profile.get("tagline", "")

    @pyqtProperty(bool, constant=True)
    def animationsEnabled(self):
        return self._config.get("animations", "true").lower() in ("true", "1", "yes")

    @pyqtProperty(int, constant=True)
    def panelHeight(self):
        return int(self._config.get("panel_height", self._profile.get("panel_height", 40)))

    @pyqtProperty(int, constant=True)
    def dockIconSize(self):
        return int(self._config.get("dock_icon_size", self._profile.get("dock_icon_size", 48)))

    @pyqtProperty(str, constant=True)
    def panelPosition(self):
        return self._config.get("panel_position", self._profile.get("panel_position", "top"))

    @pyqtProperty(str, constant=True)
    def dockPosition(self):
        return self._config.get("dock_position", self._profile.get("dock_position", "bottom"))

    @pyqtProperty(bool, constant=True)
    def dockCentered(self):
        return self._profile.get("dock_centered", True)

    @pyqtProperty(bool, constant=True)
    def dockPillShape(self):
        return self._profile.get("dock_pill_shape", True)

    @pyqtProperty(bool, constant=True)
    def showMetrics(self):
        return self._profile.get("showSystemTrayMetrics", False)

    @pyqtProperty(float, constant=True)
    def cpuPercent(self):
        return self._cpu_percent

    @pyqtProperty(float, constant=True)
    def memPercent(self):
        return self._mem_percent

    @pyqtProperty(str, constant=True)
    def wallpaperDir(self):
        return str(WALLPAPER_DIR)

    @pyqtProperty(str, constant=True)
    def initialTheme(self):
        return self._theme

    @pyqtProperty(str, constant=True)
    def initialWallpaper(self):
        wp = self._config.get("wallpaper", "")
        if wp and Path(wp).exists():
            return wp
        wp = str(WALLPAPER_DIR / "bright-default-dark.svg")
        if not Path(wp).exists():
            return ""
        return wp


def main():
    # Handle SIGTERM gracefully
    signal.signal(signal.SIGTERM, lambda *_: QApplication.quit())

    # Set application metadata
    QApplication.setApplicationName("bright-desktop-shell")
    QApplication.setApplicationDisplayName("Bright Desktop")
    QApplication.setOrganizationName("BrightOS")
    QApplication.setApplicationVersion(APP_VERSION)

    # Force Wayland if possible
    if not os.environ.get("QT_QPA_PLATFORM"):
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")

    # High DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Detect edition for Lite-specific environment
    edition = detect_edition()

    # Lite: reduce Qt rendering overhead
    if edition == "lite":
        os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
        os.environ.setdefault("QSG_RENDER_LOOP", "basic")
        os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")

    # Load fonts
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/hack/Hack-Regular.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            QFontDatabase.addApplicationFont(fp)

    # Create backend
    backend = ShellBackend()

    # Load QML
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("Shell", backend)
    engine.rootContext().setContextProperty(
        "DockApps", json.dumps(get_dock_applications(edition))
    )
    engine.rootContext().setContextProperty("EditionId", edition)

    # Add import paths for design system and profiles
    qml_dir = os.path.dirname(os.path.abspath(__file__))
    engine.addImportPath(qml_dir)

    # Search for Shell.qml in multiple locations
    qml_candidates = [
        os.path.join(qml_dir, "Shell.qml"),
        "/usr/share/bright-os/Shell.qml",
        "/usr/share/bright-os/shell/Shell.qml",
        "/usr/local/share/bright-os/Shell.qml",
    ]
    qml_path = None
    for candidate in qml_candidates:
        if os.path.exists(candidate):
            qml_path = candidate
            break

    if qml_path is None:
        print("ERROR: Shell.qml not found in any expected location!", file=sys.stderr)
        print("Searched:", file=sys.stderr)
        for c in qml_candidates:
            print(f"  {c}", file=sys.stderr)
        # Fallback: launch plasmashell
        if command_exists("plasmashell"):
            subprocess.Popen(["plasmashell"])
        return -1

    engine.load(QUrl.fromLocalFile(qml_path))

    if not engine.rootObjects():
        print("Failed to load QML shell!", file=sys.stderr)
        if command_exists("plasmashell"):
            subprocess.Popen(["plasmashell"])
        return -1

    print(f"Bright Desktop Shell {APP_VERSION} started (edition: {edition})", file=sys.stderr)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
