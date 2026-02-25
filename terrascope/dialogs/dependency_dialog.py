"""
Dependency Installation Dialog for Terrascope Plugin

Provides a dialog to check and install plugin dependencies into an isolated
virtual environment at ~/.qgis_terrascope/venv/.
"""

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


class DependencyInstallWorker(QThread):
    """Worker thread for creating a venv and installing dependencies."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, packages):
        """Initialize the worker.

        Args:
            packages: List of pip package names to install.
        """
        super().__init__()
        self.packages = packages
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the installation."""
        self._cancelled = True

    def run(self):
        """Create venv if needed and install packages."""
        from ..venv_manager import (
            create_venv,
            ensure_venv_packages,
            install_packages,
            venv_exists,
        )

        try:
            # Create venv if it doesn't exist
            if not venv_exists():
                self.progress.emit("Creating virtual environment...")
                success, message = create_venv(
                    progress_callback=lambda msg: self.progress.emit(msg)
                )
                if not success:
                    self.finished.emit(False, message)
                    return

            if self._cancelled:
                self.finished.emit(False, "Installation cancelled by user")
                return

            # Install packages
            success, message = install_packages(
                self.packages,
                progress_callback=lambda msg: self.progress.emit(msg),
                cancel_check=lambda: self._cancelled,
            )

            if success:
                ensure_venv_packages()

            self.finished.emit(success, message)

        except Exception as e:
            self.finished.emit(False, f"Unexpected error: {e}")


class DependencyDialog(QDialog):
    """Dialog for checking and installing plugin dependencies."""

    def __init__(self, parent=None):
        """Initialize the dependency dialog.

        Args:
            parent: Parent widget.
        """
        super().__init__(parent)
        self._worker = None
        self._status_labels = {}

        self.setWindowTitle("Terrascope - Dependencies")
        self.setMinimumWidth(450)

        self._setup_ui()
        self._check_packages()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel("Terrascope Dependencies")
        header_font = QFont()
        header_font.setPointSize(13)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        # Required packages group
        req_group = QGroupBox("Required Packages")
        req_form = QFormLayout(req_group)
        from ..venv_manager import REQUIRED_PACKAGES

        for _, pip_name in REQUIRED_PACKAGES:
            label = QLabel("Checking...")
            label.setStyleSheet("color: gray;")
            self._status_labels[pip_name] = label
            req_form.addRow(f"{pip_name}:", label)
        layout.addWidget(req_group)

        # Optional packages group
        opt_group = QGroupBox("Optional Packages")
        opt_form = QFormLayout(opt_group)
        from ..venv_manager import OPTIONAL_PACKAGES

        for _, pip_name in OPTIONAL_PACKAGES:
            label = QLabel("Checking...")
            label.setStyleSheet("color: gray;")
            self._status_labels[pip_name] = label
            opt_form.addRow(f"{pip_name}:", label)
        layout.addWidget(opt_group)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()

        self.install_btn = QPushButton("Install")
        self.install_btn.clicked.connect(self._install_missing)
        btn_layout.addWidget(self.install_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_install)
        btn_layout.addWidget(self.cancel_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

        # Info label
        info_label = QLabel(
            "<small>Packages are installed in ~/.qgis_terrascope/venv</small>"
        )
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setStyleSheet("color: gray;")
        layout.addWidget(info_label)

    def _check_packages(self):
        """Check which packages are installed and update status labels."""
        from ..venv_manager import OPTIONAL_PACKAGES, REQUIRED_PACKAGES, get_venv_status

        _is_ready, _message, missing_req, missing_opt = get_venv_status()

        all_missing = set(missing_req + missing_opt)
        self._missing_packages = list(missing_req + missing_opt)

        for _, pip_name in REQUIRED_PACKAGES + OPTIONAL_PACKAGES:
            label = self._status_labels.get(pip_name)
            if label is None:
                continue
            if pip_name in all_missing:
                label.setText("Missing")
                label.setStyleSheet("color: red; font-weight: bold;")
            else:
                label.setText("Installed")
                label.setStyleSheet("color: green; font-weight: bold;")

        self.install_btn.setEnabled(bool(self._missing_packages))

    def _install_missing(self):
        """Start installing missing packages."""
        if not self._missing_packages:
            return

        self.install_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.close_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setVisible(True)
        self.status_label.setText("Starting installation...")
        self.status_label.setStyleSheet("color: blue;")

        self._worker = DependencyInstallWorker(self._missing_packages)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, message):
        """Handle progress signal from worker.

        Args:
            message: Progress message.
        """
        self.status_label.setText(message)

    def _on_finished(self, success, message):
        """Handle worker completion.

        Args:
            success: Whether all installations succeeded.
            message: Summary message.
        """
        self.progress_bar.setVisible(False)
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

        if success:
            self.status_label.setText("All packages installed successfully!")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setText(message)
            self.status_label.setStyleSheet("color: red;")

        # Re-check packages to update status labels
        self._check_packages()

        self._worker = None

    def _cancel_install(self):
        """Cancel the current installation."""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.status_label.setText("Cancelling...")
            self.cancel_btn.setEnabled(False)

    def closeEvent(self, event):
        """Handle dialog close event.

        Args:
            event: The close event.
        """
        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Installation in Progress",
                "An installation is in progress. Are you sure you want to cancel?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self._worker.cancel()
            self._worker.wait(5000)

        event.accept()
