"""Steps 4-5: render the ATS-friendly LaTeX template and compile it to PDF."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, PackageLoader

from .exceptions import LatexError
from .models import TailoredResume

# Order matters only for backslash, which we stash first so the replacement
# text of the other specials is not re-escaped.
_SPECIALS = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


# Unicode punctuation that pdfTeX's T1 encoding drops silently — transliterate
# to LaTeX-native ASCII first (all plain text, so the specials pass below is safe).
_UNICODE_PUNCT = {
    "—": "---",  # em dash
    "–": "--",  # en dash
    "’": "'",
    "‘": "`",
    "“": "``",
    "”": "''",
    "…": "...",
    "•": "-",  # bullet char inside prose
    " ": " ",  # non-breaking space
    "​": "",  # zero-width space (common in PDF extractions)
}


def escape_latex(value: str) -> str:
    """Escape LaTeX special characters: \\ % & _ # $ { } ~ ^, and transliterate
    Unicode punctuation that would otherwise vanish from the PDF."""
    if value is None:
        return ""
    out = str(value)
    for char, replacement in _UNICODE_PUNCT.items():
        out = out.replace(char, replacement)
    out = out.replace("\\", "\x00")
    for char, replacement in _SPECIALS.items():
        out = out.replace(char, replacement)
    return out.replace("\x00", r"\textbackslash{}")


def _jinja_env() -> Environment:
    # LaTeX-safe delimiters: \VAR{...} for variables, \BLOCK{...} for control flow.
    env = Environment(
        loader=PackageLoader("resume_forge", "templates"),
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\COMMENT{",
        comment_end_string="}",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )
    env.filters["tex"] = escape_latex
    return env


def _contact_line(resume: TailoredResume) -> str:
    c = resume.contact
    parts = [c.location, c.phone, c.email, c.linkedin, c.github, c.website]
    seen: set[str] = set()
    unique = []
    for part in parts:
        if not part:
            continue
        key = part.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        if key in seen:
            continue  # models sometimes copy the same value into two fields
        seen.add(key)
        unique.append(part)
    return r" $|$ ".join(escape_latex(p) for p in unique)


# Spacing presets from most readable (index 0) to most compact (last). The
# one-page fitter renders at the first level whose output fits a single page,
# so a short resume stays roomy and a full one tightens gracefully.
DENSITY_LEVELS: list[dict] = [
    dict(cls_size=11, margin="0.6in", name_size=r"\LARGE", sec_before="10pt", sec_after="5pt", rule_gap="-6pt", itemsep="3pt", topsep="3pt", parskip="6pt"),
    dict(cls_size=11, margin="0.55in", name_size=r"\LARGE", sec_before="8pt", sec_after="4pt", rule_gap="-6pt", itemsep="2pt", topsep="2pt", parskip="5pt"),
    dict(cls_size=10, margin="0.5in", name_size=r"\LARGE", sec_before="7pt", sec_after="3pt", rule_gap="-6pt", itemsep="1.5pt", topsep="2pt", parskip="4pt"),
    dict(cls_size=10, margin="0.45in", name_size=r"\Large", sec_before="6pt", sec_after="2pt", rule_gap="-5pt", itemsep="1pt", topsep="1pt", parskip="3pt"),
    dict(cls_size=9, margin="0.45in", name_size=r"\Large", sec_before="5pt", sec_after="2pt", rule_gap="-5pt", itemsep="1pt", topsep="1pt", parskip="2.5pt"),
    dict(cls_size=9, margin="0.4in", name_size=r"\Large", sec_before="4pt", sec_after="1pt", rule_gap="-4pt", itemsep="0.5pt", topsep="1pt", parskip="2pt"),
]
# The one-page fitter sweeps these compact presets (10pt → 9pt), tightest-last.
# Compact-first means most resumes fit on the very first compile and the output
# is dense-but-readable by default — no roomy multi-page attempts to discard.
FIT_DENSITIES = DENSITY_LEVELS[2:]
DEFAULT_DENSITY = DENSITY_LEVELS[2]


def render_tex(resume: TailoredResume, out_path: str | Path, *, density: dict | None = None) -> Path:
    """Fill the LaTeX template with tailored content and write the .tex file."""
    out_path = Path(out_path)
    template = _jinja_env().get_template("resume.tex.j2")
    rendered = template.render(
        r=resume, contact_line=_contact_line(resume), d=density or DEFAULT_DENSITY
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def count_pdf_pages(pdf_path: str | Path) -> int:
    """Number of pages in a PDF."""
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def _trim_one(resume: TailoredResume) -> TailoredResume | None:
    """Return a copy with the single lowest-priority piece of content removed,
    or None when nothing more can be trimmed.

    Removal order (least harmful first): an extra bullet from the fullest
    experience/project section (never below one bullet) → a trailing project →
    the summary. Work history entries, education, skills, and contact are never
    touched, so this can shorten a resume without ever creating gaps.
    """
    r = resume.model_copy(deep=True)

    fullest = None  # (list_ref, index, bullet_count)
    for section in (r.experience, r.projects):
        for i, item in enumerate(section):
            n = len(item.bullets)
            if n > 1 and (fullest is None or n > fullest[2]):
                fullest = (section, i, n)
    if fullest is not None:
        section, i, _ = fullest
        section[i].bullets.pop()
        return r

    if r.projects:
        r.projects.pop()
        return r

    if r.summary:
        r.summary = None
        return r

    return None


def build_one_page_pdf(
    resume: TailoredResume,
    tex_path: str | Path,
    *,
    engine: str | None = None,
    compile_fn=None,
    page_count_fn=None,
    max_trims: int = 30,
) -> Path:
    """Render + compile ``resume`` to a guaranteed single-page PDF at ``tex_path``.

    Sweeps the density presets (roomiest first) and returns the first that fits
    one page. If even the tightest overflows, trims lowest-priority content
    (see :func:`_trim_one`) until it fits. Returns best effort (fewest pages) if
    it somehow never fits. The ``*_fn`` hooks exist for testing without LaTeX.
    """
    tex_path = Path(tex_path)
    compile_fn = compile_fn or (lambda p: compile_pdf(p, engine=engine))
    page_count_fn = page_count_fn or count_pdf_pages

    pdf_path: Path | None = None
    for density in FIT_DENSITIES:
        render_tex(resume, tex_path, density=density)
        pdf_path = compile_fn(tex_path)
        if page_count_fn(pdf_path) <= 1:
            return pdf_path

    tightest = FIT_DENSITIES[-1]
    trimmed = resume
    for _ in range(max_trims):
        nxt = _trim_one(trimmed)
        if nxt is None:
            break
        trimmed = nxt
        render_tex(trimmed, tex_path, density=tightest)
        pdf_path = compile_fn(tex_path)
        if page_count_fn(pdf_path) <= 1:
            return pdf_path

    assert pdf_path is not None
    return pdf_path


def _latex_log_excerpt(output: str, max_lines: int = 30) -> str:
    """Pull the error-relevant lines out of a LaTeX log."""
    lines = output.splitlines()
    error_lines: list[str] = []
    capture = 0
    for line in lines:
        if line.startswith("!") or "Error" in line:
            capture = 4  # keep a few lines of context after each error
        if capture > 0:
            error_lines.append(line)
            capture -= 1
        if len(error_lines) >= max_lines:
            break
    return "\n".join(error_lines) if error_lines else "\n".join(lines[-max_lines:])


def compile_pdf(tex_path: str | Path, *, engine: str | None = None) -> Path:
    """Compile a .tex file to PDF using tectonic (preferred) or pdflatex.

    Raises :class:`LatexError` with a log excerpt on failure.
    """
    tex_path = Path(tex_path)
    if not tex_path.exists():
        raise LatexError(f"TeX file not found: {tex_path}")
    pdf_path = tex_path.with_suffix(".pdf")

    engine = engine or ("tectonic" if shutil.which("tectonic") else "pdflatex")
    if not shutil.which(engine):
        raise LatexError(
            "No LaTeX engine found. Install tectonic (brew install tectonic) "
            "or a TeX distribution providing pdflatex."
        )

    if engine == "tectonic":
        commands = [["tectonic", "--chatter", "minimal", tex_path.name]]
    else:
        # pdflatex needs two passes for stable output; -halt-on-error keeps logs short
        cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
        commands = [cmd, cmd]

    for cmd in commands:
        result = subprocess.run(
            cmd, cwd=tex_path.parent, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            excerpt = _latex_log_excerpt(result.stdout + "\n" + result.stderr)
            raise LatexError(
                f"LaTeX compilation failed ({' '.join(cmd)}):\n{excerpt}"
            )

    if not pdf_path.exists():
        raise LatexError(f"Compiler reported success but {pdf_path} was not produced.")
    return pdf_path
