from sqlalchemy.orm import Session
import models, schemas, crud
from database import SessionLocal, engine

models.Base.metadata.create_all(bind=engine)

mock_jobs = [
    {
        "title": "Senior Frontend Developer",
        "company": "TechCorp Solutions",
        "url": "https://example.com/job/1",
        "location": "Remote, USA",
        "description": "We are looking for an experienced React developer to lead our frontend team...",
        "job_type": "Full-time",
        "experience": "5+ years",
        "source": "LinkedIn",
        "score": 9.2,
        "match_reason": "Matches your heavy React experience and remote preference. Strong overlap in required skills like TypeScript and state management.",
        "cover_letter": "Dear TechCorp Hiring Team,\n\nI am writing to express my interest in the Senior Frontend Developer position...",
        "status": "To Apply"
    },
    {
        "title": "Full Stack Engineer",
        "company": "StartupX",
        "url": "https://example.com/job/2",
        "location": "New York, NY (Hybrid)",
        "description": "Join our fast-paced startup building next-gen AI tools. Python and React required.",
        "job_type": "Full-time",
        "experience": "3+ years",
        "source": "Y Combinator",
        "score": 8.5,
        "match_reason": "Good match for your Python and React skills. Location is hybrid, which fits your profile.",
        "cover_letter": "Dear StartupX Team,\n\nAs a Full Stack Engineer with extensive experience in React and Python...",
        "status": "Applied"
    },
    {
        "title": "Backend Developer (Python)",
        "company": "Enterprise Systems",
        "url": "https://example.com/job/3",
        "location": "San Francisco, CA",
        "description": "Looking for a Python expert to scale our microservices architecture.",
        "job_type": "Contract",
        "experience": "4+ years",
        "source": "Indeed",
        "score": 7.8,
        "match_reason": "Strong Python match, but it's a contract role and requires relocation to SF.",
        "cover_letter": "Dear Hiring Manager,\n\nI am excited to apply for the Backend Developer position...",
        "status": "Interview"
    },
    {
        "title": "React Native Developer",
        "company": "MobileFirst",
        "url": "https://example.com/job/4",
        "location": "Remote, Global",
        "description": "Help us build our cross-platform mobile app using React Native.",
        "job_type": "Full-time",
        "experience": "2+ years",
        "source": "Wellfound",
        "score": 9.5,
        "match_reason": "Perfect match for your React Native experience and remote preference.",
        "cover_letter": "Hi MobileFirst Team,\n\nI've been building React Native apps for the past 3 years...",
        "status": "To Apply"
    },
    {
        "title": "Software Engineer II",
        "company": "Big Tech Inc.",
        "url": "https://example.com/job/5",
        "location": "Seattle, WA",
        "description": "Generalist software engineer role focusing on distributed systems.",
        "job_type": "Full-time",
        "experience": "3-5 years",
        "source": "Company Website",
        "score": 6.5,
        "match_reason": "Matches your general SWE experience, but lacks specific frontend focus. Requires relocation.",
        "cover_letter": "To the Big Tech Hiring Team,\n\nI am submitting my application for the Software Engineer II role...",
        "status": "Rejected"
    }
]

def load_mock_data():
    db = SessionLocal()
    try:
        # Check if we already have data
        existing = db.query(models.Job).first()
        if not existing:
            print("Loading mock data...")
            for job_data in mock_jobs:
                job = schemas.JobCreate(**job_data)
                crud.create_job(db, job)
            print("Mock data loaded successfully.")
        else:
            print("Data already exists. Skipping mock data generation.")
    finally:
        db.close()

if __name__ == "__main__":
    load_mock_data()
