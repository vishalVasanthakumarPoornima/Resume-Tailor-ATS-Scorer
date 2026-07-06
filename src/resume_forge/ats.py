"""Step 6: local ATS scorer — 0-100 with a per-dimension breakdown.

Weights (sum = 100):
  keywords      40  keyword/skill coverage vs the JD (required skills weigh double)
  parseability  15  clean text extraction from the PDF
  sections      15  standard section headers present (Experience/Education/Skills)
  bullets       15  action-verb, quantified bullet content
  contact       10  email + phone detectable
  length         5  1-2 pages, reasonable word count

Fully local: no network, no LLM. Works on any resume PDF, not just ours.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Job, ScoreReport

WEIGHTS = {
    "keywords": 40.0,
    "parseability": 15.0,
    "sections": 15.0,
    "bullets": 15.0,
    "contact": 10.0,
    "length": 5.0,
}

ACTION_VERBS = {
    "achieved", "analyzed", "architected", "automated", "built", "collaborated",
    "created", "cut", "debugged", "delivered", "deployed", "designed", "developed",
    "directed", "drove", "engineered", "enhanced", "established", "evaluated",
    "expanded", "implemented", "improved", "increased", "initiated", "integrated",
    "launched", "led", "maintained", "managed", "mentored", "migrated", "optimized",
    "orchestrated", "organized", "owned", "partnered", "pioneered", "presented",
    "produced", "profiled", "prototyped", "published", "rearchitected", "redesigned",
    "reduced", "refactored", "released", "researched", "resolved", "scaled",
    "shipped", "spearheaded", "streamlined", "tested", "trained", "wrote",
}

SECTION_PATTERNS = {
    "experience": r"(work\s+|professional\s+|relevant\s+)?experience|employment(\s+history)?",
    "education": r"education(al\s+background)?|academic",
    "skills": r"(technical\s+|core\s+)?skills|technologies|competencies",
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\+?\d{1,3}[\s.-]?)?(\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")


def extract_pdf_text(pdf_path: str | Path) -> tuple[str, int]:
    """Return (extracted text, page count) for a PDF."""
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages), len(pages)


def keyword_found(text_lower: str, keyword: str) -> bool:
    """Whole-token match, tolerant of symbols in terms like C++, C#, Node.js."""
    kw = keyword.strip().lower()
    if not kw:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"
    return re.search(pattern, text_lower) is not None


def _score_keywords(text: str, job: Job) -> tuple[float, list[str]]:
    text_lower = text.lower()
    weighted: list[tuple[str, int]] = [(k, 2) for k in job.required_skills]
    weighted += [(k, 1) for k in job.preferred_skills]
    weighted += [(k, 1) for k in job.keywords]

    # dedupe, keeping the highest weight for a term
    seen: dict[str, int] = {}
    for term, weight in weighted:
        key = term.strip().lower()
        if key:
            seen[key] = max(seen.get(key, 0), weight)
    if not seen:
        return WEIGHTS["keywords"], []  # nothing to match against — don't punish

    total = sum(seen.values())
    matched = 0
    missing: list[tuple[str, int]] = []
    for term, weight in seen.items():
        if keyword_found(text_lower, term):
            matched += weight
        else:
            missing.append((term, weight))
    missing.sort(key=lambda pair: -pair[1])  # required (weight 2) first
    return WEIGHTS["keywords"] * matched / total, [term for term, _ in missing]


def _score_parseability(text: str, n_pages: int) -> float:
    if not text.strip():
        return 0.0
    score = WEIGHTS["parseability"]
    # embedded-font garbage from broken extraction
    cid_hits = text.count("(cid:")
    if cid_hits:
        score -= min(8.0, cid_hits * 0.5)
    # too little text per page suggests image-based or exotic layout
    chars_per_page = len(text) / max(n_pages, 1)
    if chars_per_page < 400:
        score *= chars_per_page / 400
    # replacement characters from encoding issues
    if "�" in text:
        score -= 2.0
    return max(0.0, score)


