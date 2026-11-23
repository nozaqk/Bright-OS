#!/usr/bin/env python3
"""
Bright Android - Android application management for Bright OS

A native PyQt6 interface for managing the Waydroid-based Android runtime.
Provides Home, Applications, and Settings pages.
"""
import sys
import os
import subprocess
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
    """Background worker for running waydroid operations."""
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            kwargs = dict(self.kwargs)
            kwargs["progress_cb"] = lambda msg: self.progress.emit(msg)
            self.func(*self.args, **kwargs)
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


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

        # Auto-refresh timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_status)
        self.refresh_timer.start(5000)

        self.refresh_status()

    def _detect_edition(self) -> str:
        try:
            with open("/etc/bright-os/edition") as f:
                ed = f.read().strip().lower()
                return {"lite": "Lite", "home": "Home", "developer": "Developer"}.get(ed, ed.title())
        except Exception:
            return "Home"

    def refresh_status(self):
        """Update all status displays."""
        from bright_android.core import waydroid_manager, compatibility

        compat = compatibility.run_full_check()

        if not compat["packages"]["waydroid_installed"]:
            self.status_label.setText(STATUS_NOT_INSTALLED)
            self.status_label.setObjectName("statusErr")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.init_btn.setEnabled(False)
            self.version_label.setText("Not installed")
            self.ram_label.setText(f"{compat['ram']['total_mb']} MB")
            self.storage_label.setText(f"{compat['disk']['available_gb']} GB available")
            return

        if not compat["initialized"]["initialized"]:
            self.status_label.setText("⚪ Not initialized")
            self.status_label.setObjectName("statusWarn")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.init_btn.setEnabled(True)
        elif compat["running"] if False else False:
            self.status_label.setText(STATUS_RUNNING)
            self.status_label.setObjectName("statusOk")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.init_btn.setEnabled(False)
        else:
            self.status_label.setText(STATUS_STOPPED)
            self.status_label.setObjectName("statusErr")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.init_btn.setEnabled(False)

        self.version_label.setText(compat["packages"]["details"][0] if compat["packages"]["details"] else "-")
        self.ram_label.setText(f"{compat['ram']['total_mb']} MB")
        self.storage_label.setText(f"{compat['disk']['available_gb']} GB available")

        # Force style refresh
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

        # App count
        if compat["initialized"]["initialized"] and waydroid_manager.is_running():
            try:
                apps = waydroid_manager.list_apps()
                self.apps_count_label.setText(f"{len(apps)} application(s) installed")
                if apps:
                    names = ", ".join(a["name"] for a in apps[:10])
                    if len(apps) > 10:
                        names += f" ... and {len(apps) - 10} more"
                    self.apps_list_label.setText(names)
            except Exception:
                self.apps_count_label.setText("Cannot list apps (runtime may be starting)")
        else:
            self.apps_count_label.setText("Start Android to view applications")
            self.apps_list_label.setText("")

    def _run_worker(self, func, *args, op_name="Operation"):
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress_label.setText(f"{op_name}...")
        self.setEnabled(False)

        self.worker = StatusWorker(func, *args)
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
        from bright_android.core import waydroid_manager
        self._run_worker(waydroid_manager.start_session, op_name="Starting Android")

    def stop_android(self):
        from bright_android.core import waydroid_manager
        self._run_worker(waydroid_manager.stop_session, op_name="Stopping Android")

    def init_android(self):
        reply = QMessageBox.question(
            self, "Initialize Android Runtime",
            "This will download and set up the Android system image (~400-700 MB).\n"
            "This requires administrator privileges and an internet connection.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from bright_android.core import waydroid_manager
            # Init requires pkexec; the waydroid_manager handles that
            self._run_worker(waydroid_manager.init, mode="auto",
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

    def refresh_apps(self):
        from bright_android.core import waydroid_manager
        if not waydroid_manager.is_running():
            self.apps_placeholder.setText("Start Android to view installed applications")
            # Clear existing widget list
            while self.apps_layout.count() > 1:
                item = self.apps_layout.takeAt(1)
                if item.widget():
                    item.widget().deleteLater()
            return

        try:
            apps = waydroid_manager.list_apps()
        except Exception as e:
            self.apps_placeholder.setText(f"Error listing apps: {e}")
            return

        # Clear existing
        while self.apps_layout.count():
            item = self.apps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not apps:
            label = QLabel("No Android applications installed.\nUse 'Install APK' to add applications.")
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
            QMessageBox.information(self, "Starting Android", "Android runtime needs to be started first.")
            return

        self.progress_bar.setVisible(True)
        self.setEnabled(False)
        self.worker = StatusWorker(waydroid_manager.install_apk, path)
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
        from bright_android.core import waydroid_manager
        try:
            waydroid_manager.launch_app(package)
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

        from bright_android.core import waydroid_manager
        try:
            waydroid_manager.uninstall_app(package)
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

    def save_settings(self):
        from bright_android.core import config as ba_config
        ba_config.set_bool("runtime", "auto_start", self.auto_start_cb.isChecked())
        ba_config.set_bool("runtime", "start_on_demand", self.on_demand_cb.isChecked())
        ba_config.set_bool("integration", "clipboard_share", self.clipboard_cb.isChecked())
        ba_config.set_bool("integration", "notification_forward", self.notifications_cb.isChecked())
        ba_config.set_bool("integration", "app_integration", self.app_integration_cb.isChecked())
        ba_config.set_bool("appearance", "freeform_windows", self.freeform_cb.isChecked())
        ba_config.set_bool("storage", "shared_downloads", self.share_downloads_cb.isChecked())
        ba_config.set_bool("storage", "shared_documents", self.share_documents_cb.isChecked())
        ba_config.set_bool("storage", "shared_pictures", self.share_pictures_cb.isChecked())
        ba_config.set_bool("developer", "adb_enabled", self.adb_cb.isChecked())
        ba_config.set_bool("developer", "show_logs", self.show_logs_cb.isChecked())
        ba_config.set_bool("developer", "nogpu_mode", self.nogpu_cb.isChecked())
        QMessageBox.information(self, "Settings Saved", "Android settings have been saved.")

    def restart_runtime(self):
        reply = QMessageBox.question(
            self, "Restart Android", "Restart the Android runtime?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from bright_android.core import waydroid_manager
        try:
            if waydroid_manager.is_running():
                waydroid_manager.stop_session()
            waydroid_manager.start_session()
            QMessageBox.information(self, "Restarted", "Android runtime restarted.")
        except Exception as e:
            QMessageBox.critical(self, "Restart Failed", str(e))

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

        lines = ["=== Bright Android Compatibility Report ===\n"]

        lines.append(f"Can install runtime: {'✅ YES' if report['can_install'] else '❌ NO'}")
        lines.append(f"Can run apps now:    {'✅ YES' if report['can_run'] else '❌ NO'}")
        lines.append("")

        lines.append("--- Kernel & Drivers ---")
        lines.append(f"  Binder (/dev/binder): {'✅ Available' if report['binder']['binder_available'] else '❌ Not available'}")
        for d in report['binder'].get('details', []):
            lines.append(f"    {d}")
        lines.append(f"  Wayland session: {'✅ Running' if report['wayland']['wayland_available'] else '❌ Not detected'}")
        for d in report['wayland'].get('details', []):
            lines.append(f"    {d}")
        lines.append(f"  Graphics: {'✅ Detected' if report['graphics'].get('graphics_ok') else '⚠️ Limited'}")
        for d in report['graphics'].get('details', []):
            lines.append(f"    {d}")
        lines.append("")

        lines.append("--- System Resources ---")
        lines.append(f"  RAM: {report['ram']['total_mb']} MB")
        for d in report['ram'].get('details', []):
            lines.append(f"    {d}")
        lines.append(f"  Disk: {report['disk']['available_gb']} GB available")
        for d in report['disk'].get('details', []):
            lines.append(f"    {d}")
        lines.append("")

        lines.append("--- Packages ---")
        lines.append(f"  Waydroid: {'✅ Installed' if report['packages']['waydroid_installed'] else '❌ Not installed'}")
        for d in report['packages'].get('details', []):
            lines.append(f"    {d}")
        lines.append(f"  Android image: {'✅ Initialized' if report['initialized']['initialized'] else '⚪ Not initialized'}")
        for d in report['initialized'].get('details', []):
            lines.append(f"    {d}")
        lines.append("")

        if report['issues']:
            lines.append("--- Blocking Issues ---")
            for issue in report['issues']:
                lines.append(f"  ❌ {issue}")
            lines.append("")

        if report['warnings']:
            lines.append("--- Warnings ---")
            for w in report['warnings']:
                lines.append(f"  ⚠️  {w}")
            lines.append("")

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
