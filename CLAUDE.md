# Job Application Autopilot - Project Instructions

## Git / GitHub identity (IMPORTANT)

- This is a **personal project**, NOT a company project.
- Always use my **personal GitHub account: `anubhav7723`** for everything in this repo (commits, pushes, forks, PRs, issues).
- **Never use `anubhav526`** (my company GitHub account) here, even though `gh` may be logged in as it by default.
- Commit identity for this repo (already set in local `.git/config`):
  - `user.name  = anubhav7723`
  - `user.email = 178323394+anubhav7723@users.noreply.github.com`
- Before any `git push`, `gh pr ...` or `gh repo ...` command, check the active account with `gh auth status`. If it is not `anubhav7723`, stop and tell me instead of proceeding.
- Do not add `Co-Authored-By: Claude ...` trailers or any Claude/Anthropic attribution to commits, and no "Generated with Claude Code" lines in PR descriptions.

## Repo context

- Upstream (owner: friend, I am a contributor): https://github.com/STARBORN-10/Job-Application-Autopilot
- Contribute via a fork under `anubhav7723` and open PRs to upstream; do not push directly to upstream `main` unless I say so.
- Stack: FastAPI + SQLAlchemy backend (`backend/`), React + Vite frontend (`frontend/`), docs in `docs/`.
