"""
Terrascope QGIS Plugin - Main Plugin Class

This module contains the main plugin class that manages the QGIS interface
integration, menu items, toolbar buttons, and dockable panels.
"""

import os
import re

from qgis.PyQt.QtCore import Qt, QSettings, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolBar, QMessageBox


TOOLBAR_OBJECT_NAME = "TerrascopeToolbar"
MENU_TITLE = "&Terrascope"

class TerrascopePlugin:
    """Terrascope Plugin implementation class for QGIS."""

    def __init__(self, iface):
        """Constructor.

        Args:
            iface: An interface instance that provides the hook to QGIS.
        """
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = None
        self.toolbar = None

        # Dock widgets (lazy loaded)
        self._search_dock = None
        self._time_slider_dock = None
        self._time_series_dock = None
        self._settings_dock = None

        # Shared state (lazy loaded)
        self._auth = None
        self._stac = None

        # Dependency state
        self._deps_ready = False

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        checkable=False,
        parent=None,
    ):
        """Add a toolbar icon to the toolbar.

        Args:
            icon_path: Path to the icon for this action.
            text: Text that appears in the menu for this action.
            callback: Function to be called when the action is triggered.
            enabled_flag: A flag indicating if the action should be enabled.
            add_to_menu: Flag indicating whether action should be added to menu.
            add_to_toolbar: Flag indicating whether action should be added to toolbar.
            status_tip: Optional text to show in status bar.
            checkable: Whether the action is checkable (toggle).
            parent: Parent widget for the new action.

        Returns:
            The action that was created.
        """
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)
        action.setCheckable(checkable)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.menu.addAction(action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        self._remove_toolbars_by_object_name()
        self._remove_menus_by_title()
        # Create menu
        self.menu = QMenu("&Terrascope")
        self.iface.mainWindow().menuBar().addMenu(self.menu)

        # Create toolbar
        self.toolbar = QToolBar("Terrascope Toolbar")
        self.toolbar.setObjectName(TOOLBAR_OBJECT_NAME)
        self.iface.addToolBar(self.toolbar)

        # Get icon paths with fallbacks
        icon_base = os.path.join(self.plugin_dir, "icons")

        search_icon = os.path.join(icon_base, "search.svg")
        if not os.path.exists(search_icon):
            search_icon = ":/images/themes/default/mActionSearch.svg"

        time_slider_icon = os.path.join(icon_base, "time_slider.svg")
        if not os.path.exists(time_slider_icon):
            time_slider_icon = (
                ":/images/themes/default/mActionTemporalNavigationAnimated.svg"
            )

        time_series_icon = os.path.join(icon_base, "time_series.svg")
        if not os.path.exists(time_series_icon):
            time_series_icon = ":/images/themes/default/mActionAddRasterLayer.svg"

        settings_icon = os.path.join(icon_base, "settings.svg")
        if not os.path.exists(settings_icon):
            settings_icon = ":/images/themes/default/mActionOptions.svg"

        about_icon = os.path.join(icon_base, "about.svg")
        if not os.path.exists(about_icon):
            about_icon = ":/images/themes/default/mActionHelpContents.svg"

        # Search Panel (checkable, toolbar+menu)
        self.search_action = self.add_action(
            search_icon,
            "Search Panel",
            self.toggle_search_dock,
            status_tip="Toggle STAC Search Panel",
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Time Slider (checkable, toolbar+menu)
        self.time_slider_action = self.add_action(
            time_slider_icon,
            "Time Slider",
            self.toggle_time_slider_dock,
            status_tip="Toggle Time Slider Panel",
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Time Series (checkable, toolbar+menu)
        self.time_series_action = self.add_action(
            time_series_icon,
            "Time Series",
            self.toggle_time_series_dock,
            status_tip="Toggle Time Series Plot Panel",
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Settings (checkable, toolbar+menu)
        self.settings_action = self.add_action(
            settings_icon,
            "Settings",
            self.toggle_settings_dock,
            status_tip="Toggle Settings Panel",
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Separator
        self.menu.addSeparator()

        # Check for Updates (menu only)
        update_icon = ":/images/themes/default/mActionRefresh.svg"
        self.add_action(
            update_icon,
            "Check for Updates...",
            self.show_update_checker,
            add_to_toolbar=False,
            status_tip="Check for plugin updates from GitHub",
            parent=self.iface.mainWindow(),
        )

        # Install Dependencies (menu only)
        self.add_action(
            ":/images/themes/default/mActionFileOpen.svg",
            "Install Dependencies...",
            self.show_dependency_dialog,
            add_to_toolbar=False,
            status_tip="Check and install required Python packages",
            parent=self.iface.mainWindow(),
        )

        # About (menu only)
        self.add_action(
            about_icon,
            "About Terrascope",
            self.show_about,
            add_to_toolbar=False,
            status_tip="About Terrascope Plugin",
            parent=self.iface.mainWindow(),
        )

        # Silently set up venv sys.path if deps are already installed
        self._setup_venv_if_ready()

        # Auto-login after a short delay to let QGIS finish loading
        QTimer.singleShot(1000, self._try_auto_login)


    def _remove_toolbar(self, toolbar):
        """Detach and schedule deletion of a plugin toolbar widget."""
        if toolbar is None:
            return

        main_window = self.iface.mainWindow()
        actions = []
        try:
            actions = list(toolbar.actions())
        except Exception:
            pass  # nosec B110
        try:
            toolbar.clear()
        except Exception:
            pass  # nosec B110
        for action in actions:
            try:
                action.deleteLater()
            except Exception:
                pass  # nosec B110
        try:
            main_window.removeToolBar(toolbar)
        except Exception:
            pass  # nosec B110
        try:
            toolbar.hide()
        except Exception:
            pass  # nosec B110
        try:
            toolbar.setParent(None)
        except Exception:
            pass  # nosec B110
        try:
            toolbar.deleteLater()
        except Exception:
            pass  # nosec B110

    def _remove_toolbars_by_object_name(self):
        """Remove current or stale plugin toolbars from QGIS."""
        main_window = self.iface.mainWindow()
        for toolbar in main_window.findChildren(QToolBar, TOOLBAR_OBJECT_NAME):
            self._remove_toolbar(toolbar)

    def _plugin_menu_titles(self):
        """Return possible translated and untranslated plugin menu titles."""
        titles = {MENU_TITLE}
        translator = getattr(self, "tr", None)
        if callable(translator):
            try:
                titles.add(translator(MENU_TITLE))
            except Exception:
                pass  # nosec B110
        return titles

    def _remove_menu(self, menu):
        """Detach and schedule deletion of a plugin menu."""
        if menu is None:
            return

        main_window = self.iface.mainWindow()
        try:
            menu.clear()
        except Exception:
            pass  # nosec B110
        try:
            main_window.menuBar().removeAction(menu.menuAction())
        except Exception:
            pass  # nosec B110
        try:
            menu.setParent(None)
        except Exception:
            pass  # nosec B110
        try:
            menu.deleteLater()
        except Exception:
            pass  # nosec B110

    def _remove_menus_by_title(self):
        """Remove current or stale plugin menus from QGIS."""
        menu_bar = self.iface.mainWindow().menuBar()
        titles = self._plugin_menu_titles()
        for action in menu_bar.actions():
            menu = action.menu()
            if menu is not None and menu.title() in titles:
                self._remove_menu(menu)

    def unload(self):
        """Remove the plugin menu item and icon from QGIS GUI."""
        # Remove dock widgets
        for dock_attr in (
            "_search_dock",
            "_time_slider_dock",
            "_time_series_dock",
            "_settings_dock",
        ):
            dock = getattr(self, dock_attr, None)
            if dock:
                self.iface.removeDockWidget(dock)
                dock.deleteLater()
                setattr(self, dock_attr, None)

        # Logout if authenticated
        if self._auth:
            try:
                self._auth.logout()
            except Exception:
                pass  # nosec B110 - logout failures during plugin unload are not actionable
            self._auth = None

        # Remove actions from menu
        for action in self.actions:
            self.iface.removePluginMenu("&Terrascope", action)

        # Remove toolbar
        if self.toolbar:
            del self.toolbar

        # Remove menu
        if self.menu:
            self.menu.deleteLater()

        self._remove_toolbars_by_object_name()
        self._remove_menus_by_title()

    def toggle_search_dock(self):
        """Toggle the Search dock widget visibility."""
        if self._search_dock is None and not self._ensure_dependencies():
            self.search_action.setChecked(False)
            return
        if self._search_dock is None:
            try:
                from .dialogs.search_dock import SearchDockWidget

                self._search_dock = SearchDockWidget(
                    self.iface,
                    self._get_stac,
                    self._get_auth,
                    self.load_items_to_time_slider,
                    self.iface.mainWindow(),
                )
                self._search_dock.setObjectName("TerrascopeSearchDock")
                self._search_dock.visibilityChanged.connect(
                    self._on_search_visibility_changed
                )
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea, self._search_dock
                )
                self._search_dock.show()
                self._search_dock.raise_()
                return
            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Search panel:\n{str(e)}",
                )
                self.search_action.setChecked(False)
                return

        if self._search_dock.isVisible():
            self._search_dock.hide()
        else:
            self._search_dock.show()
            self._search_dock.raise_()

    def _on_search_visibility_changed(self, visible):
        """Handle Search dock visibility change.

        Args:
            visible: Whether the dock is now visible.
        """
        self.search_action.setChecked(visible)

    def toggle_time_slider_dock(self):
        """Toggle the Time Slider dock widget visibility."""
        if self._time_slider_dock is None and not self._ensure_dependencies():
            self.time_slider_action.setChecked(False)
            return
        if self._time_slider_dock is None:
            try:
                from .dialogs.time_slider_dock import TimeSliderDockWidget

                self._time_slider_dock = TimeSliderDockWidget(
                    self.iface, self._get_auth, self.iface.mainWindow()
                )
                self._time_slider_dock.setObjectName("TerrascopeTimeSliderDock")
                self._time_slider_dock.visibilityChanged.connect(
                    self._on_time_slider_visibility_changed
                )
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.BottomDockWidgetArea, self._time_slider_dock
                )
                self._time_slider_dock.show()
                self._time_slider_dock.raise_()
                return
            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Time Slider panel:\n{str(e)}",
                )
                self.time_slider_action.setChecked(False)
                return

        if self._time_slider_dock.isVisible():
            self._time_slider_dock.hide()
        else:
            self._time_slider_dock.show()
            self._time_slider_dock.raise_()

    def _on_time_slider_visibility_changed(self, visible):
        """Handle Time Slider dock visibility change.

        Args:
            visible: Whether the dock is now visible.
        """
        self.time_slider_action.setChecked(visible)

    def toggle_time_series_dock(self):
        """Toggle the Time Series dock widget visibility."""
        if self._time_series_dock is None and not self._ensure_dependencies():
            self.time_series_action.setChecked(False)
            return
        if self._time_series_dock is None:
            try:
                from .dialogs.time_series_dock import TimeSeriesDockWidget

                self._time_series_dock = TimeSeriesDockWidget(
                    self.iface, self._get_time_steps, self.iface.mainWindow()
                )
                self._time_series_dock.setObjectName("TerrascopeTimeSeriesDock")
                self._time_series_dock.visibilityChanged.connect(
                    self._on_time_series_visibility_changed
                )
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea, self._time_series_dock
                )
                self._time_series_dock.show()
                self._time_series_dock.raise_()
                return
            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Time Series panel:\n{str(e)}",
                )
                self.time_series_action.setChecked(False)
                return

        if self._time_series_dock.isVisible():
            self._time_series_dock.hide()
        else:
            self._time_series_dock.show()
            self._time_series_dock.raise_()

    def _on_time_series_visibility_changed(self, visible):
        """Handle Time Series dock visibility change.

        Args:
            visible: Whether the dock is now visible.
        """
        self.time_series_action.setChecked(visible)

    def toggle_settings_dock(self):
        """Toggle the Settings dock widget visibility."""
        if self._settings_dock is None:
            try:
                from .dialogs.settings_dock import SettingsDockWidget

                self._settings_dock = SettingsDockWidget(
                    self.iface, self._get_auth, self.iface.mainWindow()
                )
                self._settings_dock.setObjectName("TerrascopeSettingsDock")
                self._settings_dock.visibilityChanged.connect(
                    self._on_settings_visibility_changed
                )
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea, self._settings_dock
                )
                self._settings_dock.show()
                self._settings_dock.raise_()
                return
            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Settings panel:\n{str(e)}",
                )
                self.settings_action.setChecked(False)
                return

        if self._settings_dock.isVisible():
            self._settings_dock.hide()
        else:
            self._settings_dock.show()
            self._settings_dock.raise_()

    def _on_settings_visibility_changed(self, visible):
        """Handle Settings dock visibility change.

        Args:
            visible: Whether the dock is now visible.
        """
        self.settings_action.setChecked(visible)

    def show_about(self):
        """Display the about dialog."""
        version = "Unknown"
        try:
            metadata_path = os.path.join(self.plugin_dir, "metadata.txt")
            with open(metadata_path, "r", encoding="utf-8") as f:
                content = f.read()
                version_match = re.search(r"^version=(.+)$", content, re.MULTILINE)
                if version_match:
                    version = version_match.group(1).strip()
        except Exception:
            pass  # nosec B110 - About box falls back to default version string

        about_text = f"""
<h2>Terrascope Plugin for QGIS</h2>
<p>Version: {version}</p>
<p>Author: Qiusheng Wu</p>

<h3>Features:</h3>
<ul>
<li><b>STAC Search:</b> Search Terrascope collections with spatial, temporal,
    and cloud cover filters</li>
<li><b>COG Loading:</b> Stream Cloud Optimized GeoTIFFs directly via /vsicurl/</li>
<li><b>Time Slider:</b> Step through multi-temporal raster layers</li>
<li><b>Time Series:</b> Click map locations to plot pixel values over time</li>
<li><b>Authentication:</b> Basic authentication via login form or TERRASCOPE_USERNAME/TERRASCOPE_PASSWORD environment variables</li>
</ul>

<h3>Links:</h3>
<ul>
<li><a href="https://github.com/opengeos/qgis-terrascope-plugin">
    GitHub Repository</a></li>
<li><a href="https://github.com/opengeos/qgis-terrascope-plugin/issues">
    Report Issues</a></li>
</ul>

<p>Licensed under MIT License</p>
"""
        QMessageBox.about(
            self.iface.mainWindow(),
            "About Terrascope",
            about_text,
        )

    def show_update_checker(self):
        """Display the update checker dialog."""
        try:
            from .dialogs.update_checker import UpdateCheckerDialog
        except ImportError as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Failed to import update checker dialog:\n{str(e)}",
            )
            return

        try:
            dialog = UpdateCheckerDialog(self.plugin_dir, self.iface.mainWindow())
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Failed to open update checker:\n{str(e)}",
            )

    def _setup_venv_if_ready(self):
        """Silently set up venv sys.path if dependencies are already installed."""
        from .venv_manager import ensure_venv_packages, get_venv_status

        is_ready, _message, _missing_req, _missing_opt = get_venv_status()
        if is_ready:
            ensure_venv_packages()
            self._deps_ready = True

    def _ensure_dependencies(self):
        """Ensure dependencies are available, prompting install if needed.

        Returns:
            True if dependencies are ready, False otherwise.
        """
        if self._deps_ready:
            return True

        from .venv_manager import ensure_venv_packages, get_venv_status

        is_ready, _message, missing_req, _missing_opt = get_venv_status()
        if is_ready:
            ensure_venv_packages()
            self._deps_ready = True
            return True

        if missing_req:
            from .dialogs.dependency_dialog import DependencyDialog

            dialog = DependencyDialog(self.iface.mainWindow())
            dialog.exec()

            # Re-check after dialog closes
            is_ready, _msg, _mr, _mo = get_venv_status()
            if is_ready:
                ensure_venv_packages()
                self._deps_ready = True
                return True

        return False

    def show_dependency_dialog(self):
        """Display the dependency installation dialog."""
        try:
            from .dialogs.dependency_dialog import DependencyDialog
        except ImportError as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Failed to import dependency dialog:\n{str(e)}",
            )
            return

        dialog = DependencyDialog(self.iface.mainWindow())
        dialog.exec()

    def _try_auto_login(self):
        """Attempt auto-login if enabled in settings."""
        settings = QSettings()
        if not settings.value("Terrascope/auto_login", False, type=bool):
            return

        import os

        username = settings.value("Terrascope/username", "")
        password = settings.value("Terrascope/password", "")
        if not username:
            username = os.environ.get("TERRASCOPE_USERNAME", "")
        if not password:
            password = os.environ.get("TERRASCOPE_PASSWORD", "")

        if not username or not password:
            return

        try:
            auth = self._get_auth()
            auth.login(username, password)
            self.iface.messageBar().pushMessage(
                "Terrascope",
                f"Auto-login successful ({username})",
                level=0,
                duration=3,
            )
        except Exception as e:
            self.iface.messageBar().pushMessage(
                "Terrascope",
                f"Auto-login failed: {e}",
                level=1,
                duration=5,
            )

    def _get_auth(self):
        """Get or create the shared TerrascopeAuth instance.

        Returns:
            TerrascopeAuth instance.
        """
        if self._auth is None:
            from .auth import TerrascopeAuth

            self._auth = TerrascopeAuth()
        return self._auth

    def _get_stac(self):
        """Get or create the shared TerrascopeSTAC instance.

        Returns:
            TerrascopeSTAC instance.
        """
        if self._stac is None:
            from .stac_client import TerrascopeSTAC

            self._stac = TerrascopeSTAC()
        return self._stac

    def _get_time_steps(self):
        """Get time steps from the time slider dock.

        Returns:
            List of time step dicts, or empty list if no time slider.
        """
        if self._time_slider_dock is not None:
            return self._time_slider_dock.get_time_steps()
        return []

    def load_items_to_time_slider(self, items, asset_key, render_settings=None):
        """Load STAC items into the time slider dock.

        Opens the time slider dock if not visible, then loads the items.

        Args:
            items: List of STAC item dicts from TerrascopeSTAC.search().
            asset_key: Asset key to use for COG URLs (e.g., "NDVI").
            render_settings: Optional dict with render mode and parameters.
        """
        # Ensure time slider dock exists and is visible
        if self._time_slider_dock is None:
            self.toggle_time_slider_dock()
        elif not self._time_slider_dock.isVisible():
            self._time_slider_dock.show()
            self._time_slider_dock.raise_()

        if self._time_slider_dock:
            self._time_slider_dock.load_items(items, asset_key, render_settings)
