# Job Application Autopilot: Project Brief (Version 1 to Version 2)

A short, plain-language brief for building the project report and presentation. Each numbered section can become one or two slides. Anything marked **[Deferred]** is not built yet; everything else has been built and tested (Version 2 was built in November 2026, see sections 6, 7 and 11).

---

## 1. The problem

Looking for a job is repetitive work:

- Searching several job sites every day
- Reading long job descriptions to check if you qualify
- Writing a new cover letter for every job
- Losing track of where you already applied

Most of this time is spent on work a computer can do. The decision of *where to apply* is the only part that really needs a person.

## 2. The idea

> Upload your resume once. The system finds jobs, scores how well each one fits you, writes a cover letter, and tracks your job hunt. **You decide where to apply.**

It assists with the search and the paperwork. It does not apply on its own without your approval.

## 3. How it works today (Version 1)

```
Search jobs  ->  Remove duplicates and jobs needing too much experience
     ->  AI reads each job next to your resume: score 0-10 + reason + cover letter
     ->  Keep only good matches  ->  Save  ->  Telegram alert
     ->  Website: list, filters, tracker, analytics
```

| Step | What happens | Why it matters |
|---|---|---|
| Find jobs | Pulls listings for your chosen role and location | Replaces manual searching |
| Pre-filter | Drops jobs already seen and jobs needing too many years | Saves time and AI usage |
| AI scoring | Google Gemini compares the job with your resume and gives a 0-10 score with a one-line reason | Tells you where to focus |
| Cover letter | Gemini writes a letter using your own resume details | Saves 15-20 minutes per job |
| Alert | A Telegram message with the title, score, reason and link | You see good jobs on your phone |
| Website | Dashboard, job list with filters, tracker, analytics, resume manager | One place for everything |

### Website features
- **Dashboard:** counts, best matches, and a "Find New Jobs" button that shows the real result of each run
- **Job list:** filter by score, experience, status, location, source and date; sort by newest, best match or company
- **Job page:** full description, cover letter, and an "Analyze Fit" button that lists skills you have, skills you are missing, and resume tips
- **Tracker:** move jobs through To Apply, Applied, Interview, Offer, Rejected
- **Analytics:** application funnel, score distribution, jobs found per day, top companies, sources
- **Resumes:** upload a PDF per target role
- **Export:** download all jobs as a spreadsheet (CSV)

### Built-in reliability
- Automatic retries when a service is slow or rate-limited
- Optional scheduler that runs the search every few hours
- Each job is processed on its own, so one failure never stops the others
- A failed Telegram message never loses a saved job
- The server stays up and reports a clear status if its database is unreachable

## 4. Technology (Version 1)

| Part | Technology |
|---|---|
| Website | React with Vite |
| Server | Python with FastAPI |
| Database | SQLite on a laptop; PostgreSQL online |
| AI | Google Gemini (model is configurable) |
| Job data | JSearch API (aggregates Google Jobs) |
| Alerts | Telegram Bot API |
| Hosting | Vercel for the website, Render for the server |

The project started on the no-code tool Make.com and was moved into our own Python server, so it no longer depends on an outside automation tool.

## 5. What Version 1 achieved (evidence)

- A real run with a real resume and real keys found **5 live job postings**, scored by AI between **8.5 and 9.2**, each with a personalised cover letter and a written reason.
- **274 automated checks pass** across seven test suites. They run offline, without calling any paid service.
- The job-search provider **changed its API** during development (the old search address was removed). The code was updated and verified against a real response.
- Bugs found and fixed along the way: a crash that stopped the pipeline from loading, jobs being hidden once there were more than 100, a missing setting in the Docker setup, and page links that broke on reload when deployed.

### Honest limits of Version 1
- **One search source** with a small free allowance (about 200 searches a month).
- **The score is a single AI opinion.** In the first run all five jobs scored between 8.5 and 9.2, so the score does not separate good from great, and it cannot explain how it was calculated.
- **Alerts only.** The system tells you about jobs but cannot help you apply.
- **Single user**, with no login.
- **Free hosting** can sleep or lose its database, which makes the deployed site unreliable.

## 6. Version 2: what was built

Three upgrades, chosen by the project owner, built in five phases (V2.0 to V2.4).

