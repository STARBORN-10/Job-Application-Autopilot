# 🚀 Job Application Autopilot

### AI-Powered Job Discovery, Matching & Application Management

An AI-powered full-stack application that automates job discovery, evaluates opportunities based on a candidate's profile, generates personalized cover letters, and organizes relevant jobs in a centralized dashboard.

The whole workflow runs **natively in the Python backend** (FastAPI + Google Gemini + JSearch + Telegram), with a React dashboard on top. It started on Make.com and has been migrated so no external automation tool is needed (the Make.com endpoints are kept for backwards compatibility).

---

## ✨ Features

- 🔎 **Automated Job Discovery:** Fetches listings from the JSearch API (RapidAPI) for your active role and preferred locations.
- 🧠 **AI-Powered Job Matching:** Uses Google Gemini to compare job requirements with your resume, skills, and goals.
- 🎯 **Smart Match Scoring:** Assigns a score from 0 to 10 with a short explanation of the match.
- ✍️ **Personalized Cover Letters:** Generates job-specific cover letters from your resume and the posting.
- ⚡ **Native Automation Pipeline:** Discovery → duplicate & experience pre-filter → AI scoring → threshold → save → Telegram alert, with per-job fault isolation and a single-run lock.
- 🔁 **Resilient:** Automatic retry with exponential backoff on timeouts and rate limits (JSearch, Gemini, Telegram).
- ⏰ **Built-in Scheduler:** Set `AUTO_RUN_INTERVAL_MINUTES` to run the pipeline automatically; run status is available at `/api/automation/status`.
- 📊 **Dashboard & Analytics:** React UI with live run results, application funnel, score distribution, jobs-over-time, top companies and sources.
- 🔍 **Advanced Filtering:** Filter by text, score, experience, status, location, source and date; sort by newest, score or company.
- 🧩 **Resume Fit & Skill Gaps:** One-click Gemini analysis of your resume against any job (matched skills, missing skills, resume tips).
- 📥 **CSV Export:** Download all jobs as a spreadsheet-ready CSV.
- 📬 **Telegram Notifications:** Sends job details, match scores, and links for qualifying jobs.
- 🗂️ **Application Tracking:** Tracks status from To Apply through Offer/Rejected.

> The system assists with job discovery and application preparation. It does not automatically submit job applications.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    S[Scheduler / "Find New Jobs" button] --> P[Pipeline Orchestrator]
    P --> A[JSearch API]
    A --> D{Duplicate or too senior?}
    D -- Yes --> X[Skip, no AI cost]
    D -- No --> G[Gemini: score + cover letter]
    G --> T{Score >= min score?}
    T -- No --> X
    T -- Yes --> DB[(Database)]
    DB --> TG[Telegram alert]
    DB --> API[FastAPI REST API]
    API --> UI[React Dashboard]
```

### How It Works

1. **Trigger:** The scheduler, or the dashboard's "Find New Jobs" button, starts the pipeline in the background.
2. **Discovery:** JSearch returns listings for your active role and locations.
3. **Pre-filter:** Duplicates and jobs requiring too much experience are skipped before any AI call.
4. **AI Evaluation:** Gemini scores the job against your active resume and writes a cover letter.
5. **Threshold:** Only jobs at or above your minimum match score are kept.
6. **Storage & Alerts:** Jobs are saved, then a Telegram alert is sent (a failed alert never loses a job).
7. **Dashboard:** The UI shows the run result, job list, tracker, and analytics.

---

## 🛠️ Tech Stack

| Category | Technologies |
|---|---|
| Frontend | React, Vite, JavaScript, CSS |
| Backend | Python, FastAPI |
| Database | SQLite (local) / PostgreSQL (production), SQLAlchemy |
| AI / LLM | Google Gemini 2.5 Flash |
| Job Data | JSearch (RapidAPI) |
| Notifications | Telegram Bot API |
| API Communication | REST API, HTTP, JSON |
| Authentication | API key for machine endpoints |
| Deployment | Render (backend), Vercel (frontend) |
| Version Control | Git, GitHub |

---

## 📁 Project Structure

```text
Job-Application-Autopilot/
│
├── backend/
│   ├── main.py            # FastAPI app & endpoints
│   ├── crud.py            # Database operations
│   ├── models.py / schemas.py / database.py
│   ├── services/
│   │   ├── pipeline.py    # Automation orchestrator + run status
│   │   ├── jsearch_service.py      # Job discovery
│   │   ├── ai_service.py           # Gemini scoring, cover letters, fit analysis
│   │   ├── notification_service.py # Telegram alerts
│   │   ├── analytics.py            # Stats aggregation & CSV export
│   │   └── retry.py                # Retry with exponential backoff
│   ├── test_*.py          # Offline test scripts (run with python)
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── ...
│
├── docs/
│
├── .gitignore
└── README.md
```

---

## ⚙️ Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/STARBORN-10/Job-Application-Autopilot.git
cd Job-Application-Autopilot
```

