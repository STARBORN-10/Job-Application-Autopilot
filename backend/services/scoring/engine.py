"""
Deterministic, explainable score (0-10) computed in code from job facts and the candidate profile.

Each part is a value between 0 and 1; the score is the weighted sum (weights add up to 100) / 10.
- skills: share of required skills the candidate has (nice-to-have count half). When the evidence is
  weak (a snippet, or keyword-only facts) the value is pulled toward a neutral 0.5 in proportion to the
  missing confidence, so a short snippet can neither make nor break a job.
- role: title vs. the active role and the resume's preferred roles (services/matching.py).
- experience: required years / level vs. the candidate's years.
- preferences: location fit and preferred job type.
- freshness: 1.0 when posted in the last 3 days, falling to 0 at the maximum job age.

Relevance cap: if the title fit is below 0.35 and under a third of the stated skills match (or none
are stated), the score is capped at 4.0 and the breakdown says so.
"""
import datetime
from dataclasses import dataclass
from typing import Optional

from services import geo, matching
from services.scoring.facts import JobFacts
from services.scoring.filters import FilterResult
from services.scoring.profile import CandidateProfile
from services.scoring.skills import match_skills
from services.scoring.weights import DEFAULT_WEIGHTS, PARTS
from services.sources.common import normalize_job_type

NEUTRAL = 0.5
RELEVANCE_ROLE_MIN = 0.35
RELEVANCE_SKILLS_MIN = 0.34
RELEVANCE_CAP = 4.0
CONFIDENCE = {("llm", "full"): 1.0, ("llm", "snippet"): 0.6, ("heuristic", "full"): 0.7, ("heuristic", "snippet"): 0.45}


@dataclass
class ScoreResult:
    score: float
    breakdown: dict
    match_reason: str


def _skills_part(facts: JobFacts, profile: CandidateProfile, quality: str) -> tuple[float, dict]:
    candidate = profile.skills + profile.project_keywords
    matched, missing = match_skills(facts.required_skills, candidate)
    nice_matched, nice_missing = match_skills(facts.nice_to_have_skills, candidate)
    denominator = len(matched) + len(missing) + 0.5 * (len(nice_matched) + len(nice_missing))
    confidence = CONFIDENCE.get((facts.source, quality), 0.5)
    if denominator == 0:
        raw, confidence = NEUTRAL, min(confidence, 0.3)
    else:
        raw = (len(matched) + 0.5 * len(nice_matched)) / denominator
    value = confidence * raw + (1 - confidence) * NEUTRAL
    return value, {
        "raw": round(raw, 3), "confidence": round(confidence, 2),
        "matched": matched, "missing": missing, "nice_matched": nice_matched, "nice_missing": nice_missing,
        "detail": (f"{len(matched)}/{len(matched) + len(missing)} required skills" if matched or missing
                   else "no skills stated in the posting"),
    }


def _role_part(title: str, active_role: str, profile: CandidateProfile) -> tuple[float, dict]:
    active = matching.role_similarity(title, active_role)
    others = [r for r in profile.preferred_roles if r and r != active_role]
    other_best, other_role = matching.best_role_similarity(title, others)
    value = max(active, 0.9 * other_best)
    best = active_role if active >= 0.9 * other_best else other_role
    return value, {"detail": f"title vs '{best}'", "matched_role": best}


def _experience_part(facts: JobFacts, profile: CandidateProfile, max_years: int) -> tuple[float, dict]:
    candidate = max(profile.years_experience, 0.0)
    tolerance = max(candidate, float(max_years))
    if facts.min_years is not None:
        gap = facts.min_years - tolerance
        value = 1.0 if gap <= 0 else max(0.0, 1.0 - gap / 3.0)
        detail = f"asks {facts.min_years:g}y, you have {candidate:g}y"
    else:
        by_level = {"intern": 1.0, "junior": 1.0, "mid": 0.55, "senior": 0.15, "unknown": 0.7}
        if candidate >= 3:
            by_level.update({"intern": 0.5, "junior": 0.8, "mid": 1.0, "senior": 0.6})
        value = by_level.get(facts.level, 0.7)
        detail = f"level {facts.level}, no years stated"
    if facts.level == "senior" and candidate < 3:
        value = min(value, 0.3)
    return value, {"detail": detail, "level": facts.level, "min_years": facts.min_years}


def _preferences_part(job, facts: JobFacts, settings) -> tuple[float, dict]:
    prefs = geo.split_preferences(settings.preferred_locations)
    verdict = geo.location_match(job.location, prefs)
    location_value = {"match": 1.0, "unknown": 0.6, "mismatch": 0.0}[verdict]
    wants_remote = any(p.lower() == "remote" for p in prefs)
    if wants_remote and facts.work_mode == "remote":
        location_value = 1.0
    wanted_types = [normalize_job_type(t) for t in (getattr(settings, "preferred_job_types", "") or "").split(",") if t.strip()]
    job_type = normalize_job_type(job.job_type)
    if not wanted_types:
        type_value = 1.0
    elif job_type is None:
        type_value = 0.6
    else:
        type_value = 1.0 if job_type in wanted_types else 0.0
    return (location_value + type_value) / 2, {
        "detail": f"location {verdict}, work mode {facts.work_mode}, type {job_type or 'not stated'}",
        "location": verdict, "work_mode": facts.work_mode,
    }