### 6.1 More job sources (V2.0)
Each source is a separate plug-in that can fail without stopping the rest. Every run records each
source's result (jobs found, errors) and the dashboard shows its health. JSearch has a monthly budget
(150 of the 200 free requests) counted in the database.

| Source | Status |
|---|---|
| JSearch (existing) | Built. Google Jobs; full descriptions |
| Adzuna India, Jooble India | Built and tested live. Short description snippets |
| Company career boards (Greenhouse, Lever, Ashby) | Built and tested live. Default list: Groww, Databricks, Stripe, CRED, Meesho, Paytm, Zeta, Notion, OpenAI (editable). Filtered to India/remote and to the active role |
| Internshala | Built as an experimental scraper (off by default): public listing pages only, 2 requests per run, 1 per second. Tested live |
| Indeed and LinkedIn (python-jobspy) | Built as an optional, experimental source (off by default, library not installed by default). Tested offline only |
| Naukri, Google Jobs | Not used: tested and not usable with the available tool |

Also built: **merging duplicates** across sites (same link, or same company + near-identical title +
compatible city), and a **switchable AI layer** (Gemini, then Groq, then OpenRouter) that moves on to
the next provider when one is rate limited, down or returns bad output. This happened in a live run:
Gemini answered "high demand" (503) and Groq took over automatically.

Database **migrations** (Alembic) were added first, so existing databases upgrade without data loss.

### 6.2 A smarter, explainable score (V2.1)
1. The resume is turned once into a structured profile (skills, years, education, roles), cached until the resume changes.
2. **Hard filters** run first: experience, location, job type, blocked companies and keywords.
3. A cheap keyword score ranks all jobs; only the top 15 per run use AI to *extract facts* (required skills, years, level, work mode). Facts not found in the posting text are thrown away.
4. **The score is computed by code** from five parts: skills 40%, role fit 20%, experience 15%, preferences 15%, freshness 10% (editable).
5. The job page shows the breakdown as bars, with matched and missing skills, and says when only a short snippet was available.
6. Titles that do not fit the target role are capped (6.5), so they stay under the default minimum of 7.

### 6.3 Approve in Telegram, then apply (V2.2, V2.3)
Each alert has buttons: **Approve, Skip, Cover letter**. The same buttons are on the website. Only the
owner's Telegram chat is obeyed. After **Approve**:

| Job type | What happens |
|---|---|
| Posting lists a recruiter e-mail | Cover letter + resume PDF e-mailed by SMTP (e.g. Gmail app password), with a daily cap. **Dry-run by default**: logged, not sent |
| Everything else, including Greenhouse / Lever / Ashby career pages | "Assisted": the link and cover letter are sent to Telegram and shown on the Applications page with a copy button; you submit |

Every attempt is logged with what was (or would have been) sent. Logging in as the user on Naukri,
LinkedIn or Internshala is **deliberately excluded**.

**Added after the first user test (V2.5):**
- **Tailored resume:** for a job scoring below 9 the system re-orders and re-words the user's own
  resume for that posting. Every skill, employer, title, date and number is checked against the original,
  anything unverifiable is removed, and the job is re-scored before and after (for example 7.8 to 8.0).
  It never invents experience, never promises a score, and lists the real gaps. PDF and Word downloads.
- **Career-page form pre-fill** (Greenhouse, Lever, Ashby): a browser fills the user's details, uploads the
  resume, pastes the cover letter and takes a screenshot. It stops before Submit unless submitting is
  explicitly enabled, leaves custom and legal questions to the user, and hands over at a CAPTCHA.
- **Live progress** when searching for jobs, an explicit "what will happen" panel on Approve, and export as
  CSV, Excel or PDF.

### 6.4 Learning and protection (V2.4 and supporting work)
- After 30 or more Approve/Skip decisions the system suggests new score weights from what you approved
  (each weight moves at most 5 points per step, stays between 5 and 60, total 100). Applied only on request.
- An optional admin key protects approve, skip, apply, webhook setup and tuning; the "Find New Jobs"
  button has a 2-minute cooldown.
- **[Deferred]** Gmail tracking of interview/rejection e-mails and follow-up reminders (they need Gmail
  sign-in, which is out of scope for this pass).

## 7. Version 1 vs Version 2

A normal day with Version 2:

