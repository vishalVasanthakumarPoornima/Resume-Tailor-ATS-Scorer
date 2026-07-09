"""resume-forge: ATS-optimized, LaTeX-generated resume tailoring.

Programmatic API:

    from resume_forge import forge
    result = forge("https://jobs.example.com/123", "resume.pdf", "output/")
    print(result.report.score, result.pdf_path)

Or compose the individual pipeline steps: ingest_master_resume, extract_job,
tailor, render_tex, compile_pdf, score_ats, optimize.
"""

from .ats import score_ats, score_resume_text
from .cover import generate_cover_letter, render_cover_letter_tex, write_cover_letter
from .exceptions import (
    IngestError,
    JobFetchError,
    LatexError,
    LLMError,
    ResumeForgeError,
)
from .ingest import extract_resume_text, ingest_master_resume
from .jobs import extract_job, fetch_job_posting, fetch_job_posting_browser
from .latex import compile_pdf, escape_latex, render_tex
from .llm import LLM, AnthropicLLM, OllamaLLM, default_llm
from .models import (
    Contact,
    CoverLetter,
    EducationItem,
    ExperienceItem,
    ForgeResult,
    Job,
    MasterProfile,
    ProjectItem,
    ScoreReport,
    SkillGroup,
    TailoredResume,
)
from .pipeline import forge, optimize
from .tailor import enforce_no_fabrication, tailor

__version__ = "0.1.0"

__all__ = [
    "AnthropicLLM",
    "Contact",
    "CoverLetter",
    "EducationItem",
    "ExperienceItem",
    "ForgeResult",
    "IngestError",
    "Job",
    "JobFetchError",
    "LLM",
    "LLMError",
    "LatexError",
    "MasterProfile",
    "OllamaLLM",
    "ProjectItem",
    "ResumeForgeError",
    "ScoreReport",
    "SkillGroup",
    "TailoredResume",
    "compile_pdf",
    "default_llm",
    "enforce_no_fabrication",
    "escape_latex",
    "extract_job",
    "extract_resume_text",
    "fetch_job_posting",
    "fetch_job_posting_browser",
    "forge",
    "generate_cover_letter",
    "ingest_master_resume",
    "optimize",
    "render_cover_letter_tex",
    "render_tex",
    "score_ats",
    "write_cover_letter",
    "score_resume_text",
    "tailor",
]
