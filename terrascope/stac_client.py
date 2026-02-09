"""
Terrascope STAC Client Module

Wraps pystac_client to provide search and collection listing for the
Terrascope STAC API. Returns plain dicts for safe cross-thread use.
"""

import logging
from datetime import datetime, timezone

try:
    from pystac_client import Client
except ImportError:
    Client = None

STAC_URL = "https://stac.terrascope.be"

_logger = logging.getLogger(__name__)


class TerrascopeSTAC:
    """Client for the Terrascope STAC API."""

    def __init__(self, stac_url=None):
        """Initialize the STAC client.

        Args:
            stac_url: STAC API URL. Defaults to the Terrascope endpoint.
        """
        self._stac_url = stac_url or STAC_URL
        self._client = None

    def _get_client(self):
        """Get or create the pystac_client Client instance.

        Returns:
            pystac_client.Client instance.

        Raises:
            ImportError: If pystac_client is not installed.
        """
        if Client is None:
            raise ImportError("pystac-client is required: pip install pystac-client")
        if self._client is None:
            self._client = Client.open(self._stac_url)
        return self._client

    def get_collections(self):
        """List all available collections.

        Returns:
            List of dicts with 'id', 'title', and 'description' keys.
        """
        client = self._get_client()
        collections = []
        for c in client.get_collections():
            collections.append(
                {
                    "id": c.id,
                    "title": getattr(c, "title", c.id) or c.id,
                    "description": getattr(c, "description", "") or "",
                }
            )
        return collections

    def search(
        self,
        collections,
        bbox=None,
        datetime_range=None,
        max_cloud_cover=None,
        limit=100,
        unique_dates=True,
    ):
        """Search for items in the STAC catalog.

        Args:
            collections: List of collection IDs to search.
            bbox: Bounding box [west, south, east, north] in WGS84.
            datetime_range: Tuple of (start, end) as strings "YYYY-MM-DD"
                or datetime objects.
            max_cloud_cover: Maximum cloud cover percentage (0-100).
            limit: Maximum number of items to return.
            unique_dates: If True, return only one item per unique date.

        Returns:
            List of dicts with item metadata, sorted by date. Each dict
            contains 'id', 'datetime', 'date_str', 'cloud_cover', and
            'assets' keys.
        """
        client = self._get_client()

        search_kwargs = {"collections": collections}

        if bbox:
            search_kwargs["bbox"] = bbox

        if datetime_range:
            start, end = datetime_range
            if isinstance(start, str):
                start = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
            if isinstance(end, str):
                end = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
            search_kwargs["datetime"] = [start, end]

        if max_cloud_cover is not None:
            search_kwargs["filter"] = {
                "op": "<=",
                "args": [
                    {"property": "properties.eo:cloud_cover"},
                    max_cloud_cover,
                ],
            }

        if limit:
            search_kwargs["limit"] = limit
            if not unique_dates:
                search_kwargs["max_items"] = limit

        search_result = client.search(**search_kwargs)

        # Convert to plain dicts for thread safety.
        # When unique_dates is True, iterate lazily and stop once we
        # have enough unique dates. This avoids fetching all items for
        # large bboxes where each date has many tiles.
        result = []
        seen_dates = set()
        for item in search_result.items():
            date_str = item.datetime.strftime("%Y-%m-%d")

            if unique_dates:
                if date_str in seen_dates:
                    continue
                seen_dates.add(date_str)

            cloud_cover = item.properties.get("eo:cloud_cover")
            assets = {}
            for key, asset in item.assets.items():
                assets[key] = {
                    "href": asset.href,
                    "type": getattr(asset, "media_type", None),
                    "title": getattr(asset, "title", key),
                }

            result.append(
                {
                    "id": item.id,
                    "datetime": item.datetime.isoformat(),
                    "date_str": date_str,
                    "cloud_cover": cloud_cover,
                    "geometry": item.geometry,
                    "bbox": list(item.bbox) if item.bbox else None,
                    "assets": assets,
                }
            )

            if limit and len(result) >= limit:
                break

        # Sort by date
        result.sort(key=lambda i: i["datetime"])

        return result

    def get_collection_asset_keys(self, collection_id):
        """Get available asset keys for a collection.

        Inspects the first item in the collection to determine which
        asset keys are available (e.g., "NDVI", "SCL", "visual").

        Args:
            collection_id: The collection ID to inspect.

        Returns:
            List of asset key strings.
        """
        client = self._get_client()

        search_result = client.search(collections=[collection_id], limit=1, max_items=1)
        items = list(search_result.items())

        if not items:
            return []

        return list(items[0].assets.keys())
