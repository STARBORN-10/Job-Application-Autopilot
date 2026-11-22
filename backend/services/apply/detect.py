"""Choose how to apply: find a recruiter e-mail in the posting, or recognise a career-page (ATS) URL."""
import re
from typing import Optional
from urllib.parse import urlsplit

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24})(?![\w-])")

IGNORED_LOCAL_PARTS = re.compile(r"^(no-?reply|do-?not-?reply|donotreply|mailer-daemon|postmaster|bounces?|abuse|"
                                 r"privacy|gdpr|dpo|unsubscribe|support|help|webmaster|noc|security)(?:$|[._+-])", re.I)
IGNORED_DOMAINS = {"example.com", "example.org", "email.com", "domain.com", "yourcompany.com", "company.com",
                   "sentry.io", "wixpress.com", "linkedin.com", "indeed.com", "naukri.com", "internshala.com",
                   "jooble.org", "adzuna.in", "glassdoor.com", "greenhouse.io", "lever.co", "ashbyhq.com"}
FILE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".js", ".css")
HIRING_WORDS = re.compile(r"\b(resume|cv|apply|application|hiring|recruit\w*|career\w*|hr|talent|jobs?|send|share|mail)\b", re.I)

ATS_HOSTS = {"greenhouse.io": "greenhouse", "lever.co": "lever", "ashbyhq.com": "ashby",
             "myworkdayjobs.com": "workday", "smartrecruiters.com": "smartrecruiters", "workable.com": "workable"}


def find_recruiter_email(text: Optional[str]) -> Optional[str]:
    """Best recruiter address in a posting, or None. Skips no-reply, file names and placeholder domains."""
    if not text:
        return None
    candidates = []
    for m in EMAIL_RE.finditer(text):
        email = m.group(1).strip(".").lower()
        local, _, domain = email.partition("@")
        if email.endswith(FILE_SUFFIXES) or re.search(r"@\d+x\.", email):
            continue
        if domain in IGNORED_DOMAINS or any(domain.endswith("." + d) for d in IGNORED_DOMAINS):
            continue
        if IGNORED_LOCAL_PARTS.match(local):
            continue
        window = text[max(0, m.start() - 120): m.end() + 40]
        candidates.append((0 if HIRING_WORDS.search(window) else 1, m.start(), email))
    return min(candidates)[2] if candidates else None


def ats_provider(url: Optional[str]) -> Optional[str]:
    """'greenhouse' / 'lever' / ... when the URL is a known applicant-tracking career page."""
    if not url:
        return None
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return None
    for domain, name in ATS_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None
