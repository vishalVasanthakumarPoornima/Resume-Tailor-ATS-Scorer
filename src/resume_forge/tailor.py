"""Step 3: tailor the master profile to a job — emphasis and rewording, never fabrication.

Two layers of defense against invented content:
1. The tailoring prompt states the no-fabrication rule explicitly.
2. ``enforce_no_fabrication`` programmatically drops any employer, education,
   or certification entry that does not exist in the master profile.
"""

from __future__ import annotations

import json

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
    """Drop tailored entries whose anchor facts don't exist in the master profile.

    Returns the cleaned resume and a list of human-readable violations (empty if
    the model behaved). Bullets are the model's responsibility (prompt-level rule);
    this guard catches the structural fabrications: employers, schools, certs.
    """
    violations: list[str] = []

    known_companies = {_norm(e.company) for e in profile.experience}
    experience = []
    for item in tailored.experience:
        if _norm(item.company) in known_companies:
            experience.append(item)
        else:
            violations.append(f"Dropped invented employer: {item.company!r}")

    known_schools = {_norm(e.institution) for e in profile.education}
    education = []
    for item in tailored.education:
        if _norm(item.institution) in known_schools:
            education.append(item)
        else:
            violations.append(f"Dropped invented institution: {item.institution!r}")

    known_projects = {_norm(p.name) for p in profile.projects}
    projects = []
    for item in tailored.projects:
        if _norm(item.name) in known_projects:
            projects.append(item)
        else:
            violations.append(f"Dropped invented project: {item.name!r}")

    known_certs = {_norm(c) for c in profile.certifications}
    certifications = []
    for cert in tailored.certifications:
        if _norm(cert) in known_certs:
            certifications.append(cert)
        else:
            violations.append(f"Dropped invented certification: {cert!r}")

    cleaned = tailored.model_copy(
        update={
            "contact": profile.contact,  # contact is never the model's to rewrite
            "experience": experience,
            "education": education,
            "projects": projects,
            "certifications": certifications,
        }
    )
    return cleaned, violations
