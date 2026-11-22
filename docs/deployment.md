# 🚀 Production Deployment Guide

This document outlines how to deploy the **Job Application Autopilot** stack (FastAPI backend with the built-in pipeline + React frontend) to production.

---

## 🏗️ Architecture & Storage Strategy

### Ephemeral Storage Warning (SQLite & PDF Uploads)
> [!CAUTION]
> Free and standard serverless/container hosts (such as Render free web services, Railway temporary containers, Heroku, etc.) run on an **ephemeral disk**.
> Any local files written at runtime—including `jobs.db` and PDFs saved in `backend/uploads/resumes/`—**will be permanently lost whenever the server restarts, sleeps, or deploys**.

### Production Recommendations:
1. **Database:**
   - Use a managed PostgreSQL database (e.g. Supabase, Neon, Render PostgreSQL, or ElephantSQL).
   - Set the `DATABASE_URL` environment variable:
     ```env
     DATABASE_URL=postgresql://user:password@ep-host.neon.tech/dbname?sslmode=require
     ```
   - SQLAlchemy automatically connects to PostgreSQL when `DATABASE_URL` starts with `postgresql://`.
2. **Resume PDF Storage:**
   - **Option A (Persistent Volume):** On Render or Railway, attach a Persistent Disk mounted at `/app/backend/uploads`.
   - **Option B (Cloud Blob Storage):** Configure cloud object storage (AWS S3, Cloudinary, or Supabase Storage bucket) for permanent PDF hosting.
   - Note: The plain text of each resume is stored directly in the database (`extracted_text` column in `resumes` table), ensuring AI matching continues working as long as the database is persistent.

---

## 🔑 Environment Variables Reference

### Backend (`backend/.env` or Host Environment)
| Variable | Required | Description | Example |
|---|---|---|---|
| `DATABASE_URL` | No | Database (SQLite by default, PostgreSQL recommended) | `postgresql://user:pass@host:5432/db` |
| `CORS_ORIGINS` | No | Comma-separated allowed frontend origins (defaults to `*`) | `https://my-job-app.vercel.app` |
| `RAPIDAPI_KEY` | For JSearch | JSearch (RapidAPI) key | `abc123...` |
| `JSEARCH_MONTHLY_BUDGET` | No | Max JSearch requests per calendar month (free plan = 200) | `150` (default) |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | For Adzuna | Adzuna API credentials (free at developer.adzuna.com) | |
| `JOOBLE_API_KEY` | For Jooble | Jooble API key (free at jooble.org/api/about) | |
| `ATS_REQUEST_DELAY_SECONDS` | No | Pause between company board requests | `0.5` |
| `INTERNSHALA_CACHE_HOURS` | No | Cache for the experimental Internshala scraper | `6` |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | One AI key | Gemini key and model (new keys cannot use gemini-2.5-flash) | `gemini-3.5-flash-lite` |
| `GROQ_API_KEY` | One AI key | Groq key (fallback provider, free tier ~8000 tokens/minute) | |
| `GROQ_MODEL_EXTRACT` / `GROQ_MODEL_WRITE` | No | Groq models per task | `openai/gpt-oss-20b` / `openai/gpt-oss-120b` |
| `GROQ_MAX_WAIT_SECONDS` | No | Longest wait for Groq's token window before trying the next provider | `20` |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | No | Optional third provider | |
| `LLM_PROVIDER_ORDER` | No | Provider fallback order | `gemini,groq,openrouter` |
| `LLM_MAX_JOBS_PER_RUN` | No | Jobs per run that get AI facts and cover letters (cost control) | `15` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | For alerts | Bot token and the only chat whose button taps are obeyed | `123:ABC` / `987654` |
| `TELEGRAM_WEBHOOK_SECRET` | For webhook | Random string; Telegram sends it back in a header on every update | `openssl rand -hex 24` |
| `TELEGRAM_MODE` | No | `polling` for local development without a public URL (off by default) | `polling` |
| `PUBLIC_BACKEND_URL` | No | Public https base URL used by `POST /api/telegram/set-webhook` | `https://autopilot.onrender.com` |
| `ADMIN_API_KEY` | Recommended | Required as `X-Admin-Key` for approve/skip/apply, set-webhook and weight tuning | random string |
| `TRIGGER_COOLDOWN_SECONDS` | No | Minimum gap between manual pipeline starts | `120` |
| `APPLY_DRY_RUN` | No | `true` (default) logs applications without sending anything | `true` |
| `APPLY_DAILY_CAP` | No | Max e-mail applications per day (dry runs count) | `10` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | For e-mail apply | SMTP account. Gmail: `smtp.gmail.com`, port `465`, and an App Password (Google Account > Security > 2-Step Verification > App passwords) | |
| `TUNE_MIN_DECISIONS` | No | Decisions needed before weight tuning | `30` |
| `AUTO_RUN_INTERVAL_MINUTES` | No | Built-in scheduler interval; `0`/unset disables (needs an always-on host) | `360` |
| `RETRY_MAX_ATTEMPTS` / `RETRY_BASE_DELAY_SECONDS` | No | Retry tuning for transient API errors | `3` / `1.5` |
| `MAKE_API_KEY` | Legacy | Only if an external tool still calls `POST /api/jobs` or `/api/make/*` | |
| `PORT` | No | Server port (Render sets it) | `8000` |

