"""
Terrascope QGIS Plugin

A QGIS plugin for searching and visualizing Terrascope STAC API data,
with time slider and time series plotting capabilities.
"""

from .terrascope_plugin import TerrascopePlugin


def classFactory(iface):
    """Load TerrascopePlugin class from file terrascope_plugin.

    Args:
        iface: A QGIS interface instance.

    Returns:
        TerrascopePlugin: The plugin instance.
    """
    return TerrascopePlugin(iface)
