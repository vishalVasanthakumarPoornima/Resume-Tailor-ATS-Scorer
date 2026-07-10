"""Steps 7-8: the optimize loop and the top-level ``forge`` entry point."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import ats as ats_module
from . import latex as latex_module
from . import tailor as tailor_module
from .ingest import ingest_master_resume
from .jobs import extract_job
from .llm import LLM, default_llm
from .models import ForgeResult, Job, MasterProfile, ScoreReport

DEFAULT_TARGET = 80.0
DEFAULT_MAX_ITERATIONS = 5


def _feedback_from_report(report: ScoreReport) -> dict:
    weak = {
        name: f"{value}/{report.max_subscores.get(name)}"
        for name, value in sorted(report.subscores.items(), key=lambda kv: kv[1])
        if report.max_subscores.get(name, 0) and value < report.max_subscores[name] * 0.8
    }
    return {
        "previous_score": report.score,
        "missing_keywords": report.missing_keywords[:15],
        "weakest_subscores": weak,
        "suggestions": report.suggestions,
    }


def optimize(
    profile: MasterProfile,
    job: Job,
    out_dir: str | Path,
    *,
    target_score: float = DEFAULT_TARGET,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    llm: LLM | None = None,
    tailor_fn=None,
    render_fn=None,
    compile_fn=None,
    build_fn=None,
    score_fn=None,
    on_progress=None,
) -> ForgeResult:
    """Tailor → render → compile → score, iterating on scorer feedback until
    ``target_score`` is reached or ``max_iterations`` is exhausted.

    The build step produces a guaranteed one-page PDF (density fit + trim). By
    default it uses :func:`resume_forge.latex.build_one_page_pdf`; passing the
    legacy ``render_fn`` + ``compile_fn`` composes them instead (used by tests).

    Returns the best iteration even if the target was never reached, with notes
    explaining what is still missing.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    llm = llm or default_llm()
    tailor_fn = tailor_fn or (lambda p, j, feedback: tailor_module.tailor(p, j, feedback=feedback, llm=llm))
    score_fn = score_fn or ats_module.score_ats

    if build_fn is None:
        if render_fn is not None or compile_fn is not None:
            _render = render_fn or latex_module.render_tex
            _compile = compile_fn or latex_module.compile_pdf
            build_fn = lambda tailored, tex_path: _compile(_render(tailored, tex_path))  # noqa: E731
        else:
            build_fn = latex_module.build_one_page_pdf

    notes: list[str] = []
    best: tuple[float, Path, Path, ScoreReport] | None = None
    feedback: dict | None = None
    iterations = 0

    for iteration in range(1, max_iterations + 1):
        iterations = iteration
        if on_progress:
            on_progress({"stage": "tailoring", "iteration": iteration, "max_iterations": max_iterations})
        tailored = tailor_fn(profile, job, feedback)
        _, violations = tailor_module.enforce_no_fabrication(tailored, profile)
        notes.extend(f"iteration {iteration}: {v}" for v in violations)

        tex_path = out_dir / f"resume_iter{iteration}.tex"
        pdf_path = build_fn(tailored, tex_path)
        report = score_fn(pdf_path, job)

        if best is None or report.score > best[0]:
            best = (report.score, Path(pdf_path), Path(tex_path), report)

        if on_progress:
            on_progress({"stage": "scored", "iteration": iteration, "score": report.score})

        if report.score >= target_score:
            break
        feedback = _feedback_from_report(report)

    assert best is not None
    best_score, best_pdf, best_tex, best_report = best

    final_pdf = out_dir / "resume_tailored.pdf"
    final_tex = out_dir / "resume_tailored.tex"
    shutil.copyfile(best_pdf, final_pdf)
    shutil.copyfile(best_tex, final_tex)

    achieved = best_score >= target_score
    if not achieved:
        notes.append(
            f"Best score {best_score} after {iterations} iteration(s) did not reach the "
            f"target of {target_score}. Remaining gaps are usually keywords the master "
            f"profile cannot truthfully claim: {', '.join(best_report.missing_keywords[:10]) or 'none'}."
        )

    result = ForgeResult(
        pdf_path=str(final_pdf),
        tex_path=str(final_tex),
        report=best_report,
        iterations=iterations,
        achieved_target=achieved,
        notes=notes,
    )
    (out_dir / "score_report.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


def forge(
    job_url_or_text: str,
    resume_path: str | Path,
    out_dir: str | Path,
    *,
    target_score: float = DEFAULT_TARGET,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    job_description_text: str | None = None,
    llm: LLM | None = None,
    use_browser: bool = True,
    cover_letter: bool = False,
) -> ForgeResult:
    """End-to-end: ingest resume + extract job + optimize (+ optional cover letter)."""
    llm = llm or default_llm()
    profile = ingest_master_resume(resume_path, llm=llm)
    job = extract_job(
        job_url_or_text,
        job_description_text=job_description_text,
        llm=llm,
        use_browser=use_browser,
    )
    result = optimize(
        profile,
        job,
        out_dir,
        target_score=target_score,
        max_iterations=max_iterations,
        llm=llm,
    )
    if cover_letter:
        from .cover import generate_cover_letter

        pdf_path, tex_path = generate_cover_letter(profile, job, out_dir, llm=llm)
        result = result.model_copy(
            update={"cover_letter_pdf_path": str(pdf_path), "cover_letter_tex_path": str(tex_path)}
        )
        (Path(out_dir) / "score_report.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
    return result
