"""Step 3: tailor the master profile to a job — emphasis and rewording, never fabrication.

Two layers of defense against invented content:
1. The tailoring prompt states the no-fabrication rule explicitly.
2. ``enforce_no_fabrication`` programmatically drops any employer, education,
   or certification entry that does not exist in the master profile.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from .llm import LLM, default_llm
from .models import Job, MasterProfile, SkillGroup, TailoredResume

NO_FABRICATION_RULE = """HARD RULE — NO FABRICATION:
Only use facts present in the master profile. NEVER invent or alter employers, job titles,
employment dates, degrees, institutions, GPAs, certifications, project names, or metrics.
Every number in a bullet must already exist in the master profile. Tailoring means
emphasis, reordering, rewording, and keyword alignment — NOT adding experience the
candidate does not have. If the job asks for a skill the candidate lacks, simply do not
mention it; do not imply familiarity."""

TAILOR_SYSTEM = f"""You are an expert resume writer optimizing a resume for a specific job
posting and its Applicant Tracking System (ATS).

{NO_FABRICATION_RULE}

What you SHOULD do:
- Reorder experience bullets and skill groups so the most job-relevant items come first.
- Reword bullets to use the job posting's exact terminology where it truthfully applies
  (e.g. if the profile says "built REST services" and the job says "microservices", write
  "microservices" only if the profile supports it).
- Weave the job's required skills and keywords into the summary, skills section, and
  bullets — but only skills the candidate actually has evidence for.
- Keep bullets in strong action-verb form (Led, Built, Reduced, Shipped...), ideally with
  the quantified results that already exist in the profile.
- Prefer 1 page of content: keep the most relevant experience/projects, and trim bullets
  that add nothing for this job. Keep ALL employment history entries (gaps look worse),
  but you may shorten less-relevant ones to 1-2 bullets.
