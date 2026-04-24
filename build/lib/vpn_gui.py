#!/usr/bin/env python3
"""
OpenVPN3 GUI - PyQt5-based GUI and tray icon for openvpn3 CLI
Profiles are stored in ~/.config/openvpn3-gui/profiles/
"""

import sys
import os
import re
import shutil
import subprocess
import threading
import stat
import html
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QSystemTrayIcon, QMenu, QAction,
    QFrame, QSizePolicy, QMessageBox, QComboBox, QFileDialog, QInputDialog,
    QLineEdit
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, QUrl
from PyQt5.QtGui import QIcon, QColor, QPainter, QPixmap, QFont, QTextCursor, QPen, QDesktopServices

APP_VERSION  = "1.2.4"
OPENVPN3     = shutil.which("openvpn3") or "/usr/bin/openvpn3"
PROFILES_DIR = os.path.expanduser("~/.config/openvpn3-gui/profiles")
PID_FILE     = os.path.expanduser("~/.config/openvpn3-gui/app.pid")

# ── Status constants ──────────────────────────────────────────────────────────
ST_DISCONNECTED = "Disconnected"
ST_CONNECTING   = "Connecting…"
ST_CONNECTED    = "Connected"
ST_PAUSED       = "Paused"
ST_ERROR        = "Error"
ST_AWAITING_AUTH = "Awaiting Auth"

STATUS_COLORS = {
    ST_DISCONNECTED: "#888888",
    ST_CONNECTING:   "#f0a500",
    ST_CONNECTED:    "#00c853",
    ST_PAUSED:       "#f0a500",
    ST_ERROR:        "#e53935",
    ST_AWAITING_AUTH: "#f0a500",
}


# ── Tray icon drawing ─────────────────────────────────────────────────────────
def make_tray_icon(status: str) -> QIcon:
    color = STATUS_COLORS.get(status, "#888888")
    pm = QPixmap(22, 22)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 18, 18)
    # lock body
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(5, 11, 12, 8, 2, 2)
    # lock shackle
    p.setBrush(Qt.NoBrush)
    pen = QPen(QColor("#ffffff"), 2)
    p.setPen(pen)
    p.drawArc(7, 6, 8, 8, 0, 180 * 16)
    p.end()
    return QIcon(pm)


# ── Worker: runs openvpn3 commands in a thread ────────────────────────────────
class Signals(QObject):
    log          = pyqtSignal(str)
    status       = pyqtSignal(str)
    session_path = pyqtSignal(str)
    url_found    = pyqtSignal(str)  # emits URL


class VPNWorker(QThread):
    """Runs a single openvpn3 command and emits output line by line."""

    def __init__(self, cmd, signals: Signals, capture=False):
        super().__init__()
        self.cmd = cmd
        self.signals = signals
        self.capture = capture
        self.output_lines: list[str] = []

    def run(self):
        try:
            proc = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.signals.log.emit(line)
                    
                    # Detect URLs for web auth
                    urls = re.findall(r'https?://[^\s\r\n]+', line)
                    for url in urls:
                        self.signals.url_found.emit(url)
                    
                    if self.capture:
                        self.output_lines.append(line)
            proc.wait()
        except Exception as e:
            self.signals.log.emit(f"[error] {e}")


# ── Status poller ─────────────────────────────────────────────────────────────
class StatusPoller(QObject):
    status_changed  = pyqtSignal(str)
    session_changed = pyqtSignal(str)   # emits session path or ""
    log_line        = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._timer = QTimer()
        self._timer.timeout.connect(self.poll)
        self._last_status = None
        self._last_path   = None

    def start(self, interval_ms=3000):
        self.poll()
        self._timer.start(interval_ms)

    def stop(self):
        self._timer.stop()

    def poll(self):
        try:
            result = subprocess.run(
                [OPENVPN3, "sessions-list"],
                capture_output=True, text=True, timeout=5
            )
            out = result.stdout + result.stderr
            status, path = self._parse_sessions(out)
        except Exception as e:
            status, path = ST_ERROR, ""
            self.log_line.emit(f"[poller error] {e}")

        if status != self._last_status:
            self._last_status = status
            self.status_changed.emit(status)
        if path != self._last_path:
            self._last_path = path
            self.session_changed.emit(path)

    def _parse_sessions(self, text: str):
        if "No sessions available" in text:
            return ST_DISCONNECTED, ""

        path_match = re.search(r"(/net/openvpn/v3/sessions/\S+)", text)
        path = path_match.group(1) if path_match else ""

        text_lower = text.lower()
        if "connected" in text_lower:
            return ST_CONNECTED, path
        
        # Check for web auth / external auth states specifically
        if any(s in text_lower for s in (
            "awaiting external authentication", 
            "web based authentication",
            "await_auth",
            "await_web_auth"
        )):
            return ST_AWAITING_AUTH, path
            
        if "connecting" in text_lower or "get config" in text_lower:
            return ST_CONNECTING, path
        if "paused" in text_lower:
            return ST_PAUSED, path

        if path:
            return ST_CONNECTING, path
        return ST_DISCONNECTED, ""


