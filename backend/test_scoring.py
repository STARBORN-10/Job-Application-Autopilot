"""
Offline tests for explainable scoring (services/scoring): skill aliases and fuzzy matching, role
similarity, hard filters, job facts (with the no-invention guard), candidate profile caching,
weights validation, and the deterministic score with fixed inputs and hand-computed expectations.
"""
import datetime
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker, use_temp_database

use_temp_database()

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import crud, models, schemas
import db_migrations
from database import engine, get_db
from main import app
from services import llm, matching
from services.llm import LLMResult
from services.scoring import engine as eng, facts as facts_mod, profile as profile_mod, weights as w
from services.scoring.facts import JobFacts
from services.scoring.filters import first_failure, run_hard_filters
from services.scoring.profile import CandidateProfile
from services.scoring.skills import extract_skills, match_skills, normalize_skill, skill_in_text

db_migrations.upgrade_database(engine)
Session = sessionmaker(bind=engine)

NOW = datetime.datetime(2026, 11, 21, 12, 0, 0)
SETTINGS = schemas.GeneralSettings(active_role="Backend Developer", preferred_locations="Remote, India",
                                   max_years_experience=1, min_match_score=7.0)


def job(**kw):
    base = dict(title="Backend Developer", company="Acme", location="Bengaluru, India", description="",
                source="jsearch", description_quality="full", posted_date=NOW - datetime.timedelta(days=1))
    base.update(kw)
    return schemas.JobCreate(**base)


