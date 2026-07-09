"""Cover letter generation, grounded in the master profile — same no-fabrication
contract as tailoring. The model writes body paragraphs only; salutation, date,
and signature come from verified data via the template."""

from __future__ import annotations

import datetime
import re
from pathlib import Path

from .latex import _jinja_env, compile_pdf, escape_latex
from .llm import LLM, default_llm
from .models import Contact, CoverLetter, Job, MasterProfile
from .tailor import NO_FABRICATION_RULE

COVER_SYSTEM = f"""You write concise, professional cover letters.

{NO_FABRICATION_RULE}

Additional rules for cover letters:
- Write 3-4 body paragraphs, 220-320 words total, in the first person.
- Open with genuine interest in THIS role; do not restate the resume.
- Middle paragraphs: connect 2-3 concrete, REAL experiences/projects from the
  profile to the job's top requirements, using the posting's terminology where
  it truthfully applies.
- Close with a brief, confident call to action.
- Output ONLY the body paragraphs — no salutation ("Dear..."), no sign-off
  ("Sincerely"), no name, no date, and NEVER bracketed placeholders like
  [Company Name]."""

_PLACEHOLDER_RE = re.compile(r"\[[^\]]{1,40}\]")


def write_cover_letter(profile: MasterProfile, job: Job, *, llm: LLM | None = None) -> CoverLetter:
    """Draft grounded cover-letter body paragraphs for ``job``."""
    llm = llm or default_llm()
    letter = llm.parse(
        system=COVER_SYSTEM,
        prompt=(
            "Write the cover letter body for this candidate and job.\n\n"
            f"<candidate_profile>\n{profile.model_dump_json(indent=2)}\n</candidate_profile>\n\n"
            f"<job>\n{job.model_dump_json(indent=2)}\n</job>"
        ),
        output_type=CoverLetter,
    )
    # Strip stray salutations/sign-offs and template placeholders the model
    # was told not to produce — belt and suspenders for small local models.
    paragraphs = []
    for para in letter.paragraphs:
        text = _PLACEHOLDER_RE.sub("", para).strip()
        lowered = text.lower()
        if not text:
            continue
        if lowered.startswith(("dear ", "sincerely", "best regards", "regards,", "to whom")):
            continue
        paragraphs.append(re.sub(r"\s{2,}", " ", text))
    return CoverLetter(paragraphs=paragraphs)


def render_cover_letter_tex(
    letter: CoverLetter,
    contact: Contact,
    job: Job,
    out_path: str | Path,
    *,
    date: datetime.date | None = None,
) -> Path:
    """Fill the letter template and write the .tex file."""
    out_path = Path(out_path)
    salutation = f"Dear {job.company} Hiring Team," if job.company else "Dear Hiring Manager,"
    contact_bits = [contact.location, contact.phone, contact.email]
    template = _jinja_env().get_template("cover_letter.tex.j2")
    rendered = template.render(
        letter=letter,
        contact=contact,
        job=job,
        salutation=escape_latex(salutation),
        contact_line=r" $|$ ".join(escape_latex(p) for p in contact_bits if p),
        date_line=escape_latex(f"{(d := date or datetime.date.today()):%B} {d.day}, {d:%Y}"),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def generate_cover_letter(
    profile: MasterProfile,
    job: Job,
    out_dir: str | Path,
    *,
    llm: LLM | None = None,
) -> tuple[Path, Path]:
    """Write + render + compile the cover letter. Returns (pdf_path, tex_path)."""
    out_dir = Path(out_dir)
    letter = write_cover_letter(profile, job, llm=llm)
    tex_path = render_cover_letter_tex(letter, profile.contact, job, out_dir / "cover_letter.tex")
    pdf_path = compile_pdf(tex_path)
    return pdf_path, tex_path