# ── Main Window ───────────────────────────────────────────────────────────────
class VPNWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._session_path = ""
        self._status = ST_DISCONNECTED
        self._auth_url = ""
        self._worker: VPNWorker | None = None
        self.signals = Signals()
        self.signals.log.connect(self._append_log)
        self.signals.url_found.connect(self._on_url_found)

        os.makedirs(PROFILES_DIR, exist_ok=True)

        self._build_ui()
        self._build_tray()
        self._update_button_states()

        self._append_log("OpenVPN3 GUI started")
        self._append_log(f"Profiles directory: {PROFILES_DIR}")
        if not self._profile_names():
            self._append_log("[hint] No profiles found — use 'Import Profile' to add one.")

        self._kill_orphaned_instances()
        self._cleanup_orphaned_sessions()

        self.poller = StatusPoller()
        self.poller.status_changed.connect(self._on_status_changed)
        self.poller.session_changed.connect(self._on_session_changed)
        self.poller.log_line.connect(self._append_log)
        self.poller.start(3000)

    # ── Startup cleanup ───────────────────────────────────────────────────────
    def _kill_orphaned_instances(self):
        """Kill existing instances using a PID file, then write our own."""
        import signal as _signal
        my_pid = os.getpid()
        
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, "r") as f:
                    old_pid = int(f.read().strip())
                if old_pid != my_pid:
                    try:
                        os.kill(old_pid, _signal.SIGTERM)
                        self._append_log(f"[startup] Terminated existing instance (PID {old_pid})")
                    except ProcessLookupError:
                        pass
            except (ValueError, OSError):
                pass
                
        try:
            with open(PID_FILE, "w") as f:
                f.write(str(my_pid))
        except OSError as e:
            self._append_log(f"[startup] Could not write PID file: {e}")

    def _cleanup_orphaned_sessions(self):
        """Disconnect any sessions that are in an error or unknown state."""
        try:
            result = subprocess.run(
                [OPENVPN3, "sessions-list"],
                capture_output=True, text=True, timeout=5
            )
            out = result.stdout + result.stderr
        except Exception as e:
            self._append_log(f"[startup] Could not list sessions: {e}")
            return

        if "No sessions available" in out:
            return

        # Split into per-session blocks on the dashed separator lines
        blocks = [b for b in re.split(r"-{20,}", out) if b.strip()]

        orphaned = []
        for block in blocks:
            path_match = re.search(r"(/net/openvpn/v3/sessions/\S+)", block)
            if not path_match:
                continue
            path = path_match.group(1)
            block_lower = block.lower()
            if not any(s in block_lower for s in ("connected", "paused", "connecting", "get config")):
                orphaned.append(path)

        if not orphaned:
            paths_found = re.findall(r"/net/openvpn/v3/sessions/\S+", out)
            if paths_found:
                self._append_log(f"[startup] {len(paths_found)} active session(s) found — leaving as-is.")
            return

        self._append_log(f"[startup] Found {len(orphaned)} orphaned session(s) — cleaning up…")
        for path in orphaned:
            try:
                subprocess.run(
                    [OPENVPN3, "session-manage", "--disconnect", "--path", path],
                    capture_output=True, text=True, timeout=10
                )
                self._append_log(f"[startup] Cleaned up: {path}")
            except Exception as e:
                self._append_log(f"[startup] Failed to clean up {path}: {e}")

    # ── Profile helpers ───────────────────────────────────────────────────────
    def _profile_names(self) -> list[str]:
        """Sorted list of profile names (stem of each .ovpn in PROFILES_DIR)."""
        try:
            return sorted(
                os.path.splitext(f)[0]
                for f in os.listdir(PROFILES_DIR)
                if f.endswith(".ovpn")
            )
        except OSError:
            return []

    def _active_profile_name(self) -> str | None:
        """Currently selected profile name (no extension), or None."""
        return self.profile_combo.currentText() or None

    def _active_profile_path(self) -> str | None:
        """Full path to the selected .ovpn file, or None."""
        name = self._active_profile_name()
        return os.path.join(PROFILES_DIR, f"{name}.ovpn") if name else None

    def _refresh_profiles(self):
        """Reload profile combo from disk, preserving selection if possible."""
        current = self.profile_combo.currentText()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        names = self._profile_names()
        self.profile_combo.addItems(names)
        if current in names:
            self.profile_combo.setCurrentText(current)
        self.profile_combo.blockSignals(False)
        self._on_profile_changed()  # tray is built by the time this is called

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        self.setWindowTitle(f"OpenVPN3 GUI  v{APP_VERSION}")
        self.setMinimumSize(560, 460)
        self.setWindowIcon(make_tray_icon(ST_DISCONNECTED))

        help_menu = self.menuBar().addMenu("Help")
        about_action = QAction("About OpenVPN3 GUI", help_menu)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # ── Status bar ────────────────────────────────────────────────────────
        status_frame = QFrame()
        status_frame.setFrameShape(QFrame.StyledPanel)
        status_frame.setStyleSheet("QFrame { background: #1e1e1e; border-radius: 6px; }")
        sf_layout = QHBoxLayout(status_frame)
        sf_layout.setContentsMargins(12, 8, 12, 8)

        self.status_dot = QLabel("●")
        self.status_dot.setFont(QFont("monospace", 18))
        sf_layout.addWidget(self.status_dot)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self.status_label = QLabel(ST_DISCONNECTED)
        self.status_label.setFont(QFont("Sans", 13, QFont.Bold))
        self.status_label.setStyleSheet("color: #cccccc;")
        info_col.addWidget(self.status_label)

        self.active_profile_label = QLabel("No profile selected")
        self.active_profile_label.setStyleSheet("color: #888888; font-size: 11px;")
        info_col.addWidget(self.active_profile_label)
        sf_layout.addLayout(info_col)
        sf_layout.addStretch()
        root.addWidget(status_frame)

        # ── Auth URL bar (hidden by default) ──────────────────────────────────
        self.auth_url_frame = QFrame()
        self.auth_url_frame.setFixedHeight(40)
        self.auth_url_frame.setStyleSheet("QFrame { background: #333333; border-radius: 4px; }")
        auf_layout = QHBoxLayout(self.auth_url_frame)
        auf_layout.setContentsMargins(10, 0, 10, 0)

        auf_lbl = QLabel("Action Required: Web Authentication")
        auf_lbl.setStyleSheet("color: #f0a500; font-size: 11px; font-weight: bold;")
        auf_layout.addWidget(auf_lbl)
        auf_layout.addStretch()

        btn_open = QPushButton("Open Browser")
        btn_open.setFixedHeight(24)
        btn_open.setStyleSheet(self._btn_style("#f0a500", "#c07800"))
        btn_open.clicked.connect(self._on_open_auth_url)
        auf_layout.addWidget(btn_open)

        self.auth_url_frame.setVisible(False)
        root.addWidget(self.auth_url_frame)

        # ── Profile selector ──────────────────────────────────────────────────
        profile_row = QHBoxLayout()
        profile_row.setSpacing(6)

        profile_lbl = QLabel("Profile:")
        profile_lbl.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        profile_row.addWidget(profile_lbl)

        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.profile_combo.setFixedHeight(30)
        self.profile_combo.setStyleSheet(
            "QComboBox { background: #1e1e1e; color: #cccccc; border: 1px solid #444; "
            "border-radius: 4px; padding: 0 8px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #1e1e1e; color: #cccccc; "
            "selection-background-color: #333333; }"
        )
        self.profile_combo.addItems(self._profile_names())
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        profile_row.addWidget(self.profile_combo)

        btn_import = QPushButton("Import…")
        btn_import.setFixedHeight(30)
        btn_import.setStyleSheet(self._btn_style("#1e88e5", "#1565c0"))
        btn_import.clicked.connect(self._on_import_profile)
        profile_row.addWidget(btn_import)

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setFixedHeight(30)
        self.btn_remove.setStyleSheet(self._btn_style("#555555", "#333333"))
        self.btn_remove.clicked.connect(self._on_remove_profile)
        profile_row.addWidget(self.btn_remove)

        root.addLayout(profile_row)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setFixedHeight(36)
        self.btn_connect.setStyleSheet(self._btn_style("#00c853", "#009624"))
        self.btn_connect.clicked.connect(self._on_connect)
        btn_row.addWidget(self.btn_connect)

        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setFixedHeight(36)
        self.btn_disconnect.setStyleSheet(self._btn_style("#e53935", "#b71c1c"))
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        btn_row.addWidget(self.btn_disconnect)

        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setFixedHeight(36)
        self.btn_pause.setStyleSheet(self._btn_style("#f0a500", "#c07800"))
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._on_pause)
        btn_row.addWidget(self.btn_pause)

        self.btn_resume = QPushButton("Resume")
        self.btn_resume.setFixedHeight(36)
        self.btn_resume.setStyleSheet(self._btn_style("#1e88e5", "#1565c0"))
        self.btn_resume.setEnabled(False)
        self.btn_resume.clicked.connect(self._on_resume)
        btn_row.addWidget(self.btn_resume)

        self.btn_stats = QPushButton("Stats")
        self.btn_stats.setFixedHeight(36)
        self.btn_stats.setStyleSheet(self._btn_style("#555555", "#333333"))
        self.btn_stats.setEnabled(False)
        self.btn_stats.clicked.connect(self._on_stats)
        btn_row.addWidget(self.btn_stats)

        root.addLayout(btn_row)

        # ── Log ───────────────────────────────────────────────────────────────
        log_label = QLabel("Log")
        log_label.setStyleSheet("color: #888888; font-size: 11px;")
        root.addWidget(log_label)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet(
            "QTextEdit { background: #111111; color: #cccccc; "
            "font-family: monospace; font-size: 11px; border-radius: 4px; }"
        )
        root.addWidget(self.log_box)

        btn_clear = QPushButton("Clear log")
        btn_clear.setFixedHeight(26)
        btn_clear.setStyleSheet(self._btn_style("#333333", "#222222"))
        btn_clear.clicked.connect(self.log_box.clear)
        root.addWidget(btn_clear, alignment=Qt.AlignRight)

        # Initialise profile label directly — tray isn't built yet so we can't
        # call _on_profile_changed() (which would reach _update_button_states).
        name = self.profile_combo.currentText()
        self.active_profile_label.setText(f"Profile: {name}" if name else "No profile selected")
        self.btn_remove.setEnabled(bool(name))

    def _btn_style(self, bg, hover):
        return (
            f"QPushButton {{ background: {bg}; color: white; border: none; "
            f"border-radius: 4px; padding: 0 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton:disabled {{ background: #333333; color: #666666; }}"
        )

    # ── Tray ──────────────────────────────────────────────────────────────────
    def _build_tray(self):
        self.tray = QSystemTrayIcon(make_tray_icon(ST_DISCONNECTED), self)
        self.tray.setToolTip("OpenVPN3 — Disconnected")
        self.tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        self._tray_status_action = QAction("Disconnected")
        self._tray_status_action.setEnabled(False)
        menu.addAction(self._tray_status_action)
        menu.addSeparator()

        self._tray_connect_action = QAction("Connect", self)
        self._tray_connect_action.triggered.connect(self._on_connect)
        menu.addAction(self._tray_connect_action)

        self._tray_disconnect_action = QAction("Disconnect", self)
        self._tray_disconnect_action.triggered.connect(self._on_disconnect)
        self._tray_disconnect_action.setEnabled(False)
        menu.addAction(self._tray_disconnect_action)

        menu.addSeparator()
        self._tray_profiles_menu = menu.addMenu("Profiles")
        self._rebuild_tray_profiles_menu()

        tray_import_action = QAction("Import Profile…", self)
        tray_import_action.triggered.connect(self._on_tray_import_profile)
        menu.addAction(tray_import_action)

        menu.addSeparator()
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)

        about_action = QAction(f"About  (v{APP_VERSION})", self)
        about_action.triggered.connect(self._on_about)
        menu.addAction(about_action)

        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._on_quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.show()

    # ── Profile slots ─────────────────────────────────────────────────────────
    def _on_profile_changed(self):
        name = self._active_profile_name()
        if name:
            self.active_profile_label.setText(f"Profile: {name}")
        else:
            self.active_profile_label.setText("No profile selected")
        has_profile = name is not None
        self.btn_remove.setEnabled(has_profile)
        self._rebuild_tray_profiles_menu()
        self._update_button_states()

    def _on_import_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import VPN Profile", os.path.expanduser("~"),
            "OpenVPN Profiles (*.ovpn);;All Files (*)"
        )
        if not path:
            return
        dest = os.path.join(PROFILES_DIR, os.path.basename(path))
        if os.path.exists(dest):
            reply = QMessageBox.question(
                self, "Overwrite?",
                f"A profile named '{os.path.basename(path)}' already exists. Overwrite?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        shutil.copy2(path, dest)
        os.chmod(dest, stat.S_IRUSR | stat.S_IWUSR)
        new_name = os.path.splitext(os.path.basename(path))[0]
        self._append_log(f"[profile] Imported: {new_name}")
        self._refresh_profiles()
        self.profile_combo.setCurrentText(new_name)

    def _on_remove_profile(self):
        name = self._active_profile_name()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Remove Profile",
            f"Remove profile '{name}'? The file will be deleted.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(os.path.join(PROFILES_DIR, f"{name}.ovpn"))
            self._append_log(f"[profile] Removed: {name}")
        except OSError as e:
            self._append_log(f"[profile] Error removing {name}: {e}")
        self._refresh_profiles()

    def _rebuild_tray_profiles_menu(self):
        self._tray_profiles_menu.clear()
        names = self._profile_names()
        current = self._active_profile_name()
        if not names:
            empty = QAction("No profiles imported", self._tray_profiles_menu)
            empty.setEnabled(False)
            self._tray_profiles_menu.addAction(empty)
            return
        for name in names:
            action = QAction(name, self._tray_profiles_menu)
            action.setCheckable(True)
            action.setChecked(name == current)
            action.triggered.connect(lambda checked, n=name: self.profile_combo.setCurrentText(n))
            self._tray_profiles_menu.addAction(action)

    def _on_tray_import_profile(self):
        self.show_window()
        self._on_import_profile()

    def _on_url_found(self, url: str):
        self._auth_url = url
        self.auth_url_frame.setVisible(True)
        self.tray.showMessage(
            "OpenVPN3 Authentication",
            "Web-based authentication required. Click 'Open Browser' in the window.",
            QSystemTrayIcon.Information, 5000
        )

    def _on_open_auth_url(self):
        if self._auth_url:
            QDesktopServices.openUrl(QUrl(self._auth_url))

    # ── VPN action slots ──────────────────────────────────────────────────────
    def _on_status_changed(self, status: str):
        self._status = status
        color = STATUS_COLORS.get(status, "#888888")
        self.status_dot.setStyleSheet(f"color: {color};")
        self.status_label.setText(status)
        self.tray.setIcon(make_tray_icon(status))
        self.tray.setToolTip(f"OpenVPN3 — {status}")
        self._tray_status_action.setText(status)
        self._update_button_states()
        self._append_log(f"[status] {status}")

        if status == ST_AWAITING_AUTH:
            if not self._auth_url:
                self._poll_for_auth_url()
        elif status not in (ST_CONNECTING,):
            self.auth_url_frame.setVisible(False)
            self._auth_url = ""

    def _poll_for_auth_url(self):
        """Try to fetch the auth URL using the CLI if it hasn't appeared in logs."""
        self._append_log("[auth] Checking for authentication URL via session-auth…")
        try:
            # First, check if session-auth lists a URL
            result = subprocess.run(
                [OPENVPN3, "session-auth", "--list"],
                capture_output=True, text=True, timeout=3
            )
            urls = re.findall(r'https?://[^\s\r\n]+', result.stdout)
            if urls:
                self._append_log(f"[auth] Found URL in session-auth: {urls[0]}")
                self._on_url_found(urls[0])
                return

            # If not, check if session-manage can reveal it for our current session
            if self._session_path:
                result = subprocess.run(
                    [OPENVPN3, "session-manage", "--path", self._session_path, "--show-auth-url"],
                    capture_output=True, text=True, timeout=3
                )
                urls = re.findall(r'https?://[^\s\r\n]+', result.stdout)
                if urls:
                    self._append_log(f"[auth] Found URL in session-manage: {urls[0]}")
                    self._on_url_found(urls[0])
                    return
            
            self._append_log("[auth] No URL found yet — checking again in a few seconds.")
        except Exception as e:
            self._append_log(f"[auth] Could not fetch URL: {e}")

    def _on_session_changed(self, path: str):
        self._session_path = path

    def _on_connect(self):
        if self._status in (ST_CONNECTED, ST_CONNECTING, ST_AWAITING_AUTH):
            return
        self._auth_url = ""
        self.auth_url_frame.setVisible(False)
        profile_path = self._active_profile_path()
        if not profile_path:
            QMessageBox.warning(self, "No Profile", "Select or import a VPN profile first.")
            return
        self._append_log(f"[connect] Starting session: {self._active_profile_name()}")
        self._run_command([OPENVPN3, "session-start", "--config", profile_path])

    def _on_disconnect(self):
        if not self._session_path and self._status not in (ST_CONNECTED, ST_PAUSED, ST_CONNECTING):
            return
        self._append_log("[disconnect] Disconnecting…")
        cmd = [OPENVPN3, "session-manage", "--disconnect"]
        if self._session_path:
            cmd += ["--path", self._session_path]
        else:
            cmd += ["--config", self._active_profile_name() or ""]
        self._run_command(cmd)

    def _on_pause(self):
        if self._status != ST_CONNECTED:
            return
        self._append_log("[pause] Pausing session…")
        cmd = [OPENVPN3, "session-manage", "--pause"]
        if self._session_path:
            cmd += ["--path", self._session_path]
        else:
            cmd += ["--config", self._active_profile_name() or ""]
        self._run_command(cmd)

    def _on_resume(self):
        if self._status != ST_PAUSED:
            return
        self._append_log("[resume] Resuming session…")
        cmd = [OPENVPN3, "session-manage", "--resume"]
        if self._session_path:
            cmd += ["--path", self._session_path]
        else:
            cmd += ["--config", self._active_profile_name() or ""]
        self._run_command(cmd)

    def _on_stats(self):
        self._append_log("[stats] Fetching session statistics…")
        cmd = [OPENVPN3, "session-stats"]
        if self._session_path:
            cmd += ["--path", self._session_path]
        else:
            cmd += ["--config", self._active_profile_name() or ""]
        self._run_command(cmd)

    def _run_command(self, cmd):
        self._append_log(f"$ {' '.join(cmd)}")
        worker = VPNWorker(cmd, self.signals)
        worker.finished.connect(lambda: self.poller.poll())
        worker.start()
        self._worker = worker

    def _update_button_states(self):
        connected   = self._status == ST_CONNECTED
        paused      = self._status == ST_PAUSED
        connecting  = self._status == ST_CONNECTING or self._status == ST_AWAITING_AUTH
        has_session = connected or paused or connecting
        has_profile = self._active_profile_name() is not None

        self.btn_connect.setEnabled(not has_session and has_profile)
        self.btn_disconnect.setEnabled(has_session)
        self.btn_pause.setEnabled(connected)
        self.btn_resume.setEnabled(paused)
        self.btn_stats.setEnabled(connected or paused)
        self._tray_connect_action.setEnabled(not has_session and has_profile)
        self._tray_disconnect_action.setEnabled(has_session)

    def _append_log(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"<span style='color:#555555'>[{ts}]</span> {html.escape(text)}")
        self.log_box.moveCursor(QTextCursor.End)

    # ── Tray / window visibility ──────────────────────────────────────────────
    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.show_window() if not self.isVisible() else self.hide()

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        """Minimize to tray instead of quitting."""
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "OpenVPN3", "Running in tray. Right-click icon to quit.",
            QSystemTrayIcon.Information, 2000
        )

    def _on_about(self):
        QMessageBox.about(
            self,
            "About OpenVPN3 GUI",
            f"<b>OpenVPN3 GUI</b> &nbsp; v{APP_VERSION}<br><br>"
            "A PyQt5 desktop client and tray icon for the <tt>openvpn3</tt> CLI.<br><br>"
            "<b>Profiles:</b><br>"
            f"<tt>{PROFILES_DIR}</tt><br><br>"
            "<b>Backend:</b><br>"
            f"<tt>{OPENVPN3}</tt>"
        )

    def _on_quit(self):
        self.poller.stop()
        self.tray.hide()
        QApplication.quit()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("OpenVPN3 GUI")
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "OpenVPN3 GUI", "No system tray available.")
        sys.exit(1)

    window = VPNWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