### Frontend (`frontend/.env` or Host Environment)
| Variable | Required | Description | Example |
|---|---|---|---|
| `VITE_API_URL` | **Yes** | Public URL of your deployed FastAPI backend (with `/api` suffix) | `https://job-application-autopilot.onrender.com/api` |
| `VITE_ADMIN_API_KEY` | If `ADMIN_API_KEY` is set | Sent as `X-Admin-Key` by the approve/skip/apply buttons. **Not secret:** anything in a frontend build can be read by anyone who loads the site | |

---

## ☁️ Deployment Instructions

### 1. Deploying Backend on Render

1. Create a new **Web Service** on [Render](https://render.com/).
2. Connect your GitHub repository.
3. Configure settings:
   - **Root Directory:** `backend`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. In the **Environment Variables** tab, add:
   - `MAKE_API_KEY`: A strong random string.
   - `DATABASE_URL`: Your PostgreSQL connection string.
   - `CORS_ORIGINS`: Your frontend production domain.
5. (Optional) In **Disks**, add a Persistent Disk mounted at `/opt/render/project/src/backend/uploads` with 1 GB storage.

---

### Database migrations (Alembic)
The backend runs `alembic upgrade head` automatically at startup (with retries while the database is
unreachable). Existing V1 databases, created by `create_all`, are upgraded in place: the baseline
migration only creates missing tables, and the V2 migration adds the new columns and tables. Take a
backup first anyway (`pg_dump` on Postgres, a file copy on SQLite).

Manual use, from `backend/`:
```bash
alembic upgrade head      # apply migrations (reads DATABASE_URL, like the app)
alembic current           # show the applied revision
alembic revision -m "..." # new migration: write it by hand, idempotent like the existing ones
```

### Telegram approvals (webhook)
1. Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and a random `TELEGRAM_WEBHOOK_SECRET` on the backend.
   To find your chat id, send the bot a message and open `https://api.telegram.org/bot<token>/getUpdates`
   (or run locally with `TELEGRAM_MODE=polling`: the backend logs the chat id of ignored messages).
2. Register the webhook once (needs a public https URL):
   ```bash
   curl -X POST https://<backend>/api/telegram/set-webhook         -H "Content-Type: application/json" -H "X-Admin-Key: <ADMIN_API_KEY>"         -d '{"base_url": "https://<backend>"}'
   ```
3. On a sleeping free host the first tap can take 30-60 s while the service wakes up; Telegram retries.
Local development without a public URL: set `TELEGRAM_MODE=polling` instead (do not use both: an active
webhook blocks polling, so the poller deletes it first).

### Render notes
- Build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT` (root `backend`).
- Use hosted Postgres (`DATABASE_URL`); migrations run on boot.
- Free web services sleep: the in-process scheduler and Telegram polling do not run while asleep.
  Use the webhook for Telegram and an external cron (e.g. GitHub Actions) calling
  `POST /api/automation/trigger` for scheduled runs.
- Scraped sources (Internshala, JobSpy) are more likely to be blocked from cloud IPs; they are off by default.
- Optional extras: `pip install -r requirements-optional.txt` adds `python-jobspy` (Indeed + LinkedIn).

---

### 2. Deploying Frontend on Vercel / Netlify / Render

#### Deploying on Vercel:
1. Import your GitHub repository in [Vercel](https://vercel.com/).
2. Set the **Root Directory** to `frontend`.
3. Framework Preset: `Vite`.
4. Under **Environment Variables**, add:
   - `VITE_API_URL`: `https://<YOUR_RENDER_BACKEND_URL>/api`
5. Click **Deploy**.

---

### 3. Docker Deployment (Alternative)

You can run the entire stack locally or on any VPS using the provided `docker-compose.yml`:

```bash
# 1. Clone and navigate to repo
git clone https://github.com/STARBORN-10/Job-Application-Autopilot.git
cd Job-Application-Autopilot

# 2. Create your .env file from template
cp .env.example .env

# 3. Build and start containers
docker-compose up -d --build
```

- Backend API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`
- Frontend Dashboard: `http://localhost:5173`
