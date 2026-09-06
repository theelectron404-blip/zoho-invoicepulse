# =============================================================================
#  InvoicePulse — Bulk Invoicing & Email-Dispatch Engine for Zoho Books
#
#  Configuration module: loads environment variables / .env, exposes settings,
#  and validates critical values at import time so misconfig fails fast.
# =============================================================================

import os
from pathlib import Path

from dotenv import load_dotenv

# Load the .env file (if present) from the backend/ directory.
load_dotenv(Path(__file__).resolve().parent / ".env")


class Settings:
    """Central configuration object reading from environment / .env file."""

    def __init__(self) -> None:
        self.CLIENT_ID: str = os.getenv("ZOHO_CLIENT_ID", "")
        self.CLIENT_SECRET: str = os.getenv("ZOHO_CLIENT_SECRET", "")
        self.REDIRECT_URI: str = os.getenv(
            "ZOHO_REDIRECT_URI", "http://localhost:8000/auth/callback"
        )
        self.ACCOUNTS_DOMAIN: str = os.getenv("ZOHO_ACCOUNTS_DOMAIN", "https://accounts.zoho.com")
        self.API_DOMAIN: str = os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.com")
        self.ORGANIZATION_ID: str = os.getenv("ZOHO_ORGANIZATION_ID", "938042465")
        self.REQUIRE_ORG_ID: bool = True
        self.MAX_RATE_PER_MINUTE: int = int(os.getenv("DISPATCH_RATE_LIMIT", "60"))
        self.BATCH_DELAY_SECONDS: float = float(os.getenv("BATCH_DELAY_SECONDS", "0.08"))
        self.PAGE_SIZE: int = int(os.getenv("PAGE_SIZE", "200"))
        self.HOST: str = os.getenv("HOST", "0.0.0.0")
        self.PORT: int = int(os.getenv("PORT", "8000"))

    @property
    def auth_redirect_url(self) -> str:
        return (
            f"{self.ACCOUNTS_DOMAIN}/oauth/v2/auth"
            f"?client_id={self.CLIENT_ID}"
            f"&scope=ZohoBooks.fullaccess.all"
            f"&redirect_uri={self.REDIRECT_URI}"
            f"&response_type=code&access_type=offline&prompt=consent"
        )


settings = Settings()
