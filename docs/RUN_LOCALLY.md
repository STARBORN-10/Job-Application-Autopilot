# Run Job Application Autopilot on your own computer

Everything here is copy and paste. You need **Python 3.13** (what the project is built and tested with; a newer one should work), **Node.js 20 or newer** and **Git**.
Nothing on this page touches the hosted website.

The project has two parts that run at the same time, each in its own terminal window:

| Part | What it is | Address |
|---|---|---|
| Backend | The Python server (jobs, scoring, accounts) | http://localhost:8000 |
| Frontend | The website you click around in | http://localhost:5173 |

---

## 1. First time only: set up

Open a terminal in the project folder (the one that contains `backend` and `frontend`).

### Windows (PowerShell)

```powershell
# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
cd ..

# Frontend
cd frontend
npm install
cd ..
```

If PowerShell refuses to run the activate script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.

### Mac or Linux

```bash
# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cd ..

# Frontend
cd frontend
npm install
cd ..
```

### Put your keys in `backend/.env`

Open `backend/.env` in any editor and fill in the keys you have. A feature without its key is skipped with a clear
message, so you can start with none. The full list, what each key is for, and where to get it is on the
**Keys & services** tab of the workflow map (see section 4) and in `docs/deployment.md`.

The most useful ones: `RAPIDAPI_KEY` (JSearch), `GEMINI_API_KEY` and/or `GROQ_API_KEY` (AI),
`ADZUNA_APP_ID` / `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`.

Never commit `backend/.env` to Git. It is already ignored.

---

## 2. Every time: start it

Use **two** terminal windows.

### Terminal 1: the backend

**Windows (PowerShell)**
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --port 8000
```

**Mac or Linux**
```bash
cd backend
source .venv/bin/activate
uvicorn main:app --port 8000
```

Wait for the line `Application startup complete`. Check it at http://localhost:8000/api/health: it should say
`"status":"ok"`.

### Terminal 2: the frontend

```bash
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

### Stop it

Click in each terminal and press **Ctrl + C**.

---

## 3. Your account

Accounts are on by default. The first time you open the site you see a sign-in page:

1. Press **Create an account** and choose an e-mail and a password (at least 8 characters).
2. **The first account keeps all the jobs, resumes and settings that already exist** in `backend/jobs.db`.
   Every later account starts empty and can never see anyone else's data.
3. Use **Profile** (sidebar) to set your name, your contact details for application forms, to connect Telegram, to
   change your password or to delete your account.

You stay signed in for 7 days on that browser. **Sign out** is the arrow at the bottom of the sidebar.

**Want no login at all on your own computer?** Add this line to `backend/.env` and restart the backend:

```
AUTH_ENABLED=false
```

Then the site opens straight to the dashboard, like before, with one shared set of data.

**Forgot your password?** There is no e-mail reset, but you own the computer. From the `backend` folder, with the
virtual environment active:

```bash
python manage_users.py list                          # see the accounts
python manage_users.py reset-password you@example.com   # asks for a new password
```

Other commands: `disable`, `enable` and `signout-all` (run `python manage_users.py help`).

---

## 4. The workflow map (explain the project to anyone)

An interactive, n8n-style map of the whole system: every step, how they connect, the job sources, and every key
and setting (names only). Click a box for details, press **Walkthrough** for a 9-step tour.

| How | Command or address |
|---|---|
| While the frontend is running | http://localhost:5173/workflow.html (or **Workflow map** in the sidebar) |
| Without running anything | Double-click `frontend/public/workflow.html` (it works from a file, no server needed) |

The file is one self-contained HTML page. Put it on a USB stick or email it, and it opens in any browser.

---

## 5. Telegram alerts on your computer (optional)

1. Create a bot: in Telegram open **@BotFather**, send `/newbot`, and copy the token it gives you.
2. Add these lines to `backend/.env`, then restart the backend:
   ```
   TELEGRAM_BOT_TOKEN=the token from BotFather
   TELEGRAM_MODE=polling
   ```
3. In the website open **Profile, Connect Telegram**, and send the bot the code it shows. The page connects by itself.

`polling` means the backend asks Telegram for new button taps, so no public address is needed. Do not use polling
on your computer while the hosted site uses the Telegram webhook with the same bot, because they take turns.

---

## 6. Useful commands

Run these from the `backend` folder with the virtual environment active.

| Task | Command |
|---|---|
| Run every test (takes about a minute, uses no real service) | `python run_tests.py` |
| Run one test file | `python -W ignore test_auth.py` |
| Apply database updates by hand (it also happens at startup) | `alembic upgrade head` |
| Make a backup before experimenting (SQLite) | copy `backend/jobs.db` somewhere safe |

From the `frontend` folder:

| Task | Command |
|---|---|
| Check the code style | `npm run lint` |
| Build the production site | `npm run build` |

### Optional extras

Form filling on company career pages and the Indeed/LinkedIn source need extra packages:

```bash
cd backend
pip install -r requirements-optional.txt
python -m playwright install chromium
```

---

## 7. If something goes wrong

| What you see | What to do |
|---|---|
| "Port already in use" | Something is still running. Windows: `netstat -ano \| findstr :8000` then `taskkill /PID <number> /F`. Mac/Linux: `lsof -i :8000` then `kill <number>`. Or start on another port: `uvicorn main:app --port 8001` (then set `VITE_API_URL=http://localhost:8001/api` for the frontend). |
| The page says the server is not responding | The backend is not running, or is still starting. Check Terminal 1 and http://localhost:8000/api/health. |
| "Please sign in" keeps appearing after a restart | You have no `AUTH_SECRET` and the file `backend/.auth_secret` could not be written. Set `AUTH_SECRET=` to any long random text in `backend/.env`. |
| Jobs search finds nothing or fails | Open **Settings, Sources**: each source shows if its key is missing or rejected. |
| Telegram is silent | Check the token, that you pressed **Connect Telegram**, and that `TELEGRAM_MODE=polling` is set and the backend restarted. |
| You want to start from nothing | Stop the backend, move `backend/jobs.db` aside, start again (a new empty database is created). |

---

## 8. Where things are

| Folder or file | What it holds |
|---|---|
| `backend/main.py` | The API (endpoints) |
| `backend/auth.py`, `backend/tenancy.py` | Accounts and the rule that keeps each person's data private |
| `backend/services/` | The pipeline, job sources, scoring, AI, Telegram, applying |
| `frontend/src/` | The website |
| `frontend/public/workflow.html` | The workflow map |
| `docs/` | Architecture, deployment, this guide, the report |
