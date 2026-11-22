# Job Application Autopilot: Version 2 Plan

Status: **V2.0 to V2.5 built** (November 2026) on branch `feature/v2-sources-scoring-approval`. Section 9 records what was built, what was verified live, and what is deferred. Sections 1 to 8 are the original plan and research.

## 1. Where V1 stands

V1 is the native Python pipeline: JSearch finds jobs, Gemini scores them and writes cover letters, results are saved and shown in the dashboard, and Telegram sends alerts.

**Verified in a live run (local):** with real keys and an uploaded resume, JSearch returned jobs, Gemini scored them (8.5 to 9.2) and wrote personalised cover letters, and everything was saved and shown in the dashboard.

**Known V1 weaknesses that shape V2:**
- All 5 scored jobs landed between 8.5 and 9.2. A single "give me a 0 to 10" AI call is generous and cannot explain itself. (Small sample, but consistent with the design concern.)
- Run status is kept in memory, so it is lost on restart.
- JSearch's free plan allows **200 requests per month**.
- Gemini 2.5 Flash was closed to new API keys, so the model name has to be configurable and replaceable.
- The deployed Render backend was not answering during testing (accepts a connection, never replies). Needs a look at its logs. See section 7.
- Needs a Telegram chat ID before alerts send.

## 2. Decisions made

| Question | Decision |
|---|---|
| Where it runs | Cloud server, always on |
| Job scope | India: full-time jobs and internships |
| Auto-apply | Only after approval in Telegram, and only the safe methods |
| Build first | More job sources |

"Safe" apply means: email apply, company career-page forms (Greenhouse, Lever, Ashby), and an assisted apply for everything else (open the job with the cover letter ready, the user clicks Submit). Logging in as the user on Naukri, LinkedIn or Internshala is out of scope because those sites forbid it and the account could be banned.

## 3. Source research (tested, not guessed)

Tested from a home connection with throwaway scripts. A cloud IP is likely to be blocked more often by LinkedIn and Indeed, so scraped sources must be re-tested from the real host.

| Source | Result | Verdict |
|---|---|---|
| **Indeed India** (via `python-jobspy`) | 10 of 10 results, 8 of 10 relevant to "python developer", full descriptions | Good. Experimental because scraping may break or be blocked |
| **LinkedIn** (via `python-jobspy`, with description fetch) | 9 of 10 relevant, 8 of 10 with descriptions, about 9 s per 10 jobs | Good but slow and likely to be rate limited. Experimental |
| **Naukri** (via `python-jobspy`) | Results mostly irrelevant (0 to 1 of 10 matched), no descriptions. Naukri's own pages are a JavaScript shell with no job data | **Not usable as is.** Needs a custom approach or skip. Its experience range field is useful if solved |
| **Google Jobs** (via `python-jobspy`) | 0 results | Skip. JSearch already covers Google Jobs |
| **Internshala** (public listing pages) | Clean pages parse: 42 job cards and 51 internship titles. `robots.txt` disallows query strings and `/api/`, not these paths | Feasible with a small scraper using clean URLs only, low request rate. Also: JSearch already returned an Internshala job link |
| **Greenhouse boards** (public JSON) | Works. Groww 9 India jobs, Databricks 78 India jobs, Stripe 5. Some guessed names returned 404 | Good, reliable. Needs a curated list of company board names |
| **Lever boards** | Works, but the Indian companies tried (CRED, Meesho, Paytm) showed 0 jobs tagged India in the category field | Works, India tagging is unreliable. Filter by location text instead |
| **Ashby boards** | Works. OpenAI 12 India mentions | Good |
| **Remotive, Arbeitnow, Himalayas** | All respond | Remote and Europe oriented. Low value for India. Optional |
| **JSearch** (current) | Works with `/search-v2` | Keep, but 200 requests per month means it is one source of several |
| **Adzuna India, Jooble India** | Tested live: Adzuna 50 results per request (snippets, some empty or bot-check company names), Jooble 20 (snippets) | Built as sources |
| **Groq, OpenRouter (AI providers)** | Groq tested live (JSON mode, gpt-oss models, ~8000 tokens/min). OpenRouter not tested (no key) | Groq built as fallback; OpenRouter built, untested live |

Not yet verified: Adzuna and Jooble India coverage, the Groq and OpenRouter free limits, and everything from a cloud IP address.

## 4. V2 architecture

```
Scheduler / button
      |
Source plugins (each fails on its own, reports health)
  JSearch | Adzuna | Jooble | ATS boards | Indeed/LinkedIn (JobSpy) | Internshala
      |
Normalize  ->  de-duplicate across sources  ->  hard filters
      |
Score engine (breakdown, explainable)  ->  AI provider layer (fallback chain)
      |
Database (hosted Postgres)  ->  Telegram: [Approve] [Skip] [Cover letter]
      |
Approved -> apply by method:  email | career-page form | assisted
      |
Application log
```

## 5. Build order

**V2.0 Sources (first)**
1. Database migrations (Alembic) and hosted Postgres. V2 adds tables, and the current app cannot change its schema safely.
2. Put a key or login on the trigger and any apply action.
3. Source plugin interface: one shape, on/off switch, last success and error, cross-source duplicate detection.
4. Sources, in order: Adzuna and Jooble (after testing), ATS boards, Indeed and LinkedIn via JobSpy, Internshala.
5. AI provider layer: Gemini, then Groq, then OpenRouter free models, chosen per task.

Done when three or more sources return real India results in a live run on the cloud host, duplicates are merged, and a broken source does not stop the run.

**V2.1 Scoring.** Structured profile from the resume, hard filters, weighted score computed in code from AI-extracted facts (skills required versus held, role fit, level fit, preferences, freshness), with the breakdown shown in the UI.