1. The system searches **several sources** (button, built-in scheduler, or an external cron).
2. It merges duplicates and drops jobs that fail your hard requirements.
3. It scores each remaining job with a **visible breakdown**.
4. Telegram sends the good ones with **Approve / Skip / Cover letter** buttons.
5. You tap **Approve**; the system e-mails the recruiter (once you turn dry-run off) or prepares an assisted apply.
6. The dashboard shows the applications log, your funnel and each source's health.

| Measure | Version 1 | Version 2 (built) |
|---|---|---|
| Job sources | 1 | 4 working in live runs (JSearch, Adzuna, Jooble, career boards) + Internshala (experimental) |
| Score | One AI number, no explanation | Code-computed score with a five-part breakdown |
| Applying | Manual | After approval: e-mail (dry-run by default) or assisted |
| Learns from you | No | Weight suggestions from Approve and Skip |
| If one AI provider fails | Pipeline stops | Falls back to another (seen live) |
| Users | One | Still one (multi-user not built) |

## 8. Safety and responsibility

- The system **never applies without your approval**.
- Your resume is used only to score jobs and write letters.
- AI scores are estimates, not a promise of an interview or a job.
- Scraping is limited to public pages, at low volume, and each scraped source can be switched off.
- Secrets (API keys and tokens) are kept in a private settings file, never in the code repository.

## 9. Risks and how they are handled

| Risk | Handling |
|---|---|
| Websites block or change their pages | Scraped sources are optional plug-ins that fail quietly |
| Free AI or API limits change (this already happened once) | Configurable model and a fallback chain |
| Free hosting sleeps or loses data | Always-on host and a hosted database; the server reports clear health status |
| Auto-apply getting an account banned | Only safe apply methods; the risky one is excluded |
| Bad AI cover letters | The user reviews and approves every application |

## 10. Roadmap

| Phase | Goal | Status |
|---|---|---|
| **V1** | Search, AI scoring, cover letters, Telegram alerts, website, analytics | Done |
| **V2.0** | Migrations, source plug-ins, new sources, de-duplication, switchable AI, trigger protection | Done |
| **V2.1** | Explainable scoring | Done |
| **V2.2** | Telegram Approve and Skip buttons | Done (needs `TELEGRAM_CHAT_ID` and a webhook or polling to use) |
| **V2.3** | Safe apply methods and the application log | Done (e-mail, assisted, career-page pre-fill) |
| **V2.4** | Learning from decisions | Done. Gmail tracking deferred |
| **V2.5** | Live progress, tailored resume, form pre-fill, export, UI pass | Done |

## 11. Current status (for the report)

- Version 2 is built and tested: **592 automated checks pass across 15 offline test suites** (HTTP,
  Telegram and e-mail are mocked).
- Live test (local, real keys, a copy of the real database): one run fetched **258 jobs** from five sources
  (JSearch 10, Adzuna 50, Jooble 20, career boards 77, Internshala 102), merged **75 duplicate listings**
  (most were one job re-posted within a source; at least 6 were the same job on Adzuna and Jooble), dropped 64 jobs needing too much experience, extracted AI facts for
  the top 8 jobs, wrote 6 cover letters and saved the qualifying jobs with score breakdowns. Telegram and
  e-mail stayed off.
- The live runs exposed a scoring weakness (off-role titles such as "Mechanical Engineer" scored above 7);
  it was fixed and re-checked against the same real jobs.
- To use Telegram buttons the owner still needs to set `TELEGRAM_CHAT_ID` (and a webhook secret).
- The deployed Render server still needs to be checked and redeployed with the new settings.

## 12. Suggested slide outline

1. Title and one-line idea
2. The problem
3. The solution in one picture (the flow diagram)
4. How Version 1 works
5. Website tour (screenshots: dashboard, job page with cover letter, analytics)
6. Technology
7. Results and evidence
8. Limits of Version 1
9. Version 2: more sources
10. Version 2: explainable scoring
11. Version 2: approve in Telegram, then apply
12. A day with Version 2
13. Safety and ethics
14. Risks and roadmap
15. Conclusion and next steps

**Screenshots to capture before presenting:** the dashboard after a run, a job page showing the score breakdown and cover letter, the Settings page with source health, the Applications page, the analytics page, and a Telegram alert with buttons.
