# =============================================================================
#  InvoicePulse Pro — Email Tracking & Cryptographic Beacon Engine
#
#  Features:
#    1. HMAC-signed, tamper-proof tracking token generation (SHA-256)
#    2. 1x1 transparent tracking pixel injection into HTML templates
#    3. Deduplication window (e.g. 5 minutes) to filter spam scanners / duplicate opens
#    4. IP address and User-Agent telemetry capture with invoice status transition
# =============================================================================

import datetime
import hashlib
import hmac
import logging
import os
import uuid
from typing import Any, Dict, Optional, Tuple

from config import settings
from database import TRANSPARENT_GIF_BYTES, get_db_connection

logger = logging.getLogger("tracker")

# Secret key for HMAC token signing (configurable in .env)
TRACKING_SECRET = os.getenv("TRACKING_SECRET", "inv_pulse_sec_9942a781b092fec442")
DEDUPLICATION_WINDOW_SECONDS = int(os.getenv("TRACKING_DEDUP_WINDOW_SECONDS", "180"))


def generate_tracking_token(invoice_number: str, recipient_email: str) -> str:
    """Generate a tamper-proof HMAC-signed tracking token for an invoice.

    Format: <uuid_prefix>.<signature_hash>
    """
    token_base = f"{invoice_number}:{recipient_email}:{uuid.uuid4().hex[:12]}"
    signature = hmac.new(
        TRACKING_SECRET.encode("utf-8"),
        token_base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f"{uuid.uuid4().hex[:8]}_{signature}"


def inject_tracking_pixel(html_content: str, tracking_id: str, base_url: Optional[str] = None) -> str:
    """Inject a hidden 1x1 tracking pixel before the closing </body> tag.

    If </body> is absent, the beacon is appended at the end of the markup.
    """
    host = base_url or f"http://localhost:{settings.PORT}"
    pixel_url = f"{host}/api/track/open/{tracking_id}.gif"

    beacon_tag = (
        f'\n<!-- InvoicePulse Engagement Beacon -->\n'
        f'<img src="{pixel_url}" alt="" width="1" height="1" '
        f'style="display:none !important; width:1px !important; height:1px !important; border:0 !important; margin:0 !important; padding:0 !important; visibility:hidden !important;" />\n'
    )

    if "</body>" in html_content:
        return html_content.replace("</body>", f"{beacon_tag}</body>")
    return html_content + beacon_tag


def record_open_event(
    tracking_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Record an email open engagement event with deduplication logic.

    Returns:
        (is_first_open: bool, invoice_dict: Optional[Dict])
    """
    now_iso = datetime.datetime.now().isoformat()
    now_ts = datetime.datetime.now()

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Fetch matching invoice by tracking_id
        cursor.execute("SELECT * FROM invoices WHERE tracking_id = ?", (tracking_id,))
        row = cursor.fetchone()
        if not row:
            logger.warning(f"Tracking beacon requested with unrecognized token: {tracking_id}")
            return (False, None)

        invoice_id = row["id"]
        current_status = row["status"]
        last_opened_at = row["last_opened_at"]
        open_count = row["open_count"] or 0

        # 2. Deduplication check (avoid rapid consecutive pings from proxy scanners)
        is_duplicate = False
        if last_opened_at:
            try:
                last_dt = datetime.datetime.fromisoformat(last_opened_at)
                diff_seconds = (now_ts - last_dt).total_seconds()
                if diff_seconds < DEDUPLICATION_WINDOW_SECONDS:
                    is_duplicate = True
            except Exception:
                pass

        # 3. Log open event in email_open_logs
        cursor.execute(
            """
            INSERT INTO email_open_logs (tracking_id, invoice_id, ip_address, user_agent, is_deduplicated, opened_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tracking_id, invoice_id, ip_address or "127.0.0.1", user_agent or "Unknown Client", 1 if is_duplicate else 0, now_iso),
        )

        # 4. Update invoice open telemetry & status
        new_open_count = open_count + 1
        first_open = row["first_opened_at"] or now_iso

        cursor.execute(
            """
            UPDATE invoices
            SET status = 'Opened',
                first_opened_at = COALESCE(first_opened_at, ?),
                last_opened_at = ?,
                open_count = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (first_open, now_iso, new_open_count, now_iso, invoice_id),
        )
        conn.commit()

        logger.info(
            f"Logged email open for {row['invoice_number']} ({row['email']}) "
            f"from IP {ip_address}. Total opens: {new_open_count} (Dedup: {is_duplicate})"
        )

        return (open_count == 0, dict(row))
