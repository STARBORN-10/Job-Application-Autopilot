# 🚀 Production Deployment Guide

This document outlines how to deploy the **Job Application Autopilot** stack (FastAPI Backend + React Frontend + External Make.com Automation) to production.

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
| `MAKE_API_KEY` | **Yes** | Shared secret key required for Make.com to call `/api/jobs` and `/api/make/*` | `super_secret_make_key_123` |
| `DATABASE_URL` | No | Connection string for database (SQLite by default, PostgreSQL recommended) | `postgresql://user:pass@host:5432/db` |
| `CORS_ORIGINS` | No | Comma-separated list of allowed frontend origins (defaults to `*`) | `https://my-job-app.vercel.app,http://localhost:5173` |
| `MAKE_WEBHOOK_URL`| No | Default Make.com Webhook URL (can also be configured via Settings UI) | `https://hook.eu2.make.com/xxxx` |
| `PORT` | No | Server listening port (Render sets this automatically) | `8000` |

### Frontend (`frontend/.env` or Host Environment)
| Variable | Required | Description | Example |
|---|---|---|---|
| `VITE_API_URL` | **Yes** | Public URL of your deployed FastAPI backend (with `/api` suffix) | `https://job-application-autopilot.onrender.com/api` |

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
