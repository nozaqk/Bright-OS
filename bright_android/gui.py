#!/usr/bin/env python3
"""
Bright Android - Android application management for Bright OS

A native PyQt6 interface for managing the Waydroid-based Android runtime.
Provides Home, Applications, and Settings pages.
"""
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QLabel, QPushButton,
    QGroupBox, QFormLayout, QCheckBox, QProgressBar, QMessageBox,
    QScrollArea, QFrame, QGridLayout, QFileDialog, QLineEdit,
    QComboBox, QSpinBox, QTextEdit, QSizePolicy, QSplitter, QToolButton,
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QFont, QColor

APP_NAME = "Bright Android"
APP_VERSION = "0.1.0-alpha"

# Color scheme consistent with Bright OS design
DARK_STYLE = """
QMainWindow, QWidget { background: #0f172a; color: #e2e8f0; font-size: 13px; }
QListWidget { background: #1e293b; border: none; border-radius: 0; padding: 8px; outline: none; }
QListWidget::item { padding: 10px 12px; border-radius: 8px; margin-bottom: 2px; color: #cbd5e1; }
QListWidget::item:selected { background: #3b82f6; color: white; }
QListWidget::item:hover { background: #334155; }
QGroupBox { border: 1px solid #334155; border-radius: 10px; margin-top: 16px; padding: 16px; font-weight: bold; font-size: 14px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; color: #94a3b8; }
QPushButton { background: #3b82f6; color: white; border: none; border-radius: 8px; padding: 8px 16px; font-weight: 500; }
QPushButton:hover { background: #2563eb; }
QPushButton:pressed { background: #1d4ed8; }
QPushButton:disabled { background: #334155; color: #64748b; }
QPushButton#dangerBtn { background: #ef4444; }
QPushButton#dangerBtn:hover { background: #dc2626; }
QPushButton#secondaryBtn { background: transparent; color: #94a3b8; border: 1px solid #334155; }
QPushButton#secondaryBtn:hover { background: #334155; color: #e2e8f0; }
QPushButton#successBtn { background: #22c55e; }
QPushButton#successBtn:hover { background: #16a34a; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 2px solid #475569; background: #1e293b; }
QCheckBox::indicator:checked { background: #3b82f6; border-color: #3b82f6; }
QSpinBox, QComboBox { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px; padding: 6px 12px; }
QComboBox QAbstractItemView { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; selection-background-color: #3b82f6; }
QLineEdit { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px; padding: 6px 12px; }
QProgressBar { background: #1e293b; border: none; border-radius: 8px; text-align: center; height: 20px; }
QProgressBar::chunk { background: #3b82f6; border-radius: 8px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #0f172a; width: 8px; }
QScrollBar::handle:vertical { background: #334155; border-radius: 4px; }
QTextEdit { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px; font-family: 'Hack', 'Fira Code', monospace; font-size: 12px; padding: 8px; }
QLabel#title { font-size: 22px; font-weight: bold; color: #f1f5f9; }
QLabel#subtitle { color: #64748b; font-size: 13px; margin-bottom: 16px; }
QLabel#statusOk { color: #22c55e; font-weight: bold; }
QLabel#statusErr { color: #ef4444; font-weight: bold; }
QLabel#statusWarn { color: #f59e0b; font-weight: bold; }
QFrame#card { background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; }
"""

# Status icons
STATUS_RUNNING = "🟢 Running"
STATUS_STOPPED = "🔴 Stopped"
STATUS_NOT_INSTALLED = "⚪ Not installed"
STATUS_INITIALIZING = "🟡 Setting up..."


