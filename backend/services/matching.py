"""
Lightweight role/title similarity (pure Python, no embeddings).

A role such as "AI/ML Engineer" is parsed into word groups: [{ai, ml}] are the core words (a slash
means "either"), and "engineer" is a generic role noun. A job title matches the role to the extent
that it contains the core words; sharing a generic noun (engineer ~ developer ~ programmer) adds a
little. Common phrases are normalised first ("machine learning" -> "ml", "back-end" -> "backend").
"""
import difflib
import re
from typing import Iterable, Optional

PHRASES = [
    (r"\bmachine[\s-]+learning\b", "ml"),
    (r"\bartificial[\s-]+intelligence\b", "ai"),
    (r"\bgen(?:erative)?[\s-]*ai\b", "genai ai"),
    (r"\blarge[\s-]+language[\s-]+models?\b", "llm"),
    (r"\bnatural[\s-]+language[\s-]+processing\b", "nlp"),
    (r"\bdeep[\s-]+learning\b", "dl ml"),
    (r"\bcomputer[\s-]+vision\b", "vision"),
    (r"\bback[\s-]+end\b", "backend"),
    (r"\bfront[\s-]+end\b", "frontend"),
    (r"\bfull[\s-]+stack\b", "fullstack"),
    (r"\bsoftware[\s-]+development[\s-]+engineer\b", "software engineer"),
    (r"\bsde\b", "software engineer"),
    (r"\bdata[\s-]+science\b", "data scientist"),
    (r"\bml[\s-]*ops\b", "mlops ml"),
]

GENERIC_NOUNS = {"engineer", "developer", "programmer", "dev", "specialist", "consultant", "associate"}
IGNORED = {
    "senior", "sr", "junior", "jr", "lead", "intern", "internship", "trainee", "staff", "principal",
    "i", "ii", "iii", "iv", "and", "the", "of", "for", "with", "in", "a", "an", "to", "at", "on",
    "remote", "hybrid", "fresher", "freshers", "entry", "level", "graduate", "new", "grad", "team",
    "role", "position", "job", "opening", "hiring", "urgent", "immediate", "joiner", "joiners",
}

STEMS = [("analy", "analy"), ("scien", "scien"), ("automat", "automat"), ("develop", "developer"),
         ("engineer", "engineer"), ("program", "programmer"), ("architect", "architect"),
         ("research", "research"), ("platform", "platform"), ("infra", "infra")]


def _stem(word: str) -> str:
    for prefix, stem in STEMS:
        if word.startswith(prefix):
            return stem
    return word


def normalize_text(text: Optional[str]) -> str:
    t = (text or "").lower()
    for pattern, repl in PHRASES:
        t = re.sub(pattern, f" {repl} ", t)
    return t


def tokens(text: Optional[str]) -> set[str]:
    words = re.findall(r"[a-z0-9+#]+", normalize_text(text).replace("/", " "))
    return {_stem(w) for w in words if w not in IGNORED}


def role_groups(role: str) -> tuple[list[set[str]], bool]:
    """('AI/ML Engineer') -> ([{'ai', 'ml'}], has_generic_noun=True)."""
    normalized = normalize_text(role)
    groups: list[set[str]] = []
    has_generic = False
    for chunk in normalized.split():
        alts = {_stem(w) for w in re.findall(r"[a-z0-9+#]+", chunk) if w not in IGNORED}
        if not alts:
            continue
        if alts <= {_stem(g) for g in GENERIC_NOUNS}:
            has_generic = True
            continue
        groups.append(alts)
    return groups, has_generic


_GENERIC_STEMS = {_stem(g) for g in GENERIC_NOUNS}


def role_similarity(title: Optional[str], role: Optional[str]) -> float:
    """0..1 similarity between a job title and one role name."""
    if not title or not role:
        return 0.0
    title_tokens = tokens(title)
    groups, role_generic = role_groups(role)
    title_generic = bool(title_tokens & _GENERIC_STEMS)
    if groups:
        matched = sum(1 for g in groups if g & title_tokens)
        core = matched / len(groups)
    else:
        core = 0.5
    generic = 1.0 if (role_generic and title_generic) or not role_generic else 0.0
    token_score = 0.8 * core + 0.2 * generic if groups else 0.5 * generic
    ratio = difflib.SequenceMatcher(None, " ".join(sorted(tokens(role))), " ".join(sorted(title_tokens))).ratio()
    return round(max(token_score, ratio * 0.9), 3)


def best_role_similarity(title: Optional[str], roles: Iterable[str]) -> tuple[float, Optional[str]]:
    best, best_role = 0.0, None
    for role in roles:
        sim = role_similarity(title, role)
        if sim > best:
            best, best_role = sim, role
    return best, best_role


def is_relevant(title: Optional[str], role: str, description: Optional[str] = None, threshold: float = 0.5) -> bool:
    """Cheap relevance test for unfiltered listings (ATS boards, scraped pages)."""
    if role_similarity(title, role) >= threshold:
        return True
    groups, _ = role_groups(role)
    if not groups or not description:
        return False
    # e.g. role "Python Developer" and title "Software Engineer, Backend" whose description asks for Python.
    title_tokens = tokens(title)
    desc_tokens = tokens(description)
    return bool(title_tokens & _GENERIC_STEMS) and all(g & desc_tokens for g in groups)
