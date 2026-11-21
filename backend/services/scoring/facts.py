"""
Job facts: required / nice-to-have skills, minimum years, level and work mode.

Two ways to get them:
- heuristic_facts(): keyword scan, no AI, used for the cheap pre-score of every job;
- llm_facts(): the LLM layer (task "extract") for the top jobs of a run.

LLM output is checked against the posting text: a skill that does not appear in the text (by name
or alias) is dropped, and a minimum-years value without any number in the text is discarded, so
short snippets (Adzuna, Jooble) never get invented requirements.
"""
import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from services import geo, llm
from services.scoring.skills import extract_skills, normalize_skills, skill_in_text
from services.sources.common import experience_from_text

DESCRIPTION_PROMPT_CHARS = 3500
LEVELS = ("intern", "junior", "mid", "senior", "unknown")
WORK_MODES = ("remote", "hybrid", "onsite", "unknown")


class JobFacts(BaseModel):
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    min_years: Optional[float] = None
    level: str = "unknown"
    work_mode: str = "unknown"
    source: str = "heuristic"           # "llm" or "heuristic"
    provider: Optional[str] = None
    dropped_unverified: list[str] = Field(default_factory=list)

    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, v):
        v = (v or "unknown").lower()
        return v if v in LEVELS else "unknown"

    @field_validator("work_mode", mode="before")
    @classmethod
    def _mode(cls, v):
        v = (v or "unknown").lower().replace("on-site", "onsite").replace("on site", "onsite")
        return v if v in WORK_MODES else "unknown"

    @field_validator("min_years", mode="before")
    @classmethod
    def _years(cls, v):
        try:
            return None if v in (None, "") else max(0.0, min(30.0, float(v)))
        except (TypeError, ValueError):
            return None


class _LLMFacts(BaseModel):
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    min_years: Optional[float] = None
    level: Optional[str] = "unknown"
    work_mode: Optional[str] = "unknown"


def _years_from(experience: Optional[str]) -> Optional[float]:
    if not experience:
        return None
    if re.search(r"\b(fresher|intern|entry)", experience.lower()):
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)", experience)
    if not m:
        return None
    value = float(m.group(1))
    return value / 12.0 if re.search(r"month|mos?\b", experience.lower()) else value


def level_from_title(title: str) -> str:
    t = (title or "").lower()
    if re.search(r"\b(intern|internship|trainee|apprentice)\b", t):
        return "intern"
    if re.search(r"\b(senior|sr\.?|lead|principal|staff|architect|head|manager|director)\b", t):
        return "senior"
    if re.search(r"\b(junior|jr\.?|graduate|fresher|entry|associate)\b", t):
        return "junior"
    if re.search(r"\b(ii|iii|mid)\b", t):
        return "mid"
    return "unknown"


def work_mode_of(job) -> str:
    text = f"{job.location or ''} {(job.description or '')[:600]}"
    if geo.is_remote(job.location) or re.search(r"\b(fully remote|remote[- ]first|100% remote)\b", text.lower()):
        return "remote"
    if geo.is_hybrid(text):
        return "hybrid"
    if job.location and job.location.strip().lower() not in ("not specified", ""):
        return "onsite"
    return "unknown"


def heuristic_facts(job) -> JobFacts:
    text = f"{job.title or ''}\n{job.description or ''}"
    years = _years_from(job.experience) if job.experience else _years_from(experience_from_text(job.description))
    level = level_from_title(job.title)
    if level == "unknown" and years is not None:
        level = "junior" if years <= 1 else "mid" if years < 5 else "senior"
    return JobFacts(required_skills=extract_skills(text), min_years=years, level=level,
                    work_mode=work_mode_of(job), source="heuristic")


FACTS_SYSTEM = ("You extract facts from a job posting. Reply with one JSON object only. Use ONLY information "
                "stated in the text. If something is not stated, use null, \"unknown\" or an empty list. Never guess.")


def _facts_prompt(job) -> str:
    quality = getattr(job, "description_quality", None) or "full"
    note = "NOTE: this is only a short snippet of the posting; list only what it states.\n" if quality == "snippet" else ""
    return (
        f"{note}Title: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n"
        f"Experience field: {job.experience or 'not given'}\n"
        f"Description:\n{(job.description or '')[:DESCRIPTION_PROMPT_CHARS]}\n\n"
        'Return JSON: {"required_skills": [skills the posting requires], '
        '"nice_to_have_skills": [skills marked preferred/bonus/nice to have], '
        '"min_years": number or null, "level": "intern|junior|mid|senior|unknown", '
        '"work_mode": "remote|hybrid|onsite|unknown"}'
    )


def llm_facts(job, fallback: Optional[JobFacts] = None) -> JobFacts:
    """AI-extracted facts, verified against the posting text. Raises llm.LLMError when no provider works."""
    result = llm.generate_json("extract", _facts_prompt(job), schema=_LLMFacts, system=FACTS_SYSTEM, max_tokens=600)
    data = result.data
    text = f"{job.title or ''}\n{job.experience or ''}\n{job.description or ''}"
    dropped: list[str] = []

    def verified(skills):
        keep = []
        for s in skills or []:
            if isinstance(s, str) and s.strip():
                (keep if skill_in_text(s, text) else dropped).append(s.strip())
        return normalize_skills(keep)

    required = verified(data.get("required_skills"))
    nice = [s for s in verified(data.get("nice_to_have_skills")) if s not in required]
    min_years = data.get("min_years")
    if min_years is not None and not re.search(r"\d", text):
        min_years = None
    base = fallback or heuristic_facts(job)
    return JobFacts(
        required_skills=required,
        nice_to_have_skills=nice,
        min_years=min_years if min_years is not None else base.min_years,
        level=data.get("level") if (data.get("level") or "unknown") != "unknown" else base.level,
        work_mode=data.get("work_mode") if (data.get("work_mode") or "unknown") != "unknown" else base.work_mode,
        source="llm",
        provider=result.provider,
        dropped_unverified=dropped[:10],
    )
