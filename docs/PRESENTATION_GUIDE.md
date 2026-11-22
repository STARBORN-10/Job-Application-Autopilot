# Presentation guide: how to explain Job Application Autopilot to the panel

This is **for our own use**. It explains the whole project in simple words: why we built it, what it does, how it works,
the tech stack, how we built it, what we found, the limits, and the likely questions from the panel with answers.
Read it once from top to bottom, then keep sections 12 to 14 (slides, demo, questions) next to you when you practise.

---

## 1. The project in one minute (say this first)

> Looking for a job is slow and repetitive. You search the same sites every day, read long descriptions to find out you
> don't qualify, write a new cover letter each time, and then forget where you applied.
>
> **Job Application Autopilot** does the repetitive part for you. You upload your resume once. The system searches
> many job sources, removes duplicates and jobs that don't fit, **scores every job against your resume with rules you can
> check**, writes a cover letter, and tells you about the good ones on **Telegram** with **Approve** and **Skip** buttons.
> **Only if you approve** does it apply, and only in safe ways. For weaker matches it can rewrite your own resume for that
> job, without inventing anything.
>
> The computer does the searching, reading and writing. **The person decides where to apply.**

If you only remember one sentence: **"The system does the repetitive work, the person makes the decision."**

---

## 2. Why we made it

- **We live this problem.** We are final-year students in placement season. We saw how much of job hunting is copy work:
  the same searches, reading a description just to find "5 years experience required", rewriting cover letters, and keeping
  a hand-made list of applications.
- **Existing tools solve one step each.** A job portal gives keyword alerts. An aggregator collects listings. A browser
  extension fills a form. Nothing joins search, fit-checking, letter writing, applying and tracking into one flow.
- **Most "auto-apply" tools are risky.** They log in as you on sites that forbid bots, and the account can be banned.
  Recruiters also notice mass applications. We wanted a tool that is safe and keeps the human in charge.
- **AI scores are hard to trust.** In our first run the AI gave five jobs scores between 8.5 and 9.2. That told us nothing:
  it could not separate good from great, and it could not explain itself. This shaped the whole design.

Say it simply: *tiring, repeated work is exactly what software is good at, but the decision should stay with the person.*

---

## 3. What it does, in plain words

1. **Finds jobs** from several places at once (not just one site).
2. **Cleans the list:** merges the same job seen on two sites, throws away jobs that ask for too much experience or are in
   the wrong place.
3. **Scores each job from 0 to 10**, and shows *why* (skills matched, role fit, experience, preferences, freshness).
4. **Writes a cover letter** using only facts from your resume.
5. **Alerts you on Telegram** with Approve / Skip / Cover letter buttons. The same buttons exist on the website.
6. **After you approve:** makes a tailored resume if the job scores below 9, then applies in a safe way (see section 8).
7. **Keeps a record:** a tracker (To Apply, Applied, Interview, Offer, Rejected), an application log, analytics.
8. **Learns from you:** after 30 Approve/Skip decisions it suggests better score weights for your taste.
9. **Keeps each person's data private:** every user has their own account, jobs, resumes and alerts.

---

## 4. The journey of one job (the process, step by step)

Use this when someone says "walk me through it". Picture one job posting travelling through the system.