def _score_sections(text: str) -> tuple[float, list[str]]:
    per_section = WEIGHTS["sections"] / len(SECTION_PATTERNS)
    score = 0.0
    missing = []
    for name, pattern in SECTION_PATTERNS.items():
        if re.search(rf"^\s*(?:{pattern})\s*:?\s*$", text, re.IGNORECASE | re.MULTILINE) or re.search(
            rf"\b(?:{pattern})\b", text, re.IGNORECASE
        ):
            score += per_section
        else:
            missing.append(name)
    return score, missing


def _score_contact(text: str) -> tuple[float, list[str]]:
    score = 0.0
    missing = []
    if EMAIL_RE.search(text):
        score += WEIGHTS["contact"] / 2
    else:
        missing.append("email address")
    if PHONE_RE.search(text):
        score += WEIGHTS["contact"] / 2
    else:
        missing.append("phone number")
    return score, missing


def _score_length(text: str, n_pages: int) -> float:
    page_score = {1: 1.0, 2: 0.8}.get(n_pages, 0.4 if n_pages == 3 else 0.0)
    words = len(text.split())
    if words < 150:
        word_factor = words / 150
    elif words > 1100:
        word_factor = 0.6
    else:
        word_factor = 1.0
    return WEIGHTS["length"] * page_score * word_factor


def _candidate_bullet_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("•-–*● ").strip()
        words = line.split()
        if 5 <= len(words) <= 45:
            lines.append(line)
    return lines


def _score_bullets(text: str) -> float:
    lines = _candidate_bullet_lines(text)
    if not lines:
        return 0.0
    action = sum(1 for line in lines if line.split()[0].lower().rstrip(",.") in ACTION_VERBS)
    quantified = sum(1 for line in lines if re.search(r"\d|%|\$", line))
    action_frac = action / len(lines)
    quant_frac = quantified / len(lines)
    # Full marks ≈ half the content lines start with action verbs and half carry numbers.
    return WEIGHTS["bullets"] * (0.6 * min(1.0, action_frac / 0.5) + 0.4 * min(1.0, quant_frac / 0.5))


def score_resume_text(text: str, n_pages: int, job: Job) -> ScoreReport:
    """Score already-extracted resume text. Core, dependency-free logic for tests."""
    kw_score, missing_keywords = _score_keywords(text, job)
    parse_score = _score_parseability(text, n_pages)
    section_score, missing_sections = _score_sections(text)
    bullet_score = _score_bullets(text)
    contact_score, missing_contact = _score_contact(text)
    length_score = _score_length(text, n_pages)

    subscores = {
        "keywords": round(kw_score, 1),
        "parseability": round(parse_score, 1),
        "sections": round(section_score, 1),
        "bullets": round(bullet_score, 1),
        "contact": round(contact_score, 1),
        "length": round(length_score, 1),
    }

    suggestions: list[str] = []
    if missing_keywords:
        top = ", ".join(missing_keywords[:8])
        suggestions.append(f"Add these JD keywords where truthful: {top}")
    if missing_sections:
        suggestions.append(f"Add standard section header(s): {', '.join(missing_sections)}")
    if missing_contact:
        suggestions.append(f"Include contact info: {', '.join(missing_contact)}")
    if parse_score < WEIGHTS["parseability"] * 0.7:
        suggestions.append("PDF text extraction is degraded — avoid graphics, tables, and multi-column layouts")
    if bullet_score < WEIGHTS["bullets"] * 0.6:
        suggestions.append("Start bullets with strong action verbs and quantify results with numbers")
    if length_score < WEIGHTS["length"] * 0.7:
        suggestions.append("Aim for 1-2 pages with 300-900 words of substantive content")

    return ScoreReport(
        score=round(sum(subscores.values()), 1),
        subscores=subscores,
        max_subscores=WEIGHTS,
        missing_keywords=missing_keywords,
        suggestions=suggestions,
    )


def score_ats(pdf_path: str | Path, job: Job) -> ScoreReport:
    """Score a resume PDF against a job. Local, deterministic, 0-100."""
    text, n_pages = extract_pdf_text(pdf_path)
    return score_resume_text(text, n_pages, job)
