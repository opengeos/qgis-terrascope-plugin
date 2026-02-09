"""
Terrascope OAuth2 Authentication Module

Handles OAuth2 Resource Owner Password Grant authentication with the
Terrascope SSO endpoint, including automatic token refresh and GDAL
header file management for COG streaming.
"""

import json
import logging
import os
import threading
import time

try:
    import requests
except ImportError:
    requests = None

# Constants
TOKEN_URL = (
    "https://sso.terrascope.be/auth/realms/terrascope/protocol/openid-connect/token"
)
TOKEN_CACHE_PATH = os.path.expanduser("~/.terrascope_tokens.json")
HEADER_FILE_PATH = os.path.expanduser("~/.gdal_http_headers")
REFRESH_INTERVAL = 240  # Refresh every 4 minutes (token expires in 5)
REQUEST_TIMEOUT = 30

_logger = logging.getLogger(__name__)


class TerrascopeAuth:
    """Manages Terrascope OAuth2 authentication and GDAL header configuration."""

    def __init__(self):
        """Initialize the authentication manager."""
        self._token_cache = {}
        self._token_lock = threading.Lock()
        self._refresh_thread = None
        self._refresh_stop = threading.Event()

    def login(self, username, password):
        """Authenticate with Terrascope using username and password.

        Args:
            username: Terrascope username.
            password: Terrascope password.

        Returns:
            Access token string.

        Raises:
            ImportError: If requests is not installed.
            requests.HTTPError: If authentication fails.
        """
        if requests is None:
            raise ImportError("requests is required: pip install requests")

        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "password",
                "client_id": "public",
                "username": username,
                "password": password,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        with self._token_lock:
            self._save_tokens(
                data["access_token"],
                data["refresh_token"],
                data["expires_in"],
                data["refresh_expires_in"],
            )
            self._write_gdal_headers(data["access_token"])

        os.environ["GDAL_HTTP_HEADER_FILE"] = HEADER_FILE_PATH
        os.environ["GDAL_DISABLE_READDIR_ON_OPEN"] = "EMPTY_DIR"

        self._start_refresh_thread()
        return data["access_token"]

    def logout(self):
        """Stop token refresh and clear all cached tokens."""
        self._stop_refresh_thread()

        with self._token_lock:
            self._token_cache = {}
            if os.path.exists(TOKEN_CACHE_PATH):
                os.remove(TOKEN_CACHE_PATH)
            if os.path.exists(HEADER_FILE_PATH):
                os.remove(HEADER_FILE_PATH)

        os.environ.pop("GDAL_HTTP_HEADER_FILE", None)
        os.environ.pop("GDAL_DISABLE_READDIR_ON_OPEN", None)

    def refresh_token(self):
        """Use the refresh token to obtain a new access token.

        Returns:
            New access token string.

        Raises:
            ImportError: If requests is not installed.
            ValueError: If no refresh token is available.
        """
        if requests is None:
            raise ImportError("requests is required: pip install requests")

        with self._token_lock:
            refresh_tok = self._token_cache.get("refresh_token")

        if not refresh_tok:
            raise ValueError("No refresh token available. Please login first.")

        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": "public",
                "refresh_token": refresh_tok,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        with self._token_lock:
            self._save_tokens(
                data["access_token"],
                data["refresh_token"],
                data["expires_in"],
                data["refresh_expires_in"],
            )
            self._write_gdal_headers(data["access_token"])

        return data["access_token"]

    def is_authenticated(self):
        """Check if a valid access token exists.

        Returns:
            True if authenticated with a valid token.
        """
        with self._token_lock:
            if not self._token_cache:
                self._load_tokens()
            now = time.time()
            return self._token_cache.get("access_expires_at", 0) > now

    def get_access_token(self):
        """Get the current access token, refreshing if needed.

        Returns:
            Valid access token string, or None if not authenticated.
        """
        with self._token_lock:
            if not self._token_cache:
                self._load_tokens()

            now = time.time()

            if self._token_cache.get("access_expires_at", 0) > now:
                return self._token_cache["access_token"]

        # Try refresh outside the lock
        if self._token_cache.get("refresh_expires_at", 0) > now:
            try:
                return self.refresh_token()
            except Exception:
                pass

        return None

    def ensure_gdal_config(self):
        """Ensure GDAL environment is configured for authenticated COG access.

        Checks for a valid token (from cache or refresh) and sets the
        GDAL_HTTP_HEADER_FILE environment variable if not already set.

        Returns:
            True if GDAL is configured for authenticated access.
        """
        # Already configured
        if os.environ.get("GDAL_HTTP_HEADER_FILE") == HEADER_FILE_PATH:
            if os.path.exists(HEADER_FILE_PATH):
                return True

        token = self.get_access_token()
        if token:
            self._write_gdal_headers(token)
            os.environ["GDAL_HTTP_HEADER_FILE"] = HEADER_FILE_PATH
            os.environ["GDAL_DISABLE_READDIR_ON_OPEN"] = "EMPTY_DIR"
            return True

        return False

    def _save_tokens(self, access_token, refresh_token, expires_in, refresh_expires_in):
        """Save tokens to memory cache and disk.

        Args:
            access_token: The OAuth2 access token.
            refresh_token: The OAuth2 refresh token.
            expires_in: Access token lifetime in seconds.
            refresh_expires_in: Refresh token lifetime in seconds.
        """
        now = time.time()
        self._token_cache = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "access_expires_at": now + expires_in - 30,
            "refresh_expires_at": now + refresh_expires_in - 60,
        }
        with open(TOKEN_CACHE_PATH, "w") as f:
            json.dump(self._token_cache, f)
        os.chmod(TOKEN_CACHE_PATH, 0o600)

    def _load_tokens(self):
        """Load tokens from disk cache."""
        if os.path.exists(TOKEN_CACHE_PATH):
            try:
                with open(TOKEN_CACHE_PATH, "r") as f:
                    self._token_cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._token_cache = {}

    def _write_gdal_headers(self, token):
        """Write authorization header to GDAL header file.

        Args:
            token: The access token to write.
        """
        with open(HEADER_FILE_PATH, "w") as f:
            f.write(f"Authorization: Bearer {token}\n")
        os.chmod(HEADER_FILE_PATH, 0o600)

    def _start_refresh_thread(self):
        """Start the background token refresh daemon thread."""
        self._stop_refresh_thread()
        self._refresh_stop.clear()
        self._refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._refresh_thread.start()

    def _stop_refresh_thread(self):
        """Stop the background token refresh thread."""
        self._refresh_stop.set()
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=1)
        self._refresh_thread = None

    def _refresh_loop(self):
        """Background loop that refreshes the token periodically."""
        while not self._refresh_stop.wait(REFRESH_INTERVAL):
            try:
                self.refresh_token()
            except Exception as e:
                _logger.debug(f"Background token refresh failed: {e}")