### 2. Set Up the Backend

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment.

**Windows:**

```powershell
.venv\Scripts\activate
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in your keys:

```env
RAPIDAPI_KEY=...          # JSearch job discovery
GEMINI_API_KEY=...        # AI scoring, cover letters, fit analysis
TELEGRAM_BOT_TOKEN=...    # optional alerts
TELEGRAM_CHAT_ID=...
MAKE_API_KEY=...          # only for the legacy /api/make/* and POST /api/jobs endpoints
DATABASE_URL=sqlite:///./jobs.db
AUTO_RUN_INTERVAL_MINUTES=360   # optional scheduler (0 = off)
```

Then upload a resume for your active role on the **Resumes** page and click **Find New Jobs** on the Dashboard.

**Never upload real API keys, tokens, or credentials to GitHub.**

### Run the Tests

The tests are offline scripts (no live API calls). From `backend/`:

```bash
python test_pipeline.py && python test_features.py && python test_suite.py && python test_phase1.py
python test_jsearch.py && python test_ai_service.py && python test_notification_service.py
```

### 4. Run the Backend

From the `backend` directory:

```bash
uvicorn main:app --reload
```

Backend URL:

```text
http://127.0.0.1:8000
```

Interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

### 5. Run the Frontend

Open a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the local development URL provided by Vite, usually:

```text
http://localhost:5173
```

Make sure the frontend is configured to use the intended backend API URL.

---

## 🔌 API Endpoints

The FastAPI backend provides REST endpoints for job management.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/jobs` | Retrieve job listings with score and status filters |
| POST | `/api/jobs` | Ingest qualified job (API key, duplicate detection & experience guard) |
| GET | `/api/jobs/{id}` | Retrieve specific job details |
| PUT | `/api/jobs/{id}` | Update job status ('Applied', 'Interview', etc.) |
| DELETE | `/api/jobs/{id}` | Delete job record |
| GET | `/api/make/context` | **Make.com:** Retrieve active role, resume text, and filter criteria (API key required) |
| GET | `/api/make/resume` | **Make.com:** Retrieve resume text for a specific role (API key required) |
| GET | `/api/resumes` | List all uploaded resumes across all roles |
| POST | `/api/resumes` | Upload new PDF resume and associate with target role |
| PUT | `/api/resumes/{id}/activate` | Select active resume for a specific role |
| PUT | `/api/resumes/{id}/replace` | Replace uploaded PDF file for an existing resume |
| GET | `/api/resumes/{id}/text` | Preview plain text extracted from a resume PDF |
| DELETE | `/api/resumes/{id}` | Delete a resume and its PDF from disk |
| GET | `/api/settings` | Retrieve unified job search & automation settings |
| PUT | `/api/settings` | Update settings (roles, min score, locations, webhook URL) |
| POST | `/api/automation/trigger` | Start the native discovery pipeline in the background (`already_running` if busy) |
| GET | `/api/automation/status` | Whether the pipeline is running + summary of the last run |
| GET | `/api/analytics?days=30` | Funnel, score distribution, jobs-over-time, top companies, sources |
| GET | `/api/export/jobs.csv` | Download all jobs as CSV |
| POST | `/api/jobs/{id}/analyze` | Gemini skill-gap analysis of the active resume vs. this job |

