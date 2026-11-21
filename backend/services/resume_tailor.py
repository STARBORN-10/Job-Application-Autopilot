"""
Tailored resume per job.

Flow (tailor_for_job):
1. If the job already scores at or above TAILOR_SCORE_THRESHOLD (default 9.0) the original resume is
   kept unchanged (status "not_needed").
2. Otherwise the LLM layer (task "write": Gemini -> Groq -> OpenRouter, Groq's token throttle applies)
   rewrites the active resume into structured JSON: summary, skills ordered by relevance to the job,
   experience / project bullets reworded and reordered, education, certifications.
3. HONESTY GUARDRAIL - verify(): every employer, title, degree, institution, certification, skill, tool,
   number and date in the output must be traceable to the original resume text (normalised matching).
   Anything that is not is removed and logged in `removed_unverified`. Skills the job wants but the
   resume does not support are never added; they are returned as `gaps`.
4. The job is re-scored with the SAME scoring engine (services/scoring/engine.py) using a profile built
   from the tailored resume, next to a re-score with the original profile at the same moment. The 9.0
   target is a goal, not a promise: the result is reported as computed, never raised artificially.
5. A clean, ATS-friendly PDF (reportlab) and a DOCX (python-docx) are rendered into GENERATED_DIR
   (default backend/generated, git-ignored). Files can always be re-rendered from structured_json.

Results are cached per (job, resume id, resume text hash); pass regenerate=True to redo.
"""
import datetime
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

import crud
import models
from services import llm
from services.scoring import facts as facts_mod
from services.scoring import profile as profile_mod
from services.scoring import weights as weights_mod
from services.scoring.engine import score_job
from services.scoring.facts import JobFacts
from services.scoring.skills import extract_skills, normalize_skill, normalize_skills, skill_in_text

logger = logging.getLogger("resume_tailor")

BACKEND_DIR = Path(__file__).resolve().parent.parent
RESUME_CHARS = 7000
DESCRIPTION_CHARS = 2800


def threshold() -> float:
    try:
        return float(os.getenv("TAILOR_SCORE_THRESHOLD", "9.0"))
    except ValueError:
        return 9.0


def auto_tailor_on_approve() -> bool:
    return (os.getenv("AUTO_TAILOR_ON_APPROVE") or "true").strip().lower() not in ("false", "0", "no", "off")


def output_dir() -> Path:
    base = Path(os.getenv("GENERATED_DIR") or (BACKEND_DIR / "generated"))
    path = base / "tailored"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Structured resume
# ---------------------------------------------------------------------------
def _clean_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in (value or []) if isinstance(v, (str, int, float)) and str(v).strip()]


class Entry(BaseModel):
    title: str = ""
    organization: str = ""
    location: str = ""
    dates: str = ""
    bullets: list[str] = Field(default_factory=list)

    @field_validator("title", "organization", "location", "dates", mode="before")
    @classmethod
    def _s(cls, v):
        return str(v or "").strip()

    @field_validator("bullets", mode="before")
    @classmethod
    def _b(cls, v):
        return _clean_list(v)


class Project(BaseModel):
    name: str = ""
    dates: str = ""
    technologies: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)

    @field_validator("name", "dates", mode="before")
    @classmethod
    def _s(cls, v):
        return str(v or "").strip()

    @field_validator("technologies", "bullets", mode="before")
    @classmethod
    def _l(cls, v):
        return _clean_list(v)


class Education(BaseModel):
    degree: str = ""
    institution: str = ""
    dates: str = ""
    details: str = ""

    @field_validator("degree", "institution", "dates", "details", mode="before")
    @classmethod
    def _s(cls, v):
        return str(v or "").strip()


class StructuredResume(BaseModel):
    name: str = ""
    contact: list[str] = Field(default_factory=list)
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[Entry] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)

    @field_validator("name", "summary", mode="before")
    @classmethod
    def _s(cls, v):
        return str(v or "").strip()

    @field_validator("contact", "skills", "certifications", "achievements", mode="before")
    @classmethod
    def _l(cls, v):
        return _clean_list(v)

    @field_validator("experience", "projects", "education", mode="before")
    @classmethod
    def _objs(cls, v):
        return [x for x in (v or []) if isinstance(x, dict)]


