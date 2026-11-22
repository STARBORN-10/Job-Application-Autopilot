# More job sources: what was checked

Checked on 22 November 2026 with **one polite request per endpoint** (public URLs only, no login, no scraping of HTML).
"Verified" means the request returned usable data that day. Endpoints can change, so every source stays optional and
health-tracked.

## Added in this pass

| Source | Result | Notes |
|---|---|---|
| **Amazon Jobs India** | Verified, **built** (`services/sources/amazon.py`) | 258 India matches for "machine learning", every one in India, descriptions about 3,700 characters including basic and preferred qualifications. Unofficial JSON feed (the one amazon.jobs uses); one request per run; switch it off in Settings if it ever breaks. |
| **Razorpay, Zscaler, Okta, MongoDB** (Greenhouse) and **Sarvam AI** (Ashby) | Verified, **added to the default company list** | India openings found on each board: Okta 103, Zscaler 89, MongoDB 70, Sarvam AI 42 (all India), Razorpay 25. |

## Company career boards already supported (add more in Settings, no code needed)

Verified India openings (India / total on the board):

| Platform | Board token | India / total |
|---|---|---|
| Greenhouse | `razorpaysoftwareprivatelimited` | 25 / 29 |
| Greenhouse | `groww` | 9 / 9 |
| Greenhouse | `druva` | 10 / 29 |
| Greenhouse | `databricks` | 78 / 895 |
| Greenhouse | `stripe` | 44 / 777 |
| Greenhouse | `elastic`, `airbnb`, `datadog` | 14 / 382, 12 / 202, 9 / 382 |
| Lever | `paytm` | 159 / 199 |
| Lever | `meesho` | 47 / 48 |
| Lever | `zeta`, `cred` | 29 / 33, 10 / 11 |
| Ashby | `sarvam` | 42 / 42 |
| Ashby | `snowflake`, `openai`, `notion` | 12 / 374, 9 / 852, 2 / 170 |

Tokens I tried that returned either no board or no India openings (my test did not tell the two apart; the company may
use another token or another platform): on Greenhouse `phonepe`, `meesho`, `cred`, `swiggy`, `zomato`, `sharechat`,
`dream11`, `upstox`, `navi`, `rapido`, `postman`, `browserstack`, `chargebee`, `freshworks`, `atlan`; on Ashby `razorpay`, `zepto`.

**How to find a company's token:** open its careers page. A Greenhouse board looks like `boards.greenhouse.io/<token>`
or `job-boards.greenhouse.io/<token>`, a Lever board like `jobs.lever.co/<token>`, an Ashby board like
`jobs.ashbyhq.com/<token>`. Add `provider` + `token` in Settings, then run a search.

## Verified but not built

| Source | Result | Why not built / what it would take |
|---|---|---|
| **Workday** (`.../wday/cxs/<tenant>/<site>/jobs`, POST) | Works. NVIDIA returned 529 "machine learning" postings | Each company has its own tenant and site name (my guess for Walmart returned HTTP 422), and India filtering needs per-company facets. Doable as a per-company config like the career boards. |
| **SmartRecruiters** public postings API | Works for the company `smartrecruiters` | Per company, and my test for `Visa` with `country=in` returned 0 postings. Needs company identifiers. |
| **Arbeitnow** | Works (large feed) | Mostly Germany and Europe. Low India relevance. |
| **RemoteOK** | Works | Remote only, global. Its terms require a visible link back to RemoteOK for every job shown. |
| **Remotive** | Works (domain moved to `remotive.com`) | Remote only, global. |
| **Himalayas** | Works (small feed) | Remote only, global. |
| **Hacker News "Who is hiring"** (Algolia API) | Works | One thread a month; needs comment parsing; few India roles. Many comments contain a recruiter e-mail, which suits e-mail apply. |

## Could not be verified

| Source | What happened |
|---|---|
| Workable | The widget URL returned 404 for the account I tried. A real company slug is needed to test. |
| Recruitee | 404 for the account I tried. |
| Microsoft careers search API | No response at all, so unverified. |
| Google careers API | HTTP 404 (the old endpoint appears to be gone). |
| Careerjet (India) | Not called. It needs a free affiliate key, so it needs you to register first. A good next candidate for India. |

## Not recommended

- **Naukri:** `robots.txt` disallows crawling and the site is bot-protected. Excluded since V2 planning.
- **Foundit, Cutshort, Instahyre, TimesJobs:** no public API found. I only skimmed their `robots.txt` and did not read their
  terms. Sites like these normally forbid automated collection, so do not add them without checking the terms first.
- **Logging in to any job site as you** to search or apply: deliberately excluded.

## Suggested next steps

1. Register for a **Careerjet** key (free) and add it as a source: the best remaining India-wide job search.
2. Add more **company boards** you actually want to work at (Settings, no code).
3. Add **Workday** support for a few Indian-office companies if you target large enterprises.
4. Enable **Indeed / LinkedIn (JobSpy)** locally first; cloud servers tend to get blocked.
