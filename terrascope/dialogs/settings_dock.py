"""
Settings Dock Widget for Terrascope Plugin

Provides authentication UI (login/logout), general settings (default collection,
cloud cover, STAC URL), and advanced settings (token refresh, debug mode).
"""

import os

from qgis.PyQt.QtCore import Qt, QSettings, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QTabWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QSpinBox,
    QGroupBox,
    QMessageBox,
)


class LoginWorker(QThread):
    """Worker thread for non-blocking authentication."""

    finished = pyqtSignal(bool, str)

    def __init__(self, auth, username, password):
        """Initialize the login worker.

        Args:
            auth: TerrascopeAuth instance.
            username: Terrascope username.
            password: Terrascope password.
        """
        super().__init__()
        self.auth = auth
        self.username = username
        self.password = password

    def run(self):
        """Perform the login."""
        try:
            self.auth.login(self.username, self.password)
            self.finished.emit(True, "Authenticated successfully")
        except Exception as e:
            self.finished.emit(False, str(e))


class SettingsDockWidget(QDockWidget):
    """Settings dock widget with authentication and configuration tabs."""

    def __init__(self, iface, get_auth, parent=None):
        """Initialize the settings dock.

        Args:
            iface: QGIS interface instance.
            get_auth: Callable that returns the shared TerrascopeAuth instance.
            parent: Parent widget.
        """
        super().__init__("Terrascope Settings", parent)
        self.iface = iface
        self._get_auth = get_auth
        self._workers = []

        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        self._settings = QSettings()
        self._setup_ui()
        self._load_settings()
        self._update_auth_status()

    def _start_worker(self, worker):
        """Start a QThread worker and track it for cleanup.

        Args:
            worker: QThread worker to start.
        """

        def _cleanup():
            if worker in self._workers:
                self._workers.remove(worker)

        worker.finished.connect(_cleanup)
        self._workers.append(worker)
        worker.start()

    def _stop_all_workers(self):
        """Wait for all active workers to finish."""
        for worker in list(self._workers):
            worker.wait(5000)
        self._workers.clear()

    def closeEvent(self, event):
        """Handle dock close event, ensuring workers are stopped.

        Args:
            event: The close event.
        """
        self._stop_all_workers()
        super().closeEvent(event)

    def _setup_ui(self):
        """Set up the dock widget UI."""
        container = QWidget()
        layout = QVBoxLayout(container)

        tabs = QTabWidget()

        # Authentication tab
        auth_tab = QWidget()
        auth_layout = QVBoxLayout(auth_tab)

        auth_group = QGroupBox("Authentication")
        auth_form = QFormLayout(auth_group)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Terrascope username")
        auth_form.addRow("Username:", self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Terrascope password")
        auth_form.addRow("Password:", self.password_edit)

        self.save_credentials_cb = QCheckBox("Save credentials")
        auth_form.addRow(self.save_credentials_cb)

        self.auto_login_cb = QCheckBox("Auto-login on startup")
        auth_form.addRow(self.auto_login_cb)

        auth_layout.addWidget(auth_group)

        # Login/Logout buttons
        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("Login")
        self.login_btn.clicked.connect(self._on_login)
        btn_layout.addWidget(self.login_btn)

        self.logout_btn = QPushButton("Logout")
        self.logout_btn.clicked.connect(self._on_logout)
        self.logout_btn.setEnabled(False)
        btn_layout.addWidget(self.logout_btn)
        auth_layout.addLayout(btn_layout)

        # Status
        self.auth_status_label = QLabel("Not authenticated")
        self.auth_status_label.setStyleSheet("color: gray; font-weight: bold;")
        self.auth_status_label.setAlignment(Qt.AlignCenter)
        auth_layout.addWidget(self.auth_status_label)

        auth_layout.addStretch()
        tabs.addTab(auth_tab, "Authentication")

        # General tab
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_form = QFormLayout()

        self.default_collection_edit = QLineEdit()
        self.default_collection_edit.setPlaceholderText("terrascope-s2-ndvi-v2")
        general_form.addRow("Default collection:", self.default_collection_edit)

        self.default_cloud_cover_spin = QSpinBox()
        self.default_cloud_cover_spin.setRange(0, 100)
        self.default_cloud_cover_spin.setValue(30)
        self.default_cloud_cover_spin.setSuffix("%")
        general_form.addRow("Default max cloud cover:", self.default_cloud_cover_spin)

        self.default_max_results_spin = QSpinBox()
        self.default_max_results_spin.setRange(1, 500)
        self.default_max_results_spin.setValue(50)
        general_form.addRow("Default max results:", self.default_max_results_spin)

        self.stac_url_edit = QLineEdit()
        self.stac_url_edit.setText("https://stac.terrascope.be")
        general_form.addRow("STAC URL:", self.stac_url_edit)

        general_layout.addLayout(general_form)

        save_general_btn = QPushButton("Save Settings")
        save_general_btn.clicked.connect(self._save_settings)
        general_layout.addWidget(save_general_btn)

        general_layout.addStretch()
        tabs.addTab(general_tab, "General")

        # Advanced tab
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)
        advanced_form = QFormLayout()

        self.refresh_interval_spin = QSpinBox()
        self.refresh_interval_spin.setRange(60, 600)
        self.refresh_interval_spin.setValue(240)
        self.refresh_interval_spin.setSuffix(" seconds")
        advanced_form.addRow("Token refresh interval:", self.refresh_interval_spin)

        self.header_file_edit = QLineEdit()
        self.header_file_edit.setReadOnly(True)
        self.header_file_edit.setText("~/.gdal_http_headers")
        advanced_form.addRow("GDAL header file:", self.header_file_edit)

        self.debug_cb = QCheckBox("Enable debug logging")
        advanced_form.addRow(self.debug_cb)

        advanced_layout.addLayout(advanced_form)
        advanced_layout.addStretch()
        tabs.addTab(advanced_tab, "Advanced")

        layout.addWidget(tabs)
        self.setWidget(container)

    def _on_login(self):
        """Handle login button click.

        Uses the UI fields first, falling back to TERRASCOPE_USERNAME
        and TERRASCOPE_PASSWORD environment variables if fields are empty.
        """
        username = self.username_edit.text().strip()
        password = self.password_edit.text().strip()

        if not username:
            username = os.environ.get("TERRASCOPE_USERNAME", "")
        if not password:
            password = os.environ.get("TERRASCOPE_PASSWORD", "")

        if not username or not password:
            QMessageBox.warning(
                self,
                "Terrascope",
                "Please enter both username and password, or set\n"
                "TERRASCOPE_USERNAME and TERRASCOPE_PASSWORD\n"
                "environment variables.",
            )
            return

        self.login_btn.setEnabled(False)
        self.auth_status_label.setText("Logging in...")
        self.auth_status_label.setStyleSheet("color: blue; font-weight: bold;")

        auth = self._get_auth()
        worker = LoginWorker(auth, username, password)
        worker.finished.connect(self._on_login_finished)
        self._start_worker(worker)

    def _on_login_finished(self, success, message):
        """Handle login result.

        Args:
            success: Whether login succeeded.
            message: Result message.
        """
        self.login_btn.setEnabled(True)

        if success:
            self.auth_status_label.setText("Authenticated")
            self.auth_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.login_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)

            if self.save_credentials_cb.isChecked():
                self._settings.setValue(
                    "Terrascope/username", self.username_edit.text().strip()
                )
                self._settings.setValue(
                    "Terrascope/password", self.password_edit.text().strip()
                )
        else:
            self.auth_status_label.setText(f"Login failed: {message}")
            self.auth_status_label.setStyleSheet("color: red; font-weight: bold;")

    def _on_logout(self):
        """Handle logout button click."""
        auth = self._get_auth()
        auth.logout()
        self.auth_status_label.setText("Not authenticated")
        self.auth_status_label.setStyleSheet("color: gray; font-weight: bold;")
        self.login_btn.setEnabled(True)
        self.logout_btn.setEnabled(False)

    def _update_auth_status(self):
        """Update the authentication status display."""
        auth = self._get_auth()
        if auth.is_authenticated():
            self.auth_status_label.setText("Authenticated")
            self.auth_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.login_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)

    def _save_settings(self):
        """Save settings to QSettings."""
        self._settings.setValue(
            "Terrascope/default_collection",
            self.default_collection_edit.text().strip(),
        )
        self._settings.setValue(
            "Terrascope/default_cloud_cover",
            self.default_cloud_cover_spin.value(),
        )
        self._settings.setValue(
            "Terrascope/default_max_results",
            self.default_max_results_spin.value(),
        )
        self._settings.setValue(
            "Terrascope/stac_url",
            self.stac_url_edit.text().strip(),
        )
        self._settings.setValue(
            "Terrascope/refresh_interval",
            self.refresh_interval_spin.value(),
        )
        self._settings.setValue(
            "Terrascope/debug_mode",
            self.debug_cb.isChecked(),
        )
        self._settings.setValue(
            "Terrascope/auto_login",
            self.auto_login_cb.isChecked(),
        )

        QMessageBox.information(self, "Terrascope", "Settings saved.")

    def _load_settings(self):
        """Load settings from QSettings."""
        self.default_collection_edit.setText(
            self._settings.value("Terrascope/default_collection", "")
        )
        self.default_cloud_cover_spin.setValue(
            int(self._settings.value("Terrascope/default_cloud_cover", 30))
        )
        self.default_max_results_spin.setValue(
            int(self._settings.value("Terrascope/default_max_results", 50))
        )
        stac_url = self._settings.value(
            "Terrascope/stac_url", "https://stac.terrascope.be"
        )
        self.stac_url_edit.setText(stac_url)
        self.refresh_interval_spin.setValue(
            int(self._settings.value("Terrascope/refresh_interval", 240))
        )
        self.debug_cb.setChecked(
            self._settings.value("Terrascope/debug_mode", False, type=bool)
        )
        self.auto_login_cb.setChecked(
            self._settings.value("Terrascope/auto_login", False, type=bool)
        )
        self.save_credentials_cb.setChecked(
            bool(self._settings.value("Terrascope/username", ""))
        )

        # Load saved credentials, then fall back to environment variables
        saved_username = self._settings.value("Terrascope/username", "")
        saved_password = self._settings.value("Terrascope/password", "")

        if not saved_username:
            saved_username = os.environ.get("TERRASCOPE_USERNAME", "")
        if not saved_password:
            saved_password = os.environ.get("TERRASCOPE_PASSWORD", "")

        if saved_username:
            self.username_edit.setText(saved_username)
        if saved_password:
            self.password_edit.setText(saved_password)
