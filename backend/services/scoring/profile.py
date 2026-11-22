"""
Candidate profile: a structured summary of the active resume, extracted once by the LLM layer (task
"extract") and cached in candidate_profiles by resume id + content hash. If no AI provider works, a
keyword-based profile is used so scoring never fails; it is upgraded to an AI profile on a later run.
"""
import hashlib
import json
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

import models
from services import llm
from services.scoring.skills import extract_skills, normalize_skills

logger = logging.getLogger("scoring.profile")

RESUME_PROMPT_CHARS = 6000


class CandidateProfile(BaseModel):
    skills: list[str] = Field(default_factory=list)
    years_experience: float = 0.0
    education_level: str = "unknown"          # none / diploma / bachelor / master / phd / unknown
    roles: list[str] = Field(default_factory=list)            # roles held (internships count)
    project_keywords: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)  # roles the resume targets
    source: str = "heuristic"                 # "llm" or "heuristic"

    @field_validator("years_experience", mode="before")
    @classmethod
    def _years(cls, value):
        try:
            return max(0.0, min(50.0, float(value or 0)))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("skills", "roles", "project_keywords", "preferred_roles", mode="before")
    @classmethod
    def _lists(cls, value):
        if isinstance(value, str):
            value = [v for v in re.split(r"[,;\n]", value)]
        return [str(v).strip() for v in (value or []) if str(v).strip()][:60]


class _LLMProfile(BaseModel):
    skills: list[str] = Field(default_factory=list)
    years_experience: Optional[float] = 0
    education_level: Optional[str] = "unknown"
    roles: list[str] = Field(default_factory=list)
    project_keywords: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)


def resume_hash(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


_EDU = [("phd", r"\b(ph\.?d|doctorate)\b"), ("master", r"\b(m\.?tech|m\.?e\b|m\.?sc|mca|mba|master'?s?|ms in)\b"),
        ("bachelor", r"\b(b\.?tech|b\.?e\b|b\.?sc|bca|bachelor'?s?|undergraduate|b\.?s\b)\b"),
        ("diploma", r"\bdiploma\b")]


def heuristic_profile(resume_text: str, active_role: str = "", target_roles: str = "") -> CandidateProfile:
    text = resume_text or ""
    lowered = text.lower()
    years = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:professional\s+|work\s+|industry\s+)?experience", lowered)
    if m:
        years = float(m.group(1))
    education = next((level for level, pattern in _EDU if re.search(pattern, lowered)), "unknown")
    roles = [r.strip() for r in (target_roles or "").split(",") if r.strip()]
    preferred = [active_role] if active_role else []
    return CandidateProfile(skills=extract_skills(text), years_experience=years, education_level=education,
                            roles=[], project_keywords=[], preferred_roles=preferred + [r for r in roles if r != active_role],
                            source="heuristic")


PROFILE_SYSTEM = ("You extract structured facts from a resume. Reply with one JSON object only. "
                  "Use only what the resume states; never guess or embellish.")


def _profile_prompt(resume_text: str) -> str:
    return (
        "Resume:\n" + resume_text[:RESUME_PROMPT_CHARS] + "\n\n"
        'Return JSON: {"skills": [technical skills, tools, languages], '
        '"years_experience": number (full-time professional years; internships count as 0.25 each; 0 for students), '
        '"education_level": "none|diploma|bachelor|master|phd|unknown", '
        '"roles": [job titles held], "project_keywords": [up to 10 domain keywords from projects], '
        '"preferred_roles": [roles this resume targets, at most 4]}'
    )


def get_profile(db, resume, active_role: str = "", target_roles: str = "", use_llm: bool = True) -> CandidateProfile:
    """Cached AI profile for this resume version; re-extracts only when the resume text changes."""
    text = (resume.extracted_text or "").strip()
    digest = resume_hash(text)
    cached = None
    try:
        cached = (
            db.query(models.CandidateProfile)
            .filter(models.CandidateProfile.resume_id == resume.id, models.CandidateProfile.resume_hash == digest)
            .order_by(models.CandidateProfile.id.desc())
            .first()
        )
    except Exception:
        logger.exception("Could not read cached candidate profile")
    if cached is not None:
        try:
            profile = CandidateProfile.model_validate(json.loads(cached.profile_json))
            if profile.source == "llm" or not use_llm or not llm.available_providers():
                return _with_roles(profile, active_role)
        except (TypeError, ValueError):
            pass

    profile = heuristic_profile(text, active_role, target_roles)
    if use_llm and llm.available_providers():
        try:
            result = llm.generate_json("extract", _profile_prompt(text), schema=_LLMProfile,
                                       system=PROFILE_SYSTEM, max_tokens=900)
            data = result.data
            profile = CandidateProfile(
                # AI skills plus keyword hits: both come from the resume text itself.
                skills=normalize_skills(list(data.get("skills") or []) + profile.skills),
                years_experience=data.get("years_experience") or 0,
                education_level=(data.get("education_level") or "unknown").lower(),
                roles=data.get("roles") or [],
                project_keywords=data.get("project_keywords") or [],
                preferred_roles=data.get("preferred_roles") or [],
                source="llm",
            )
        except llm.LLMError as exc:
            logger.warning(f"Profile extraction fell back to keywords: {exc}")

    try:
        db.add(models.CandidateProfile(resume_id=resume.id, resume_hash=digest,
                                       profile_json=profile.model_dump_json()))
        db.commit()
    except Exception:
        logger.exception("Could not cache candidate profile")
        db.rollback()
    return _with_roles(profile, active_role)


def _with_roles(profile: CandidateProfile, active_role: str) -> CandidateProfile:
    if active_role and active_role not in profile.preferred_roles:
        profile = profile.model_copy(update={"preferred_roles": [active_role, *profile.preferred_roles]})
    return profile
