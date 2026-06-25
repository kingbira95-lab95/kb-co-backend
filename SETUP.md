# KB & Co Backend — Setup Guide

## Prerequisites
- Python 3.11+ (Python 3.13 tested)
- PostgreSQL 15+ running locally
- (Optional) Redis for caching

---

## 1. Create the PostgreSQL database

```bash
psql -U postgres
CREATE DATABASE kbco;
\q
```

---

## 2. Configure environment variables

```bash
copy .env.example .env
```

Open `.env` and fill in:

| Variable | Description |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/kbco` |
| `SECRET_KEY` | Random 64-char string (use `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `GOOGLE_CLIENT_ID` | From Google Cloud Console → OAuth 2.0 Credentials |
| `GOOGLE_CLIENT_SECRET` | Same credential |
| `FLW_SECRET_KEY` | Flutterwave Dashboard → API Keys |
| `FLW_PUBLIC_KEY` | Flutterwave Dashboard → API Keys |
| `FLW_WEBHOOK_SECRET` | Set in Flutterwave webhook settings |
| `TERMII_API_KEY` | From termii.com dashboard |
| `SMTP_USER` | Gmail address (enable App Passwords) |
| `SMTP_PASSWORD` | Gmail App Password |

---

## 3. Install dependencies & start

```bash
pip install -r requirements.txt
python run.py
```

The server starts at **http://localhost:8000**

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

---

## 4. Google OAuth setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → APIs & Services → Credentials → OAuth 2.0 Client ID
3. Application type: **Web application**
4. Authorized redirect URIs: `http://localhost:8000/auth/google/callback`
5. Copy Client ID and Secret to `.env`

---

## 5. Flutterwave setup

1. Sign up at [flutterwave.com](https://flutterwave.com)
2. Dashboard → Settings → API Keys → copy Test keys to `.env`
3. Dashboard → Settings → Webhooks → set URL to `http://YOUR_DOMAIN/payments/webhook`
4. Set the same secret hash in `.env` as `FLW_WEBHOOK_SECRET`

For local testing with webhooks, use [ngrok](https://ngrok.com):
```bash
ngrok http 8000
# Use the https:// URL as your webhook endpoint in Flutterwave
```

---

## 6. Termii SMS setup (Nigeria)

1. Sign up at [termii.com](https://termii.com)
2. Dashboard → API Keys → copy key to `.env`
3. Request sender ID `KB-Co` from Termii dashboard

---

## 7. NGX Data scraping

The scraper runs automatically every **5 minutes** (configurable via `NGX_SCRAPE_INTERVAL_MINUTES`).

On first startup it immediately scrapes NGX for live prices. If the NGX site is unreachable, the backend falls back to the 25 static stocks in `app/data/static_stocks.py`.

Force a refresh manually:
```bash
curl http://localhost:8000/stocks/live
```

---

## Running both frontend and backend

**Terminal 1 — Backend:**
```bash
cd "kb-co-backend"
python run.py
```

**Terminal 2 — Frontend:**
```bash
cd "kb-co-platform"
npm run dev
```

Open http://localhost:3000