The Make.com guide ([docs/make_automation_guide.md](docs/make_automation_guide.md)) is kept for reference only; the native pipeline replaces it.
For hosting and cloud persistence guidelines, see [Production Deployment Guide](docs/deployment.md).

### Example: Create a Job

**Request:**

```http
POST /api/jobs
Content-Type: application/json
x-api-key: YOUR_API_KEY
```

**Request Body:**

```json
{
  "title": "Data Analyst Intern",
  "company": "Example Company",
  "url": "https://example.com/job",
  "location": "India",
  "description": "Analyze business data and generate insights.",
  "job_type": "Internship",
  "experience": "Fresher",
  "source": "IndianAPI",
  "score": 8.5,
  "match_reason": "Strong alignment with Python and SQL skills.",
  "cover_letter": "Personalized cover letter content.",
  "status": "To Apply"
}
```

---

## 🧠 AI Job Matching

The matching system evaluates job listings using a candidate profile that includes:

- Programming languages and technical skills
- AI, machine learning, and data science knowledge
- Relevant projects and practical experience
- Target job roles
- Experience and eligibility requirements

Each job receives a score from **0 to 10**.

| Score | Interpretation |
|---|---|
| 9–10 | Excellent match |
| 7–8 | Good match |
| 5–6 | Partial match |
| 0–4 | Poor match |

Only jobs with a score of **7 or above** pass through the current automation filter.

The score is an AI-generated estimate, not a guarantee of eligibility or hiring success.

---

## 🔐 Security and Data Handling

- Job creation is protected through API key verification.
- The backend reads the expected key from an environment variable.
- API credentials should be stored securely in the relevant service configurations.
- SQLite is used to store job records.
- Applications are not submitted automatically.

**Deployment note:** The current backend is hosted on Render's free service and uses SQLite. Free hosting can experience cold starts, and ephemeral storage should not be treated as permanent production storage.

---

## ☁️ Deployment

The backend is deployed on Render.

- **Backend:** https://job-application-autopilot.onrender.com
- **API Documentation:** https://job-application-autopilot.onrender.com/docs
- **GitHub Repository:** https://github.com/STARBORN-10/Job-Application-Autopilot

The React frontend can be run locally using Vite. To publish it, deploy it separately and configure its API URL and the backend's CORS settings.

---

## 🚧 Future Enhancements

- [x] Native Python pipeline replacing Make.com
- [x] Job deduplication to prevent repeated listings
- [x] Advanced filtering (text, score, experience, status, location, source, date) and sorting
- [x] Resume upload per target role
- [x] Resume-to-job compatibility analysis
- [x] Application progress analytics and visualizations
- [x] Retry with backoff and run-status reporting
- [x] Built-in scheduler and CSV export
- [ ] Persistent cloud database (PostgreSQL supported via `DATABASE_URL`; needs a hosted instance)
- [ ] Salary filtering (needs a new database column and a migration tool)
- [ ] Integration with additional job sources
- [ ] User authentication and multi-profile support

---

## 🎯 Project Objective

The goal of Job Application Autopilot is to explore how **AI, workflow automation, and full-stack development** can work together to solve a practical problem.

By automating repetitive job-search tasks, the system helps candidates identify relevant opportunities, prepare application materials, and organize their job search in one place—while keeping the final application decision in their hands.

---

## 👨‍💻 Developer

**Soham H. Wadekar**  
B.Tech Computer Science Engineering — AI & ML  
University of Engineering and Management, Jaipur

- GitHub: [STARBORN-10](https://github.com/STARBORN-10)
- Project: [Job Application Autopilot](https://github.com/STARBORN-10/Job-Application-Autopilot)

---

⭐ If you find this project interesting, consider giving the repository a star!