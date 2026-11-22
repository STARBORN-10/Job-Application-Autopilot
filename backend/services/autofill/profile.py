"""
Applicant profile used to fill career-page forms (stored in app_settings, edited on the Settings page).

Only plain contact facts are stored. Work authorisation, visa, salary, EEO / diversity and other legal
or personal questions are deliberately NOT part of the profile: the form filler never answers them and
reports them as "needs your answer".
"""
import re
from typing import Optional

from pydantic import BaseModel, field_validator

import crud

SETTINGS_KEY = "applicant_profile"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9 ()\-.]{7,20}$")


def _url(value: Optional[str], host_hint: Optional[str] = None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    if not re.match(r"^https?://[^\s/]+\.[^\s]+", value, re.I):
        raise ValueError("must be a web address such as https://example.com/you")
    if host_hint and host_hint not in value.lower():
        raise ValueError(f"must be a {host_hint} address")
    return value


class ApplicantProfile(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""                 # city, country
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    current_company: str = ""          # optional
    notice_period: str = ""            # optional, e.g. "Immediately" or "30 days"

    @field_validator("first_name", "last_name", "location", "current_company", "notice_period", mode="before")
    @classmethod
    def _text(cls, v):
        v = str(v or "").strip()
        if len(v) > 120:
            raise ValueError("is too long (max 120 characters)")
        return v

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v):
        v = str(v or "").strip()
        if v and not EMAIL_RE.match(v):
            raise ValueError("is not a valid e-mail address")
        return v

    @field_validator("phone", mode="before")
    @classmethod
    def _phone(cls, v):
        v = str(v or "").strip()
        if v and (not PHONE_RE.match(v) or len(re.sub(r"\D", "", v)) < 7):
            raise ValueError("is not a valid phone number (digits, spaces, + ( ) - only)")
        return v

    @field_validator("linkedin", mode="before")
    @classmethod
    def _linkedin(cls, v):
        return _url(v, "linkedin.com")

    @field_validator("github", mode="before")
    @classmethod
    def _github(cls, v):
        return _url(v, "github.com")

    @field_validator("portfolio", mode="before")
    @classmethod
    def _portfolio(cls, v):
        return _url(v)

    @property
    def full_name(self) -> str:
        return " ".join(x for x in (self.first_name, self.last_name) if x)

    def value_for(self, key: str) -> str:
        if key == "full_name":
            return self.full_name
        return getattr(self, key, "") or ""

    def missing_basics(self) -> list[str]:
        return [label for key, label in (("first_name", "first name"), ("last_name", "last name"),
                                         ("email", "e-mail"), ("phone", "phone")) if not getattr(self, key)]


def get_profile(db) -> ApplicantProfile:
    stored = crud.get_json_setting(db, SETTINGS_KEY, {}) or {}
    try:
        return ApplicantProfile.model_validate(stored if isinstance(stored, dict) else {})
    except ValueError:
        # A stored value that no longer validates must not break the form filler: keep the valid parts.
        clean = {}
        for key, value in (stored or {}).items():
            try:
                ApplicantProfile.model_validate({key: value})
                clean[key] = value
            except ValueError:
                pass
        return ApplicantProfile.model_validate(clean)


def save_profile(db, profile: ApplicantProfile) -> ApplicantProfile:
    crud.set_json_setting(db, SETTINGS_KEY, profile.model_dump())
    return profile