def run():
    check = Checker("RUNNING OFFLINE SCORING TESTS")

    check.section("1. Skills: aliases, fuzzy matching, extraction")
    check(normalize_skill("JS") == "javascript" and normalize_skill("k8s") == "kubernetes", "js/k8s aliases")
    check(normalize_skill("ML") == "machine learning" and normalize_skill("Postgres") == "postgresql", "ml/postgres aliases")
    check(normalize_skill("Node JS") == "node.js" and normalize_skill("scikit learn") == "scikit-learn", "spacing variants")
    matched, missing = match_skills(["Python", "K8s", "PostgreSQL", "Kafka"], ["python3", "kubernetes", "postgres"])
    check(matched == ["python", "kubernetes", "postgresql"] and missing == ["kafka"], "match_skills with aliases")
    check(match_skills(["tensorflow 2"], ["tensorflow"])[0] == ["tensorflow 2"], "Fuzzy match of close names")
    check(match_skills(["java"], ["javascript"])[0] == [], "java is not javascript")
    found = extract_skills("We need Python, Django and REST APIs on AWS; K8s a plus. Go-getter attitude.")
    check({"python", "django", "rest api", "aws", "kubernetes"} <= set(found) and "go" not in found,
          f"Keyword extraction finds skills, ignores ambiguous words ({found})")
    check(skill_in_text("Machine Learning", "strong ML background") and not skill_in_text("Figma", "HTML/CSS only"),
          "skill_in_text checks aliases and rejects absent skills")

    check.section("2. Role similarity")
    check(matching.role_similarity("Machine Learning Engineer", "AI/ML Engineer") >= 0.9, "ML Engineer fits AI/ML Engineer")
    check(matching.role_similarity("Senior Backend Engineer", "Backend Developer") == 1.0, "engineer ~ developer")
    check(matching.role_similarity("Data Analytics Intern", "Data Analyst") == 1.0, "analyst ~ analytics")
    check(matching.role_similarity("Frontend Developer", "Backend Developer") < 0.5, "frontend is not backend")
    check(matching.is_relevant("Software Engineer, Backend", "Python Developer", "We use Python and Django"),
          "Generic engineering title relevant when the description has the core skill")
    check(not matching.is_relevant("Accounts Payable Manager", "Python Developer", "Excel"), "Unrelated title not relevant")

    check.section("3. Hard filters")
    s = SETTINGS.model_copy(update={"blocked_companies": "Bad Corp", "blocked_keywords": "night shift",
                                    "preferred_job_types": "Full-time"})
    check(first_failure(run_hard_filters(job(), s, 1.0)) is None, "Eligible job passes every filter")
    check(first_failure(run_hard_filters(job(), s, 3.0)).name == "experience", "3y > max 1y fails experience")
    check(first_failure(run_hard_filters(job(location="Berlin, Germany"), s, None)).name == "location", "Foreign location")
    check(first_failure(run_hard_filters(job(location="Not Specified"), s, None)) is None, "Unknown location passes")
    check(first_failure(run_hard_filters(job(company="Bad Corp India"), s, None)).name == "blocked_company", "Blocked company")
    check(first_failure(run_hard_filters(job(description="Rotational Night Shift"), s, None)).name == "blocked_keyword",
          "Blocked keyword (case-insensitive)")
    check(first_failure(run_hard_filters(job(job_type="INTERN"), s, None)).name == "job_type", "Internship not wanted")
    check(first_failure(run_hard_filters(job(job_type="FULLTIME"), s, None)) is None, "FULLTIME == Full-time")
    off = SETTINGS.model_copy(update={"filter_enabled": False})
    check(first_failure(run_hard_filters(job(), off, 9.0)) is None, "Experience filter can be disabled")

    check.section("4. Job facts: heuristic and AI (verified against the text)")
    hf = facts_mod.heuristic_facts(job(title="Senior Python Developer", description="Python, Django. 5+ years experience.",
                                       location="Remote"))
    check(hf.required_skills == ["python", "django"] and hf.min_years == 5.0, "Heuristic skills and years")
    check(hf.level == "senior" and hf.work_mode == "remote", "Level from title, remote work mode")
    snippet_job = job(description="Looking for a Python developer to build REST APIs.", description_quality="snippet")
    invented = {"required_skills": ["Python", "REST API", "Kubernetes", "Kafka"], "nice_to_have_skills": ["AWS"],
                "min_years": 3, "level": "mid", "work_mode": "onsite"}
    with patch("services.llm.generate_json", return_value=LLMResult(invented, "fake", "m")) as fake:
        lf = facts_mod.llm_facts(snippet_job)
    prompt = fake.call_args[0][1]
    check("short snippet" in prompt, "Snippet postings are flagged in the prompt")
    check(lf.required_skills == ["python", "rest api"] and lf.nice_to_have_skills == [],
          "Skills not present in the text are dropped (no invented facts)")
    check(set(lf.dropped_unverified) == {"Kubernetes", "Kafka", "AWS"}, "Dropped skills are recorded")
    check(lf.min_years is None, "min_years discarded when the text has no number")
    check(lf.source == "llm" and lf.provider == "fake" and lf.level == "mid", "Source/provider/level recorded")

    check.section("5. Candidate profile (cached per resume version)")
    db = Session()
    resume = crud.create_resume(db, filename="r.pdf", target_role="Backend Developer",
                                extracted_text="B.Tech CSE. Python, FastAPI, PostgreSQL, Docker. 1 year of experience.",
                                file_path="/tmp/r.pdf", file_size=1)
    hp = profile_mod.heuristic_profile(resume.extracted_text, "Backend Developer")
    check({"python", "fastapi", "postgresql", "docker"} <= set(hp.skills) and hp.years_experience == 1.0
          and hp.education_level == "bachelor", "Keyword profile: skills, years, education")
    ai_profile = {"skills": ["Python", "FastAPI", "Postgres"], "years_experience": 1, "education_level": "bachelor",
                  "roles": ["Backend Intern"], "project_keywords": ["fintech"], "preferred_roles": ["Backend Developer"]}
    with patch("services.llm.available_providers", return_value=["fake"]), \
         patch("services.llm.generate_json", return_value=LLMResult(ai_profile, "fake", "m")) as fake:
        p1 = profile_mod.get_profile(db, resume, "Backend Developer")
        p2 = profile_mod.get_profile(db, resume, "Backend Developer")
        check(fake.call_count == 1 and p1.source == "llm" and p2 == p1, "Extracted once, then served from the cache")
        check("postgresql" in p1.skills and "docker" in p1.skills, "AI skills merged with keyword hits from the resume")
        crud.replace_resume_file(db, resume.id, "r2.pdf", resume.extracted_text + " Kafka.", "/tmp/r2.pdf", 1)
        profile_mod.get_profile(db, crud.get_resume(db, resume.id), "Backend Developer")
        check(fake.call_count == 2, "Changed resume text -> re-extracted")
    with patch("services.llm.available_providers", return_value=["fake"]), \
         patch("services.llm.generate_json", side_effect=llm.LLMUnavailableError("down")):
        r2 = crud.create_resume(db, filename="x.pdf", target_role="Data Analyst", extracted_text="SQL, Excel, Tableau",
                                file_path="/tmp/x.pdf", file_size=1)
        p3 = profile_mod.get_profile(db, r2, "Data Analyst")
    check(p3.source == "heuristic" and "sql" in p3.skills, "AI down -> keyword profile (scoring never fails)")
    with patch("services.llm.available_providers", return_value=["fake"]), \
         patch("services.llm.generate_json", return_value=LLMResult(ai_profile, "fake", "m")) as fake:
        p4 = profile_mod.get_profile(db, r2, "Data Analyst")
    check(fake.call_count == 1 and p4.source == "llm", "Keyword profile is upgraded to an AI profile later")

    check.section("6. Weights")
    check(w.validate_weights(w.DEFAULT_WEIGHTS) == {"skills": 40, "role": 20, "experience": 15, "preferences": 15,
                                                    "freshness": 10}, "Defaults 40/20/15/15/10")
    for bad, label in [({**w.DEFAULT_WEIGHTS, "skills": 41}, "sum 101"), ({"skills": 100}, "missing parts"),
                       ({**w.DEFAULT_WEIGHTS, "skills": 40.5}, "fractional"), ({**w.DEFAULT_WEIGHTS, "skills": -5,
                                                                                 "role": 65}, "negative")]:
        try:
            w.validate_weights(bad)
            ok = False
        except w.WeightsError:
            ok = True
        check(ok, f"Invalid weights rejected ({label})")
    check(w.get_weights(db) == w.DEFAULT_WEIGHTS, "Defaults used when nothing is stored")

    check.section("7. Deterministic score with fixed inputs")
    profile = CandidateProfile(skills=["python", "sql", "docker"], years_experience=0, source="llm")
    facts = JobFacts(required_skills=["python", "sql", "docker", "kubernetes"], nice_to_have_skills=["aws"],
                     min_years=1, level="junior", work_mode="onsite", source="llm")
    r = eng.score_job(job(), facts, profile, SETTINGS, w.DEFAULT_WEIGHTS, now=NOW)
    parts = r.breakdown["parts"]
    # skills raw = 3 / (4 + 0.5) = 0.6667 -> 2.667 pts; role 1.0 -> 2; experience 1.0 -> 1.5;
    # preferences 1.0 -> 1.5; freshness (1 day) 1.0 -> 1.0; total 8.667 -> 8.7
    check(abs(parts["skills"]["value"] - 0.667) < 0.001 and parts["skills"]["points"] == 2.67, "Skills part 0.667 x 40")
    check(parts["role"]["value"] == 1.0 and parts["experience"]["value"] == 1.0, "Role and experience parts 1.0")
    check(parts["preferences"]["value"] == 1.0 and parts["freshness"]["value"] == 1.0, "Preferences and freshness 1.0")
    check(r.score == 8.7 and r.breakdown["total"] == 8.7, f"Total 8.7 ({r.score})")
    check(r.breakdown["matched_skills"] == ["python", "sql", "docker"] and r.breakdown["missing_skills"] == ["kubernetes"]
          and r.breakdown["nice_to_have_missing"] == ["aws"], "Matched / missing / nice-to-have recorded")
    check("3/4 required skills" in r.match_reason and "missing kubernetes" in r.match_reason, "Reason matches breakdown")

    snip = eng.score_job(job(description_quality="snippet"), facts, profile, SETTINGS, w.DEFAULT_WEIGHTS, now=NOW)
    # confidence 0.6: 0.6 * 0.6667 + 0.4 * 0.5 = 0.6 -> 2.4 pts -> 8.4
    check(snip.breakdown["confidence"] == 0.6 and snip.score == 8.4, f"Snippet: skills pulled toward neutral (8.4, got {snip.score})")
    check("short snippet" in snip.match_reason, "Reason mentions the snippet")

    old = eng.score_job(job(posted_date=NOW - datetime.timedelta(days=16, hours=12)), facts, profile, SETTINGS,
                        w.DEFAULT_WEIGHTS, now=NOW)
    check(old.breakdown["parts"]["freshness"]["value"] == 0.5, "16.5 days old with a 30-day window -> freshness 0.5")
    nodate = eng.score_job(job(posted_date=None), facts, profile, SETTINGS, w.DEFAULT_WEIGHTS, now=NOW)
    check(nodate.breakdown["parts"]["freshness"]["value"] == 0.5, "Unknown date -> neutral 0.5")

    custom = {"skills": 60, "role": 10, "experience": 10, "preferences": 10, "freshness": 10}
    check(eng.score_job(job(), facts, profile, SETTINGS, custom, now=NOW).score == 8.0, "Custom weights 60/10/10/10/10 -> 8.0")

    senior = JobFacts(required_skills=["python"], level="senior", source="llm")
    sr = eng.score_job(job(title="Senior Backend Developer"), senior, profile, SETTINGS, w.DEFAULT_WEIGHTS, now=NOW)
    check(sr.breakdown["parts"]["experience"]["value"] <= 0.3, "Senior role for a fresher -> low experience fit")
    gap = JobFacts(required_skills=["python"], min_years=2.5, source="llm")
    gr = eng.score_job(job(), gap, profile, SETTINGS, w.DEFAULT_WEIGHTS, now=NOW)
    check(gr.breakdown["parts"]["experience"]["value"] == 0.5, "1.5 years over the tolerance -> 0.5")

    # Keyword facts from a snippet: skills are pulled toward neutral, so the uncapped total is ~5.1
    offrole = JobFacts(required_skills=["html", "css"], source="heuristic")
    cr = eng.score_job(job(title="Graphic Designer", description_quality="snippet"), offrole, profile, SETTINGS,
                       w.DEFAULT_WEIGHTS, now=NOW)
    check(cr.score == 4.0 and cr.breakdown["cap"]["uncapped"] > 4.0, "Off-role title + no skill match -> capped at 4.0")
    check("Capped at 4" in cr.match_reason, "Cap is explained")
    remote = eng.score_job(job(location="Remote"), facts, profile, SETTINGS, w.DEFAULT_WEIGHTS, now=NOW)
    check(remote.breakdown["parts"]["preferences"]["location"] == "match", "Remote job matches a Remote preference")
    typed = SETTINGS.model_copy(update={"preferred_job_types": "Internship"})
    ty = eng.score_job(job(job_type=None), facts, profile, typed, w.DEFAULT_WEIGHTS, now=NOW)
    check(ty.breakdown["parts"]["preferences"]["value"] == 0.8, "Unknown job type with a type preference -> 0.8")

    check.section("8. Weights API")

    def override():
        s2 = Session()
        try:
            yield s2
        finally:
            s2.close()

    app.dependency_overrides[get_db] = override
    api = TestClient(app)
    check(api.get("/api/scoring/weights").json()["weights"] == w.DEFAULT_WEIGHTS, "GET weights")
    r = api.put("/api/scoring/weights", json={"weights": custom})
    check(r.status_code == 200 and r.json()["weights"] == custom, "PUT valid weights")
    r = api.put("/api/scoring/weights", json={"weights": {**custom, "skills": 61}})
    check(r.status_code == 422 and "100" in r.json()["detail"], "PUT weights not summing to 100 -> 422")
    check(w.get_weights(db) == custom, "Stored weights used by the scorer")
    old_job = crud.create_job(db, schemas.JobCreate(title="Old V1 job", company="X", source="JSearch", score=8.5))
    old_job.score_breakdown = None
    db.commit()
    r = api.get(f"/api/jobs/{old_job.id}")
    check(r.status_code == 200 and r.json()["score_breakdown"] is None and r.json()["source_names"] == ["JSearch"],
          "V1-style rows (no breakdown) still serialise")
    app.dependency_overrides.clear()
    db.close()
    check.done("SCORING")


if __name__ == "__main__":
    run()