**V2.2 Telegram approval.** Approve, Skip and Show-cover-letter buttons. Webhook mode so a sleeping free host still responds. Only the owner's chat ID is obeyed. Every decision is saved as training data for scoring.

**V2.3 Apply (safe methods).** Email apply with a daily cap, career-page forms, assisted apply, and a full log of what was sent.

**V2.4 Learning and tracking.** Scoring weights tuned from Approve and Skip history, Gmail tracking of interview and rejection emails, tailored resume per job, follow-up reminders.

## 6. Hosting notes (cloud, always on)

- Free web hosts sleep. Telegram webhook mode can wake them, with a delay of roughly 30 to 60 seconds on the first tap.
- A free always-on VM (for example Oracle Cloud Always Free) is the best fit for the backend, the bot and a headless browser. Not verified: current availability and the sign-up requirements (it asks for a card).
- Database: a free hosted Postgres (Neon or Supabase).
- Scheduling alternative: GitHub Actions cron calling the trigger.

## 7. Risks and open items

| Item | Notes |
|---|---|
| Scraping stability | LinkedIn, Indeed and Naukri block bots and change often. Every scraped source must be optional and fail quietly |
| Terms of service | LinkedIn, Indeed, Naukri and Internshala restrict scraping. Keep to public listing pages, low volume, and no logged-in access |
| Cloud IP blocking | Re-test every scraped source from the real host before relying on it |
| Free-tier changes | AI and API quotas have changed before (Gemini 2.5 Flash). Keep models configurable |
| Render backend not answering | Check its logs before V2 builds on it |
| Frontend routing on Vercel | Fixed in PR #2 (rewrite for deep links, request timeout, backend-unreachable banner) |

## 8. Needed from the owner to continue

Free keys, placed in `backend/.env` (never in chat or in git):
- `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`
- `JOOBLE_API_KEY`
- `GROQ_API_KEY`
- `TELEGRAM_CHAT_ID`

Decisions: which hosting provider for the always-on server, and the list of Indian companies whose career boards should be watched.

## 9. Progress (V2 build)

| Phase | Built | Verified |
|---|---|---|
| V2.0 Foundation | Alembic (idempotent V1 baseline + V2 schema, run on startup in the DB retry loop); source plug-ins with registry, runner, per-source health, per-run caps and JSearch monthly budget (`api_usage`); JSearch, Adzuna, Jooble, ATS boards, Internshala (off), JobSpy (off, optional); cross-source de-dup; LLM layer (Gemini, Groq, OpenRouter); trigger cooldown; optional admin key; persisted run summary; `/api/sources`, ATS company list | Offline suites; migration of a copy of the real V1 database (rows kept); live runs |
| V2.1 Scoring | Cached candidate profile, hard filters, keyword pre-score, AI facts for the top N verified against the text, weighted score in code with breakdown and relevance caps, editable weights, UI breakdown | Offline suites with hand-computed scores; live runs; re-score of real jobs after a calibration fix |
| V2.2 Telegram | Approve / Skip / Cover letter buttons, webhook with secret header, chat-id check, polling mode, set-webhook, dashboard buttons, decision log | Offline only (all Telegram HTTP mocked; `TELEGRAM_CHAT_ID` not set) |
| V2.3 Apply | E-mail apply (SMTP, dry-run default, daily cap, duplicate guard), assisted apply, application log and page | Offline only (smtplib mocked); never sent anything |
| V2.4 Learning | Weight tuning from 30+ decisions (logistic regression, 5-point steps, 5-60 bounds, sum 100), suggestion UI | Offline with synthetic decisions |

**Live results (local machine, copy of the real database, real keys, Telegram and e-mail off):**
- Run with five sources: JSearch 10, Adzuna 50, Jooble 20 (1 too old), career boards 77 (9 requests), Internshala 102 (2 requests); 258 fetched, 75 merged, 183 unique.
- Gemini returned 503 "high demand" once; Groq took over automatically.
- The first runs exposed two problems, both fixed: career boards kept non-engineering roles, and off-role titles ("Mechanical Engineer") could score above 7.
- JSearch used 2 of its 200 monthly requests in total during testing.

**V2.5 (built after the first user test):**
- Live run progress: stage stepper, a row per source, counters, "new jobs" tag, final per-source summary; a running indicator on every page and a disabled button while a run is active.
- Dashboard "Top matching opportunities" sorted by score (it used to show the newest jobs); source filter lists real sources; source badges and "Also found on".
- Approve is explicit: a "what will happen" panel before, an application outcome and timeline after (copy cover letter, open link, download resume).
- Tailored resume per job (score below 9): AI rewrites only what the resume already says, a verifier removes anything unverifiable, the job is re-scored before and after with the same engine, real gaps are listed. PDF and Word downloads. The 9 is a goal, not a guarantee.
- Career-page form pre-fill (Greenhouse / Lever / Ashby, Playwright): fills the form, uploads the resume, pastes the cover letter, screenshots, never submits unless explicitly enabled, never guesses custom or legal questions. Tested against local fixture pages only; never run against a live company form.
- Export as CSV, Excel or PDF. Make.com removed from the UI and docs (legacy endpoints kept, marked deprecated).

**Deferred (not built):**
- Gmail tracking of replies and follow-up reminders (need Gmail OAuth).
- Naukri and Google Jobs sources (not usable, see section 3).
- Multi-user support and login.
- Testing the scraped sources from a cloud IP, and the Render deployment itself (section 7).

**Calibration note:** for fresher roles the experience, preference and freshness parts are usually full,
so scores of relevant jobs still cluster around 7 to 9. Raise the minimum score or tune the weights once
there are 30+ decisions.
