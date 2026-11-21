"""
Skill vocabulary, alias normalisation and fuzzy matching (pure Python).

`normalize_skill("JS") == normalize_skill("javascript") == "javascript"`. The dictionary also drives the
keyword fallback that finds skills in resume and job text when no AI provider is available.
"""
import difflib
import re
from typing import Iterable

# canonical name -> aliases (lower case). Keep entries specific: short aliases match whole words only.
SKILL_ALIASES: dict[str, list[str]] = {
    "python": ["python3", "python 3", "py"],
    "java": ["core java", "java se"],
    "javascript": ["js", "ecmascript", "es6"],
    "typescript": ["ts"],
    "c++": ["cpp", "c plus plus"],
    "c#": ["csharp", "c sharp", ".net c#"],
    "c": ["c programming", "c language"],
    "go": ["golang"],
    "rust": [],
    "kotlin": [],
    "scala": [],
    "r": ["r programming", "r language"],
    "sql": ["structured query language", "t-sql", "pl/sql", "plsql"],
    "mysql": [],
    "postgresql": ["postgres", "psql"],
    "mongodb": ["mongo"],
    "redis": [],
    "sqlite": [],
    "nosql": [],
    "elasticsearch": ["elastic search", "opensearch"],
    "django": [],
    "flask": [],
    "fastapi": ["fast api"],
    "spring boot": ["springboot", "spring"],
    "node.js": ["nodejs", "node js", "node"],
    "express": ["express.js", "expressjs"],
    "react": ["react.js", "reactjs"],
    "angular": ["angularjs"],
    "vue": ["vue.js", "vuejs"],
    "next.js": ["nextjs"],
    "html": ["html5"],
    "css": ["css3"],
    "tailwind": ["tailwindcss", "tailwind css"],
    "rest api": ["rest", "restful", "restful api", "rest apis", "restful apis", "apis"],
    "graphql": [],
    "grpc": [],
    "microservices": ["micro services", "microservice"],
    "docker": ["containers", "containerization"],
    "kubernetes": ["k8s"],
    "aws": ["amazon web services", "ec2", "s3", "lambda"],
    "azure": ["microsoft azure"],
    "gcp": ["google cloud", "google cloud platform"],
    "linux": ["unix", "bash", "shell scripting"],
    "git": ["github", "gitlab", "version control"],
    "ci/cd": ["cicd", "ci cd", "jenkins", "github actions", "continuous integration"],
    "terraform": [],
    "kafka": ["apache kafka"],
    "rabbitmq": [],
    "celery": [],
    "airflow": ["apache airflow"],
    "spark": ["pyspark", "apache spark"],
    "hadoop": [],
    "snowflake": [],
    "databricks": [],
    "etl": ["elt", "data pipelines", "data pipeline"],
    "data analysis": ["data analytics", "analytics"],
    "data visualization": ["data visualisation", "visualization", "dashboards"],
    "excel": ["ms excel", "microsoft excel", "advanced excel"],
    "power bi": ["powerbi"],
    "tableau": [],
    "statistics": ["statistical analysis", "stats"],
    "pandas": [],
    "numpy": [],
    "scikit-learn": ["sklearn", "scikit learn"],
    "tensorflow": ["tf", "keras"],
    "pytorch": ["torch"],
    "machine learning": ["ml"],
    "deep learning": ["dl", "neural networks", "neural network"],
    "nlp": ["natural language processing"],
    "computer vision": ["cv", "opencv", "image processing"],
    "llm": ["llms", "large language models", "large language model", "generative ai", "genai", "gen ai"],
    "langchain": [],
    "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
    "prompt engineering": [],
    "hugging face": ["huggingface", "transformers"],
    "mlops": ["ml ops", "mlflow"],
    "data science": [],
    "artificial intelligence": ["ai"],
    "selenium": [],
    "playwright": [],
    "automation": ["test automation", "process automation", "rpa"],
    "web scraping": ["scraping", "beautifulsoup", "scrapy"],
    "testing": ["unit testing", "pytest", "unittest", "qa"],
    "oop": ["object oriented programming", "object-oriented programming"],
    "data structures": ["dsa", "data structures and algorithms", "algorithms"],
    "system design": [],
    "agile": ["scrum"],
    "communication": ["communication skills"],
    "jira": [],
    "figma": [],
}

