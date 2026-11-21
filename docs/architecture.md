# System Architecture

## Overview
Job Application Autopilot is a React dashboard on top of a FastAPI backend. The whole discovery → scoring → alerting workflow runs **inside the backend** (it previously ran on Make.com).

## Components

### 1. Pipeline Orchestrator (`backend/services/pipeline.py`)
Runs one discovery cycle:
1. Acquire a single-run lock (overlapping runs return `already_running`).
2. Load settings and the active resume for the active role.
3. Fetch jobs from JSearch (`jsearch_service`).
4. Skip duplicates and over-experienced jobs **before** calling the AI (zero token cost).
5. Score each job and write a cover letter with Gemini (`ai_service`).
6. Drop jobs below the minimum match score.
7. Save to the database, then send a Telegram alert (`notification_service`). Alert failures never lose a job.

Every external call goes through `retry_call` (`services/retry.py`): transient failures (timeouts, rate limits, malformed AI output) are retried with exponential backoff; auth/config errors fail immediately. Each job is processed in isolation so one failure never aborts the batch.

Each run's summary and timestamps are recorded and served at `GET /api/automation/status`.

### 2. Triggers
- **Manual:** `POST /api/automation/trigger` (dashboard "Find New Jobs"). The UI polls the status endpoint and shows the real result.
- **Scheduled:** set `AUTO_RUN_INTERVAL_MINUTES` > 0 to start an in-process scheduler (FastAPI lifespan). This needs an always-on host; on a sleeping free tier, call the trigger endpoint from an external cron instead.

### 3. FastAPI Backend (`backend/main.py`)
- Jobs CRUD, resumes (PDF upload + text extraction), settings, experience filter.
- `GET /api/analytics`, `GET /api/export/jobs.csv`, `POST /api/jobs/{id}/analyze` (all computed on demand; no extra tables).
- Legacy Make.com endpoints (`/api/make/*`, API-key protected) remain for backwards compatibility.
- SQLite locally; PostgreSQL in production via `DATABASE_URL`.

### 4. React Frontend (`frontend/`)
Dashboard, Job Listings (advanced filters + CSV export), Job Details (cover letter + AI fit analysis), Tracker, Analytics, Resumes, Settings.

## Data Flow
1. **Discovery:** trigger → JSearch → pre-filter → Gemini → threshold → database
2. **Alert:** Telegram message after the job is committed
3. **Display:** React fetches `/api/jobs`, `/api/analytics`
4. **Tracking:** status updates via `PUT /api/jobs/{id}` from the Tracker UI

## Known limitations
- No user authentication; the app is single-user. The trigger endpoint is unauthenticated and spends API quota.
- No migration tool: schema changes (e.g. a salary column) need Alembic before they can be applied to an existing database.
- Resume PDFs are stored on local disk; use a persistent disk or object storage in production (extracted text is kept in the database).
