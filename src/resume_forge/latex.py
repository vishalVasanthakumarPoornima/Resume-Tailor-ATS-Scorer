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


def escape_latex(value: str) -> str:
    """Escape LaTeX special characters: \\ % & _ # $ { } ~ ^."""
    if value is None:
        return ""
    out = str(value).replace("\\", "\x00")
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


def render_tex(resume: TailoredResume, out_path: str | Path) -> Path:
    """Fill the LaTeX template with tailored content and write the .tex file."""
    out_path = Path(out_path)
    template = _jinja_env().get_template("resume.tex.j2")
    rendered = template.render(r=resume, contact_line=_contact_line(resume))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


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
