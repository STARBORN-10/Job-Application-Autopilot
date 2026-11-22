# System Architecture (V2)

## Overview
Job Application Autopilot is a React dashboard on top of a FastAPI backend. Discovery, scoring,
alerts, approvals and safe applying all run **inside the backend**.

```
Trigger (button / scheduler / cron)
      |
Source plugins (each isolated, health recorded, budgets enforced)
  JSearch | Adzuna | Jooble | ATS boards (Greenhouse/Lever/Ashby) | Internshala* | Indeed+LinkedIn via JobSpy*
      |
Normalise -> cross-source de-duplication -> database duplicate check -> hard filters
      |
Keyword pre-score (all jobs) -> AI facts for the top N -> deterministic score + breakdown
      |                               (AI provider layer: Gemini -> Groq -> OpenRouter)
Save (score >= minimum) -> Telegram alert [Approve] [Skip] [Cover letter]
      |
Approve (Telegram or dashboard) -> apply: e-mail (dry-run by default) | assisted
      |
job_decisions (training data) -> weight tuning (30+ decisions, guard-railed)
```
`*` experimental, off by default.

## Components

### 1. Pipeline (`backend/services/pipeline.py`)
1. Single-run lock (overlapping runs return `already_running`).
2. Settings, active resume and its cached **candidate profile** (`services/scoring/profile.py`).
3. **Sources** via `services/sources/runner.py`: every enabled and configured source runs in its own
   try/except with retries (`services/retry.py`), a per-run request cap and, for JSearch, a monthly
   budget (`JSEARCH_MONTHLY_BUDGET`, default 150 of the 200 free requests) counted in `api_usage`.
   Each outcome is written to `source_health`. One failing source never stops the others; the run is an
   error only when every source failed.
4. **De-duplication** (`services/dedupe.py`): canonical URL, or same company + near-identical title
   (difflib >= 0.9, seniority words must agree) + compatible location. Merged jobs keep every source in
   `source_names` and the richest description. The run summary lists each merge and its reason.
5. **Database duplicates** only get `last_seen` / `source_names` updated (zero AI cost).
6. **Hard filters** (`services/scoring/filters.py`): experience (V1 rule), location (clearly elsewhere only),
   job type, blocked companies, blocked keywords.
7. **Scoring** (`services/scoring/engine.py`): a keyword pre-score for every job; only the top
   `LLM_MAX_JOBS_PER_RUN` (default 15) get AI-extracted facts and a re-score. Cover letters (task `write`)
   only for AI-scored jobs at or above the minimum score.
8. Save, then send the Telegram alert (failures never lose a job).
9. The summary (per-source counts and errors, merges, filters, AI usage) is kept in memory and
   persisted to `app_settings` so `GET /api/automation/status` shows it after a restart.

### 2. Explainable score
Five parts, each 0-1, weighted (defaults skills 40, role 20, experience 15, preferences 15, freshness 10;
editable, must sum to 100). The score (0-10) is computed in code; AI only extracts facts.
- **Skills:** share of required skills found in the profile (nice-to-have count half), with alias
  normalisation (js = javascript, k8s = kubernetes, ml = machine learning, ...) and fuzzy matching.
  AI facts are verified against the posting text (absent skills are dropped). With weak evidence (a
  short snippet, or keyword-only facts) the value is pulled toward 0.5.
- **Role:** pure-Python title similarity (`services/matching.py`) to the active role and the resume's roles.
- **Experience:** required years / level vs. the candidate (within the configured maximum = full fit).
- **Preferences:** location (remote handled) and preferred job type.
- **Freshness:** 1.0 for the first 3 days, down to 0 at the maximum job age.
- **Relevance caps:** an off-role title caps the score at 6.5, or 4.0 if the skills do not fit either.

`score_breakdown` (JSON) stores every part, matched/missing skills, confidence, filter results, facts
source and any cap; `match_reason` is generated from it.