def _freshness_part(posted: Optional[datetime.datetime], max_age_days: int, now: datetime.datetime) -> tuple[float, dict]:
    if not posted:
        return NEUTRAL, {"detail": "posting date unknown", "age_days": None}
    if posted.tzinfo:
        posted = posted.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    age = max(0.0, (now - posted).total_seconds() / 86400)
    horizon = max(4, max_age_days)
    value = 1.0 if age <= 3 else max(0.0, 1.0 - (age - 3) / (horizon - 3))
    return value, {"detail": f"posted {age:.0f} day(s) ago", "age_days": round(age, 1)}


def score_job(job, facts: JobFacts, profile: CandidateProfile, settings, weights: Optional[dict] = None,
              filters: Optional[list[FilterResult]] = None, now: Optional[datetime.datetime] = None) -> ScoreResult:
    weights = weights or DEFAULT_WEIGHTS
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    quality = getattr(job, "description_quality", None) or "full"
    active_role = settings.active_role or "AI/ML Engineer"

    values, details = {}, {}
    values["skills"], details["skills"] = _skills_part(facts, profile, quality)
    values["role"], details["role"] = _role_part(job.title, active_role, profile)
    values["experience"], details["experience"] = _experience_part(facts, profile, settings.max_years_experience)
    values["preferences"], details["preferences"] = _preferences_part(job, facts, settings)
    values["freshness"], details["freshness"] = _freshness_part(getattr(job, "posted_date", None),
                                                                getattr(settings, "max_job_age_days", 30) or 30, now)

    parts = {}
    total = 0.0
    for part in PARTS:
        points = weights[part] * values[part] / 10.0
        total += points
        parts[part] = {"value": round(values[part], 3), "weight": weights[part], "points": round(points, 2),
                       **{k: v for k, v in details[part].items() if k not in ("matched", "missing", "nice_matched", "nice_missing")}}
    skill = details["skills"]
    # Relevance cap: eligibility parts (experience, preferences, freshness) are full for most fresher
    # jobs, so an off-role posting could otherwise score well. When neither the title nor the skills fit,
    # the score is capped.
    cap = None
    if values["role"] < RELEVANCE_ROLE_MIN and skill["raw"] < RELEVANCE_SKILLS_MIN and total > RELEVANCE_CAP:
        cap = {"limit": RELEVANCE_CAP, "uncapped": round(total, 1),
               "reason": "title and skills do not fit your role"}
        total = RELEVANCE_CAP
    score = round(total, 1)  # points are weight x value / 10, so they already add up to 0-10
    breakdown = {
        "version": 2,
        "total": score,
        "parts": parts,
        "matched_skills": skill["matched"],
        "missing_skills": skill["missing"],
        "nice_to_have_matched": skill["nice_matched"],
        "nice_to_have_missing": skill["nice_missing"],
        "confidence": skill["confidence"],
        "facts_source": facts.source,
        "llm_provider": facts.provider,
        "description_quality": quality,
        "job_facts": {"min_years": facts.min_years, "level": facts.level, "work_mode": facts.work_mode},
        "dropped_unverified_skills": facts.dropped_unverified,
        "filters": [f.as_dict() for f in (filters or [])],
        "cap": cap,
    }
    return ScoreResult(score=score, breakdown=breakdown, match_reason=explain(breakdown))


def explain(breakdown: dict) -> str:
    """Short reason text built only from the breakdown, so it always agrees with the numbers."""
    parts = breakdown["parts"]
    matched, missing = breakdown["matched_skills"], breakdown["missing_skills"]
    bits = []
    if matched or missing:
        line = f"Has {len(matched)}/{len(matched) + len(missing)} required skills"
        if matched:
            line += f" ({', '.join(matched[:4])})"
        if missing:
            line += f"; missing {', '.join(missing[:3])}"
        bits.append(line)
    else:
        bits.append("Posting lists no clear skills")
    role = parts["role"]
    bits.append(f"title fit {role['value']:.0%} vs {role.get('matched_role') or 'your role'}")
    bits.append(parts["experience"]["detail"])
    bits.append(parts["preferences"]["detail"])
    bits.append(parts["freshness"]["detail"])
    text = "; ".join(bits) + "."
    if breakdown.get("cap"):
        text += f" Capped at {breakdown['cap']['limit']:g}: {breakdown['cap']['reason']}."
    if breakdown["description_quality"] == "snippet":
        text += " Based on a short snippet, so skills carry less weight."
    return text[0].upper() + text[1:]
