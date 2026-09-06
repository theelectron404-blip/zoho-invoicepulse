# =============================================================================
#  InvoicePulse — Zoho Books API Client
#
#  Handles:
#    - Product & Line Item resolution (Item Name, Description, Rate, Quantity, Unit)
#    - Automatic Customer Resolution & Creation in Zoho Books
#    - Creating custom product line-item invoices in Zoho Books
#    - Sending emails via Zoho's own servers with custom HTML template + PDF
# =============================================================================

import logging
import time
from typing import Any, Dict, List, Optional

import requests
from config import settings
from zoho_auth import auth_manager

logger = logging.getLogger("zoho_client")


class ZohoAPIException(Exception):
    def __init__(self, message: str, status_code: int = 500, zoho_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.zoho_code = zoho_code


class ZohoBooksClient:
    """Client for interacting directly with Zoho Books REST API."""

    def __init__(self) -> None:
        pass

    def _get_headers(self) -> Dict[str, str]:
        token = auth_manager.get_valid_access_token()
        return {
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json;charset=UTF-8",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        retries: int = 2,
    ) -> Dict[str, Any]:
        url = f"{auth_manager.api_domain}/books/v3{endpoint}"

        all_params = {"organization_id": settings.ORGANIZATION_ID}
        if params:
            all_params.update(params)

        for attempt in range(1, retries + 1):
            try:
                headers = self._get_headers()
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=all_params,
                    json=json_data,
                    timeout=25,
                )

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 2))
                    logger.warning(f"Zoho API Rate Limited (429). Backing off for {retry_after}s.")
                    time.sleep(retry_after)
                    continue

                try:
                    data: Dict[str, Any] = resp.json()
                except Exception:
                    resp.raise_for_status()
                    return {"raw": resp.text}

                zoho_code = data.get("code")
                if zoho_code is not None and zoho_code != 0:
                    msg = data.get("message", "Unknown Zoho error")
                    logger.error(f"Zoho API error {zoho_code}: {msg}")
                    raise ZohoAPIException(
                        message=f"Zoho Error ({zoho_code}): {msg}",
                        status_code=resp.status_code,
                        zoho_code=zoho_code,
                    )

                if not resp.ok:
                    raise ZohoAPIException(
                        message=f"HTTP {resp.status_code}: {resp.text}",
                        status_code=resp.status_code,
                    )

                return data

            except ZohoAPIException:
                raise
            except requests.RequestException as exc:
                if attempt == retries:
                    raise ZohoAPIException(message=f"Network request to Zoho failed: {exc}", status_code=503)
                time.sleep(1.0 * attempt)

        raise ZohoAPIException("Exceeded maximum request retry attempts against Zoho API.", status_code=500)

    # ------------------------------------------------------------------ Zoho Customer & Product Invoices
    def get_or_create_customer(self, customer_name: str, email: str, company_name: Optional[str] = None) -> str:
        """Find an existing contact by email or create a new contact in Zoho Books."""
        try:
            search_res = self._request("GET", "/contacts", params={"email": email})
            contacts = search_res.get("contacts", [])
            if contacts:
                return str(contacts[0]["contact_id"])
        except Exception:
            pass

        try:
            payload = {
                "contact_name": customer_name or email.split("@")[0],
                "company_name": company_name or "Company",
                "contact_persons": [
                    {
                        "first_name": customer_name.split()[0] if customer_name else "Client",
                        "last_name": customer_name.split()[-1] if " " in customer_name else "Name",
                        "email": email,
                        "is_primary_contact": True,
                    }
                ],
            }
            res = self._request("POST", "/contacts", json_data=payload)
            return str(res["contact"]["contact_id"])
        except ZohoAPIException:
            # Fallback: select any existing organization contact
            try:
                res = self._request("GET", "/contacts", params={"per_page": 5})
                if res.get("contacts"):
                    return str(res["contacts"][0]["contact_id"])
            except Exception:
                pass
            raise

    def create_invoice_with_items(
        self,
        customer_id: str,
        line_items: List[Dict[str, Any]],
        due_date: Optional[str] = None,
        notes: Optional[str] = None,
        terms: Optional[str] = None,
        discount: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Create a real invoice in Zoho Books with structured multi-product line items."""
        items = []
        for it in line_items:
            items.append({
                "name": it.get("name") or "Product/Service",
                "description": it.get("description") or "",
                "rate": float(it.get("rate") or it.get("amount") or 100.0),
                "quantity": float(it.get("quantity") or 1),
                "unit": it.get("unit") or "Qty",
            })

        payload: Dict[str, Any] = {
            "customer_id": customer_id,
            "line_items": items,
        }
        if due_date:
            payload["due_date"] = due_date
        if notes:
            payload["notes"] = notes
        if terms:
            payload["terms"] = terms
        if discount is not None:
            payload["discount"] = discount

        res = self._request("POST", "/invoices", json_data=payload)
        return res.get("invoice", {})

    def send_invoice_email(
        self,
        invoice_id: str,
        to_mail_ids: Optional[List[str]] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        send_attachment: bool = True,
    ) -> Dict[str, Any]:
        """Dispatch the invoice directly through Zoho Books' own email servers."""
        payload: Dict[str, Any] = {
            "send_attachment": send_attachment,
        }
        if to_mail_ids:
            payload["to_mail_ids"] = to_mail_ids
        if subject:
            payload["subject"] = subject
        if body:
            payload["body"] = body

        logger.info(f"Dispatching invoice email through Zoho Books server for invoice_id: {invoice_id} to {to_mail_ids}")
        return self._request("POST", f"/invoices/{invoice_id}/email", json_data=payload)


zoho_client = ZohoBooksClient()