_ALIAS_TO_CANONICAL: dict[str, str] = {}
for canonical, aliases in SKILL_ALIASES.items():
    _ALIAS_TO_CANONICAL[canonical] = canonical
    for alias in aliases:
        _ALIAS_TO_CANONICAL.setdefault(alias, canonical)

# Aliases that are too ambiguous to find by scanning free text (still fine when an AI names the skill).
_SCAN_EXCLUDE = {"c", "r", "go", "py", "ts", "tf", "dl", "cv", "ai", "ml", "node", "rest", "apis", "spring",
                 "stats", "lambda", "s3", "qa", "analytics", "containers", "visualization", "dashboards",
                 "transformers", "scraping", "algorithms", "unix", "bash", "github", "gitlab"}

FUZZY_THRESHOLD = 0.88


def _clean(skill: str) -> str:
    s = (skill or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .,;:")


def normalize_skill(skill: str) -> str:
    """Canonical name for a skill (unknown skills are returned cleaned, lower case)."""
    s = _clean(skill)
    if s in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[s]
    s2 = re.sub(r"[\s._-]+", "", s)
    for alias, canonical in _ALIAS_TO_CANONICAL.items():
        if re.sub(r"[\s._-]+", "", alias) == s2 and len(s2) > 2:
            return canonical
    return s


def normalize_skills(skills: Iterable[str]) -> list[str]:
    out: list[str] = []
    for skill in skills or []:
        if not isinstance(skill, str):
            continue
        n = normalize_skill(skill)
        if n and n not in out:
            out.append(n)
    return out


def _alias_pattern(alias: str) -> re.Pattern:
    return re.compile(rf"(?<![a-z0-9+#]){re.escape(alias)}(?![a-z0-9+#])")


_SCAN_PATTERNS = [
    (canonical, [_alias_pattern(a) for a in [canonical, *aliases] if a not in _SCAN_EXCLUDE])
    for canonical, aliases in SKILL_ALIASES.items()
]


def extract_skills(text: str) -> list[str]:
    """Keyword scan for known skills in free text (used by the no-AI fallback)."""
    t = (text or "").lower()
    found = []
    for canonical, patterns in _SCAN_PATTERNS:
        if any(p.search(t) for p in patterns):
            found.append(canonical)
    return found


def skill_in_text(skill: str, text: str) -> bool:
    """Is this skill (or one of its aliases) actually mentioned in the text? Guards against invented facts."""
    t = (text or "").lower()
    canonical = normalize_skill(skill)
    candidates = {_clean(skill), canonical, *SKILL_ALIASES.get(canonical, [])}
    for c in candidates:
        if c and _alias_pattern(c).search(t):
            return True
    words = [w for w in re.findall(r"[a-z0-9+#]+", _clean(skill)) if len(w) > 2]
    return bool(words) and all(_alias_pattern(w).search(t) for w in words)


def skills_match(a: str, b: str) -> bool:
    na, nb = normalize_skill(a), normalize_skill(b)
    if na == nb:
        return True
    if len(na) > 3 and len(nb) > 3 and difflib.SequenceMatcher(None, na, nb).ratio() >= FUZZY_THRESHOLD:
        return True
    return False


def match_skills(required: Iterable[str], candidate: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split `required` into (matched, missing) against the candidate's skills."""
    cand = normalize_skills(candidate)
    matched, missing = [], []
    for skill in normalize_skills(required):
        (matched if any(skills_match(skill, c) for c in cand) else missing).append(skill)
    return matched, missing
