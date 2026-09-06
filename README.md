# InvoicePulse Pro — Zoho Books Bulk Invoicing & Dispatch System

A production-ready enterprise engine and interactive control dashboard built to manage, track, and bulk-dispatch **400+ invoices simultaneously** with the **Zoho Books API**.

---

## 🏗 System Architecture

- **Backend (Python / FastAPI)**:
  - **`zoho_auth.py`**: Complete OAuth 2.0 flow with offline refresh token persistence and automated transparent token refreshes.
  - **`zoho_client.py`**: Robust REST client for Zoho Books API (invoices list, email dispatch, rate limit backoff retry with HTTP 429 detection).
  - **`queue_engine.py`**: High-performance asynchronous queue orchestrator managing 400+ items, rate-limiting delays, live telemetry logging, and pause/resume capabilities.
  - **`app.py`**: REST API endpoints for queue management, batch triggers, status polling, and single-page dashboard serving.
- **Frontend (Tailwind CSS + React + Recharts)**:
  - Real-time KPI metrics, dispatch velocity area charts, queue distribution donut charts, interactive paginated data table (400 items), split-screen HTML template editor with live dynamic token hydration, and streaming execution logs.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.9+ installed
- Zoho Books account (free trial or active organization)

### 2. Install Dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure Zoho Books API Credentials

1. Go to the [Zoho Developer API Console](https://api-console.zoho.com/).
2. Click **Add Client** and select **Server-based Applications**.
3. Fill in the fields:
   - **Client Name**: `InvoicePulse Bulk Dispatcher`
   - **Homepage URL**: `http://localhost:8000`
   - **Authorized Redirect URIs**: `http://localhost:8000/auth/callback`
4. Click **Create**. Copy the generated **Client ID** and **Client Secret**.
5. Copy `.env.example` to `.env` in the `backend/` folder:
   ```bash
   cp .env.example .env
   ```
6. Open `.env` and fill in your values:
   ```ini
   ZOHO_CLIENT_ID=your_client_id_here
   ZOHO_CLIENT_SECRET=your_client_secret_here
   ZOHO_REDIRECT_URI=http://localhost:8000/auth/callback
   ZOHO_ORGANIZATION_ID=your_zoho_org_id_here
   ZOHO_ACCOUNTS_DOMAIN=https://accounts.zoho.com
   ZOHO_API_DOMAIN=https://www.zohoapis.com
   ```
   *(Note: You can find your Zoho Books Organization ID in your Zoho Books URL: `https://books.zoho.com/app/<ORGANIZATION_ID>#/home`)*

### 4. Start the Application
```bash
cd backend
python app.py
```
Or with Uvicorn directly:
```bash
uvicorn app:app --reload --port 8000
```

### 5. Access the Dashboard
Open your browser and navigate to:
```
http://localhost:8000
```

---

## 🔑 Authentication Workflow

1. Click **"Connect Zoho Books"** in the top navigation or navigate to `http://localhost:8000/auth/login`.
2. Authorize the application with the required scopes:
   - `ZohoBooks.invoices.CREATE`
   - `ZohoBooks.invoices.READ`
   - `ZohoBooks.contacts.READ`
3. Zoho will redirect to `http://localhost:8000/auth/callback`, which automatically exchanges the authorization code for an `access_token` and `refresh_token`, storing them securely in `backend/tokens.json`.
4. Subsequent API calls automatically refresh the access token before it expires.

---

## 📡 API Endpoints Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/auth/login` | Initiates Zoho OAuth 2.0 authorization redirect |
| `GET` | `/auth/callback` | OAuth redirect callback handler |
| `GET` | `/auth/status` | Returns authentication and token status |
| `POST` | `/auth/refresh` | Forces an immediate token refresh |
| `GET` | `/api/metrics` | Returns live KPI counts and revenue metrics |
| `GET` | `/api/queue` | Paginated queue records with search and status filters |
| `POST` | `/api/queue/dispatch` | Triggers the asynchronous bulk dispatch engine |
| `POST` | `/api/queue/retry` | Re-queues failed items to Pending status |
| `POST` | `/api/queue/reset` | Resets/regenerates 400 simulated queue items |
| `GET` | `/api/logs` | Returns live execution log telemetry stream |
| `POST` | `/api/zoho/sync` | Pulls real unsent draft invoices from Zoho Books API |

---

## 🛡 Rate Limiting & Error Handling

- **Automatic 429 Detection**: When Zoho's API threshold is reached, the client inspects the `Retry-After` header and applies exponential backoff rather than terminating the batch.
- **Batch Throttle Controls**: Configurable request spacing (`BATCH_DELAY_SECONDS`) to maintain consistent compliance with Zoho's quota limits.
- **Isolated Queue Exceptions**: Failed individual emails (e.g. invalid client email addresses, SMTP timeout) are tagged with specific error reasons without interrupting the remainder of the 400-item queue.
