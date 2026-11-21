"""Cover letters through the LLM layer (task "write"): short, truthful, grounded in the resume."""
from typing import Optional

from pydantic import BaseModel, field_validator

import crud
from services import llm
from services.scoring.profile import CandidateProfile, get_profile

RESUME_CHARS = 2500
DESCRIPTION_CHARS = 2000

WRITER_SYSTEM = ("You write concise, specific cover letters. Use only facts from the resume; never invent "
                 "experience, employers, numbers or skills. Reply with one JSON object only.")


class _Letter(BaseModel):
    cover_letter: str

    @field_validator("cover_letter")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or len(v.strip()) < 80:
            raise ValueError("cover letter too short")
        return v.strip()


def write_cover_letter(job, resume_text: str, profile: CandidateProfile) -> tuple[str, str]:
    """Return (letter, provider). Raises llm.LLMError when no provider can write it."""
    prompt = (
        f"Job: {job.title} at {job.company} ({job.location or 'location not stated'})\n"
        f"Job description:\n{(job.description or '')[:DESCRIPTION_CHARS]}\n\n"
        f"Candidate skills: {', '.join(profile.skills[:25])}\n"
        f"Candidate resume (excerpt):\n{(resume_text or '')[:RESUME_CHARS]}\n\n"
        "Write a 3 short paragraph cover letter (under 220 words) addressed to the hiring team, linking the "
        "candidate's real projects and skills to this role. No placeholders like [Your Name]. "
        'Return JSON: {"cover_letter": "..."}'
    )
    result = llm.generate_json("write", prompt, schema=_Letter, system=WRITER_SYSTEM, max_tokens=900)
    return result.data["cover_letter"], result.provider


def ensure_cover_letter(db, job) -> Optional[str]:
    """The job's cover letter, writing (and saving) one on demand if it has none. None if that is not possible."""
    if job.cover_letter and job.cover_letter.strip():
        return job.cover_letter
    settings = crud.get_general_settings(db)
    resume = crud.get_active_resume_for_role(db, settings.active_role)
    if not resume or not (resume.extracted_text or "").strip():
        return None
    try:
        profile = get_profile(db, resume, settings.active_role, settings.target_roles)
        letter, _provider = write_cover_letter(job, resume.extracted_text, profile)
    except llm.LLMError:
        return None
    job.cover_letter = letter
    db.commit()
    return letter
