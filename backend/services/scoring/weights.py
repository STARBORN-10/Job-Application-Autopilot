"""Score weights: five parts that must add up to 100 (stored in app_settings)."""
import crud

WEIGHTS_KEY = "scoring_weights"
PARTS = ("skills", "role", "experience", "preferences", "freshness")
DEFAULT_WEIGHTS = {"skills": 40, "role": 20, "experience": 15, "preferences": 15, "freshness": 10}


class WeightsError(ValueError):
    pass


def validate_weights(weights: dict) -> dict:
    if not isinstance(weights, dict) or set(weights) != set(PARTS):
        raise WeightsError(f"Weights must have exactly these parts: {', '.join(PARTS)}")
    clean = {}
    for part in PARTS:
        value = weights[part]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
            raise WeightsError(f"Weight '{part}' must be a whole number")
        if not 0 <= value <= 100:
            raise WeightsError(f"Weight '{part}' must be between 0 and 100")
        clean[part] = int(value)
    if sum(clean.values()) != 100:
        raise WeightsError(f"Weights must add up to 100 (they add up to {sum(clean.values())})")
    return clean


def get_weights(db) -> dict:
    stored = crud.get_json_setting(db, WEIGHTS_KEY, None)
    try:
        return validate_weights(stored) if stored else dict(DEFAULT_WEIGHTS)
    except WeightsError:
        return dict(DEFAULT_WEIGHTS)


def set_weights(db, weights: dict) -> dict:
    clean = validate_weights(weights)
    crud.set_json_setting(db, WEIGHTS_KEY, clean)
    return clean
