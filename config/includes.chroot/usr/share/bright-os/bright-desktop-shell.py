#!/usr/bin/env python3
"""
Bright Desktop Shell - Main compositor shell for Bright OS
Provides panel, dock, wallpaper, window management, and launcher integration.

This is the primary shell entry point for Bright Desktop.
It uses KWin as the Wayland compositor and provides the panel and dock UI.
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


class ShellBackend(QObject):
    """Backend QObject exposing system functionality to QML"""
    
    clockUpdated = pyqtSignal(str, str)
    brightnessChanged = pyqtSignal(float)
    volumeChanged = pyqtSignal(int)
    networkStatusChanged = pyqtSignal(str, bool)
    batteryStatusChanged = pyqtSignal(float, bool)
    windowListChanged = pyqtSignal(list)
    themeChanged = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._theme = "dark"
        self._volume = 50
        self._brightness = 75
        self._network_status = "disconnected"
        self._network_connected = False
        self._battery_percent = 100
        self._battery_charging = True
        self._windows = []
        self._launcher_open = False
        self._config = self._load_config()
        
        # Clock timer
        self._clock_timer = QTimer()
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()
        
        # System monitor timer
        self._monitor_timer = QTimer()
        self._monitor_timer.timeout.connect(self._update_system)
        self._monitor_timer.start(5000)
        self._update_system()
    
    def _load_config(self):
        """Load shell configuration"""
        config = {
            "theme": "dark",
            "wallpaper": "/usr/share/bright-os/wallpapers/bright-default-dark.svg",
            "panel_position": "top",
            "panel_height": 40,
            "dock_position": "bottom",
            "dock_icon_size": 48,
            "dock_auto_hide": False,
            "animations": True
        }
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
        self._theme = config.get("theme", "dark")
        return config
    
    def _save_config(self):
        """Save shell configuration"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w") as f:
                f.write("# Bright OS Shell Configuration\n")
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
    
    @pyqtSlot(str, str)
    def launchApplication(self, app_id, command=None):
        """Launch an application by .desktop file ID or command"""
        if command:
            QProcess.startDetached(command)
            return
        try:
            QProcess.startDetached("gtk-launch", [app_id])
        except Exception:
            try:
                QProcess.startDetached(app_id)
            except Exception as e:
                print(f"Failed to launch {app_id}: {e}", file=sys.stderr)
    
    @pyqtSlot()
    def showLauncher(self):
        """Toggle the application launcher"""
        # Signal QML to show launcher
        pass
    
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
        QProcess.startDetached("bright-terminal")
    
    @pyqtSlot()
    def openFiles(self):
        QProcess.startDetached("bright-files")
    
    @pyqtSlot()
    def openSettings(self):
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
        # Try to set via brightnessctl or direct sysfs
        try:
            subprocess.run(["brightnessctl", "set", f"{int(level)}%"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        self.brightnessChanged.emit(self._brightness)
    
    @pyqtProperty(str, constant=True)
    def version(self):
        return APP_VERSION
    
    @pyqtProperty(str, constant=True)
    def wallpaperDir(self):
        return str(WALLPAPER_DIR)
    
    @pyqtProperty(str, constant=True)
    def initialTheme(self):
        return self._theme
    
    @pyqtProperty(str, constant=True)
    def initialWallpaper(self):
        wp = self._config.get("wallpaper", str(WALLPAPER_DIR / "bright-default-dark.svg"))
        if not Path(wp).exists():
            wp = str(WALLPAPER_DIR / "bright-default-dark.svg")
        return wp
    
    @pyqtProperty(int, constant=True)
    def panelHeight(self):
        return int(self._config.get("panel_height", 40))
    
    @pyqtProperty(int, constant=True)
    def dockIconSize(self):
        return int(self._config.get("dock_icon_size", 48))
    
    @pyqtProperty(bool, constant=True)
    def animationsEnabled(self):
        return self._config.get("animations", "True").lower() in ("true", "1", "yes")


def get_dock_applications():
    """Get list of pinned dock applications"""
    return [
        {"id": "firefox-esr", "name": "Firefox", "icon": "firefox", "command": "firefox-esr"},
        {"id": "bright-files", "name": "Files", "icon": "system-file-manager", "command": "bright-files"},
        {"id": "bright-terminal", "name": "Terminal", "icon": "utilities-terminal", "command": "bright-terminal"},
        {"id": "bright-settings", "name": "Settings", "icon": "preferences-system", "command": "bright-settings"},
        {"id": "org.kde.discover", "name": "Software Center", "icon": "system-software-install", "command": "plasma-discover"},
        {"id": "libreoffice-writer", "name": "LibreOffice Writer", "icon": "libreoffice-writer", "command": "libreoffice --writer"},
        {"id": "vlc", "name": "VLC", "icon": "vlc", "command": "vlc"},
        {"id": "bright-monitor", "name": "System Monitor", "icon": "utilities-system-monitor", "command": "bright-monitor"},
    ]


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
        "DockApps", json.dumps(get_dock_applications())
    )
    
    # Search for Shell.qml in multiple locations
    qml_candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "Shell.qml"),
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
        subprocess.Popen(["plasmashell"])
        return -1
    
    engine.load(QUrl.fromLocalFile(qml_path))
    
    if not engine.rootObjects():
        print("Failed to load QML shell!", file=sys.stderr)
        # Fallback: launch a basic plasmashell
        subprocess.Popen(["plasmashell"])
        return -1
    
    # Register dock app list model
    from PyQt6.QtCore import QJsonDocument, QJsonParseError
    doc = QJsonDocument.fromJson(get_dock_applications().__repr__().encode())
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
