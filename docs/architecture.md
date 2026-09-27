# System Architecture

## Overview
The Job Application Autopilot consists of a React frontend, a FastAPI backend, and an external Make.com automation pipeline.

## Components

### 1. Make.com Automation Pipeline (External)
- Scrapes job boards (LinkedIn, Indeed, etc.)
- Uses Gemini AI to analyze job descriptions against user profile
- Generates match score (1-10) and reason
- Drafts a cover letter
- Sends the structured data to the FastAPI backend via POST request

### 2. FastAPI Backend
- Exposes RESTful API endpoints for jobs
- SQLite database (can be migrated to PostgreSQL)
- Handles CRUD operations

### 3. React Frontend
- SaaS-style dashboard
- Fetches data from backend APIs
- Features: Dashboard, Job Listings, Job Details, Application Tracker, Settings

## Data Flow
1. **Discovery:** Make.com finds job -> Gemini AI scores it -> Make.com sends POST to `/api/jobs`
2. **Storage:** FastAPI validates with Pydantic and stores in SQLite
3. **Display:** React UI fetches via GET `/api/jobs` and displays in Dashboard/Listings
4. **Tracking:** User updates application status via PUT `/api/jobs/{id}` from the Tracker UI