| Step | What happens | Why |
|---|---|---|
| 1. **Trigger** | You press *Find New Jobs* (or a timer does it). A guard makes sure only one run per person is active. | Avoid double runs and wasted API quota. |
| 2. **Fetch** | Every enabled source is asked for jobs for your role and place: JSearch, Adzuna, Jooble, company career boards, Amazon Jobs. Each runs on its own. | One broken source must not stop the others. |
| 3. **Merge** | The same job on two sites becomes one record that remembers every source. Jobs you already have are skipped. | No duplicates, no wasted AI. |
| 4. **Hard filters** | Too many years required? Wrong place or job type? Blocked company or keyword? Dropped. | Cheapest way to remove jobs that can never fit. |
| 5. **Quick score** | A fast keyword score ranks everything. Only the best (15 per run) go to the AI. | Saves the AI's free limits. |
| 6. **AI reads facts** | The AI only extracts facts from the job: required skills, level, years, on-site or remote. Every skill it claims is checked against the posting text. | The AI reads; it does not decide. |
| 7. **Rule score** | Plain arithmetic over five parts gives the 0 to 10 score and a breakdown. | Explainable and checkable. |
| 8. **Gate and letter** | Below your minimum score: dropped. Otherwise the AI writes a cover letter from your resume. | Only good jobs cost AI effort. |
| 9. **Save, then alert** | The job is saved first (with its owner), then the Telegram alert is sent. | A failed alert never loses a job. |
| 10. **You decide** | Approve or Skip, on Telegram or the website. The website first shows exactly what Approve will do. | Nothing happens without you. |
| 11. **Tailor** | If the score is below 9, your resume is rewritten for this job, checked for invented facts and re-scored. | Better fit, honestly. |
| 12. **Apply safely** | E-mail, or pre-filled form that stops before Submit, or a ready link for you to submit. | No account-ban risk. |
| 13. **Log and learn** | Everything is logged. Your decisions feed the weight tuning. | Traceability and personalisation. |

---

## 5. The score, explained simply (panel favourite)

**Old idea:** ask the AI "how good is this job for this person?" and trust the number.
**Problem:** it gave 8.5 to 9.2 for everything and could not say why.
**Our idea:** the AI only **reads facts**. A fixed formula **does the scoring**.

```
Score = 10 × ( 0.40·skills + 0.20·role + 0.15·experience + 0.15·preferences + 0.10·freshness )
```

| Part | What it measures | Weight |
|---|---|---|
| Skills | Share of the job's required skills that are in your resume (nice-to-haves count half) | 40% |
| Role fit | How close the job title is to your chosen role | 20% |
| Experience | Required years or level against yours | 15% |
| Preferences | Place, remote work, job type | 15% |
| Freshness | New postings score higher | 10% |

Extra safety rules:
- A title that doesn't fit your roles **caps the score at 6.5** (a mechanical-engineering job can't win just by mentioning Python).
- If a source gives only a short snippet, the skills part is pulled toward the middle, because there is little evidence.
- The website shows the breakdown, e.g. "skills 7/8, role 10/10", so two jobs with the same total can still be told apart.

Why it is better: **you can check it, you can change the weights, and it learns from your Approve/Skip choices.**

---

## 6. Tech stack (and the simple reason for each)

| Part | Technology | Simple reason |
|---|---|---|
| Website | **React + Vite** | Fast to build, one page app, easy to host as static files. |
| Server | **Python + FastAPI** | Quick to write, automatic API docs, good for background work. |
| Database | **SQLite** (laptop) / **PostgreSQL** (online) | Zero setup locally; a real database online. |
| Database tools | **SQLAlchemy**, **Alembic** | Talk to the database in Python; update the schema safely without losing data. |
| AI | **Google Gemini**, then **Groq**, then **OpenRouter** | If one is busy or out of free quota, the next takes over. |
| Job data | **JSearch, Adzuna, Jooble, Greenhouse/Lever/Ashby boards, Amazon Jobs** | Several independent sources; many need no key. |
| Alerts | **Telegram Bot API** | Free, on every phone, supports buttons. |
| Applying | **SMTP e-mail**, **Playwright** (a real browser) | Send an application, or fill a company form. |
| Accounts | **scrypt** password hashes, signed **JWT** tokens | Standard, well-tested security building blocks. |
| Hosting | **Vercel** (website), **Render** (server) | Free tiers that deploy straight from GitHub. |
| Packaging and tests | **Docker**, 20 offline test suites | Same environment everywhere; safe to change code. |

**A simple analogy for the architecture:** the website is the shop front, the FastAPI server is the kitchen, the database is
the store room, and the outside services (job sites, AI, Telegram, mail) are the suppliers. A security guard at the door
(the sign-in check) makes sure each customer only enters their own store room shelf.

---

## 7. Why it is safe and private (important for questions)

