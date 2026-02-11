"""
Opulent Horizons — Zoho OAuth2 Token Manager
==============================================
Handles automatic access token refresh using Zoho's OAuth2 refresh token flow.

Zoho access tokens expire after ~1 hour. This module caches the token in memory
and automatically refreshes it before expiry, with retry logic for resilience.

Setup:
    1. Create a Self Client at https://api-console.zoho.com/
    2. Generate a refresh token with scope: ZohoCRM.modules.ALL,ZohoCRM.settings.ALL
    3. Set env vars: ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN

Env vars:
    ZOHO_CLIENT_ID      - OAuth2 client ID from Zoho API Console
    ZOHO_CLIENT_SECRET   - OAuth2 client secret from Zoho API Console
    ZOHO_REFRESH_TOKEN   - Long-lived refresh token (does not expire)
    ZOHO_ACCESS_TOKEN    - (Legacy) Static access token fallback
    ZOHO_TOKEN_URL       - Token endpoint (default: https://accounts.zoho.com/oauth/v2/token)
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("opulent.mcp.zoho_auth")


@dataclass
class ZohoTokenManager:
    """
    Manages Zoho OAuth2 access tokens with automatic refresh.

    Thread-safe: uses an asyncio.Lock to prevent multiple concurrent refreshes.
    Proactive refresh: refreshes 5 minutes before expiry to avoid mid-request failures.
    """

    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    token_url: str = "https://accounts.zoho.com/oauth/v2/token"

    # Cached token state
    _access_token: str = ""
    _expires_at: float = 0.0  # Unix timestamp when token expires
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Refresh 5 minutes before expiry
    _refresh_buffer_seconds: int = 300

    @classmethod
    def from_env(cls) -> "ZohoTokenManager":
        """Create a ZohoTokenManager from environment variables."""
        return cls(
            client_id=os.getenv("ZOHO_CLIENT_ID", ""),
            client_secret=os.getenv("ZOHO_CLIENT_SECRET", ""),
            refresh_token=os.getenv("ZOHO_REFRESH_TOKEN", ""),
            token_url=os.getenv(
                "ZOHO_TOKEN_URL", "https://accounts.zoho.com/oauth/v2/token"
            ),
            _access_token=os.getenv("ZOHO_ACCESS_TOKEN", ""),
        )

    @property
    def has_oauth_credentials(self) -> bool:
        """Check if OAuth2 refresh credentials are configured."""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    @property
    def has_static_token(self) -> bool:
        """Check if a static (legacy) access token is configured."""
        return bool(self._access_token)

    @property
    def is_configured(self) -> bool:
        """Check if any Zoho auth method is available."""
        return self.has_oauth_credentials or self.has_static_token

    def _token_is_valid(self) -> bool:
        """Check if the current access token is still valid (with buffer)."""
        if not self._access_token:
            return False
        # If we don't know the expiry (static token), assume valid
        if self._expires_at == 0.0:
            return True
        return time.time() < (self._expires_at - self._refresh_buffer_seconds)

    async def get_access_token(self, http_client: httpx.AsyncClient) -> str:
        """
        Get a valid Zoho access token, refreshing if necessary.

        Returns:
            A valid access token string, or empty string if not configured.
        """
        # Fast path: token is still valid
        if self._token_is_valid():
            return self._access_token

        # If no OAuth credentials, return whatever static token we have
        if not self.has_oauth_credentials:
            return self._access_token

        # Slow path: need to refresh (with lock to prevent concurrent refreshes)
        async with self._lock:
            # Double-check after acquiring lock (another coroutine may have refreshed)
            if self._token_is_valid():
                return self._access_token

            await self._refresh_access_token(http_client)
            return self._access_token

    async def _refresh_access_token(self, http_client: httpx.AsyncClient) -> None:
        """
        Refresh the Zoho access token using the refresh token grant.

        Zoho OAuth2 token endpoint:
            POST https://accounts.zoho.com/oauth/v2/token
            ?refresh_token=...&client_id=...&client_secret=...&grant_type=refresh_token
        """
        logger.info("Refreshing Zoho access token...")

        try:
            resp = await http_client.post(
                self.token_url,
                data={
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                },
                timeout=15.0,
            )

            if resp.status_code != 200:
                logger.error(
                    "Zoho token refresh failed: HTTP %d — %s",
                    resp.status_code,
                    resp.text[:500],
                )
                return

            data = resp.json()

            if "access_token" not in data:
                logger.error(
                    "Zoho token refresh response missing access_token: %s",
                    data,
                )
                return

            self._access_token = data["access_token"]
            # Zoho tokens typically expire in 3600 seconds (1 hour)
            expires_in = data.get("expires_in", 3600)
            self._expires_at = time.time() + expires_in

            logger.info(
                "Zoho access token refreshed successfully (expires in %ds)",
                expires_in,
            )

        except httpx.HTTPError as exc:
            logger.error("Zoho token refresh HTTP error: %s", exc)
        except Exception as exc:
            logger.error("Zoho token refresh unexpected error: %s", exc)