### 3. AI provider layer (`backend/services/llm/`)
`generate_json(task, prompt, schema)` tries providers in `LLM_PROVIDER_ORDER` (default
`gemini,groq,openrouter`). Rate limits, 5xx, timeouts, auth errors and invalid JSON fall through to the
next provider; a failed provider is skipped for a short cooldown. Tasks `extract` and `write` use
different models (`GROQ_MODEL_EXTRACT`, `GROQ_MODEL_WRITE`, `GEMINI_MODEL`, ...). Groq's tokens-per-minute
limit is respected by reading `x-ratelimit-*` headers and waiting (at most `GROQ_MAX_WAIT_SECONDS`).

### 4. Telegram approvals (`backend/services/telegram_bot.py`)
Alerts carry Approve / Skip / Cover letter buttons. Taps arrive via `POST /api/telegram/webhook`
(checked against `TELEGRAM_WEBHOOK_SECRET`) or a local long-polling loop (`TELEGRAM_MODE=polling`).
Only `TELEGRAM_CHAT_ID` is obeyed. Decisions go to `job_decisions` (with score snapshots) and
`jobs.approval_status`. The dashboard has the same buttons (`POST /api/jobs/{id}/approve|skip`).

### 5. Safe applying (`backend/services/apply/`)
Only after approval. `email` when the posting contains a recruiter address (cover letter as body,
active resume PDF attached, `APPLY_DRY_RUN=true` by default, `APPLY_DAILY_CAP` per day), otherwise
`assisted` (link + cover letter sent to Telegram and shown in the Applications page). Greenhouse /
Lever / Ashby career pages are detected and routed to assisted. Every attempt is logged in `applications`.

### 6. Learning (`backend/services/scoring/tuning.py`)
After 30+ decisions, an L2-regularised logistic regression on the five part values suggests new weights;
each moves at most 5 points per tuning, stays within 5-60 and the total stays 100. Applied only on request.

### 7. Database and migrations
SQLAlchemy models in `backend/models.py`; schema managed by Alembic (`backend/alembic/`). Startup runs
`upgrade head` inside the resilient retry loop, so the API still starts (and `/api/health` reports 503)
while the database is unreachable. The baseline migration is idempotent, so databases created by V1's
`create_all` upgrade in place without data loss.

Tables: `jobs` (+ V2 columns `external_id`, `canonical_url`, `source_names`, `score_breakdown`,
`description_quality`, `approval_status`, `last_seen`), `resumes`, `app_settings`, `source_health`,
`job_decisions`, `applications`, `candidate_profiles`, `api_usage`.

### 8. Protection
- `POST /api/automation/trigger`: cooldown (`TRIGGER_COOLDOWN_SECONDS`, default 120). Not key-protected
  because the browser calls it.
- `ADMIN_API_KEY` (optional): required as `X-Admin-Key` for approve/skip/apply, Telegram set-webhook and
  weight tuning. A key baked into the frontend build (`VITE_ADMIN_API_KEY`) is visible to anyone who can
  load the site; it only keeps out casual callers.
- Secret values are redacted from stored errors and API responses (`services/redact.py`).

### 9. React frontend (`frontend/`)
Dashboard, Job Listings (filters incl. decision, compact score bars), Job Details (score breakdown,
approve/skip), Applications (log, dry-run banner, copy cover letter), Tracker, Analytics, Resumes, Settings
(hard filters, weights + tuning suggestion, source toggles with health, ATS company list, AI providers).

## Known limitations
- Single user, no login. The trigger endpoint is open (rate limited only).
- Resume PDFs are stored on local disk; use a persistent disk in production.
- Scraped sources (Internshala, JobSpy) may break or be blocked, especially from cloud IPs.
- Gmail reply tracking and follow-up reminders are not built (see `docs/V2_PLAN.md`).
- Form pre-fill needs Playwright + Chromium (`requirements-optional.txt`) and a machine that can open a browser.
  It was tested against local fixture pages only. Real ATS pages change; expect to adjust selectors, and
  many Greenhouse pages show a CAPTCHA that the tool cannot (and must not) solve.
- Tailored resumes are generated from the extracted text of your PDF, not by editing the PDF, so the layout
  is a clean ATS-friendly format rather than your original design. Text that was broken during PDF extraction is repaired.
- Jobs saved by the V1 pipeline keep their old AI-opinion score and have no breakdown until they are re-scored.
