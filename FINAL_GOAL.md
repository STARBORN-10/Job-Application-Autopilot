# Job Application Autopilot: The Final Goal

## The idea in one line

> You upload your resume once. The app finds jobs for you, tells you which ones fit, writes the cover letter, and keeps track of your whole job hunt in one place. **You only decide where to apply.**

---

## The problem it solves

Looking for a job means doing the same boring things every day:

- Searching job sites again and again
- Reading long job descriptions to see if you even qualify
- Writing a new cover letter for every job
- Forgetting which jobs you already applied to

Job Application Autopilot does the boring parts for you.

---

## What a finished version looks like (a normal day)

**1. One-time setup (5 minutes)**
- Upload your resume (PDF).
- Pick the kind of job you want (for example "Python Developer"), your preferred locations, and the minimum match score you care about.
- Connect Telegram if you want phone alerts.

**2. The app works by itself**
- Every few hours it searches for new jobs that match your role and location.
- It throws away jobs you already saw and jobs that need too much experience.
- An AI reads each remaining job next to your resume and gives it a **score from 0 to 10**, with a short reason.
- Only the good matches (for example 7 and above) are kept.
- For each good match, the AI writes a **cover letter** using your own resume.

**3. You get notified**
- A Telegram message arrives on your phone: job title, company, score, why it fits, and the apply link.

**4. You open the website and decide**
- See your best matches first, and filter by location, date, score or experience.
- Open a job to read the cover letter and see **what skills you have and what you're missing**, with tips to improve your resume for it.
- Click the link and apply on the company's own website.
- Mark the job as **Applied**, **Interview**, **Offer** or **Rejected**.

**5. You see how you're doing**
- A dashboard shows how many jobs were found, how many you applied to, how many turned into interviews, and which companies show up most.
- You can download everything as a spreadsheet.

---

## What you get at the end

| You get | Instead of |
|---|---|
| New matching jobs found automatically | Searching job sites by hand every day |
| A score and a reason for every job | Reading every description yourself |
| A ready cover letter per job | Writing each one from scratch |
| Phone alerts for good matches | Checking the site again and again |
| Skill gaps and resume tips | Guessing why you aren't getting calls |
| One tracker for the whole hunt | Spreadsheets and lost links |
| Charts of your progress | Not knowing if your search is working |

---

## What it will never do

- It will **not** apply to jobs for you. Applying stays your decision.
- It will **not** share your resume with anyone. It is used only to score jobs and write letters.
- Its scores are an AI's estimate, not a promise that you'll get the job.

---

## How it works under the hood (simple)

```
Scheduler or "Find New Jobs" button
        ↓
Search jobs (JSearch)  →  Remove duplicates / too-senior jobs
        ↓
AI (Gemini) scores each job + writes the cover letter
        ↓
Keep only good matches  →  Save to database  →  Telegram alert
        ↓
Website: list, filters, tracker, analytics, skill-gap analysis
```

Everything runs in our own Python backend. We no longer need Make.com.

---

## Where we are today (for the team)

| Part | Status |
|---|---|
| Automatic job search, AI scoring, cover letters, saving, Telegram alerts | Built and tested offline. Needs real API keys for a live run |
| Scheduler, retries, run status | Built |
| Dashboard, listings, filters, tracker, resumes, settings | Built |
| Analytics, skill-gap analysis, CSV export | Built |
| Permanent cloud database | Not done yet. Needs a hosted Postgres database |
| Salary filter | Not done yet. Needs a database change |
| More job sources (beyond JSearch) | Not done yet |
| Login and multiple users | Not done yet |
| Protecting the "Find New Jobs" endpoint | Not done yet |

## Where this can grow later

- Support several people, each with their own resume and settings
- More job websites as sources
- Salary-based filtering
- Reminders to follow up on jobs you applied to