- **Approval first.** Nothing is applied for unless the person taps Approve.
- **Dry run by default.** E-mail applications are logged but not sent until switched on. Form filling stops before Submit.
- **No logging in as the user** on Naukri, LinkedIn, Internshala and similar sites. Their terms forbid bots, and the
  account could be banned. For those sites the system prepares everything and the person presses Submit.
- **No invented resume facts.** A checker compares every skill, employer, title, date and number in a tailored resume with
  the original and removes anything it cannot find.
- **Private accounts.** Passwords are stored only as salted hashes. Every row of personal data has an owner, and the
  database session itself adds the owner filter to every query, so no part of the code can forget to filter. A session with
  no user cannot read personal data at all. Uploaded resumes are downloadable only by their owner.
- **Proven by tests.** Tests try to read, change and delete another user's data through every kind of endpoint, and a
  test goes through every route to check none is open without a sign-in.

---

## 8. The three ways of applying (after Approve)

| Job type | What the system does |
|---|---|
| The posting has a **recruiter e-mail** (common in India) | E-mails your cover letter and resume. Dry run by default, daily cap, owner account only (it uses the server's mail account). |
| A company page on **Greenhouse, Lever or Ashby** | A real browser fills your details, uploads the resume, pastes the letter, takes a screenshot, then **stops before Submit**. Custom, legal and diversity questions are left to you; at a CAPTCHA it hands over. |
| **Everything else** (Naukri, LinkedIn, Wellfound...) | Assisted: the link, letter and resume are ready on the job page and you press Submit. |

Be ready to say: **"This is deliberate. We would rather be safe than fully automatic."**

---

## 9. How we built it (the story)

Tell it as a story, it sounds natural and shows real engineering:

1. **Prototype on Make.com** (a no-code tool) to check the idea: fetch jobs, ask AI, post to Telegram. It worked, but it
   was hard to test, hard to change and tied to an outside service.
2. **Rebuilt as our own Python server** with a database and a website, and wrote automated tests for each part.
3. **Real-world surprises** that made the design stronger:
   - The job API **changed** while we were building it (old address removed). We updated and verified against a real response.
   - A new **Gemini model** stopped accepting new keys, so the model name became a **setting**, and we added Groq and
     OpenRouter as fall-backs. Later, when Gemini answered "busy", Groq took over automatically.
   - The hosted server **hung when its database was unreachable**. We made it start anyway and report a clear health status.
4. **More sources** as separate plug-ins, with duplicate merging.
5. **Explainable score** replacing the single AI opinion (section 5).
6. **Approve and apply** with Telegram buttons and the three safe ways of applying.
7. **Tailored resume and form pre-fill**, then a better website: live progress, source badges, explicit approval screens.
8. **Accounts and privacy** so several people can use one server safely, and a **workflow map** that explains the system.
9. **Tests all the way:** 20 suites, 1,020 checks, all offline (no paid service is called in a test).

The first sentence of the lesson: **an AI score you can't explain is not a good enough basis for a decision.**

---

## 10. Results (the numbers to remember)

| What | Number |
|---|---|
| Automated checks | **1,020** in **20** test suites, all run offline |
| Job sources used together | **5** by default (plus 2 optional) |
| One live run | **143** listings fetched, **88** unique, **24** scored, **10** new matches saved, in about **a minute** |
| Where the new jobs came from | Jooble 9, Adzuna 1 |
| Tailored resume example | score **7.8 → 8.0**, real gaps listed (Kubernetes, Azure, GCP), nothing invented |
| Early AI-only run | 5 jobs all scored **8.5 to 9.2**: the reason for rule-based scoring |
| Workflow map | **40** steps and services, **52** connections, a 9-step walkthrough |
| Bugs the tests caught | e.g. a count query ignoring the privacy filter; resumes publicly downloadable |

---

## 11. Limitations and what is next (be honest, panels like honesty)

**Limits:**
- Scores are **estimates**. They depend on how well the posting and resume describe skills; short snippets give weaker evidence.
  We have not measured them against real hiring outcomes.
- Platforms like **Wellfound, LinkedIn and Naukri** need a login, so the user presses Submit.
- **Form filling was tested on local copies of the forms**, not on live company pages, and many pages show a CAPTCHA.
- **Replies are not tracked:** the system does not read your mailbox, so Interview/Rejected is moved by hand.
- All users **share the server's keys and free quotas**; an invite code limits who can sign up.
- **Free hosting can sleep**, so the first request after a pause can be slow.

**Next steps (future scope):**
- Read replies from the mailbox (with permission) to update status automatically, plus follow-up reminders.
- More sources (Workday sites, Careerjet) and more company boards.
- Interview preparation notes from skill gaps.
- A group view for a placement cell.
- A mobile app, salary/company insights, resumes and jobs in Indian languages.

---

## 12. Slide by slide: what to say

The presentation (`docs/Report/Job_Application_Autopilot_Presentation (1).pptx`) has 20 slides. About 1.5 to 2 minutes each
is plenty; slides 1, 2, 18, 19 and 20 are quick.

| # | Slide | What to say (short) |
|---|---|---|
| 1 | Title | Names, guide, one-line description. |
| 2 | Outlines | "We will cover the problem, the idea, the design, results, safety and what is next." |
| 3 | Introduction | The four problems (repeated searching, reading to qualify, writing letters, losing track). "Our idea: upload your resume once; **you decide where to apply**." |
| 4 | Literature review | Early recommenders, person-job fit with deep learning (needs big recruiter data), LLMs read a whole resume and job at once. **Research gap:** no single flow, scores with no breakdown, risky auto-apply, no learning from the user. "We close all four." |
| 5 | Objectives | Read the eight in your own words: many sources, merge and filter, visible-rule score, letter and tailored resume, Telegram with learning, safe approval-based applying, private accounts, one website. |
| 6 | Proposed model | The 7 boxes = section 4 in short. Mention that each job is processed on its own and saved before its alert. |
| 7 | Architecture and technology | Show the diagram, then the table. Mention: the website talks to the server over HTTPS with a signed token; the database filters by owner. Point to the **workflow map**. |
| 8 | Website features | Dashboard (live progress), job list, job page, tracker, analytics, profile, export, workflow map. |
| 9 | Website tour | Screenshots: dashboard with live progress, job page with breakdown, profile with Telegram link, Telegram alert. |
| 10 | Result analysis | 1,020 checks, 20 suites, 10 new jobs, 88 unique from 143. What worked, and the bugs we found and fixed (count query, public resumes). |
| 11 | Limitations | Be plain and calm: estimates, assisted apply on login sites, tested locally, no reply tracking, shared quotas. |
| 12 | Job sources | Five sources by default, two optional; each is a plug-in that fails quietly; duplicates merged; AI falls back Gemini, Groq, OpenRouter. |
| 13 | Explainable score | The key idea of the project (section 5). "AI reads, rules decide." |
| 14 | Approve, then apply | The three safe ways. "Deliberately excluded: logging in as the user." |
| 15 | Tailored resume and privacy | Resume rewritten only from real facts, honest before/after score. Each user has a private account; tests prove isolation. |
| 16 | Safety, risks and phases | The safety list, the risk table, and the six development phases. |
| 17 | Conclusion and future scope | "The system does the repetitive work. The person decides." Then future scope. |
| 18 | References | Mention only that the work builds on job-recommender research and the tools we used. |
| 19 | Acknowledgement | Thank the guide (Prof. Dr. Hriday Banerjee), the Head of the CSE department, faculty and lab staff. |
| 20 | Closing | "Thank you. Questions?" |

**Suggested split for three speakers** (change as you like): speaker 1 does slides 1 to 6 (problem, idea, process);
speaker 2 does slides 7 to 11 (architecture, website, results, limits); speaker 3 does slides 12 to 20 (sources, score,
applying, privacy, safety, conclusion). Everyone should still understand every slide.

---

## 13. Live demo script (about 5 minutes)

**Before you go on stage**
- Start the project (`docs/RUN_LOCALLY.md`): backend on port 8000, frontend on port 5173. Sign in with a demo account that
  already has a resume and some jobs.
- Do **one full search the day before** so the lists are full, and keep the live search for the demo only if internet and
  API limits are fine (JSearch has a small monthly budget, 150 searches in our settings, so don't burn it on repeat runs).
- Open these tabs: the dashboard, `http://localhost:5173/workflow.html`, and Telegram with a recent alert.
- **Backup if the internet fails:** the workflow map works from the file with no server: double-click
  `frontend/public/workflow.html`. Have the screenshots in the slides as the last fallback.

**The demo**
1. **Dashboard** (30 s): "These are my best matches, sorted by score."
2. **Find New Jobs** (60 s): press it. "Watch: it asks each source, merges, filters, scores and saves. The page tells us what
   it is doing, and each source shows its own status." Don't wait for the end if it is slow; say what the final summary shows.
3. **A job page** (60 s): open a good job. Show the **score breakdown** ("here is *why* it got this score"), the cover
   letter, and the matched and missing skills.
4. **Approve** (60 s): press *Approve & apply*. Read the box: "Before I confirm, it tells me exactly what will happen:
   dry run, no e-mail sent." Confirm and show the outcome and the timeline, and the **tailored resume** with before and after.
5. **Telegram** (30 s): show the alert with the buttons. "The same Approve and Skip are here on my phone."
6. **Privacy** (30 s): sign out and show the sign-in page, or open the **Profile** page. "Each person only sees their own data."
7. **Workflow map** (60 s): open it, press *Walkthrough*. "This map explains the whole system to anyone, and the second tab
   lists every key we use."

---

## 14. Questions the panel may ask (with simple answers)

**Q1. Does it apply to jobs automatically?**
Only after you approve each job, and only in safe ways: an e-mail to the recruiter, a pre-filled company form that stops
before Submit, or a link and letter ready for you to submit. Real e-mail sending is off by default (dry run).

**Q2. Why not let the AI give the score? That is the easy way.**
We tried. In an early run five different jobs all scored 8.5 to 9.2, so the number told the user nothing and could not
explain itself. Now the AI only reads facts and a fixed formula scores, so every score has a breakdown that can be checked
and tuned.

**Q3. How do you know the score is accurate?**
Honestly: it is an estimate, and we have not tested it against real hiring results. What we can show is that it is
consistent, explainable, and adjusts to the user's own Approve and Skip choices. It is a ranking aid, not a promise of an interview.

**Q4. Can the AI invent things in the cover letter or tailored resume?**
We tell it to use only real details, and for resumes we also **check**: every skill, employer, title, date and number in the
rewritten resume must be found in the original, or it is removed. Skills the job wants but you don't have are shown as gaps,
never added.

**Q5. Is it allowed to scrape or auto-apply on job sites?**
We avoid the risky parts. We use official APIs and public company boards. We do not log in as the user on sites that forbid
bots, and scraped sources are optional, polite and off by default.

**Q6. What if one website or API stops working?**
Each source is a separate plug-in. A failure is retried, reported in plain words, and the others continue. The AI also
falls back from Gemini to Groq to OpenRouter. This actually happened during the project and the run still finished.

**Q7. How is each user's data kept private?**
Every row of personal data has an owner. The database session adds the owner condition to every query automatically, so
code can't forget it, and a session with no user can't read personal data. We tested it by trying to read, change and
delete another user's data through every kind of endpoint.

**Q8. How are passwords stored?**
Never as plain text. They are stored as salted scrypt hashes, sessions use signed tokens that stop working after a password
change, and repeated wrong sign-ins are slowed down.

**Q9. Why Telegram?**
It is free, on every phone, and supports buttons, so Approve and Skip are one tap. The website has the same buttons.

**Q10. What does it cost to run?**
Everything we use has a free tier (Vercel, Render, free AI and job APIs). The limits are real: JSearch has a small monthly budget (150 searches in our settings), and Groq has per-minute limits. That is why we use a monthly budget, only send the best jobs to the AI, and cache work.

**Q11. How is this different from LinkedIn or Naukri job alerts?**
They alert on keywords and stop there. We join search across many sources, judge the fit against your actual resume with an
explanation, write the paperwork, let you approve, apply safely, track everything, and learn from your choices.

**Q12. Can many people use it at once?**
Yes. Each person has their own account, data, search runs and Telegram chat. They share the server's keys and free quotas, so
for a real deployment an invite code limits who can join.

**Q13. Why SQLite and PostgreSQL both?**
SQLite needs no setup on a laptop. PostgreSQL is a proper server database for online use. The same code works with both, and
migrations update the schema safely without losing data.

**Q14. How did you test it?**
20 automated test suites with 1,020 checks. Outside services are replaced with saved responses, so tests run offline and
spend no quota. They cover normal cases and failures (AI error, Telegram down, database down), the privacy rules, and every route.

**Q15. What was the hardest part?**
Making the score trustworthy, and making a multi-user system safe. The privacy filter even exposed a real bug in one query
style, which our tests caught before it could leak anything.

**Q16. What did you learn?**
That a plain AI answer is not a good basis for a decision unless it can be explained; that outside services change and fail,
so design for failure; and that automation should keep the human in control.

**Q17. What would you do next?**
Read replies from the mailbox (with permission) to update status automatically, add more sources, and give placement cells a
group view.

**Q18. What if someone steals the API keys?**
Keys live only in a private settings file or the host's environment, never in the code repository, and are hidden from error
messages. If one leaks, it is replaced at its provider and in the settings.

**Q19. Is a user's resume sent to AI companies?**
Yes: the resume text and the job text are sent to the AI provider to extract facts and write the letter, which is why users
should only use their own resume and the AI providers' terms apply. Resumes are not shared with other users.

**Q20. What is the workflow map?**
An interactive page that shows every step and service as boxes and connections, like n8n or Make. Click a box to see what it
does, which keys it needs and which code runs it. It also lists every API key and where to set it.

---

## 15. Plain-words glossary

| Word | Meaning |
|---|---|
| **API** | A way for one program to ask another program for data (for example, "give me jobs for Python developer"). |
| **LLM** (large language model) | An AI such as Gemini that reads and writes text. |
| **Pipeline** | The fixed chain of steps a job goes through, from fetching to saving. |
| **Plug-in / source** | One job provider with the same small interface as the others, so one can fail without stopping the rest. |
| **De-duplication** | Merging the same job found on several sites into one. |
| **Hard filter** | A rule that removes a job before any scoring (too much experience, wrong place). |
| **Explainable score** | A score made of visible parts, so you can see why it is high or low. |
| **Dry run** | Doing everything except the final real action (for example, preparing an e-mail but not sending it). |
| **Webhook** | A web address Telegram calls when you tap a button. |
| **Migration** | A safe, versioned update of the database structure that keeps the existing data. |
| **JWT / token** | A signed proof that you are signed in, sent with every request. |
| **scrypt hash** | A one-way scrambled form of a password, so the real password is never stored. |
| **Per-user filter (tenancy)** | The rule that every query automatically only sees the signed-in user's rows. |
| **Playwright** | A tool that controls a real browser, used to pre-fill company application forms. |
| **CORS / HTTPS** | Browser safety rules and encrypted web traffic between the website and the server. |

---

## 16. Last-minute checklist

- [ ] Report: press **Ctrl + A**, then **F9** in Word and click Yes if asked, so page numbers are right. Replace the screenshot frames (see `docs/Report/SCREENSHOT_GUIDE.md`).
- [ ] Presentation: replace the four screenshot frames on slide 9. Flip through all 20 slides once.
- [ ] Project runs on the laptop (`docs/RUN_LOCALLY.md`); demo account has a resume and jobs; Telegram has a recent alert.
- [ ] Workflow map opens offline (`frontend/public/workflow.html`).
- [ ] Know the five numbers: **1,020** checks, **20** suites, **143 → 88 → 10** (fetched, unique, saved), **5** sources, **40** map steps.
- [ ] Know the one sentence: **the system does the repetitive work; the person decides where to apply.**