# ---------------------------------------------------------------------------
# Verifier (pure functions, no AI)
# ---------------------------------------------------------------------------
STOPWORDS = {
    "a", "an", "and", "the", "of", "in", "on", "at", "to", "for", "with", "by", "from", "as", "or", "via", "using",
    "into", "over", "under", "across", "within", "through", "per", "its", "their", "our", "my", "is", "are", "was",
    "were", "be", "been", "this", "that", "these", "those", "it", "i", "we", "&", "-", "etc", "e.g", "ie", "e.g.",
}
# Common resume words that may be capitalised at the start of a clause; never treated as proper nouns.
COMMON_CAPS = {
    "built", "developed", "designed", "implemented", "created", "led", "improved", "reduced", "increased",
    "automated", "worked", "collaborated", "managed", "wrote", "deployed", "trained", "analyzed", "analysed",
    "optimized", "optimised", "engineered", "integrated", "maintained", "migrated", "delivered", "researched",
    "used", "applied", "achieved", "completed", "conducted", "contributed", "presented", "published", "tested",
    "skilled", "experienced", "passionate", "motivated", "detail", "strong", "proficient", "hands", "familiar",
    "currently", "seeking", "aspiring", "recent", "graduate", "student", "engineer", "developer", "analyst",
    "intern", "internship", "bachelor", "master", "b.tech", "m.tech", "university", "college", "institute",
    "school", "project", "projects", "team", "teams", "data", "machine", "learning", "computer", "science",
    "software", "systems", "system", "web", "application", "applications", "model", "models", "pipeline",
    "pipelines", "dashboard", "dashboards", "api", "apis", "backend", "frontend", "full", "stack", "cloud",
    "ai", "ml", "nlp", "summary", "skills", "experience", "education", "certifications", "achievements",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "present", "current", "remote", "india", "also", "including", "key", "focused", "focus", "end",
}
NUMBER_RE = re.compile(r"(?<![A-Za-z])(\d+(?:[.,]\d+)?)\s*(%|\+|x\b|k\b|m\b|lpa|cgpa|gpa)?", re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
CAP_WORD_RE = re.compile(r"\b([A-Z][A-Za-z0-9+#.]*[A-Za-z0-9+#]|[A-Z]{2,})\b")


def _normalise(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("–", "-").replace("—", "-").replace("’", "'").replace(" ", " ")
    return re.sub(r"\s+", " ", t)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]+(?:\.[a-z0-9]+)*", _normalise(text)))


class Verifier:
    """Checks tailored content against the original resume text."""

    def __init__(self, original_text: str):
        self.text = original_text or ""
        self.norm = _normalise(self.text)
        self.tokens = _tokens(self.text)
        self.numbers = {n.replace(",", "") for n in re.findall(r"\d+(?:[.,]\d+)?", self.text)}

    def _token_ok(self, token: str) -> bool:
        return (token in self.tokens or token.rstrip("s") in self.tokens or f"{token}s" in self.tokens
                or token.replace(".", "") in {t.replace(".", "") for t in self.tokens})

    def phrase_supported(self, phrase: str) -> bool:
        """Every significant word of the phrase appears in the resume (order not required)."""
        words = [w for w in re.findall(r"[a-z0-9+#]+(?:\.[a-z0-9]+)*", _normalise(phrase)) if w not in STOPWORDS]
        return bool(words) and all(self._token_ok(w) for w in words)

    def numbers_supported(self, text: str) -> tuple[bool, list[str]]:
        bad = [m.group(1) for m in NUMBER_RE.finditer(text or "") if m.group(1).replace(",", "") not in self.numbers]
        return not bad, bad

    def skill_supported(self, skill: str) -> bool:
        return skill_in_text(skill, self.text) or self.phrase_supported(skill)

    def sentence_problem(self, sentence: str) -> Optional[str]:
        """Why a bullet / summary sentence is not traceable to the resume, or None when it is."""
        ok, bad_numbers = self.numbers_supported(sentence)
        if not ok:
            return f"number(s) not in your resume: {', '.join(bad_numbers[:3])}"
        for skill in extract_skills(sentence):
            if not skill_in_text(skill, self.text):
                return f"skill/tool not in your resume: {skill}"
        words = CAP_WORD_RE.findall(sentence or "")
        for i, word in enumerate(words):
            low = word.lower()
            if low in COMMON_CAPS or low in STOPWORDS:
                continue
            if i == 0 and sentence.strip().startswith(word):
                continue  # first word of the sentence
            if not self._token_ok(re.sub(r"[^a-z0-9+#.]", "", low)):
                return f"name not in your resume: {word}"
        return None

    def dates_supported(self, dates: str) -> bool:
        for year in YEAR_RE.finditer(dates or ""):
            if year.group(0) not in self.norm:
                return False
        ok, _bad = self.numbers_supported(dates)
        return ok


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def verify(data: StructuredResume, original_text: str) -> tuple[StructuredResume, list[dict]]:
    """Return (clean resume, removed items). Never adds anything; only drops what cannot be traced."""
    v = Verifier(original_text)
    removed: list[dict] = []

    def drop(section: str, text: str, reason: str) -> None:
        removed.append({"section": section, "text": text[:200], "reason": reason})

    out = StructuredResume()
    # Name and contact lines must literally appear in the resume.
    if data.name and v.phrase_supported(data.name):
        out.name = data.name
    elif data.name:
        drop("name", data.name, "not found in your resume")
    for line in data.contact:
        parts = [p.strip() for p in re.split(r"[|,;·•]", line) if p.strip()]
        kept = [p for p in parts if _normalise(p) in v.norm or _normalise(p).replace(" ", "") in v.norm.replace(" ", "")]
        for p in parts:
            if p not in kept:
                drop("contact", p, "not found in your resume")
        if kept:
            out.contact.append(" | ".join(kept))

    # Summary: sentence by sentence.
    sentences = []
    for sentence in _split_sentences(data.summary):
        problem = v.sentence_problem(sentence)
        if problem:
            drop("summary", sentence, problem)
        else:
            sentences.append(sentence)
    out.summary = " ".join(sentences)

    # Skills: each must be in the resume (name or alias); duplicates removed.
    seen = set()
    for skill in data.skills:
        key = normalize_skill(skill)
        if key in seen:
            continue
        if v.skill_supported(skill):
            out.skills.append(skill)
            seen.add(key)
        else:
            drop("skills", skill, "skill not in your resume")

    def clean_bullets(section: str, bullets: list[str]) -> list[str]:
        kept = []
        for b in bullets:
            problem = v.sentence_problem(b)
            if problem:
                drop(section, b, problem)
            else:
                kept.append(b)
        return kept

    for e in data.experience:
        label = f"{e.title} at {e.organization}".strip()
        if e.title and not v.phrase_supported(e.title):
            drop("experience", label, "job title not in your resume")
            continue
        if e.organization and not v.phrase_supported(e.organization):
            drop("experience", label, "employer not in your resume")
            continue
        if not e.title and not e.organization:
            continue
        entry = Entry(title=e.title, organization=e.organization,
                      location=e.location if (not e.location or v.phrase_supported(e.location)) else "",
                      dates=e.dates if v.dates_supported(e.dates) else "",
                      bullets=clean_bullets(f"experience: {label}", e.bullets))
        if e.dates and not entry.dates:
            drop("experience", f"{label} dates '{e.dates}'", "dates not in your resume")
        out.experience.append(entry)

    for p in data.projects:
        if not p.name or not v.phrase_supported(p.name):
            drop("projects", p.name or "(unnamed project)", "project name not in your resume")
            continue
        techs = []
        for t in p.technologies:
            (techs.append(t) if v.skill_supported(t) else drop("projects", f"{p.name}: {t}", "technology not in your resume"))
        out.projects.append(Project(name=p.name, dates=p.dates if v.dates_supported(p.dates) else "",
                                    technologies=techs, bullets=clean_bullets(f"project: {p.name}", p.bullets)))

    for ed in data.education:
        if (ed.degree and not v.phrase_supported(ed.degree)) or (ed.institution and not v.phrase_supported(ed.institution)):
            drop("education", f"{ed.degree}, {ed.institution}", "degree or institution not in your resume")
            continue
        if not ed.degree and not ed.institution:
            continue
        details = ed.details if (not ed.details or v.sentence_problem(ed.details) is None) else ""
        if ed.details and not details:
            drop("education", ed.details, "details not traceable to your resume")
        out.education.append(Education(degree=ed.degree, institution=ed.institution,
                                       dates=ed.dates if v.dates_supported(ed.dates) else "", details=details))

    for c in data.certifications:
        (out.certifications.append(c) if v.phrase_supported(c) and v.numbers_supported(c)[0]
         else drop("certifications", c, "certification not in your resume"))
    out.achievements = clean_bullets("achievements", data.achievements)
    return out, removed


def render_text(r: StructuredResume) -> str:
    lines = [r.name] if r.name else []
    lines += r.contact
    if r.summary:
        lines += ["", "SUMMARY", r.summary]
    if r.skills:
        lines += ["", "SKILLS", ", ".join(r.skills)]
    if r.experience:
        lines += ["", "EXPERIENCE"]
        for e in r.experience:
            head = " - ".join(x for x in (e.title, e.organization) if x)
            lines.append(head + (f" ({e.dates})" if e.dates else "") + (f", {e.location}" if e.location else ""))
            lines += [f"- {b}" for b in e.bullets]
    if r.projects:
        lines += ["", "PROJECTS"]
        for p in r.projects:
            lines.append(p.name + (f" ({p.dates})" if p.dates else "")
                         + (f" | {', '.join(p.technologies)}" if p.technologies else ""))
            lines += [f"- {b}" for b in p.bullets]
    if r.education:
        lines += ["", "EDUCATION"]
        for ed in r.education:
            lines.append(", ".join(x for x in (ed.degree, ed.institution, ed.dates) if x)
                         + (f". {ed.details}" if ed.details else ""))
    if r.certifications:
        lines += ["", "CERTIFICATIONS"] + [f"- {c}" for c in r.certifications]
    if r.achievements:
        lines += ["", "ACHIEVEMENTS"] + [f"- {a}" for a in r.achievements]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
def facts_from_job(job) -> JobFacts:
    """The job's facts as scored (from the stored breakdown), or a keyword scan when there is none."""
    try:
        bd = json.loads(job.score_breakdown) if isinstance(job.score_breakdown, str) else (job.score_breakdown or {})
    except ValueError:
        bd = {}
    if bd and bd.get("parts"):
        jf = bd.get("job_facts") or {}
        return JobFacts(required_skills=(bd.get("matched_skills") or []) + (bd.get("missing_skills") or []),
                        nice_to_have_skills=(bd.get("nice_to_have_matched") or []) + (bd.get("nice_to_have_missing") or []),
                        min_years=jf.get("min_years"), level=jf.get("level") or "unknown",
                        work_mode=jf.get("work_mode") or "unknown", source=bd.get("facts_source") or "heuristic",
                        provider=bd.get("llm_provider"))
    return facts_mod.heuristic_facts(job)


def keyword_coverage(facts: JobFacts, text: str) -> dict:
    wanted = normalize_skills(list(facts.required_skills) + list(facts.nice_to_have_skills))
    found = [s for s in wanted if skill_in_text(s, text)]
    return {"found": len(found), "total": len(wanted), "found_skills": found}


def gaps_for(facts: JobFacts, original_text: str, profile) -> list[str]:
    """Skills the job asks for that the original resume does not support (never added to the resume)."""
    have = normalize_skills(list(profile.skills) + list(profile.project_keywords))
    out = []
    for skill in normalize_skills(list(facts.required_skills) + list(facts.nice_to_have_skills)):
        if skill_in_text(skill, original_text) or skill in have:
            continue
        out.append(skill)
    return out


def rescore(db, job, original_profile, tailored: StructuredResume, tailored_text: str, settings) -> dict:
    facts = facts_from_job(job)
    weights = weights_mod.get_weights(db)
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    before = score_job(job, facts, original_profile, settings, weights, now=now)
    # Only skills that survived verification (and are therefore in the original resume) are added.
    tailored_profile = original_profile.model_copy(update={
        "skills": normalize_skills(list(original_profile.skills) + list(tailored.skills) + extract_skills(tailored_text)),
    })
    after = score_job(job, facts, tailored_profile, settings, weights, now=now)
    return {"facts": facts, "before": before, "after": after}


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
TAILOR_SYSTEM = (
    "You tailor resumes for one job. Reply with one JSON object only. STRICT RULES: use ONLY facts written in "
    "the original resume. You may reorder, shorten, reword and emphasise. NEVER invent or upgrade employers, job "
    "titles, dates, degrees, institutions, certifications, skills, tools, technologies, metrics or numbers. Do not "
    "add a skill just because the job asks for it. Keep names, employers, titles and dates exactly as written."
)


def _prompt(job, resume_text: str, facts: JobFacts) -> str:
    wanted = ", ".join(normalize_skills(list(facts.required_skills) + list(facts.nice_to_have_skills))[:25]) or "not stated"
    return (
        f"JOB: {job.title} at {job.company} ({job.location or 'location not stated'})\n"
        f"Skills the job asks for: {wanted}\n"
        f"Job description (excerpt):\n{(job.description or '')[:DESCRIPTION_CHARS]}\n\n"
        f"ORIGINAL RESUME (the only source of facts):\n{resume_text[:RESUME_CHARS]}\n\n"
        "Rewrite the resume for this job. Order skills by relevance to the job (only skills in the resume). "
        "Reorder experience and project bullets so the most relevant come first and reword them to use the "
        "job's vocabulary where the resume supports it. Write a 2-3 sentence summary from resume facts only.\n"
        'Return JSON: {"name": str, "contact": [email, phone, links, city as written], "summary": str, '
        '"skills": [str], "experience": [{"title": str, "organization": str, "location": str, "dates": str, '
        '"bullets": [str]}], "projects": [{"name": str, "dates": str, "technologies": [str], "bullets": [str]}], '
        '"education": [{"degree": str, "institution": str, "dates": str, "details": str}], '
        '"certifications": [str], "achievements": [str]}'
    )


def generate_structured(job, resume_text: str, facts: JobFacts) -> tuple[StructuredResume, str]:
    result = llm.generate_json("write", _prompt(job, resume_text, facts), schema=StructuredResume,
                               system=TAILOR_SYSTEM, max_tokens=2200)
    return StructuredResume.model_validate(result.data), result.provider


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_pdf(r: StructuredResume, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape as esc

    styles = getSampleStyleSheet()
    name = ParagraphStyle("name", parent=styles["Title"], fontSize=18, leading=22, spaceAfter=2, alignment=0)
    contact = ParagraphStyle("contact", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#334155"))
    head = ParagraphStyle("head", parent=styles["Heading2"], fontSize=11, leading=14, spaceBefore=8, spaceAfter=3,
                          textColor=colors.HexColor("#1E293B"))
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5, leading=12.5)
    strong = ParagraphStyle("strong", parent=body, fontName="Helvetica-Bold")

    def bullets(items):
        return ListFlowable([ListItem(Paragraph(esc(b), body), leftIndent=10) for b in items],
                            bulletType="bullet", start="-", leftIndent=10, bulletFontSize=8)

    story = []
    if r.name:
        story.append(Paragraph(esc(r.name), name))
    if r.contact:
        story.append(Paragraph(esc("  |  ".join(r.contact)), contact))
    if r.summary:
        story += [Paragraph("SUMMARY", head), Paragraph(esc(r.summary), body)]
    if r.skills:
        story += [Paragraph("SKILLS", head), Paragraph(esc(", ".join(r.skills)), body)]
    if r.experience:
        story.append(Paragraph("EXPERIENCE", head))
        for e in r.experience:
            line = " - ".join(x for x in (e.title, e.organization) if x)
            meta = ", ".join(x for x in (e.dates, e.location) if x)
            story.append(Paragraph(esc(line) + (f" <font color='#64748B'>({esc(meta)})</font>" if meta else ""), strong))
            if e.bullets:
                story.append(bullets(e.bullets))
    if r.projects:
        story.append(Paragraph("PROJECTS", head))
        for p in r.projects:
            extra = f" <font color='#64748B'>| {esc(', '.join(p.technologies))}</font>" if p.technologies else ""
            story.append(Paragraph(esc(p.name) + (f" ({esc(p.dates)})" if p.dates else "") + extra, strong))
            if p.bullets:
                story.append(bullets(p.bullets))
    if r.education:
        story.append(Paragraph("EDUCATION", head))
        for ed in r.education:
            story.append(Paragraph(esc(", ".join(x for x in (ed.degree, ed.institution, ed.dates) if x)), strong))
            if ed.details:
                story.append(Paragraph(esc(ed.details), body))
    if r.certifications:
        story += [Paragraph("CERTIFICATIONS", head), bullets(r.certifications)]
    if r.achievements:
        story += [Paragraph("ACHIEVEMENTS", head), bullets(r.achievements)]
    if not story:
        story.append(Paragraph("(empty)", body))
    story.append(Spacer(1, 2))
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"Resume - {r.name or 'tailored'}", author=r.name or "")
    doc.build(story)
    return path


def render_docx(r: StructuredResume, path: Path) -> Path:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    if r.name:
        doc.add_heading(r.name, level=0)
    if r.contact:
        doc.add_paragraph("  |  ".join(r.contact))

    def section(title):
        doc.add_heading(title, level=1)

    if r.summary:
        section("Summary")
        doc.add_paragraph(r.summary)
    if r.skills:
        section("Skills")
        doc.add_paragraph(", ".join(r.skills))
    if r.experience:
        section("Experience")
        for e in r.experience:
            p = doc.add_paragraph()
            p.add_run(" - ".join(x for x in (e.title, e.organization) if x)).bold = True
            meta = ", ".join(x for x in (e.dates, e.location) if x)
            if meta:
                p.add_run(f" ({meta})")
            for b in e.bullets:
                doc.add_paragraph(b, style="List Bullet")
    if r.projects:
        section("Projects")
        for pr in r.projects:
            p = doc.add_paragraph()
            p.add_run(pr.name).bold = True
            if pr.dates:
                p.add_run(f" ({pr.dates})")
            if pr.technologies:
                p.add_run(" | " + ", ".join(pr.technologies))
            for b in pr.bullets:
                doc.add_paragraph(b, style="List Bullet")
    if r.education:
        section("Education")
        for ed in r.education:
            p = doc.add_paragraph()
            p.add_run(", ".join(x for x in (ed.degree, ed.institution, ed.dates) if x)).bold = True
            if ed.details:
                doc.add_paragraph(ed.details)
    if r.certifications:
        section("Certifications")
        for c in r.certifications:
            doc.add_paragraph(c, style="List Bullet")
    if r.achievements:
        section("Achievements")
        for a in r.achievements:
            doc.add_paragraph(a, style="List Bullet")
    doc.save(str(path))
    return path


def ensure_files(row: models.TailoredResume) -> models.TailoredResume:
    """(Re-)render the PDF / DOCX from structured_json when a file is missing (e.g. after a redeploy)."""
    if row.status != "tailored" or not row.structured_json:
        return row
    data = StructuredResume.model_validate(json.loads(row.structured_json))
    stem = output_dir() / f"job{row.job_id}_resume{row.resume_id}_{row.id}"
    if not row.pdf_path or not Path(row.pdf_path).is_file():
        row.pdf_path = str(render_pdf(data, stem.with_suffix(".pdf")))
    if not row.docx_path or not Path(row.docx_path).is_file():
        try:
            row.docx_path = str(render_docx(data, stem.with_suffix(".docx")))
        except ImportError:
            row.docx_path = None
    return row


# ---------------------------------------------------------------------------
# Persistence + public entry point
# ---------------------------------------------------------------------------
def latest(db, job_id: int, resume=None) -> Optional[models.TailoredResume]:
    q = db.query(models.TailoredResume).filter(models.TailoredResume.job_id == job_id)
    if resume is not None:
        q = q.filter(models.TailoredResume.resume_id == resume.id,
                     models.TailoredResume.resume_hash == profile_mod.resume_hash(resume.extracted_text or ""))
    return q.order_by(models.TailoredResume.id.desc()).first()


def _loads(raw, default):
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def to_dict(row: Optional[models.TailoredResume], job=None) -> Optional[dict]:
    if row is None:
        return None
    metrics = _loads(row.metrics, {})
    return {
        "id": row.id, "job_id": row.job_id, "resume_id": row.resume_id, "status": row.status,
        "score_before": row.score_before, "score_after": row.score_after,
        "stored_score": metrics.get("stored_score"), "threshold": metrics.get("threshold", threshold()),
        "keyword_coverage_before": metrics.get("keyword_before"), "keyword_coverage_after": metrics.get("keyword_after"),
        "removed_unverified": _loads(row.removed_unverified, []), "gaps": _loads(row.gaps, []),
        "structured": _loads(row.structured_json, None), "tailored_text": row.tailored_text,
        "breakdown_after": _loads(row.breakdown_after, None),
        "has_pdf": bool(row.status == "tailored" and row.structured_json),
        "has_docx": bool(row.status == "tailored" and row.structured_json),
        "provider": row.provider, "error": row.error, "message": metrics.get("message"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class TailorError(Exception):
    """Tailoring cannot start (no resume, no text...). The message is shown to the user."""


def tailor_for_job(db, job, regenerate: bool = False, settings=None) -> models.TailoredResume:
    """Create (or return the cached) tailored resume for this job and the active resume. Never fakes a score."""
    settings = settings or crud.get_general_settings(db)
    resume = crud.get_active_resume_for_role(db, settings.active_role)
    if resume is None or not (resume.extracted_text or "").strip():
        raise TailorError(f"No active resume with text for '{settings.active_role}'. Upload one on the Resumes page.")
    original_text = resume.extracted_text.strip()
    digest = profile_mod.resume_hash(original_text)

    cached = latest(db, job.id, resume)
    if cached is not None and not regenerate and cached.status in ("tailored", "not_needed"):
        return ensure_files(cached)

    limit = threshold()
    row = models.TailoredResume(job_id=job.id, resume_id=resume.id, resume_hash=digest, status="failed",
                                created_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    profile = profile_mod.get_profile(db, resume, settings.active_role, settings.target_roles)
    facts = facts_from_job(job)
    metrics: dict[str, Any] = {"stored_score": job.score, "threshold": limit}
    row.gaps = json.dumps(gaps_for(facts, original_text, profile))
    metrics["keyword_before"] = keyword_coverage(facts, original_text)

    if job.score is not None and job.score >= limit:
        row.status = "not_needed"
        row.score_before = row.score_after = job.score
        metrics["message"] = (f"Score {job.score:.1f} is already at or above {limit:g}: your original resume is used "
                              "unchanged.")
        metrics["keyword_after"] = metrics["keyword_before"]
    else:
        try:
            draft, provider = generate_structured(job, original_text, facts)
            clean, removed = verify(draft, original_text)
            text = render_text(clean)
            scores = rescore(db, job, profile, clean, text, settings)
            row.status = "tailored"
            row.provider = provider
            row.structured_json = clean.model_dump_json()
            row.tailored_text = text
            row.removed_unverified = json.dumps(removed)
            row.score_before = scores["before"].score
            row.score_after = scores["after"].score
            row.breakdown_after = json.dumps(scores["after"].breakdown)
            metrics["keyword_after"] = keyword_coverage(facts, text)
            reached = row.score_after >= limit
            metrics["message"] = (
                f"Tailored with {provider}. Score {row.score_before:.1f} -> {row.score_after:.1f} "
                + ("(target reached)." if reached else
                   f"(still below {limit:g}: the score measures real fit, and rewording cannot add skills you do not have).")
                + (f" {len(removed)} unverifiable item(s) were removed." if removed else "")
            )
            if removed:
                logger.info(f"Tailored resume for job {job.id}: removed {len(removed)} unverifiable item(s)")
        except llm.LLMError as exc:
            row.error = f"AI providers unavailable: {exc}"
            metrics["message"] = "Could not tailor the resume: no AI provider answered. Your original resume is unchanged."
            metrics["keyword_after"] = None
    row.metrics = json.dumps(metrics, default=str)
    db.add(row)
    db.commit()
    db.refresh(row)
    if row.status == "tailored":
        try:
            ensure_files(row)
            db.commit()
        except Exception as exc:  # rendering problems must not lose the tailored content
            logger.exception("Rendering the tailored resume failed")
            row.error = f"Rendering failed ({type(exc).__name__}); the text version is still available."
            db.commit()
    return row


def file_for(row: models.TailoredResume, kind: str) -> Optional[Path]:
    ensure_files(row)
    path = row.pdf_path if kind == "pdf" else row.docx_path
    return Path(path) if path and Path(path).is_file() else None
