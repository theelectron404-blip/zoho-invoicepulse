# =============================================================================
#  InvoicePulse Pro — Bulk Dispatch Async Queue Engine (Zoho Server Delivery)
# =============================================================================

import asyncio
import datetime
import logging
from typing import Any, Dict, List, Optional

from config import settings
from database import get_db_connection
from tracker import generate_tracking_token, inject_tracking_pixel
from zoho_auth import auth_manager
from zoho_client import ZohoAPIException, zoho_client

logger = logging.getLogger("queue_engine")


class BulkQueueEngine:
    """Async dispatch worker that creates invoices and sends via Zoho Books."""

    def __init__(self) -> None:
        self.is_running: bool = False
        self.progress_percent: float = 0.0
        self.logs: List[Dict[str, Any]] = []
        self.rate_limit_delay: float = settings.BATCH_DELAY_SECONDS

    def log(self, level: str, message: str, invoice_number: Optional[str] = None) -> None:
        now_time = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {
            "time": now_time,
            "level": level.upper(),
            "msg": message,
            "invoiceNumber": invoice_number,
        }
        self.logs.append(entry)
        if len(self.logs) > 350:
            self.logs.pop(0)

        try:
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO batch_logs (level, message, invoice_number) VALUES (?, ?, ?)",
                    (level.upper(), message, invoice_number),
                )
                conn.commit()
        except Exception:
            pass

        logger.info(f"[{entry['level']}] {message}")

    def get_metrics(self) -> Dict[str, Any]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'Queued' THEN 1 ELSE 0 END) as queued,
                    SUM(CASE WHEN status = 'Sent' THEN 1 ELSE 0 END) as sent,
                    SUM(CASE WHEN status = 'Delivered' THEN 1 ELSE 0 END) as delivered,
                    SUM(CASE WHEN status = 'Opened' THEN 1 ELSE 0 END) as opened,
                    SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) as failed,
                    SUM(amount) as total_revenue,
                    SUM(open_count) as total_open_events
                FROM invoices
            """)
            row = cursor.fetchone()

            total = row["total"] or 0
            queued = row["queued"] or 0
            sent = row["sent"] or 0
            delivered = row["delivered"] or 0
            opened = row["opened"] or 0
            failed = row["failed"] or 0
            total_rev = row["total_revenue"] or 0.0
            total_opens = row["total_open_events"] or 0

            successful_dispatches = sent + delivered + opened
            open_rate = (opened / successful_dispatches * 100) if successful_dispatches > 0 else 0.0

            return {
                "total": total,
                "queued": queued,
                "sent": sent,
                "delivered": delivered,
                "opened": opened,
                "failed": failed,
                "successfulDispatches": successful_dispatches,
                "openRate": round(open_rate, 1),
                "totalRevenue": round(total_rev, 2),
                "totalOpenEvents": total_opens,
                "isRunning": self.is_running,
                "progress": round(self.progress_percent, 1),
            }

    def get_paginated_invoices(
        self,
        page: int = 1,
        limit: int = 100,
        status: str = "All",
        search: str = "",
    ) -> Dict[str, Any]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            conditions = []
            params: List[Any] = []

            if status and status != "All":
                conditions.append("status = ?")
                params.append(status)

            if search:
                s = f"%{search.strip().lower()}%"
                conditions.append("(LOWER(client_name) LIKE ? OR LOWER(email) LIKE ? OR LOWER(invoice_number) LIKE ? OR LOWER(company) LIKE ?)")
                params.extend([s, s, s, s])

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            cursor.execute(f"SELECT COUNT(*) as cnt FROM invoices {where_clause}", params)
            total_count = cursor.fetchone()["cnt"]

            total_pages = max(1, (total_count + limit - 1) // limit)
            offset = (page - 1) * limit

            cursor.execute(
                f"""
                SELECT id, invoice_number as invoiceNumber, zoho_invoice_id as zohoInvoiceId,
                       client_name as clientName, company, email, amount, currency,
                       due_date as dueDate, status, tracking_id as trackingId,
                       attempts, last_error as lastError, open_count as openCount
                FROM invoices
                {where_clause}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            )
            rows = [dict(r) for r in cursor.fetchall()]

            return {
                "items": rows,
                "total": total_count,
                "page": page,
                "limit": limit,
                "totalPages": total_pages,
            }

    async def add_and_queue_customer(
        self,
        name: str,
        email: str,
        company: str = "Company",
        amount: float = 1500.0,
        due_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        inv_num = f"INV-2026-{int(datetime.datetime.now().timestamp()) % 100000}"
        tracking_id = generate_tracking_token(inv_num, email)

        zoho_id = None
        if auth_manager.is_authenticated():
            try:
                cust_id = zoho_client.find_or_create_contact(name, email, company)
                zoho_inv = zoho_client.create_invoice(
                    customer_id=cust_id,
                    amount=amount,
                    due_date=due_date,
                    notes=f"Invoice {inv_num} for {name}",
                )
                zoho_id = str(zoho_inv.get("invoice_id"))
                inv_num = zoho_inv.get("invoice_number", inv_num)
                self.log("SUCCESS", f"Created real invoice in Zoho Books: {inv_num} (ID: {zoho_id})")
            except Exception as e:
                self.log("WARN", f"Could not pre-create in Zoho Books: {e}. Will create during dispatch.")

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO invoices (
                    invoice_number, zoho_invoice_id, client_name, company, email,
                    amount, due_date, status, tracking_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Queued', ?)
                """,
                (inv_num, zoho_id, name, company, email, amount, due_date or "2026-09-30", tracking_id),
            )
            conn.commit()
            new_id = cursor.lastrowid

        return {
            "id": new_id,
            "invoiceNumber": inv_num,
            "zohoInvoiceId": zoho_id,
            "clientName": name,
            "email": email,
            "amount": amount,
            "status": "Queued",
            "trackingId": tracking_id,
        }

    async def start_dispatch_job(
        self,
        item_ids: Optional[List[int]] = None,
        custom_subject: Optional[str] = None,
        custom_html_template: Optional[str] = None,
    ) -> None:
        """Dispatches invoices directly using Zoho Books' own mail servers with try/finally reset."""
        if self.is_running:
            self.log("WARN", "Dispatch job already running. Resetting stale job state...")
            self.is_running = False

        self.is_running = True
        self.progress_percent = 0.0

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                if item_ids:
                    placeholders = ",".join("?" * len(item_ids))
                    cursor.execute(f"SELECT * FROM invoices WHERE id IN ({placeholders})", item_ids)
                else:
                    cursor.execute("SELECT * FROM invoices WHERE status IN ('Queued', 'Failed')")
                target_rows = [dict(r) for r in cursor.fetchall()]

            if not target_rows:
                self.log("INFO", "No queued invoices to dispatch.")
                return

            total_count = len(target_rows)
            self.log("INFO", f"Sending {total_count} invoices directly through Zoho Books server...")

            processed = 0
            for idx, item in enumerate(target_rows, start=1):
                inv_id = item["id"]
                inv_num = item["invoice_number"]
                email = item["email"]
                name = item["client_name"]
                amount = item["amount"]
                company = item["company"]
                due_date = item["due_date"]
                tracking_id = item["tracking_id"]
                zoho_invoice_id = item.get("zoho_invoice_id")

                base_body = custom_html_template or (
                    f"<p>Hello {name},</p><p>Please find attached your invoice <b>#{inv_num}</b> for ${amount:,.2f}.</p>"
                )
                tracked_html = base_body.replace("{{client_name}}", name).replace("{{invoice_number}}", inv_num).replace("{{amount}}", f"{amount:,.2f}")
                tracked_html = inject_tracking_pixel(tracked_html, tracking_id)

                subject = custom_subject or f"Invoice #{inv_num} from {company}"
                subject = subject.replace("{{invoice_number}}", inv_num).replace("{{company_name}}", company)

                try:
                    if not zoho_invoice_id:
                        self.log("INFO", f"[{idx}/{total_count}] Creating contact and invoice in Zoho Books for {name} ({email})...", inv_num)
                        cust_id = zoho_client.find_or_create_contact(name, email, company)
                        created_inv = zoho_client.create_invoice(
                            customer_id=cust_id,
                            amount=amount,
                            due_date=due_date,
                            notes=f"Invoice {inv_num}",
                        )
                        zoho_invoice_id = str(created_inv["invoice_id"])
                        inv_num = created_inv.get("invoice_number", inv_num)

                    self.log("INFO", f"[{idx}/{total_count}] Dispatching email via Zoho Books mail servers to {email}...", inv_num)
                    zoho_client.send_invoice_email(
                        invoice_id=zoho_invoice_id,
                        to_mail_ids=[email],
                        subject=subject,
                        body=tracked_html,
                        send_attachment=True,
                    )

                    now_iso = datetime.datetime.now().isoformat()
                    with get_db_connection() as conn:
                        conn.execute(
                            """
                            UPDATE invoices
                            SET status = 'Sent',
                                zoho_invoice_id = ?,
                                invoice_number = ?,
                                attempts = attempts + 1,
                                last_error = NULL,
                                sent_at = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (zoho_invoice_id, inv_num, now_iso, now_iso, inv_id),
                        )
                        conn.commit()

                    self.log("SUCCESS", f"[{idx}/{total_count}] Email successfully delivered by Zoho server to {email} for {inv_num}!", inv_num)

                except Exception as exc:
                    err_msg = str(exc)
                    self.log("ERROR", f"[{idx}/{total_count}] Failed to send via Zoho server: {err_msg}", inv_num)
                    with get_db_connection() as conn:
                        conn.execute(
                            "UPDATE invoices SET status = 'Failed', last_error = ?, attempts = attempts + 1 WHERE id = ?",
                            (err_msg, inv_id),
                        )
                        conn.commit()

                processed += 1
                self.progress_percent = (processed / total_count) * 100.0
                await asyncio.sleep(self.rate_limit_delay)

            self.log("SUCCESS", f"Bulk dispatch run complete! Processed {processed} invoices through Zoho Books.")

        finally:
            self.is_running = False
            self.progress_percent = 100.0


queue_engine = BulkQueueEngine()
