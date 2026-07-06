"""FastAPI backend for the resume-forge web UI.

Jobs run in a background thread (the pipeline takes ~30s on a local model);
the frontend polls GET /api/jobs/{id} for per-stage progress, then downloads
the PDF. State is in-memory — this is a single-user local tool, not a service.

Run: `resume-forge-server` (default http://127.0.0.1:8000).
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .exceptions import ResumeForgeError
from .ingest import ingest_master_resume
from .jobs import extract_job
from .llm import default_llm
from .pipeline import optimize

SAMPLE_RESUME = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "sample_resume.txt"

app = FastAPI(title="resume-forge", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def _update(job_id: str, **fields) -> None:
    with JOBS_LOCK:
        JOBS[job_id].update(fields, updated_at=time.time())


def _run_job(
    job_id: str,
    resume_path: Path,
    job_input: str,
    job_text_fallback: str | None,
    target: float,
    max_iterations: int,
    workdir: Path,
) -> None:
    def on_progress(event: dict) -> None:
        if event["stage"] == "tailoring":
            _update(
                job_id,
                stage="tailoring",
                detail=f"Tailoring — iteration {event['iteration']} of {event['max_iterations']}",
                iteration=event["iteration"],
            )
        elif event["stage"] == "scored":
            _update(
                job_id,
                stage="scoring",
                detail=f"Iteration {event['iteration']} scored {event['score']}/100",
                last_score=event["score"],
            )

    try:
        llm = default_llm()
        _update(job_id, stage="ingest", detail="Parsing your resume into a structured profile")
        profile = ingest_master_resume(resume_path, llm=llm)

        _update(job_id, stage="job", detail="Analyzing the job posting")
        job = extract_job(job_input, job_description_text=job_text_fallback, llm=llm)

        result = optimize(
            profile,
            job,
            workdir,
            target_score=target,
            max_iterations=max_iterations,
            llm=llm,
            on_progress=on_progress,
        )
        _update(
            job_id,
            status="done",
            stage="done",
            detail="Finished",
            result=result.model_dump(),
            job_title=job.title,
            job_company=job.company,
        )
    except ResumeForgeError as exc:
        _update(job_id, status="error", stage="error", detail=str(exc))
    except Exception as exc:  # surface unexpected failures to the UI instead of hanging
        _update(job_id, status="error", stage="error", detail=f"Unexpected error: {exc}")


@app.post("/api/jobs")
async def create_job(
    resume: UploadFile | None = None,
    job_input: str = Form(...),
    job_text_fallback: str = Form(""),
    target: float = Form(80),
    max_iterations: int = Form(5),
    use_sample_resume: bool = Form(False),
):
    if not job_input.strip():
        raise HTTPException(422, "job_input must be a job posting URL or the pasted JD text")

    workdir = Path(tempfile.mkdtemp(prefix="resume_forge_web_"))
    if use_sample_resume:
        resume_path = workdir / "resume.txt"
        shutil.copyfile(SAMPLE_RESUME, resume_path)
    elif resume is not None and resume.filename:
        suffix = Path(resume.filename).suffix.lower() or ".txt"
        if suffix not in (".pdf", ".docx", ".tex", ".txt", ".md"):
            raise HTTPException(422, f"Unsupported resume format '{suffix}'")
        resume_path = workdir / f"resume{suffix}"
        resume_path.write_bytes(await resume.read())
    else:
        raise HTTPException(422, "Attach a resume file (or set use_sample_resume)")

    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "status": "running",
            "stage": "queued",
            "detail": "Starting",
            "target": target,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    threading.Thread(
        target=_run_job,
        args=(job_id, resume_path, job_input, job_text_fallback or None, target, max_iterations, workdir),
        daemon=True,
    ).start()
    return {"job_id": job_id}


def _get_job(job_id: str) -> dict:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job id")
    return job


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return _get_job(job_id)


def _artifact(job_id: str, key: str, media_type: str, filename: str) -> FileResponse:
    job = _get_job(job_id)
    result = job.get("result")
    if not result:
        raise HTTPException(409, "Job has not finished yet")
    path = Path(result[key])
    if not path.exists():
        raise HTTPException(410, "Artifact no longer exists on disk")
    return FileResponse(path, media_type=media_type, filename=filename)


@app.get("/api/jobs/{job_id}/pdf")
def job_pdf(job_id: str):
    return _artifact(job_id, "pdf_path", "application/pdf", "resume_tailored.pdf")


@app.get("/api/jobs/{job_id}/tex")
def job_tex(job_id: str):
    return _artifact(job_id, "tex_path", "application/x-tex", "resume_tailored.tex")


@app.get("/api/jobs/{job_id}/report")
def job_report(job_id: str):
    job = _get_job(job_id)
    result = job.get("result")
    if not result:
        raise HTTPException(409, "Job has not finished yet")
    report_path = Path(result["pdf_path"]).parent / "score_report.json"
    if not report_path.exists():
        raise HTTPException(410, "Report no longer exists on disk")
    return FileResponse(report_path, media_type="application/json", filename="score_report.json")


@app.get("/api/health")
def health():
    info: dict = {"status": "ok"}
    try:
        llm = default_llm()
        info["backend"] = type(llm).__name__.removesuffix("LLM").lower()
        info["model"] = getattr(llm, "model", None)
    except ResumeForgeError as exc:
        info["status"] = "degraded"
        info["llm_error"] = str(exc)
    return info


# Production mode: if the frontend has been built (cd frontend && npm run build),
# serve it from this process so `resume-forge-server` alone runs the whole app.
# Mounted last so /api/* routes always win.
FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")


def main() -> None:
    import argparse
    import os

    import uvicorn

    parser = argparse.ArgumentParser(prog="resume-forge-server")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 8000)),
        help="Port to listen on (default: $PORT or 8000)",
    )
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