- Copy contact and education verbatim from the profile."""


def _feedback_block(feedback: dict | None) -> str:
    if not feedback:
        return ""
    return (
        "\n\nA previous version of this tailored resume was scored by an ATS scanner. "
        "Improve on it using this feedback (still respecting the no-fabrication rule — "
        "only add a missing keyword if the master profile truthfully supports it):\n"
        f"{json.dumps(feedback, indent=2)}"
    )


def tailor(
    profile: MasterProfile,
    job: Job,
    *,
    feedback: dict | None = None,
    llm: LLM | None = None,
) -> TailoredResume:
    """Produce tailored resume content for ``job`` from ``profile``."""
    llm = llm or default_llm()
    prompt = (
        "Tailor this master profile to the job posting below.\n\n"
        f"<master_profile>\n{profile.model_dump_json(indent=2)}\n</master_profile>\n\n"
        f"<job>\n{job.model_dump_json(indent=2)}\n</job>"
        f"{_feedback_block(feedback)}"
    )
    tailored = llm.parse(system=TAILOR_SYSTEM, prompt=prompt, output_type=TailoredResume)
    cleaned, _ = enforce_no_fabrication(tailored, profile)
    cleaned, _ = backfill_truthful_skills(cleaned, profile, job)
    return cleaned


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


_CANON_STRIP = re.compile(r"[^a-z0-9 ]+")
_CANON_SUFFIXES = (" inc", " llc", " ltd", " corp", " corporation", " co", " company")


def _canon(value: str | None) -> str:
    """Canonical form for fuzzy entity comparison: lowercase, no punctuation,
    no legal suffixes, collapsed whitespace."""
    out = _CANON_STRIP.sub(" ", _norm(value))
    out = re.sub(r"\s+", " ", out).strip()
    for suffix in _CANON_SUFFIXES:
        if out.endswith(suffix):
            out = out[: -len(suffix)].strip()
    return out


def _same_entity(a: str | None, b: str | None) -> bool:
    """Fuzzy match for employer/school/project names.

    Tolerates cosmetic drift a model introduces ('Perficient, Inc.' vs
    'Perficient', 'Acme Analytics, San Jose, CA' vs 'Acme Analytics') without
    accepting genuinely different entities.
    """
    ca, cb = _canon(a), _canon(b)
    if not ca or not cb:
        return False
    if ca == cb or ca in cb or cb in ca:
        return True
    return SequenceMatcher(None, ca, cb).ratio() >= 0.8


def backfill_truthful_skills(
    tailored: TailoredResume, profile: MasterProfile, job: Job
) -> tuple[TailoredResume, list[str]]:
    """Re-add job-relevant skills the model dropped — but ONLY ones the master
    profile already lists, so this can never fabricate.

    Small local models sometimes over-trim the skills section; this guarantees a
    skill that is both in the JD and in the master profile survives tailoring.
    """
    from .ats import keyword_found

    profile_skills: dict[str, tuple[str, str]] = {}  # normalized item -> (category, item)
    for group in profile.skills:
        for item in group.items:
            profile_skills.setdefault(_norm(item), (group.category, item))

    tailored_text = tailored.model_dump_json().lower()
    job_terms = job.required_skills + job.preferred_skills + job.keywords

    skills = [group.model_copy(deep=True) for group in tailored.skills]
    added: list[str] = []
    for term in job_terms:
        key = _norm(term)
        if key not in profile_skills or keyword_found(tailored_text, term):
            continue
        category, item = profile_skills[key]
        target = next((g for g in skills if _norm(g.category) == _norm(category)), None)
        if target is None:
            target = SkillGroup(category=category, items=[])
            skills.append(target)
        if all(_norm(existing) != key for existing in target.items):
            target.items.append(item)
            added.append(item)

    if not added:
        return tailored, []
    return tailored.model_copy(update={"skills": skills}), added


def enforce_no_fabrication(
    tailored: TailoredResume, profile: MasterProfile
) -> tuple[TailoredResume, list[str]]:
    """Two-way structural guard against both fabrication AND content loss.

    - Drops tailored entries whose anchor facts (employer/school/project/cert)
      don't fuzzy-match anything in the master profile — the model may reword
      bullets, never invent entities.
    - RESTORES master experience and education entries the model omitted:
      tailoring must never delete employment history or degrees. (Projects and
      certifications may legitimately be trimmed for relevance, so those are
      only restored wholesale if the model dropped ALL of them.)
    Returns the cleaned resume and human-readable notes about what it fixed.
    """
    violations: list[str] = []

    # --- experience: filter fabrications, then restore omissions ---
    matched_master: set[int] = set()
    experience = []
    for item in tailored.experience:
        match = next(
            (i for i, m in enumerate(profile.experience) if _same_entity(item.company, m.company)),
            None,
        )
        if match is not None:
            matched_master.add(match)
            experience.append(item)
        else:
            violations.append(f"Dropped invented employer: {item.company!r}")
    for i, master_item in enumerate(profile.experience):
        if i not in matched_master:
            experience.append(master_item.model_copy(deep=True))
            violations.append(f"Restored omitted employer: {master_item.company!r}")

    # --- education: always verbatim from the master profile ---
    # Rewording education adds nothing and risks implied falsehoods (e.g. an
    # in-progress degree phrased as "Completed..."), so the model's version is
    # discarded wholesale.
    education = [item.model_copy(deep=True) for item in profile.education]

    # --- projects: filter fabrications; restore only on total loss ---
    projects = []
    for item in tailored.projects:
        if any(_same_entity(item.name, m.name) for m in profile.projects):
            projects.append(item)
        else:
            violations.append(f"Dropped invented project: {item.name!r}")
    if not projects and profile.projects:
        projects = [p.model_copy(deep=True) for p in profile.projects]
        violations.append("Restored all projects (model omitted the section)")

    # --- certifications: filter fabrications; restore only on total loss ---
    certifications = []
    for cert in tailored.certifications:
        if any(_same_entity(cert, c) for c in profile.certifications):
            certifications.append(cert)
        else:
            violations.append(f"Dropped invented certification: {cert!r}")
    if not certifications and profile.certifications:
        certifications = list(profile.certifications)

    # A weak parser sometimes duplicates a certification as a "project" (e.g.
    # "AWS Certified Developer"). If a project's name is exactly a certification,
    # it's that mis-parse, not a real project — keep it only under Certifications.
    cert_keys = {_norm(c) for c in certifications}
    deduped_projects = []
    for item in projects:
        if _norm(item.name) in cert_keys:
            violations.append(f"Removed certification duplicated as a project: {item.name!r}")
        else:
            deduped_projects.append(item)
    projects = deduped_projects

    cleaned = tailored.model_copy(
        update={
            "contact": profile.contact,  # contact is never the model's to rewrite
            "summary": tailored.summary or profile.summary,
            "experience": experience,
            "education": education,
            "projects": projects,
            "certifications": certifications,
        }
    )
    return cleaned, violations
