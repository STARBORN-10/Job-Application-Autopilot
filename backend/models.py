from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from database import Base
import datetime

class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    company = Column(String, index=True)
    url = Column(String)
    location = Column(String)
    description = Column(Text)
    job_type = Column(String)
    experience = Column(String)
    source = Column(String)
    posted_date = Column(DateTime, default=datetime.datetime.utcnow)
    date_found = Column(DateTime, default=datetime.datetime.utcnow)
    score = Column(Float)
    match_reason = Column(Text)
    cover_letter = Column(Text)
    status = Column(String, default="To Apply")