class StatusWorker(QThread):
    """Background worker for running waydroid operations that
    may take time (init, start, stop, APK install)."""
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str)

    def __init__(self, func, *args, op_name="Operation", **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.op_name = op_name

    def run(self):
        try:
            kwargs = dict(self.kwargs)
            kwargs["progress_cb"] = lambda msg: self.progress.emit(msg)
            self.func(*self.args, **kwargs)
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class StatusRefreshWorker(QThread):
    """Background worker for GUI status refreshes.

    Runs all the heavyweight checks (kernel, disk, waydroid status, app list)
    off the GUI thread. Returns a dict with compat report, runtime status,
    and app list. Short-lived caching in waydroid_manager avoids duplicate
    subprocess calls if other UI pages request the same state.
    """
    finished = pyqtSignal(dict)

    def run(self):
        try:
            from bright_android.core import waydroid_manager, compatibility
            compat = compatibility.run_full_check()
            runtime = {"running": False, "starting": False, "session": "STOPPED"}
            apps = []
            if compat.get("packages", {}).get("waydroid_installed"):
                try:
                    runtime = waydroid_manager.get_status()
                except Exception:
                    runtime = compat.get("runtime", runtime)
                if runtime.get("running"):
                    try:
                        apps = waydroid_manager.list_apps()
                    except Exception:
                        apps = []
            self.finished.emit({"compat": compat, "runtime": runtime, "apps": apps})
        except Exception as e:
            self.finished.emit({"error": str(e), "compat": {}, "runtime": {}, "apps": []})


class AppListWorker(QThread):
    """Background worker for fetching the installed-app list."""
    finished = pyqtSignal(bool, list, str)  # running, apps, error

    def run(self):
        try:
            from bright_android.core import waydroid_manager
            if not waydroid_manager.is_running():
                self.finished.emit(False, [], "")
                return
            apps = waydroid_manager.list_apps()
            self.finished.emit(True, apps, "")
        except Exception as e:
            self.finished.emit(False, [], str(e))


class HomePage(QWidget):
    """Android Home: status, controls, installed apps overview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(32, 24, 32, 24)
        self.layout.setSpacing(16)

        title = QLabel("Android Home")
        title.setObjectName("title")
        self.layout.addWidget(title)

        desc = QLabel("Manage the Android runtime and view installed applications")
        desc.setObjectName("subtitle")
        self.layout.addWidget(desc)

        # Status card
        self.status_card = QGroupBox("System Status")
        sl = QFormLayout(self.status_card)

        self.status_label = QLabel("Checking...")
        self.status_label.setObjectName("statusWarn")
        sl.addRow("Status:", self.status_label)

        self.version_label = QLabel("-")
        sl.addRow("Version:", self.version_label)

        self.edition_label = QLabel(self._detect_edition())
        sl.addRow("Edition:", self.edition_label)

        self.ram_label = QLabel("-")
        sl.addRow("Memory:", self.ram_label)

        self.storage_label = QLabel("-")
        sl.addRow("Storage:", self.storage_label)

        self.layout.addWidget(self.status_card)

        # Controls
        ctrl_group = QGroupBox("Controls")
        cl = QHBoxLayout(ctrl_group)

        self.start_btn = QPushButton("▶  Start Android")
        self.start_btn.clicked.connect(self.start_android)
        cl.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹  Stop Android")
        self.stop_btn.setObjectName("dangerBtn")
        self.stop_btn.clicked.connect(self.stop_android)
        cl.addWidget(self.stop_btn)

        self.init_btn = QPushButton("📥  Initialize Runtime")
        self.init_btn.setObjectName("successBtn")
        self.init_btn.clicked.connect(self.init_android)
        cl.addWidget(self.init_btn)

        self.refresh_btn = QPushButton("↻  Refresh")
        self.refresh_btn.setObjectName("secondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_status)
        cl.addWidget(self.refresh_btn)

        self.layout.addWidget(ctrl_group)

        # Progress bar for long operations
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.progress_label.setVisible(False)
        self.layout.addWidget(self.progress_label)

        # Installed apps overview
        apps_group = QGroupBox("Installed Applications")
        al = QVBoxLayout(apps_group)
        self.apps_count_label = QLabel("No applications installed")
        self.apps_count_label.setStyleSheet("color: #94a3b8;")
        al.addWidget(self.apps_count_label)
        self.apps_list_label = QLabel("")
        self.apps_list_label.setWordWrap(True)
        self.apps_list_label.setStyleSheet("color: #64748b; font-size: 12px;")
        al.addWidget(self.apps_list_label)
        self.layout.addWidget(apps_group)

        self.layout.addStretch()

        # Auto-refresh timer (every 10s — long enough to avoid hammering
        # subprocess calls; waydroid_manager has a 3s TTL status cache too)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_status)
        self.refresh_timer.start(10000)

        self._refresh_worker = None
        self.refresh_status()

    def _detect_edition(self) -> str:
        try:
            with open("/etc/bright-os/edition") as f:
                ed = f.read().strip().lower()
                return {"lite": "Lite", "home": "Home", "developer": "Developer"}.get(ed, ed.title())
        except Exception:
            return "Home"

    def refresh_status(self):
        """Trigger an async status refresh (never blocks the GUI thread).

        Heavy checks (kernel config, mount parsing, waydroid status command,
        app listing) all run on a background thread; results are applied
        when done. Short-lived caching in waydroid_manager prevents
        duplicate subprocess calls.
        """
        # Don't overlap a refresh if one is already running
        if hasattr(self, "_refresh_worker") and self._refresh_worker is not None:
            if self._refresh_worker.isRunning():
                return
        self._refresh_worker = StatusRefreshWorker()
        self._refresh_worker.finished.connect(self._apply_status)
        self._refresh_worker.start()

    def _apply_status(self, data):
        """Apply results of the async status refresh."""
        compat = data.get("compat", {})
        runtime = data.get("runtime", {})
        apps = data.get("apps", [])
        error = data.get("error", "")

        if error:
            self.status_label.setText(f"⚠️ Error: {error}")
            self.status_label.setObjectName("statusErr")

        packages = compat.get("packages", {})
        initialized = compat.get("initialized", {})
        ram = compat.get("ram", {})
        disk = compat.get("disk", {})
        hw = compat.get("hardware_readiness", {})

        installed = packages.get("waydroid_installed", False)
        is_init = initialized.get("initialized", False)
        running = runtime.get("running", False)
        starting = runtime.get("starting", False)
        version = packages.get("waydroid_version", "")

        if not installed:
            self.status_label.setText(STATUS_NOT_INSTALLED)
            self.status_label.setObjectName("statusErr")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.init_btn.setEnabled(False)
            self.version_label.setText("Not installed (sudo apt install waydroid)")
        elif not is_init:
            self.status_label.setText("⚪ Not initialized")
            self.status_label.setObjectName("statusWarn")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.init_btn.setEnabled(True)
            self.version_label.setText(version or "-")
        elif starting:
            self.status_label.setText(STATUS_INITIALIZING)
            self.status_label.setObjectName("statusWarn")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.init_btn.setEnabled(False)
            self.version_label.setText(version or "-")
        elif running:
            self.status_label.setText(STATUS_RUNNING)
            self.status_label.setObjectName("statusOk")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.init_btn.setEnabled(False)
            self.version_label.setText(version or "-")
        else:
            self.status_label.setText(STATUS_STOPPED)
            self.status_label.setObjectName("statusErr")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.init_btn.setEnabled(False)
            self.version_label.setText(version or "-")

        # Resource info
        total_ram = ram.get("total_mb", 0)
        avail_disk = disk.get("available_gb", 0)
        self.ram_label.setText(f"{total_ram} MB" + ("  ⚠️" if ram.get("low_resource") else ""))
        self.storage_label.setText(f"{avail_disk} GB available")

        # Hardware-readiness warnings (prominent for 8 GB systems)
        warning_text = ""
        if hw.get("status") == "supported_with_limitations":
            w = hw.get("warnings", [])
            if w:
                warning_text = w[0]
        elif hw.get("status") == "unsupported":
            b = hw.get("blockers", [])
            if b:
                warning_text = "Blocked: " + b[0]

        # App count (only valid when running)
        if running:
            self.apps_count_label.setText(f"{len(apps)} application(s) installed")
            if apps:
                names = ", ".join(a["name"] for a in apps[:10])
                if len(apps) > 10:
                    names += f" … and {len(apps) - 10} more"
                self.apps_list_label.setText(names)
            else:
                self.apps_list_label.setText("No Android applications installed yet")
        elif is_init and not running:
            self.apps_count_label.setText("Start Android to view applications")
            self.apps_list_label.setText(warning_text or "")
        elif not is_init and installed:
            self.apps_count_label.setText("Initialize Android to install applications")
            self.apps_list_label.setText(warning_text or "")
        else:
            self.apps_count_label.setText("Install Waydroid to enable Android support")
            self.apps_list_label.setText(warning_text or "")

        # Update warning style
        if warning_text and "Blocked" in warning_text:
            self.apps_list_label.setStyleSheet("color: #ef4444; font-size: 12px;")
        elif warning_text:
            self.apps_list_label.setStyleSheet("color: #f59e0b; font-size: 12px;")
        else:
            self.apps_list_label.setStyleSheet("color: #64748b; font-size: 12px;")

        # Force style refresh on status label
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self._refresh_worker = None

    def _run_worker(self, func, *args, op_name="Operation", **kwargs):
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress_label.setText(f"{op_name}...")
        self.setEnabled(False)

        self.worker = StatusWorker(func, *args, op_name=op_name, **kwargs)
        self.worker.progress.connect(lambda msg: self.progress_label.setText(msg))
        self.worker.finished.connect(self._on_worker_done)
        self.worker.start()

    def _on_worker_done(self, success, error):
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.setEnabled(True)
        if not success:
            QMessageBox.critical(self, "Operation Failed", error)
        self.refresh_status()

    def start_android(self):
        from bright_android.core.service_client import BrightAndroidClient
        self._run_worker(BrightAndroidClient().start_runtime, op_name="Starting Android")

    def stop_android(self):
        from bright_android.core.service_client import BrightAndroidClient
        self._run_worker(BrightAndroidClient().stop_runtime, op_name="Stopping Android")

    def init_android(self):
        reply = QMessageBox.question(
            self, "Initialize Android Runtime",
            "This will download and set up the Android system image (~400-700 MB).\n"
            "This requires administrator privileges and an internet connection.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            # The service authorizes initialization (Polkit admin) and waits for completion.
            from bright_android.core.service_client import BrightAndroidClient
            self._run_worker(BrightAndroidClient().initialize_runtime,
                            op_name="Initializing Android (downloading images)")


class ApplicationsPage(QWidget):
    """Android application management."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(32, 24, 32, 24)
        self.layout.setSpacing(16)

        title = QLabel("Android Applications")
        title.setObjectName("title")
        self.layout.addWidget(title)

        desc = QLabel("Install, launch and manage Android applications (APK files)")
        desc.setObjectName("subtitle")
        self.layout.addWidget(desc)

        # Install APK button
        btn_row = QHBoxLayout()
        install_btn = QPushButton("📦  Install APK...")
        install_btn.clicked.connect(self.install_apk)
        btn_row.addWidget(install_btn)

        refresh_btn = QPushButton("↻  Refresh")
        refresh_btn.setObjectName("secondaryBtn")
        refresh_btn.clicked.connect(self.refresh_apps)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        self.layout.addLayout(btn_row)

        # Compatibility note
        note = QLabel(
            "ℹ️  Bright Android runs on x86_64. Applications with only ARM native "
            "code will not run without additional translation libraries. "
            "Pure Java/Kotlin apps work universally."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #f59e0b; font-size: 12px; padding: 8px; border-radius: 6px; background: rgba(245,158,11,0.1);")
        self.layout.addWidget(note)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)

        # Apps list
        apps_group = QGroupBox("Installed Applications")
        self.apps_layout = QVBoxLayout(apps_group)
        self.apps_placeholder = QLabel("Start Android to view installed applications")
        self.apps_placeholder.setStyleSheet("color: #64748b; padding: 16px;")
        self.apps_layout.addWidget(self.apps_placeholder)
        self.layout.addWidget(apps_group)

        self.layout.addStretch()

        self._apps_refresh_worker = None

    def refresh_apps(self):
        """Refresh the app list (uses a short spinner to avoid freezing)."""
        self.apps_placeholder.setText("Loading applications...")
        if not hasattr(self, "_apps_refresh_worker") or self._apps_refresh_worker is None:
            self._apps_refresh_worker = AppListWorker()
            self._apps_refresh_worker.finished.connect(self._apply_app_list)
            self._apps_refresh_worker.start()

    def _apply_app_list(self, running, apps, error):
        self._apps_refresh_worker = None
        if error:
            self.apps_placeholder.setText(f"Error: {error}")
            return
        if not running:
            self.apps_placeholder.setText(
                "Start Android to view installed applications.\n"
                "Go to Android Home → ▶ Start Android"
            )
            # Clear existing widget list
            while self.apps_layout.count() > 1:
                item = self.apps_layout.takeAt(1)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    # Remove nested layouts
                    while item.layout().count():
                        c = item.layout().takeAt(0)
                        if c.widget():
                            c.widget().deleteLater()
            return

        # Clear existing
        while self.apps_layout.count():
            item = self.apps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    c = item.layout().takeAt(0)
                    if c.widget():
                        c.widget().deleteLater()

        if not apps:
            label = QLabel(
                "No Android applications installed.\n"
                "Use 'Install APK...' to add applications."
            )
            label.setStyleSheet("color: #64748b; padding: 16px;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.apps_layout.addWidget(label)
            return

        for app in apps:
            row = QHBoxLayout()
            name_label = QLabel(f"📱  {app['name']}")
            name_label.setStyleSheet("font-weight: bold; font-size: 14px;")
            row.addWidget(name_label, 2)

            pkg_label = QLabel(app["package"])
            pkg_label.setStyleSheet("color: #64748b; font-size: 11px; font-family: monospace;")
            row.addWidget(pkg_label, 3)

            launch_btn = QPushButton("Launch")
            launch_btn.setObjectName("secondaryBtn")
            launch_btn.clicked.connect(lambda checked, p=app["package"]: self.launch_app(p))
            row.addWidget(launch_btn)

            uninstall_btn = QPushButton("Uninstall")
            uninstall_btn.setObjectName("dangerBtn")
            uninstall_btn.clicked.connect(lambda checked, p=app["package"], n=app["name"]: self.uninstall_app(p, n))
            row.addWidget(uninstall_btn)

            self.apps_layout.addLayout(row)

    def install_apk(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select APK File", str(Path.home()),
            "Android Packages (*.apk);;All Files (*)"
        )
        if not path:
            return

        from bright_android.core import apk_validator
        compat = apk_validator.is_compatible_x86_64(path)
        info = apk_validator.get_app_info(path)

        msg = f"File: {Path(path).name}\n"
        msg += f"Size: {info['size_bytes'] // (1024*1024)} MB\n"
        msg += f"Architectures: {', '.join(compat['architectures'])}\n\n"
        msg += f"{compat['reason']}\n\n"

        if not compat["compatible"]:
            msg += "This APK may not work on x86_64 Android. Install anyway?"
            reply = QMessageBox.warning(
                self, "APK Compatibility Warning", msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        else:
            msg += "Install this application?"
            reply = QMessageBox.question(
                self, "Install APK", msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        from bright_android.core import waydroid_manager
        if not waydroid_manager.is_running():
            reply = QMessageBox.question(
                self, "Start Android",
                "Android runtime needs to be started before installing apps.\n"
                "Start it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.progress_bar.setVisible(True)
            self.setEnabled(False)
            from bright_android.core.service_client import BrightAndroidClient
            self.worker = StatusWorker(BrightAndroidClient().start_runtime,
                                      op_name="Starting Android...")
            # After start completes, chain to install
            self.worker.finished.connect(lambda ok, err: self._on_start_then_install(ok, err, path))
            self.worker.start()
            return

        self._do_install_apk(path)

    def _on_start_then_install(self, ok, err, apk_path):
        if not ok:
            self.progress_bar.setVisible(False)
            self.setEnabled(True)
            QMessageBox.critical(self, "Start Failed", f"Could not start Android: {err}")
            return
        self._do_install_apk(apk_path)

    def _do_install_apk(self, path):
        from bright_android.core.service_client import BrightAndroidClient
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.setEnabled(False)
        self.worker = StatusWorker(BrightAndroidClient().install_apk, path,
                                  op_name=f"Installing {Path(path).name}")
        self.worker.finished.connect(self._on_install_done)
        self.worker.start()

    def _on_install_done(self, success, error):
        self.progress_bar.setVisible(False)
        self.setEnabled(True)
        if success:
            QMessageBox.information(self, "Success", "Application installed successfully.")
        else:
            QMessageBox.critical(self, "Installation Failed", error)
        self.refresh_apps()

    def launch_app(self, package):
        from bright_android.core.service_client import BrightAndroidClient
        try:
            BrightAndroidClient().launch_app(package)
        except Exception as e:
            QMessageBox.critical(self, "Launch Failed", str(e))

    def uninstall_app(self, package, name):
        reply = QMessageBox.question(
            self, "Uninstall Application",
            f"Are you sure you want to uninstall '{name}' ({package})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from bright_android.core.service_client import BrightAndroidClient
        try:
            BrightAndroidClient().uninstall_app(package)
            QMessageBox.information(self, "Uninstalled", f"{name} has been uninstalled.")
        except Exception as e:
            QMessageBox.critical(self, "Uninstall Failed", str(e))
        self.refresh_apps()

    def showEvent(self, event):
        self.refresh_apps()
        super().showEvent(event)


class SettingsPage(QWidget):
    """Android settings: startup, storage, integration, developer options."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(32, 24, 32, 24)
        self.layout.setSpacing(16)

        title = QLabel("Android Settings")
        title.setObjectName("title")
        self.layout.addWidget(title)

        desc = QLabel("Configure Android runtime behavior and integration")
        desc.setObjectName("subtitle")
        self.layout.addWidget(desc)

        # Scroll area for all settings groups
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        # --- Startup ---
        startup_group = QGroupBox("Startup")
        sl = QVBoxLayout(startup_group)
        self.auto_start_cb = QCheckBox("Start Android automatically on login")
        sl.addWidget(self.auto_start_cb)
        self.on_demand_cb = QCheckBox("Start Android when an app is launched")
        self.on_demand_cb.setChecked(True)
        sl.addWidget(self.on_demand_cb)
        content_layout.addWidget(startup_group)

        # --- Integration ---
        integ_group = QGroupBox("Desktop Integration")
        il = QVBoxLayout(integ_group)
        self.clipboard_cb = QCheckBox("Share clipboard between desktop and Android")
        self.clipboard_cb.setChecked(True)
        il.addWidget(self.clipboard_cb)
        self.notifications_cb = QCheckBox("Forward Android notifications to desktop")
        self.notifications_cb.setChecked(True)
        il.addWidget(self.notifications_cb)
        self.app_integration_cb = QCheckBox("Show Android apps in launcher")
        self.app_integration_cb.setChecked(True)
        il.addWidget(self.app_integration_cb)
        self.freeform_cb = QCheckBox("Freeform window mode (multi-window apps)")
        self.freeform_cb.setChecked(True)
        il.addWidget(self.freeform_cb)
        content_layout.addWidget(integ_group)

        # --- Storage ---
        storage_group = QGroupBox("Shared Folders")
        stl = QVBoxLayout(storage_group)
        self.share_downloads_cb = QCheckBox("Downloads")
        self.share_downloads_cb.setChecked(True)
        stl.addWidget(self.share_downloads_cb)
        self.share_documents_cb = QCheckBox("Documents")
        stl.addWidget(self.share_documents_cb)
        self.share_pictures_cb = QCheckBox("Pictures")
        stl.addWidget(self.share_pictures_cb)
        content_layout.addWidget(storage_group)

        # --- Developer ---
        dev_group = QGroupBox("Developer Options")
        dl = QVBoxLayout(dev_group)
        self.adb_cb = QCheckBox("Enable ADB debugging (port 5555)")
        dl.addWidget(self.adb_cb)
        self.show_logs_cb = QCheckBox("Show runtime logs")
        dl.addWidget(self.show_logs_cb)
        self.nogpu_cb = QCheckBox("Disable GPU acceleration (software rendering)")
        dl.addWidget(self.nogpu_cb)

        logs_btn = QPushButton("View Runtime Logs")
        logs_btn.setObjectName("secondaryBtn")
        logs_btn.clicked.connect(self.show_logs)
        dl.addWidget(logs_btn)
        content_layout.addWidget(dev_group)

        # --- Danger zone ---
        danger_group = QGroupBox("Maintenance")
        dl2 = QVBoxLayout(danger_group)

        restart_btn = QPushButton("🔄  Restart Android Runtime")
        restart_btn.clicked.connect(self.restart_runtime)
        dl2.addWidget(restart_btn)

        reset_btn = QPushButton("🗑  Remove Android Data")
        reset_btn.setObjectName("dangerBtn")
        reset_btn.clicked.connect(self.remove_data)
        dl2.addWidget(reset_btn)

        uninstall_btn = QPushButton("⚠️  Uninstall Android Runtime")
        uninstall_btn.setObjectName("dangerBtn")
        uninstall_btn.clicked.connect(self.uninstall_runtime)
        dl2.addWidget(uninstall_btn)

        content_layout.addWidget(danger_group)

        content_layout.addStretch()
        scroll.setWidget(content)
        self.layout.addWidget(scroll)

        # Save button
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        self.layout.addWidget(save_btn)

        self.load_settings()

    def load_settings(self):
        from bright_android.core import config as ba_config
        self.auto_start_cb.setChecked(ba_config.get_bool("runtime", "auto_start", False))
        self.on_demand_cb.setChecked(ba_config.get_bool("runtime", "start_on_demand", True))
        self.clipboard_cb.setChecked(ba_config.get_bool("integration", "clipboard_share", True))
        self.notifications_cb.setChecked(ba_config.get_bool("integration", "notification_forward", True))
        self.app_integration_cb.setChecked(ba_config.get_bool("integration", "app_integration", True))
        self.freeform_cb.setChecked(ba_config.get_bool("appearance", "freeform_windows", True))
        self.share_downloads_cb.setChecked(ba_config.get_bool("storage", "shared_downloads", True))
        self.share_documents_cb.setChecked(ba_config.get_bool("storage", "shared_documents", False))
        self.share_pictures_cb.setChecked(ba_config.get_bool("storage", "shared_pictures", False))
        self.adb_cb.setChecked(ba_config.get_bool("developer", "adb_enabled", False))
        self.show_logs_cb.setChecked(ba_config.get_bool("developer", "show_logs", False))
        self.nogpu_cb.setChecked(ba_config.get_bool("developer", "nogpu_mode", False))

    def _setting_checkboxes(self):
        """(section, key, checkbox) for every setting this page controls."""
        return [
            ("runtime", "auto_start", self.auto_start_cb),
            ("runtime", "start_on_demand", self.on_demand_cb),
            ("integration", "clipboard_share", self.clipboard_cb),
            ("integration", "notification_forward", self.notifications_cb),
            ("integration", "app_integration", self.app_integration_cb),
            ("appearance", "freeform_windows", self.freeform_cb),
            ("storage", "shared_downloads", self.share_downloads_cb),
            ("storage", "shared_documents", self.share_documents_cb),
            ("storage", "shared_pictures", self.share_pictures_cb),
            ("developer", "adb_enabled", self.adb_cb),
            ("developer", "show_logs", self.show_logs_cb),
            ("developer", "nogpu_mode", self.nogpu_cb),
        ]

    def save_settings(self):
        from bright_android.core import config as ba_config
        # Send only changed values. Each SetConfig call is authorized by the
        # service, and a change may require an admin prompt.
        changes = []
        for section, key, checkbox in self._setting_checkboxes():
            want = checkbox.isChecked()
            current = ba_config.get_value(section, key, None)
            if current is None or (str(current).lower() == "true") != want:
                changes.append((f"{section}/{key}", want))
        if not changes:
            QMessageBox.information(self, "Settings Saved", "No changes to save.")
            return
        self.save_worker = StatusWorker(self._apply_settings, changes,
                                        op_name="Saving settings")
        self.save_worker.finished.connect(self._on_settings_saved)
        self.save_worker.start()

    def _apply_settings(self, changes, progress_cb=None):
        from bright_android.core.service_client import (
            BrightAndroidClient, BrightAndroidClientError,
        )
        client = BrightAndroidClient()
        done = 0
        for path, value in changes:
            try:
                client.set_config(path, value)
            except BrightAndroidClientError as e:
                raise BrightAndroidClientError(
                    f"Saved {done} of {len(changes)} changes. "
                    f"Failed on {path}: {e}") from e
            done += 1

    def _on_settings_saved(self, success, error):
        if success:
            QMessageBox.information(self, "Settings Saved", "Android settings have been saved.")
        else:
            QMessageBox.critical(self, "Settings Not Saved", error)

    def restart_runtime(self):
        reply = QMessageBox.question(
            self, "Restart Android", "Restart the Android runtime?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from bright_android.core import waydroid_manager
        from bright_android.core.service_client import BrightAndroidClient

        def restart(progress_cb=None):
            client = BrightAndroidClient()
            if waydroid_manager.is_running():  # read-only check
                client.stop_runtime()
            client.start_runtime()

        self.restart_worker = StatusWorker(restart, op_name="Restarting Android")
        self.restart_worker.finished.connect(self._on_restart_done)
        self.restart_worker.start()

    def _on_restart_done(self, success, error):
        if success:
            QMessageBox.information(self, "Restarted", "Android runtime restarted.")
        else:
            QMessageBox.critical(self, "Restart Failed", error)

    def remove_data(self):
        reply = QMessageBox.warning(
            self, "Remove Android Data",
            "This will delete ALL Android application data, including installed apps, "
            "photos, and settings inside Android.\n\n"
            "This action CANNOT be undone. Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        reply2 = QMessageBox.warning(
            self, "Confirm Deletion",
            "Type ERASE to confirm deletion of all Android data.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply2 != QMessageBox.StandardButton.Yes:
            return
        QMessageBox.information(self, "Not Implemented",
                                "Data reset requires administrator privileges.\n"
                                "Run: pkexec waydroid session stop && pkexec rm -rf /var/lib/waydroid/data")

    def uninstall_runtime(self):
        reply = QMessageBox.warning(
            self, "Uninstall Android Runtime",
            "This will remove the Android runtime and all associated data.\n\n"
            "Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            QMessageBox.information(self, "Uninstall",
                                    "Use your package manager to remove waydroid:\n"
                                    "sudo apt remove waydroid")

    def show_logs(self):
        from bright_android.core import waydroid_manager
        logs = waydroid_manager.get_logs(200)
        msg = QMessageBox(self)
        msg.setWindowTitle("Android Runtime Logs")
        text = QTextEdit()
        text.setPlainText(logs if logs else "No logs available (is Android running?)")
        text.setReadOnly(True)
        text.setMinimumSize(600, 400)
        layout = QVBoxLayout(msg)
        layout.addWidget(text)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(msg.close)
        layout.addWidget(close_btn)
        msg.exec()


class CompatibilityPage(QWidget):
    """Compatibility/requirements check page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(32, 24, 32, 24)
        self.layout.setSpacing(16)

        title = QLabel("Compatibility Check")
        title.setObjectName("title")
        self.layout.addWidget(title)

        desc = QLabel("Verify your system can run Android applications")
        desc.setObjectName("subtitle")
        self.layout.addWidget(desc)

        self.report_area = QTextEdit()
        self.report_area.setReadOnly(True)
        self.layout.addWidget(self.report_area)

        refresh_btn = QPushButton("↻  Re-check")
        refresh_btn.setObjectName("secondaryBtn")
        refresh_btn.clicked.connect(self.run_check)
        self.layout.addWidget(refresh_btn)

        self.layout.addStretch()
        self.run_check()

    def run_check(self):
        from bright_android.core import compatibility
        report = compatibility.run_full_check()
        hw = report.get("hardware_readiness", {})

        lines = ["=== Bright Android Hardware Readiness Report ===\n"]

        # Overall readiness badge
        status_icon = {"supported": "✅", "supported_with_limitations": "⚠️",
                       "unsupported": "❌"}.get(hw.get("status", ""), "?")
        lines.append(f"Overall status: {status_icon} {hw.get('summary', 'Unknown')}")
        lines.append("")

        # Blockers
        if hw.get("blockers"):
            lines.append("--- Blocking Issues ---")
            for b in hw["blockers"]:
                lines.append(f"  ❌ {b}")
            lines.append("")

        if hw.get("warnings"):
            lines.append("--- Limitations / Warnings ---")
            for w in hw["warnings"]:
                lines.append(f"  ⚠️  {w}")
            lines.append("")

        if hw.get("recommendations"):
            lines.append("--- Recommendations ---")
            for r in hw["recommendations"]:
                lines.append(f"  💡 {r}")
            lines.append("")

        lines.append(f"Can install runtime: {'✅ YES' if report['can_install'] else '❌ NO'}")
        lines.append(f"Can run apps now:    {'✅ YES' if report['can_run'] else '❌ NO'}")
        lines.append("")

        lines.append("--- CPU & Architecture ---")
        cpu = report.get("cpu", {})
        lines.append(f"  Architecture: {cpu.get('arch', '?')} ({'✅' if cpu.get('compatible') else '❌'} x86_64 required)")
        lines.append(f"  CPU cores: {cpu.get('cores', '?')}")
        if cpu.get("model"):
            lines.append(f"  Model: {cpu['model']}")
        lines.append("")

        lines.append("--- Kernel & Memory ---")
        binder = report.get("binder", {})
        lines.append(f"  Binder: {'✅ Available' if binder.get('binder_available') else '❌ Not available'}")
        if binder.get("module_needs_loading"):
            lines.append(f"    → Module needs loading: pkexec modprobe binder_linux")
        for d in binder.get('details', []):
            lines.append(f"    {d}")
        memfd = report.get("memfd", {})
        lines.append(f"  memfd: {'✅ Available' if memfd.get('memfd_available') else '❌ Missing'}")
        for d in memfd.get('details', []):
            lines.append(f"    {d}")
        lines.append("")

        lines.append("--- Session & Graphics ---")
        wayland = report.get("wayland", {})
        lines.append(f"  Wayland session: {'✅ Running' if wayland.get('wayland_available') else '❌ Not detected'}")
        for d in wayland.get('details', []):
            lines.append(f"    {d}")
        gfx = report.get("graphics", {})
        lines.append(f"  GPU: {gfx.get('renderer', 'unknown')}")
        lines.append(f"  Vendor: {gfx.get('vendor', 'unknown')}")
        lines.append(f"  OpenGL: {gfx.get('gl_version', 'unknown')}")
        if gfx.get("software_rendering"):
            lines.append("  ⚠️  Software rendering detected (very slow)")
        for d in gfx.get('details', []):
            lines.append(f"    {d}")
        lines.append("")

        lines.append("--- Memory ---")
        ram = report.get("ram", {})
        swap = report.get("swap", {})
        lines.append(f"  RAM total: {ram.get('total_mb', 0)} MB  (available: {ram.get('available_mb', 0)} MB)")
        for d in ram.get('details', []):
            lines.append(f"    {d}")
        lines.append(f"  Swap: {swap.get('swap_total_mb', 0)} MB" +
                     (" (none configured)" if not swap.get("swap_available") else f" ({swap.get('swap_free_mb', 0)} MB free)"))
        for d in swap.get('details', []):
            lines.append(f"    {d}")
        lines.append("")

        lines.append("--- Storage ---")
        disk = report.get("disk", {})
        lines.append(f"  Free space: {disk.get('available_gb', 0):.1f} GB of {disk.get('total_gb', 0):.1f} GB")
        for d in disk.get('details', []):
            lines.append(f"    {d}")
        lines.append("")

        lines.append("--- Runtime Status ---")
        pkgs = report.get("packages", {})
        init = report.get("initialized", {})
        lines.append(f"  Waydroid installed: {'✅' if pkgs.get('waydroid_installed') else '❌'} " +
                     (pkgs.get('waydroid_version', '') if pkgs.get('waydroid_installed') else "(install: sudo apt install waydroid)"))
        lines.append(f"  Android image: {'✅ Initialized' if init.get('initialized') else '⚪ Not initialized'}")
        for d in init.get('details', []):
            lines.append(f"    {d}")
        lines.append(f"  Running now: {'✅ YES' if report.get('running') else '❌ NO'}")

        self.report_area.setPlainText("\n".join(lines))


class BrightAndroidWindow(QMainWindow):
    """Main Bright Android management window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(900, 650)
        self.setStyleSheet(DARK_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # Navigation sidebar
        self.nav = QListWidget()
        self.nav.setFixedWidth(220)

        pages = [
            ("🏠  Android Home", HomePage),
            ("📱  Applications", ApplicationsPage),
            ("⚙️  Settings", SettingsPage),
            ("🔍  Compatibility", CompatibilityPage),
        ]

        self.stack = QStackedWidget()
        for name, cls in pages:
            self.nav.addItem(QListWidgetItem(name))
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(cls())
            self.stack.addWidget(scroll)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        h.addWidget(self.nav)
        h.addWidget(self.stack, 1)


def main():
    QApplication.setApplicationName("bright-android")
    QApplication.setApplicationDisplayName(APP_NAME)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = BrightAndroidWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
