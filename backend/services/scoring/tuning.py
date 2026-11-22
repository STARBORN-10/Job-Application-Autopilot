"""
Learn the score weights from approve / skip decisions (pure Python, guard-railed).

Data: the latest decision per job, with the part values (0-1) of the score breakdown saved at
decision time. Needs at least TUNE_MIN_DECISIONS (default 30) such decisions, with at least
MIN_PER_CLASS approvals and skips.

Method: L2-regularised logistic regression (batch gradient descent, fixed iterations, so the result is
deterministic) predicting "approved" from the five part values. Positive coefficients, normalised to
100, are the target weights. Guard rails: each weight moves at most MAX_STEP points per tuning, stays
within [MIN_WEIGHT, MAX_WEIGHT], and the total stays exactly 100. Nothing changes unless the caller
asks to apply.
"""
import json
import math
import os
from typing import Optional

import models
from services.scoring.weights import PARTS, get_weights, set_weights

MAX_STEP = 5
MIN_WEIGHT = 5
MAX_WEIGHT = 60
MIN_PER_CLASS = 5
L2 = 0.05
LEARNING_RATE = 0.5
ITERATIONS = 2000


def min_decisions() -> int:
    try:
        return max(1, int(os.getenv("TUNE_MIN_DECISIONS", "30")))
    except ValueError:
        return 30


def training_rows(db) -> list[tuple[list[float], int]]:
    """(part values, 1 = approved / 0 = skipped) for the latest decision of each job."""
    latest: dict[int, models.JobDecision] = {}
    for d in db.query(models.JobDecision).order_by(models.JobDecision.id).all():
        latest[d.job_id] = d
    rows = []
    for d in latest.values():
        try:
            parts = json.loads(d.breakdown_snapshot or "{}").get("parts") or {}
            x = [float(parts[p]["value"]) for p in PARTS]
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        rows.append((x, 1 if d.decision == "approved" else 0))
    return rows


def fit_logistic(rows: list[tuple[list[float], int]]) -> list[float]:
    """Coefficients for the five parts (the intercept is fitted but not returned)."""
    n = len(rows)
    w = [0.0] * len(PARTS)
    b = 0.0
    for _ in range(ITERATIONS):
        gw = [0.0] * len(PARTS)
        gb = 0.0
        for x, y in rows:
            z = b + sum(wi * xi for wi, xi in zip(w, x))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            err = p - y
            gb += err
            for i, xi in enumerate(x):
                gw[i] += err * xi
        b -= LEARNING_RATE * gb / n
        w = [wi - LEARNING_RATE * (gwi / n + L2 * wi) for wi, gwi in zip(w, gw)]
    return w


def _bounds(old: dict) -> dict:
    out = {}
    for p in PARTS:
        lo, hi = max(MIN_WEIGHT, old[p] - MAX_STEP), min(MAX_WEIGHT, old[p] + MAX_STEP)
        if lo > hi:  # current weight outside the tunable range: only move toward it
            lo = hi = old[p] - MAX_STEP if old[p] > MAX_WEIGHT else old[p] + MAX_STEP
        out[p] = (lo, hi)
    return out


def constrain(target: dict, old: dict) -> Optional[dict]:
    """Closest whole-number weights to `target` within the guard rails that add up to 100 (None if impossible)."""
    bounds = _bounds(old)
    if sum(b[0] for b in bounds.values()) > 100 or sum(b[1] for b in bounds.values()) < 100:
        return None
    vals = {p: min(max(target[p], bounds[p][0]), bounds[p][1]) for p in PARTS}
    for _ in range(50):  # spread the difference over the parts that still have room
        diff = 100 - sum(vals.values())
        if abs(diff) < 1e-9:
            break
        free = [p for p in PARTS if (diff > 0 and vals[p] < bounds[p][1]) or (diff < 0 and vals[p] > bounds[p][0])]
        if not free:
            return None
        for p in free:
            vals[p] = min(max(vals[p] + diff / len(free), bounds[p][0]), bounds[p][1])
    ints = {p: math.floor(vals[p] + 1e-9) for p in PARTS}
    order = sorted(PARTS, key=lambda p: vals[p] - ints[p], reverse=True)
    while sum(ints.values()) < 100:
        p = next(p for p in order if ints[p] < bounds[p][1])
        ints[p] += 1
        order.remove(p)
        order.append(p)
    return ints


def tune(db, apply: bool = False) -> dict:
    old = get_weights(db)
    rows = training_rows(db)
    approved = sum(y for _, y in rows)
    result = {"old_weights": old, "new_weights": old, "applied": False, "decisions_used": len(rows),
              "approved": approved, "skipped": len(rows) - approved, "min_decisions": min_decisions(),
              "max_step": MAX_STEP, "bounds": [MIN_WEIGHT, MAX_WEIGHT], "coefficients": None, "reason": ""}
    if len(rows) < min_decisions():
        result["reason"] = f"Need at least {min_decisions()} decisions with a score breakdown (have {len(rows)})."
        return result
    if approved < MIN_PER_CLASS or len(rows) - approved < MIN_PER_CLASS:
        result["reason"] = f"Need at least {MIN_PER_CLASS} approvals and {MIN_PER_CLASS} skips to learn from."
        return result

    coef = fit_logistic(rows)
    result["coefficients"] = {p: round(c, 4) for p, c in zip(PARTS, coef)}
    positive = {p: max(c, 0.0) for p, c in zip(PARTS, coef)}
    total = sum(positive.values())
    if total <= 0:
        result["reason"] = "Decisions do not favour any score part; weights unchanged."
        return result
    target = {p: 100.0 * v / total for p, v in positive.items()}
    new = constrain(target, old)
    if new is None:
        result["reason"] = "Current weights are outside the tunable range; reset them to the defaults first."
        return result
    result["new_weights"] = new
    result["reason"] = "Weights moved toward what your decisions favour (max 5 points per part)."
    if apply and new != old:
        set_weights(db, new)
        result["applied"] = True
    return result
