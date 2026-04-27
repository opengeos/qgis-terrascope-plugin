"""Terrascope Basic Authentication Module.

Handles basic authentication with TerraScope services using GDAL_HTTP_USERPWD
environment variable for COG streaming access.

According to TerraScope documentation, basic auth can be used with:
- GDAL_HTTP_AUTH=BASIC
- GDAL_HTTP_USERPWD=${USERNAME}:${PASSWORD}

Or using the password inline in the URL.
"""

import logging
import os

_logger = logging.getLogger(__name__)

# Environment variable names
ENV_USERNAME = "TERRASCOPE_USERNAME"
ENV_PASSWORD = "TERRASCOPE_PASSWORD"  # nosec B105 # pragma: allowlist secret - env var name, not a credential


class TerrascopeAuth:
    """Manages TerraScope basic authentication and GDAL configuration."""

    def __init__(self):
        """Initialize the authentication manager."""
        self._is_authenticated = False
        self._username = None
        self._password = None

    def login(self, username=None, password=None):
        """Set up basic authentication for TerraScope.

        Uses provided credentials or falls back to environment variables
        TERRASCOPE_USERNAME and TERRASCOPE_PASSWORD.

        Args:
            username: TerraScope username (optional, uses env var if not provided).
            password: TerraScope password (optional, uses env var if not provided).

        Returns:
            True if authentication is configured.

        Raises:
            ValueError: If no credentials are provided or available via env vars.
        """
        # Use provided credentials or fall back to env vars
        self._username = username or os.environ.get(ENV_USERNAME)
        self._password = password or os.environ.get(ENV_PASSWORD)

        if not self._username or not self._password:
            raise ValueError(
                f"TerraScope credentials not found. Please provide username/password "
                f"or set {ENV_USERNAME} and {ENV_PASSWORD} environment variables."
            )

        # Configure GDAL for basic authentication
        # According to TerraScope docs:
        # export GDAL_HTTP_AUTH=BASIC
        # export GDAL_HTTP_USERPWD=${USERNAME}:${PASSWORD}
        os.environ["GDAL_HTTP_AUTH"] = "BASIC"
        os.environ["GDAL_HTTP_USERPWD"] = f"{self._username}:{self._password}"
        os.environ["GDAL_DISABLE_READDIR_ON_OPEN"] = "EMPTY_DIR"

        self._is_authenticated = True
        _logger.debug("TerraScope basic authentication configured")

        return True

    def logout(self):
        """Clear authentication settings."""
        self._is_authenticated = False
        self._username = None
        self._password = None

        # Remove GDAL environment variables
        for var in [
            "GDAL_HTTP_AUTH",
            "GDAL_HTTP_USERPWD",
            "GDAL_DISABLE_READDIR_ON_OPEN",
        ]:
            os.environ.pop(var, None)

        _logger.debug("TerraScope authentication cleared")

    def is_authenticated(self):
        """Check if authentication is configured.

        Returns:
            True if authenticated with credentials.
        """
        if not self._is_authenticated:
            return False

        # Verify GDAL env vars are still set
        return (
            os.environ.get("GDAL_HTTP_AUTH") == "BASIC"
            and os.environ.get("GDAL_HTTP_USERPWD") is not None
        )

    def ensure_gdal_config(self):
        """Ensure GDAL environment is configured for authenticated COG access.

        Tries to configure using environment variables if not already authenticated.

        Returns:
            True if GDAL is configured for authenticated access.
        """
        # Verify GDAL env vars are actually set
        if os.environ.get("GDAL_HTTP_AUTH") == "BASIC" and os.environ.get(
            "GDAL_HTTP_USERPWD"
        ):
            self._is_authenticated = True
            return True

        # Try to auto-configure from environment variables
        try:
            self.login()
            return True
        except ValueError:
            return False

    def get_username(self):
        """Get the configured username.

        Returns:
            Username string or None if not authenticated.
        """
        return self._username

    def get_basic_auth_env(self):
        """Get the GDAL HTTP auth environment configuration.

        Returns:
            Dict with GDAL_HTTP_AUTH and GDAL_HTTP_USERPWD values,
            or empty dict if not authenticated.
        """
        if not self._is_authenticated:
            return {}

        return {
            "GDAL_HTTP_AUTH": "BASIC",
            "GDAL_HTTP_USERPWD": f"{self._username}:{self._password}",
        }
