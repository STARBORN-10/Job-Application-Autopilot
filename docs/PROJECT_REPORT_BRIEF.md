# Job Application Autopilot: Project Brief (Version 1 to Version 2)

A short, plain-language brief for building the project report and presentation. Each numbered section can become one or two slides. Anything marked **[Planned]** is not built yet; everything else has been built and tested.

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

## 6. Version 2: what changes **[Planned]**

Three upgrades, chosen by the project owner:

### 6.1 More job sources (built first)
Instead of one provider, the system will search many, each as a separate plug-in that can fail without stopping the rest.

| Source | What it adds |
|---|---|
| JSearch (existing) | Google Jobs, includes some Internshala, LinkedIn and Shine listings |
| Adzuna and Jooble | India-focused job APIs (to be tested) |
| Company career boards (Greenhouse, Lever, Ashby) | Jobs straight from companies, for example Groww and Databricks have India openings |
| Indeed and LinkedIn (scraper library) | Tested: relevant results with descriptions; may be blocked on servers |
| Internshala | Internships; public listing pages can be read |
| Naukri | Tested and **not usable** with the available tool; needs another approach or is skipped |

Also added: merging duplicates that appear on several sites, and a **switchable AI layer** (Gemini first, then Groq, then OpenRouter free models) so one provider's quota cut cannot stop the system.

### 6.2 A smarter, explainable score
Today the AI gives one number. In Version 2:

1. The resume is turned into a structured profile (skills, years, projects, preferred roles).
2. **Hard filters** run first: location, experience, job type.
3. The AI only *extracts facts* from the job (required skills, level).
4. **The score is computed by rules** from five parts: skills covered, role fit, experience level, preferences, and freshness.
5. The screen shows the breakdown (for example "skills 8/10, level 6/10") so the result can be trusted and checked.
6. Every Approve or Skip you tap becomes feedback, and the weights are tuned to your taste over time.

### 6.3 Approve in Telegram, then apply
Each alert gets buttons: **Approve, Skip, Show cover letter**. Only after you tap **Approve** does the system apply, and only in safe ways:

| Job type | What happens after Approve |
|---|---|
| Posting lists an email address (common in India) | Resume and cover letter are emailed from your Gmail, with a daily cap |
| Company career page (Greenhouse, Lever, Ashby) | The form is filled automatically |
| Naukri, Internshala, LinkedIn | The job opens with your cover letter ready; you press Submit |

Logging in as the user on Naukri, LinkedIn or Internshala to apply automatically is **deliberately excluded**. Those sites forbid it and the account could be banned.

Every application is logged with exactly what was sent.

### 6.4 Supporting upgrades **[Planned]**
- A permanent online database with safe schema updates (migrations)
- A login or key on actions that spend money or send applications
- Gmail tracking that updates statuses when interview or rejection emails arrive
- A tailored resume per job (reordering real experience, never inventing)
- Follow-up reminders

## 7. What Version 2 will be able to do

A normal day once Version 2 is finished:

1. The system searches **many sources** by itself every few hours.
2. It removes duplicates and jobs that do not fit your hard requirements.
3. It scores each remaining job with a **visible breakdown**.
4. Telegram sends the good ones with **Approve / Skip** buttons.
5. You tap **Approve** on the ones you like.
6. The system applies by email or career-page form, or opens the job with the letter ready.
7. The dashboard shows your funnel, and Gmail updates statuses when companies reply.

| Measure | Version 1 | Version 2 (target) |
|---|---|---|
| Job sources | 1 | 4 or more working at once |
| Score | One AI number, no explanation | Rule-based score with breakdown |
| Applying | Manual | One tap after approval, safe methods only |
| Learns from you | No | Yes, from Approve and Skip |
| If one AI provider fails | Pipeline stops | Falls back to another |
| Users | One | Designed for several |

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

| Phase | Goal |
|---|---|
| **Done (V1)** | Search, AI scoring, cover letters, Telegram alerts, website, analytics |
| **V2.0** | Migrations and online database, source plug-ins, new sources, switchable AI |
| **V2.1** | Explainable scoring |
| **V2.2** | Telegram Approve and Skip buttons |
| **V2.3** | Safe apply methods and the application log |
| **V2.4** | Learning from decisions, Gmail tracking, tailored resumes |

## 11. Current status (for the report)

- Version 1 works end to end on a local machine.
- The deployed website was reachable, but its online server was not answering when last checked. A fix that keeps the server running when its database is unavailable has been submitted for review.
- Version 2 is at the planning and research stage. Several sources were tested; Adzuna, Jooble and the free AI providers still need free keys to be tested.

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

**Screenshots to capture before presenting:** the dashboard after a run, a job page showing the cover letter and the "Analyze Fit" result, the analytics page, and a Telegram alert.
