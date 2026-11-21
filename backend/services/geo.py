"""
Small, dependency-free location helpers (India-focused).

Used by de-duplication (same city?), ATS board filtering (is this posting in a preferred location?)
and the hard location filter.
"""
import re
from typing import Iterable, Optional

# Common spellings -> one canonical city name.
CITY_ALIASES = {
    "bangalore": "bengaluru", "bengaluru": "bengaluru", "blr": "bengaluru",
    "gurgaon": "gurugram", "gurugram": "gurugram",
    "bombay": "mumbai", "mumbai": "mumbai", "navi mumbai": "mumbai", "thane": "mumbai",
    "new delhi": "delhi", "delhi": "delhi", "delhi ncr": "delhi", "ncr": "delhi",
    "noida": "noida", "greater noida": "noida", "ghaziabad": "ghaziabad", "faridabad": "faridabad",
    "hyderabad": "hyderabad", "secunderabad": "hyderabad",
    "pune": "pune", "chennai": "chennai", "madras": "chennai",
    "kolkata": "kolkata", "calcutta": "kolkata",
    "ahmedabad": "ahmedabad", "gandhinagar": "ahmedabad", "jaipur": "jaipur", "kochi": "kochi",
    "cochin": "kochi", "thiruvananthapuram": "thiruvananthapuram", "trivandrum": "thiruvananthapuram",
    "coimbatore": "coimbatore", "indore": "indore", "chandigarh": "chandigarh", "mohali": "chandigarh",
    "lucknow": "lucknow", "bhubaneswar": "bhubaneswar", "nagpur": "nagpur", "mysore": "mysuru",
    "mysuru": "mysuru", "mangalore": "mangaluru", "mangaluru": "mangaluru", "vadodara": "vadodara",
    "surat": "surat", "visakhapatnam": "visakhapatnam", "vizag": "visakhapatnam", "patna": "patna",
    "bhopal": "bhopal", "warangal": "warangal", "vijayawada": "vijayawada", "dehradun": "dehradun",
}

INDIAN_STATES = {
    "karnataka", "maharashtra", "telangana", "tamil nadu", "kerala", "haryana", "uttar pradesh",
    "west bengal", "gujarat", "rajasthan", "delhi", "andhra pradesh", "odisha", "madhya pradesh",
    "punjab", "bihar", "goa", "uttarakhand", "assam", "jharkhand", "chhattisgarh",
}

# Countries we can recognise in free-text locations, to tell "clearly elsewhere" from "unknown".
FOREIGN_MARKERS = {
    "united states", "usa", "u.s.", "united kingdom", "uk", "london", "england", "canada", "toronto",
    "germany", "berlin", "france", "paris", "singapore", "australia", "sydney", "netherlands",
    "amsterdam", "ireland", "dublin", "spain", "japan", "tokyo", "uae", "dubai", "new york",
    "san francisco", "seattle", "california", "texas", "poland", "brazil", "mexico", "israel",
    "switzerland", "zurich", "sweden", "philippines", "indonesia", "vietnam", "malaysia",
    "south korea", "seoul", "hong kong", "china", "taiwan", "argentina", "colombia", "chile",
    # regions used by remote postings
    "nordics", "emea", "europe", "eu", "latam", "americas", "north america", "dach", "benelux", "anz",
    "mena", "uk&i", "us only", "canada only",
}

REMOTE_WORDS = ("remote", "work from home", "wfh", "anywhere")


def _clean(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def is_remote(text: Optional[str]) -> bool:
    t = _clean(text)
    return any(w in t for w in REMOTE_WORDS)


def is_hybrid(text: Optional[str]) -> bool:
    return "hybrid" in _clean(text)


def cities_in(text: Optional[str]) -> set[str]:
    """Canonical Indian city names mentioned in a location string."""
    t = _clean(text)
    found = set()
    for alias, city in CITY_ALIASES.items():
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", t):
            found.add(city)
    return found


def mentions_india(text: Optional[str]) -> bool:
    t = _clean(text)
    if re.search(r"(?<![a-z])(india|bharat)(?![a-z])", t) or re.search(r"(?<![a-z])in(?![a-z])$", t):
        return True
    return bool(cities_in(t)) or any(re.search(rf"(?<![a-z]){s}(?![a-z])", t) for s in INDIAN_STATES)


def mentions_foreign(text: Optional[str]) -> bool:
    t = _clean(text)
    return any(re.search(rf"(?<![a-z]){re.escape(m)}(?![a-z])", t) for m in FOREIGN_MARKERS)


def primary_city(text: Optional[str]) -> Optional[str]:
    """First recognised city in the string (by position), or None."""
    t = _clean(text)
    best = None
    for alias, city in CITY_ALIASES.items():
        m = re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", t)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), city)
    return best[1] if best else None


def split_preferences(preferred_locations: Optional[str]) -> list[str]:
    return [p.strip() for p in (preferred_locations or "").split(",") if p.strip()]


def location_match(location: Optional[str], preferred: Iterable[str]) -> str:
    """
    Compare a job location with the user's preferred locations.

    Returns "match", "mismatch" or "unknown". "mismatch" is only returned when the location is
    clearly somewhere else (a recognised foreign place, or a different Indian city when only cities
    were preferred), so an unclear location never filters a job out.
    """
    prefs = [_clean(p) for p in preferred if _clean(p)]
    loc = _clean(location)
    if not prefs:
        return "match"
    if not loc or loc in ("not specified", "n/a", "na", "unknown"):
        return "unknown"

    wants_remote = any(p in ("remote", "work from home", "wfh", "anywhere") for p in prefs)
    wants_hybrid = any(p == "hybrid" for p in prefs)
    wants_india = any(p in ("india", "in", "bharat") for p in prefs)
    wanted_cities = set().union(*(cities_in(p) for p in prefs))
    other_prefs = [p for p in prefs if p not in ("remote", "work from home", "wfh", "anywhere", "hybrid",
                                                  "india", "in", "bharat") and not cities_in(p)]

    remote_job = is_remote(loc)
    in_india = mentions_india(loc)
    foreign = mentions_foreign(loc) and not in_india

    if remote_job and wants_remote and not foreign:
        return "match"
    if remote_job and wants_remote and foreign:
        # "Remote (US)" style postings usually require residence in that country.
        return "mismatch" if (wants_india or wanted_cities) else "match"
    if wants_india and in_india:
        return "match"
    if wanted_cities and cities_in(loc) & wanted_cities:
        return "match"
    if wants_hybrid and is_hybrid(loc) and in_india:
        return "match"
    if any(p in loc for p in other_prefs):
        return "match"
    if foreign:
        return "mismatch"
    if in_india and wanted_cities:
        # An Indian city that is not one of the preferred cities (and the whole country was not preferred).
        return "mismatch"
    return "unknown"
