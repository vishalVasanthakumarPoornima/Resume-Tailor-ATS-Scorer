"""MCP server exposing the resume-forge pipeline as tools.

Run with: `resume-forge-mcp` (stdio transport), or register with Claude Code:

    claude mcp add resume-forge -- uv run --directory /path/to/repo resume-forge-mcp
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .exceptions import ResumeForgeError

mcp = FastMCP(
    "resume-forge",
    instructions=(
        "Tools for tailoring a resume to a job posting and scoring it against a "
        "local ATS scorer. If a job URL cannot be fetched (JS-heavy page or bot "
        "wall), pass the pasted job description via job_description_text."
    ),
)


@mcp.tool()
def tailor_resume(
    job_url_or_text: str,
    master_resume_path: str,
    target_score: float = 80,
    output_dir: str = "",
    job_description_text: str = "",
    max_iterations: int = 5,
) -> dict:
    """Tailor a resume to a job posting and return the PDF path plus a score report.

    Runs the full pipeline: parse the master resume (cached), extract the job,
    tailor content (no fabrication), render LaTeX, compile to PDF, and iterate
    until the local ATS score reaches target_score (max max_iterations rounds).

    Args:
        job_url_or_text: Job posting URL or the pasted job description text.
        master_resume_path: Path to the candidate's existing resume (pdf/docx/tex/txt/md).
        target_score: Stop iterating once the ATS score reaches this value (0-100).
        output_dir: Where to write the PDF/TeX/report. Defaults to a temp directory.
        job_description_text: Fallback JD text used if the URL cannot be fetched.
        max_iterations: Cap on tailor/score rounds.
    """
    from .pipeline import forge

    out = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="resume_forge_"))
    try:
        result = forge(
            job_url_or_text,
            master_resume_path,
            out,
            target_score=target_score,
            max_iterations=max_iterations,
            job_description_text=job_description_text or None,
        )
    except ResumeForgeError as exc:
        return {"error": str(exc)}
    return result.model_dump()


@mcp.tool()
def extract_job_posting(url_or_text: str, job_description_text: str = "") -> dict:
    """Extract a job posting (URL or pasted text) into structured requirements.

    Returns {title, company, required_skills, preferred_skills, keywords,
    responsibilities}. If the URL cannot be fetched, job_description_text is
    used as the fallback source.
    """
    from .jobs import extract_job

    try:
        job = extract_job(url_or_text, job_description_text=job_description_text or None)
    except ResumeForgeError as exc:
        return {"error": str(exc)}
    return job.model_dump()


@mcp.tool()
def score_resume(pdf_path: str, job_url_or_text: str, job_description_text: str = "") -> dict:
    """Score an existing resume PDF against a job posting with the local ATS scorer.

    Returns {score, subscores, missing_keywords, suggestions}. Works on any
    resume PDF, not just ones produced by tailor_resume.
    """
    from .ats import score_ats
    from .jobs import extract_job

    try:
        job = extract_job(job_url_or_text, job_description_text=job_description_text or None)
        report = score_ats(pdf_path, job)
    except ResumeForgeError as exc:
        return {"error": str(exc)}
    except FileNotFoundError:
        return {"error": f"PDF not found: {pdf_path}"}
    return report.model_dump()


@mcp.tool()
def ingest_resume(path: str, use_cache: bool = True) -> dict:
    """Parse a master resume into a structured profile (contact, experience,
    education, skills). Cached by file content, so repeat calls are free."""
    from .ingest import ingest_master_resume

    try:
        profile = ingest_master_resume(path, use_cache=use_cache)
    except ResumeForgeError as exc:
        return {"error": str(exc)}
    return profile.model_dump()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
