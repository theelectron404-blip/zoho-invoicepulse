# =============================================================================
#  InvoicePulse Pro — FastAPI Server with Multi-Product Invoicing & Zoho Dispatch
# =============================================================================

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings
from database import TRANSPARENT_GIF_BYTES, get_db_connection
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from queue_engine import queue_engine
from tracker import record_open_event
from zoho_auth import auth_manager
from zoho_client import ZohoAPIException, zoho_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("server")

app = FastAPI(
    title="InvoicePulse Pro - Bulk Invoicing & Open Tracking Platform",
    version="2.1.0",
    description="Enterprise bulk invoice dispatch engine with multi-product line items, transparent open tracking, and Zoho Books API integration",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request Models ---
class ProductItem(BaseModel):
    name: str
    description: Optional[str] = ""
    rate: float = 100.0
    quantity: float = 1.0
    unit: Optional[str] = "Qty"


class CustomerCreateRequest(BaseModel):
    name: str
    email: str
    company: Optional[str] = "Company"
    amount: Optional[float] = 1500.0
    due_date: Optional[str] = "2026-09-30"


class DirectSendRecipient(BaseModel):
    name: str
    email: str
    company: Optional[str] = "Company"
    amount: Optional[float] = 1500.0
    due_date: Optional[str] = "2026-09-30"
    po_number: Optional[str] = "PO-001"
    items: Optional[List[ProductItem]] = None
    variables: Optional[Dict[str, Any]] = None


class DirectDispatchRequest(BaseModel):
    recipients: List[DirectSendRecipient]
    subject: Optional[str] = None
    html_body: Optional[str] = None
    default_items: Optional[List[ProductItem]] = None


class ConfigPayload(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    organization_id: Optional[str] = None
    accounts_domain: Optional[str] = None
    api_domain: Optional[str] = None


# --- 1. Settings & Config Endpoint ---

@app.get("/api/config", summary="Get Current Zoho API Config")
def get_config():
    return {
        "client_id": settings.CLIENT_ID,
        "client_secret": "••••••••••••••••" if settings.CLIENT_SECRET else "",
        "organization_id": settings.ORGANIZATION_ID,
        "accounts_domain": settings.ACCOUNTS_DOMAIN,
        "api_domain": settings.API_DOMAIN,
        "redirect_uri": settings.REDIRECT_URI,
        "authenticated": auth_manager.is_authenticated(),
    }


@app.post("/api/config", summary="Save Zoho API Keys")
def save_config(cfg: ConfigPayload):
    env_path = Path(__file__).resolve().parent / ".env"

    if cfg.client_id:
        settings.CLIENT_ID = cfg.client_id
    if cfg.client_secret and "•" not in cfg.client_secret:
        settings.CLIENT_SECRET = cfg.client_secret
    if cfg.organization_id:
        settings.ORGANIZATION_ID = cfg.organization_id
    if cfg.accounts_domain:
        settings.ACCOUNTS_DOMAIN = cfg.accounts_domain
    if cfg.api_domain:
        settings.API_DOMAIN = cfg.api_domain

    env_content = f"""ZOHO_CLIENT_ID={settings.CLIENT_ID}
ZOHO_CLIENT_SECRET={settings.CLIENT_SECRET}
ZOHO_REDIRECT_URI={settings.REDIRECT_URI}
ZOHO_ACCOUNTS_DOMAIN={settings.ACCOUNTS_DOMAIN}
ZOHO_API_DOMAIN={settings.API_DOMAIN}
ZOHO_ORGANIZATION_ID={settings.ORGANIZATION_ID}
BATCH_DELAY_SECONDS={settings.BATCH_DELAY_SECONDS}
"""
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(env_content)

    queue_engine.log("SUCCESS", "Updated and saved Zoho Books API credentials to .env")
    return {"status": "success", "message": "Credentials saved successfully!"}


# --- 2. Open & Read Tracking Pixel Route ---

@app.get("/api/track/open/{tracking_id}.gif", summary="Serve 1x1 Transparent Tracking Pixel")
async def track_email_open(
    tracking_id: str,
    request: Request,
    user_agent: Optional[str] = Header(None),
):
    client_ip = request.client.host if request.client else "127.0.0.1"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    try:
        is_first_open, inv = record_open_event(
            tracking_id=tracking_id,
            ip_address=client_ip,
            user_agent=user_agent or "Unknown Client",
        )
        if inv:
            status_text = "FIRST OPEN" if is_first_open else "REPEAT OPEN"
            queue_engine.log(
                "SUCCESS" if is_first_open else "INFO",
                f"[{status_text}] {inv['invoice_number']} opened by {inv['email']} (IP: {client_ip})",
                invoice_number=inv["invoice_number"],
            )
    except Exception as exc:
        logger.error(f"Error logging open tracking event for {tracking_id}: {exc}")

    return Response(
        content=TRANSPARENT_GIF_BYTES,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0, proxy-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*",
        },
    )


# --- 3. Synchronous Direct Dispatch via Zoho ---

@app.post("/api/send-direct", summary="Send Invoices Synchronously via Zoho")
def send_direct_via_zoho(req: DirectDispatchRequest):
    """Creates customer and multi-product invoice in Zoho Books, then dispatches email via Zoho Books servers."""
    if not auth_manager.is_authenticated():
        raise HTTPException(status_code=400, detail="Not authorized with Zoho Books. Please authorize in Settings first.")

    results = []
    for r in req.recipients:
        try:
            # 1. Customer
            cid = zoho_client.get_or_create_customer(r.name, r.email, r.company)

            # 2. Line Items (multi-product or single rate)
            line_items = []
            if r.items and len(r.items) > 0:
                line_items = [it.dict() for it in r.items]
            elif req.default_items and len(req.default_items) > 0:
                line_items = [it.dict() for it in req.default_items]
            else:
                line_items = [{
                    "name": "Professional Services",
                    "description": f"Invoice billing for {r.name}",
                    "rate": float(r.amount or 1500.0),
                    "quantity": 1,
                    "unit": "Qty",
                }]

            total_amount = sum(it.get("rate", 0) * it.get("quantity", 1) for it in line_items)

            # 3. Create Real Multi-Product Invoice in Zoho Books
            inv = zoho_client.create_invoice_with_items(
                customer_id=cid,
                line_items=line_items,
                due_date=r.due_date,
                notes=f"Invoice for {r.name} (PO: {r.po_number})",
            )
            invid = str(inv["invoice_id"])
            invnum = inv.get("invoice_number", f"INV-{invid}")

            # 4. Generate Tracking ID & inject
            from tracker import generate_tracking_token, inject_tracking_pixel
            tracking_id = generate_tracking_token(invnum, r.email)

            # Dynamic Subject & Body Substitution
            subject = req.subject or f"Invoice #{invnum} from {r.company}"
            body = req.html_body or f"<p>Hello {r.name},</p><p>Please find attached your invoice #{invnum} for ${total_amount:,.2f}.</p>"

            # Replace custom variables
            all_vars = {
                "client_name": r.name,
                "invoice_number": invnum,
                "amount": f"{total_amount:,.2f}",
                "company_name": r.company or "Company",
                "due_date": r.due_date or "2026-09-30",
                "po_number": r.po_number or "PO-001",
                "tracking_id": tracking_id,
            }
            if r.variables:
                all_vars.update(r.variables)

            for k, v in all_vars.items():
                subject = subject.replace(f"{{{{{k}}}}}", str(v))
                body = body.replace(f"{{{{{k}}}}}", str(v))

            body = inject_tracking_pixel(body, tracking_id)

            # 5. Record to local DB
            with get_db_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO invoices (
                        invoice_number, zoho_invoice_id, client_name, company, email,
                        amount, due_date, status, tracking_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Sent', ?)
                    """,
                    (invnum, invid, r.name, r.company, r.email, total_amount, r.due_date, tracking_id),
                )
                conn.commit()

            # 6. SEND EMAIL VIA ZOHO OWN SERVERS
            zoho_res = zoho_client.send_invoice_email(
                invoice_id=invid,
                to_mail_ids=[r.email],
                subject=subject,
                body=body,
                send_attachment=True,
            )

            queue_engine.log("SUCCESS", f"Sent invoice {invnum} to {r.email} directly via Zoho Books servers!", invnum)
            results.append({"email": r.email, "invoiceNumber": invnum, "status": "Sent", "zohoResponse": zoho_res})

        except Exception as e:
            err_msg = str(e)
            queue_engine.log("ERROR", f"Failed dispatch to {r.email}: {err_msg}")
            results.append({"email": r.email, "status": "Failed", "error": err_msg})

    return {"status": "complete", "results": results}


# --- 4. Queue & Metrics Endpoints ---

@app.get("/api/metrics", summary="Get Live Aggregated KPI Analytics")
def get_metrics():
    return queue_engine.get_metrics()


@app.get("/api/queue", summary="Get Paginated Invoices with Filtering")
def get_queue(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    status: str = Query("All"),
    search: str = Query(""),
):
    return queue_engine.get_paginated_invoices(
        page=page,
        limit=limit,
        status=status,
        search=search,
    )


@app.get("/api/logs", summary="Stream Execution & Telemetry Logs")
def get_logs():
    return {"logs": queue_engine.logs}


# --- 5. Zoho Books OAuth Endpoints ---

@app.get("/auth/login", summary="Initiate Zoho Books OAuth")
def oauth_login():
    if not settings.CLIENT_ID or not settings.CLIENT_SECRET:
        raise HTTPException(status_code=400, detail="ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET are required.")
    return RedirectResponse(url=settings.auth_redirect_url)


@app.get("/auth/callback", summary="Zoho OAuth Redirect Callback")
def oauth_callback(code: Optional[str] = None, error: Optional[str] = None):
    if error:
        return HTMLResponse(f"<h2>Auth Failed</h2><p>{error}</p><a href='/'>Back</a>", status_code=400)
    if not code:
        raise HTTPException(status_code=400, detail="Missing auth code.")
    try:
        auth_manager.exchange_code_for_tokens(code)
        queue_engine.log("SUCCESS", "Successfully authorized with Zoho Books API via OAuth 2.0.")
        return RedirectResponse(url="/?auth_success=true")
    except Exception as exc:
        return HTMLResponse(f"<h2>Token Exchange Error</h2><p>{exc}</p><a href='/'>Back</a>", status_code=500)


@app.get("/auth/status", summary="Get Current OAuth Status")
def get_auth_status():
    return auth_manager.get_status()


# --- 6. SPA Host ---

index_file = Path(__file__).resolve().parent.parent / "index.html"


@app.get("/", response_class=HTMLResponse, summary="Serve UI Control Dashboard")
def serve_dashboard():
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Dashboard index.html not found.</h1>", status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=settings.HOST, port=settings.PORT, reload=True)
