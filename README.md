# Job Application Autopilot

A complete portfolio-quality full-stack application that discovers jobs, scores them, and tracks applications.

## Architecture

- **Frontend:** React + Vite + Vanilla CSS
- **Backend:** Python + FastAPI
- **Database:** SQLite (Development)

## Local Setup

### Backend

1. Navigate to the `backend` directory.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Load mock data:
   ```bash
   python mock_data.py
   ```
4. Run the API server:
   ```bash
   uvicorn main:app --reload
   ```

### Frontend

1. Navigate to the `frontend` directory.
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the development server:
   ```bash
   npm run dev
   ```

## Future Integration (Make.com)
This application is designed to be connected to an existing Make.com automation that discovers jobs, uses Gemini AI to score them, generates cover letters, and stores them via the `/api/jobs` POST endpoint.

See `/docs/architecture.md` for more details.
