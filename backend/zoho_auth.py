# =============================================================================
#  InvoicePulse — Zoho Books OAuth 2.0 Token Manager
#
#  Handles the complete OAuth 2.0 flow for Zoho Books:
#    1. Building the initial consent authorization URL
#    2. Exchanging the one-time `code` for an access_token + refresh_token
#    3. Persisting the tokens locally (JSON file with read/write safety)
#    4. Automatically refreshing expired access tokens transparently
# =============================================================================

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from config import settings

logger = logging.getLogger("zoho_auth")

# Token storage file location (by default stored next to this file).
TOKEN_FILE = Path(__file__).resolve().parent / "tokens.json"


class ZohoAuthManager:
    """Manages Zoho Books OAuth 2.0 tokens, persistence, and auto-refresh."""

    def __init__(self, token_file: Path = TOKEN_FILE) -> None:
        self.token_file: Path = token_file
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at: float = 0.0
        self.token_type: str = "Bearer"
        self.api_domain: str = settings.API_DOMAIN
        self._load_tokens_from_disk()

    # ------------------------------------------------------------------ storage
    def _load_tokens_from_disk(self) -> None:
        """Load stored tokens from JSON if the file exists on disk."""
        if not self.token_file.exists():
            return
        try:
            with open(self.token_file, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                self.expires_at = data.get("expires_at", 0.0)
                self.api_domain = data.get("api_domain", settings.API_DOMAIN)
                logger.info("Loaded cached Zoho tokens from disk.")
        except Exception as exc:
            logger.warning(f"Could not read tokens file {self.token_file}: {exc}")

    def _save_tokens_to_disk(self) -> None:
        """Persist current tokens and expiration timestamp to disk."""
        try:
            payload = {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at": self.expires_at,
                "api_domain": self.api_domain,
            }
            with open(self.token_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            logger.info("Persisted refreshed Zoho tokens to disk.")
        except Exception as exc:
            logger.error(f"Failed to write tokens to {self.token_file}: {exc}")

    # ------------------------------------------------------------------ oauth flow
    def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """Exchange the one-time authorization code for access & refresh tokens.

        Args:
            code: The authorization code returned by Zoho in the callback redirect.

        Returns:
            Dictionary with the raw token response.
        """
        token_url = f"{settings.ACCOUNTS_DOMAIN}/oauth/v2/token"
        payload = {
            "code": code,
            "client_id": settings.CLIENT_ID,
            "client_secret": settings.CLIENT_SECRET,
            "redirect_uri": settings.REDIRECT_URI,
            "grant_type": "authorization_code",
        }

        logger.info(f"Requesting token exchange at {token_url}...")
        resp = requests.post(token_url, data=payload, timeout=15)
        if not resp.ok:
            logger.error(f"Token exchange failed ({resp.status_code}): {resp.text}")
            resp.raise_for_status()

        data: Dict[str, Any] = resp.json()

        # Handle Zoho error structures
        if "error" in data:
            raise RuntimeError(f"Zoho OAuth error: {data.get('error')}")

        self.access_token = data.get("access_token")
        # Zoho only returns refresh_token on the FIRST authorization exchange.
        if "refresh_token" in data:
            self.refresh_token = data.get("refresh_token")

        expires_in = int(data.get("expires_in", 3600))
        # Add a 60-second safety cushion to ensure we refresh before real expiry.
        self.expires_at = time.time() + expires_in - 60
        if "api_domain" in data:
            self.api_domain = data["api_domain"]

        self._save_tokens_to_disk()
        return data

    def refresh_access_token(self) -> str:
        """Use the saved refresh token to obtain a new, valid access token.

        Returns:
            The newly issued access_token string.
        """
        if not self.refresh_token:
            raise RuntimeError(
                "Cannot refresh token: No refresh_token found. "
                "Please run the initial OAuth authorization flow first via /auth/login."
            )

        token_url = f"{settings.ACCOUNTS_DOMAIN}/oauth/v2/token"
        payload = {
            "refresh_token": self.refresh_token,
            "client_id": settings.CLIENT_ID,
            "client_secret": settings.CLIENT_SECRET,
            "grant_type": "refresh_token",
        }

        logger.info(f"Refreshing Zoho access token via {token_url}...")
        resp = requests.post(token_url, data=payload, timeout=15)
        if not resp.ok:
            logger.error(f"Token refresh failed ({resp.status_code}): {resp.text}")
            resp.raise_for_status()

        data: Dict[str, Any] = resp.json()
        if "error" in data:
            raise RuntimeError(f"Zoho token refresh error: {data.get('error')}")

        self.access_token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))
        self.expires_at = time.time() + expires_in - 60

        self._save_tokens_to_disk()
        return str(self.access_token)

    def get_valid_access_token(self) -> str:
        """Get an active access token, refreshing it automatically if expired."""
        if not self.access_token:
            # Check if we have a refresh token to boot up from
            if self.refresh_token:
                return self.refresh_access_token()
            raise RuntimeError(
                "Application is not authenticated with Zoho Books. "
                "Please visit the /auth/login endpoint or Dashboard to authenticate."
            )

        # Check if the access token has expired
        if time.time() >= self.expires_at:
            logger.info("Current access token is expired or close to expiry. Refreshing...")
            return self.refresh_access_token()

        return self.access_token

    def is_authenticated(self) -> bool:
        """Return True if we have valid credentials or a usable refresh token."""
        return bool(self.access_token or self.refresh_token)

    def get_status(self) -> Dict[str, Any]:
        """Return current authentication metadata for the status API."""
        now = time.time()
        is_auth = self.is_authenticated()
        expires_in_sec = max(0, int(self.expires_at - now)) if is_auth else 0

        return {
            "authenticated": is_auth,
            "has_refresh_token": bool(self.refresh_token),
            "token_expires_in_seconds": expires_in_sec,
            "api_domain": self.api_domain,
            "organization_id": settings.ORGANIZATION_ID,
            "accounts_domain": settings.ACCOUNTS_DOMAIN,
        }


# Singleton auth manager instance
auth_manager = ZohoAuthManager()
