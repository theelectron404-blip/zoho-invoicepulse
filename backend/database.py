# =============================================================================
#  InvoicePulse Pro — Database Layer (SQLite with WAL mode)
#
#  Stores:
#    1. Invoices & dispatch queue state (Queued, Sent, Delivered, Opened, Failed)
#    2. Email open events with IP, User-Agent, geo, and deduplication
#    3. Batch dispatch run telemetry and dead-letter logs
# =============================================================================

import datetime
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("database")

DB_PATH = Path(__file__).resolve().parent / "invoicepulse.db"

# 1x1 transparent GIF binary (43 bytes standard transparent gif)
TRANSPARENT_GIF_BYTES = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01"
    b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


def get_db_connection() -> sqlite3.Connection:
    """Create a thread-safe connection to SQLite with WAL mode enabled."""
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db() -> None:
    """Initialize relational database tables and performance indexes."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Invoices / Queue table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT NOT NULL UNIQUE,
            zoho_invoice_id TEXT,
            client_name TEXT NOT NULL,
            company TEXT NOT NULL,
            email TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            due_date TEXT,
            status TEXT DEFAULT 'Queued', -- 'Queued', 'Sent', 'Delivered', 'Opened', 'Failed'
            tracking_id TEXT UNIQUE NOT NULL,
            attempts INTEGER DEFAULT 0,
            last_error TEXT,
            sent_at TEXT,
            delivered_at TEXT,
            first_opened_at TEXT,
            last_opened_at TEXT,
            open_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Email open tracking events table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_open_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_id TEXT NOT NULL,
            invoice_id INTEGER NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            is_deduplicated INTEGER DEFAULT 0,
            opened_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id)
        );
        """)

        # Execution batch run logs
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS batch_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            invoice_number TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Indexes for high-throughput lookup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_tracking_id ON invoices(tracking_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_open_logs_tracking ON email_open_logs(tracking_id);")

        conn.commit()
        logger.info("Initialized InvoicePulse SQLite database with WAL mode.")


# Run migration on module load
init_db()
