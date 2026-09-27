from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List

import models, schemas, crud
from database import SessionLocal, engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Job Application Autopilot API")

# Allow CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Job Application Autopilot API is running"}

@app.get("/api/jobs", response_model=List[schemas.JobResponse])
def read_jobs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    jobs = crud.get_jobs(db, skip=skip, limit=limit)
    return jobs

@app.get("/api/jobs/{job_id}", response_model=schemas.JobResponse)
def read_job(job_id: int, db: Session = Depends(get_db)):
    db_job = crud.get_job(db, job_id=job_id)
    if db_job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return db_job

@app.post("/api/jobs", response_model=schemas.JobResponse)
def create_job(job: schemas.JobCreate, db: Session = Depends(get_db)):
    return crud.create_job(db=db, job=job)

@app.put("/api/jobs/{job_id}", response_model=schemas.JobResponse)
def update_job(job_id: int, job: schemas.JobUpdate, db: Session = Depends(get_db)):
    db_job = crud.update_job(db, job_id=job_id, job=job)
    if db_job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return db_job

@app.delete("/api/jobs/{job_id}", response_model=schemas.JobResponse)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    db_job = crud.delete_job(db, job_id=job_id)
    if db_job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return db_job
