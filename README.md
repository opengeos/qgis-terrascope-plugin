# Terrascope QGIS Plugin

A QGIS plugin for searching and visualizing [Terrascope](https://terrascope.be) STAC API data, with time slider and time series plotting capabilities.

## Features

- **STAC Search Panel** - Query Terrascope collections with spatial extent, date range, and cloud cover filters
- **COG Loading** - Stream Cloud Optimized GeoTIFFs (COGs) directly into QGIS via `/vsicurl/`
- **Time Slider** - Step through multi-temporal raster layers with auto-play
- **Time Series Plot** - Click a map location to extract and chart pixel values over time
- **Authentication** - OAuth2 login with automatic background token refresh
- **Update Checker** - Check for plugin updates from GitHub

## Installation

### From QGIS Plugin Manager (Recommended)

1. Open QGIS
2. Go to **Plugins > Manage and Install Plugins...**
3. Search for "Terrascope"
4. Click **Install Plugin**

### Manual Installation

1. Download the latest release zip from [GitHub Releases](https://github.com/opengeos/qgis-terrascope-plugin/releases)
2. In QGIS, go to **Plugins > Manage and Install Plugins... > Install from ZIP**
3. Select the downloaded zip file

### From Source

```bash
git clone https://github.com/opengeos/qgis-terrascope-plugin.git
cd qgis-terrascope-plugin
python install.py
```

## Authentication

To access Terrascope data, you need a free account:

1. Register at [https://terrascope.be](https://terrascope.be)
2. In QGIS, open the **Terrascope > Settings** panel
3. Enter your username and password
4. Click **Login**

The plugin handles OAuth2 authentication and automatically refreshes tokens in the background.

## Usage

### Search for Data

1. Open **Terrascope > Search Panel**
2. Select a collection (e.g., `terrascope-s2-ndvi-v2`)
3. Click **Use Map Canvas Extent** to set the bounding box
4. Set the date range and cloud cover filter
5. Click **Search**
6. Select results and click **Load Selected** or **Load All to Time Slider**

### Time Slider

1. Load data via the Search Panel's **Load All to Time Slider** button
2. Use the slider or transport controls (First, Previous, Next, Last) to step through dates
3. Enable **Auto-Play** to animate through time steps

### Time Series Plot

1. Load data into the Time Slider
2. Open **Terrascope > Time Series**
3. Click **Activate Point Tool**
4. Click on the map to extract pixel values at that location across all time steps
5. Export results with **Export CSV** or **Save Plot**

## Development

### Setup

```bash
git clone https://github.com/opengeos/qgis-terrascope-plugin.git
cd qgis-terrascope-plugin
pip install pre-commit
pre-commit install
```

### Install for Testing

```bash
python install.py --name terrascope
```

### Package for Release

```bash
python package_plugin.py
```

### Code Quality

```bash
pre-commit run --all-files
```

## Dependencies

The plugin requires the following Python packages (auto-installed on first run):

- `requests` - HTTP client for OAuth2 authentication
- `pystac-client` - STAC API client
- `matplotlib` - Time series plotting (optional, for chart functionality)

## License

MIT License - see [LICENSE](LICENSE) for details.
