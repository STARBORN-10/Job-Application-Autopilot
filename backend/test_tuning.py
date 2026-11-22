"""
Offline tests for learning score weights from decisions (services/scoring/tuning.py) with synthetic
decisions: minimum data guard, direction of change, guard rails (max step, bounds, sum 100),
determinism, apply flag, and the admin-protected API.
"""
import json
import os
import random
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
from services.decisions import record_decision
from services.scoring import tuning, weights as w

db_migrations.upgrade_database(engine)
Session = sessionmaker(bind=engine)


def add_decisions(db, n, rule, seed=7):
    """n jobs with random part values; `rule(parts)` decides approve (True) / skip (False)."""
    rng = random.Random(seed)
    for i in range(n):
        parts = {p: {"value": round(rng.random(), 3), "weight": 20, "points": 0} for p in w.PARTS}
        job = crud.create_job(db, schemas.JobCreate(title=f"Job {seed}-{i}", company=f"C{seed}-{i}", score=5.0,
                                                    score_breakdown={"total": 5.0, "parts": parts}))
        record_decision(db, job, "approved" if rule(parts) else "skipped", channel="dashboard")


def run():
    check = Checker("RUNNING OFFLINE WEIGHT TUNING TESTS")
    db = Session()

    check.section("1. Not enough data")
    add_decisions(db, 20, lambda p: p["skills"]["value"] > 0.5, seed=1)
    r = tuning.tune(db)
    check(r["decisions_used"] == 20 and r["new_weights"] == r["old_weights"] and not r["applied"],
          "Under 30 decisions: no change")
    check("at least 30" in r["reason"], "Reason explains the minimum")
    crud.create_job(db, schemas.JobCreate(title="Old", company="Old", score=8.0))  # V1 row without breakdown
    record_decision(db, db.query(models.Job).filter_by(title="Old").first(), "approved", "dashboard")
    check(len(tuning.training_rows(db)) == 20, "Decisions without a breakdown are not used")

    check.section("2. Learning direction and guard rails")
    add_decisions(db, 40, lambda p: p["skills"]["value"] > 0.5, seed=2)  # approvals follow skills only
    r = tuning.tune(db)
    old, new = r["old_weights"], r["new_weights"]
    check(r["decisions_used"] == 60 and r["approved"] >= 5 and r["skipped"] >= 5, "60 decisions used")
    check(r["coefficients"]["skills"] > max(v for k, v in r["coefficients"].items() if k != "skills"),
          "Skills has the strongest coefficient")
    check(new["skills"] == old["skills"] + 5, f"Skills weight rises by the maximum step ({old['skills']} -> {new['skills']})")
    check(all(abs(new[p] - old[p]) <= tuning.MAX_STEP for p in w.PARTS), "No part moves more than 5 points")
    check(all(tuning.MIN_WEIGHT <= new[p] <= tuning.MAX_WEIGHT for p in w.PARTS), "Every weight within [5, 60]")
    check(sum(new.values()) == 100 and all(isinstance(v, int) for v in new.values()), "Total stays exactly 100")
    check(r["applied"] is False and w.get_weights(db) == w.DEFAULT_WEIGHTS, "Not applied without apply=true")
    check(tuning.tune(db)["new_weights"] == new, "Deterministic: same decisions, same suggestion")

    check.section("3. Applying and repeated tuning")
    r = tuning.tune(db, apply=True)
    check(r["applied"] and w.get_weights(db) == new, "apply=true stores the new weights")
    r2 = tuning.tune(db)
    check(r2["old_weights"] == new and r2["new_weights"]["skills"] <= new["skills"] + 5,
          "Next tuning starts from the stored weights (still max 5 per step)")
    for _ in range(12):
        tuning.tune(db, apply=True)
    final = w.get_weights(db)
    check(final["skills"] <= tuning.MAX_WEIGHT and min(final.values()) >= tuning.MIN_WEIGHT
          and sum(final.values()) == 100, f"Repeated tuning respects the bounds ({final})")

    check.section("4. Constraint helper")
    c = tuning.constrain({"skills": 90, "role": 10, "experience": 0, "preferences": 0, "freshness": 0}, w.DEFAULT_WEIGHTS)
    check(c == {"skills": 45, "role": 15, "experience": 15, "preferences": 15, "freshness": 10}
          or (sum(c.values()) == 100 and c["skills"] == 45), f"Extreme target clipped to the step window ({c})")
    check(tuning.constrain(w.DEFAULT_WEIGHTS, w.DEFAULT_WEIGHTS) == w.DEFAULT_WEIGHTS, "Target equal to old: unchanged")
    odd = {"skills": 80, "role": 5, "experience": 5, "preferences": 5, "freshness": 5}
    moved = tuning.constrain(w.DEFAULT_WEIGHTS, odd)
    check(moved["skills"] == 75 and sum(moved.values()) == 100,
          "A weight above the 60 cap only moves 5 points toward it per tuning")
    stuck = {"skills": 60, "role": 40, "experience": 0, "preferences": 0, "freshness": 0}
    check(tuning.constrain(w.DEFAULT_WEIGHTS, stuck) is None, "Infeasible guard rails: refused, not forced")

    check.section("5. One-sided decisions")
    db2 = Session()
    db2.query(models.JobDecision).delete()
    db2.commit()
    w.set_weights(db2, w.DEFAULT_WEIGHTS)
    add_decisions(db2, 35, lambda p: True, seed=3)
    r = tuning.tune(db2)
    check(r["new_weights"] == r["old_weights"] and "approvals and" in r["reason"], "Only approvals: nothing learned")
    db2.close()

    check.section("6. API")

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    api = TestClient(app)
    r = api.post("/api/scoring/tune")
    check(r.status_code == 200 and {"old_weights", "new_weights", "applied"} <= set(r.json()) and not r.json()["applied"],
          "POST /api/scoring/tune shows old vs new without applying")
    with patch.dict(os.environ, {"ADMIN_API_KEY": "k-1"}):
        check(api.post("/api/scoring/tune?apply=true").status_code == 401, "Tune needs X-Admin-Key when configured")
        r = api.post("/api/scoring/tune?apply=false", headers={"X-Admin-Key": "k-1"})
        check(r.status_code == 200, "Tune with the admin key")
    check(api.get("/api/scoring/weights").status_code == 200, "GET /api/scoring/weights")
    app.dependency_overrides.clear()
    db.close()
    check.done("WEIGHT TUNING")


if __name__ == "__main__":
    run()
