"""
Field mapping: which applicant-profile value (if any) belongs in a form field.

classify_field() looks at the field's label, name, id, placeholder, autocomplete and type. It returns a
profile key ("first_name", "email", "resume", ...), "sensitive" for questions the filler must never
answer (EEO / diversity, visa / work authorisation, salary, legal, consent), or None (unknown: left alone).
Sensitive patterns are checked first, so "Are you authorised to work in India?" is never mistaken for
a location field.
"""
import re
from typing import Optional

SENSITIVE = re.compile(
    r"gender|\bsex\b|pronoun|\brace\b|racial|ethnic|hispanic|latin[oax]|veteran|disabilit|handicap|sexual|orientation|"
    r"religio|caste|marital|date of birth|\bdob\b|birth ?date|\bage\b|visa|sponsor|authori[sz]ed to work|"
    r"work authori[sz]ation|right to work|citizen|nationality|immigration|salary|compensation|\bctc\b|"
    r"expected pay|pay expectation|criminal|convict|background check|consent|privacy|gdpr|terms|acknowledg|"
    r"how did you hear|referr|security clearance|relocat",
    re.I,
)

RULES: list[tuple[str, re.Pattern]] = [
    ("current_company", re.compile(r"current (company|employer|organi[sz]ation)|^org$|\borg\b|employer|company name", re.I)),
    ("first_name", re.compile(r"first[ _-]?name|given[ _-]?name|\bfname\b|first_name", re.I)),
    ("last_name", re.compile(r"last[ _-]?name|surname|family[ _-]?name|\blname\b|last_name", re.I)),
    ("email", re.compile(r"e-?mail", re.I)),
    ("phone", re.compile(r"phone|mobile|\btel\b|telephone|contact number", re.I)),
    ("linkedin", re.compile(r"linked ?in", re.I)),
    ("github", re.compile(r"git ?hub", re.I)),
    ("portfolio", re.compile(r"portfolio|personal (web)?site|website|\bblog\b|other (url|link|website)|urls\[other\]", re.I)),
    ("location", re.compile(r"current location|\blocation\b|\bcity\b|where are you (based|located)", re.I)),
    ("notice_period", re.compile(r"notice period|availability|earliest start|start date|when can you start|available to start", re.I)),
    ("full_name", re.compile(r"full[ _-]?name|your name|^name$|^name\b|_systemfield_name|candidate name|legal name", re.I)),
]


def _clean(*parts: Optional[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def classify_field(label: str = "", name: str = "", element_id: str = "", input_type: str = "text",
                   placeholder: str = "", autocomplete: str = "", tag: str = "input") -> Optional[str]:
    """Profile key for this field, 'sensitive', or None."""
    input_type = (input_type or "text").lower()
    label_text = _clean(label, placeholder)
    attrs = _clean(name, element_id, autocomplete)
    text = _clean(label_text, attrs)
    low = text.lower()
    if input_type in ("hidden", "submit", "button", "image", "reset"):
        return None
    if SENSITIVE.search(low):
        return "sensitive"
    if input_type == "file":
        if re.search(r"cover", low):
            return "cover_letter"
        if re.search(r"resume|\bcv\b|curriculum", low):
            return "resume"
        return None
    if re.search(r"cover ?letter", low) and tag == "textarea":
        return "cover_letter"
    if input_type in ("checkbox", "radio") or tag == "select":
        return None  # choices are never guessed
    # autocomplete tokens are the most reliable signal when present
    ac = (autocomplete or "").lower()
    for token, key in (("given-name", "first_name"), ("family-name", "last_name"), ("email", "email"),
                       ("tel", "phone"), ("organization", "current_company")):
        if token in ac.split():
            return key
    if ac.strip() == "name":
        return "full_name"
    for key, pattern in RULES:
        # Label text decides first; attributes (name/id) only when the label says nothing useful.
        if label_text and pattern.search(label_text):
            return key
    for key, pattern in RULES:
        if attrs and pattern.search(attrs):
            return key
    return None


def describe(field: dict) -> str:
    """Human label for a scanned field."""
    return (field.get("label") or field.get("placeholder") or field.get("name") or field.get("id") or "unnamed field")[:120]
