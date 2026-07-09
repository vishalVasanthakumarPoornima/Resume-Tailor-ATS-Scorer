"""Thin CLI wrapper: resume-forge --job <url|-> --resume <path> --out <dir> [--target 80]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .exceptions import ResumeForgeError
from .pipeline import DEFAULT_MAX_ITERATIONS, DEFAULT_TARGET, forge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resume-forge",
        description="Tailor a resume to a job posting and score it with a local ATS scorer.",
    )
    parser.add_argument(
        "--job",
        required=True,
        help="Job posting URL, pasted JD text, or '-' to read the JD from stdin.",
    )
    parser.add_argument(
        "--job-text",
        metavar="FILE",
        help="File containing the JD text; used as fallback if --job is a URL that fails to fetch.",
    )
    parser.add_argument("--resume", required=True, help="Path to your master resume (pdf/docx/tex/txt/md).")
    parser.add_argument("--out", default="output", help="Output directory (default: ./output).")
    parser.add_argument("--target", type=float, default=DEFAULT_TARGET, help="Target ATS score (default: 80).")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help="Max tailor/score iterations (default: 5).",
    )
    parser.add_argument(
        "--backend",
        choices=["ollama", "anthropic"],
        help="LLM backend (default: env RESUME_FORGE_LLM_BACKEND, or local ollama).",
    )
    parser.add_argument(
        "--model",
        help="Model id for the backend (e.g. 'llama3.1:8b-instruct-q4_K_M' or 'claude-opus-4-8').",
    )
    parser.add_argument(
        "--cover-letter",
        action="store_true",
        help="Also generate a matching cover letter PDF.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Skip the headless-browser fallback for JS-heavy job pages.",
    )
    parser.add_argument("--no-cache", action="store_true", help="Re-parse the master resume, ignoring the cache.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    job_input = args.job
    if job_input == "-":
        job_input = sys.stdin.read()
        if not job_input.strip():
            print("error: --job was '-' but stdin was empty", file=sys.stderr)
            return 2

    job_text_fallback = None
    if args.job_text:
        job_text_fallback = Path(args.job_text).read_text(encoding="utf-8")

    from .llm import default_llm

    try:
        llm = default_llm(args.backend, args.model)
    except ResumeForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.no_cache:
        # forge() caches by file content; bypass by ingesting explicitly first
        from .ingest import ingest_master_resume

        ingest_master_resume(args.resume, llm=llm, use_cache=False)

    try:
        result = forge(
            job_input,
            args.resume,
            args.out,
            target_score=args.target,
            max_iterations=args.max_iterations,
            job_description_text=job_text_fallback,
            llm=llm,
            use_browser=not args.no_browser,
            cover_letter=args.cover_letter,
        )
    except ResumeForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = result.report
    status = "TARGET REACHED" if result.achieved_target else "BELOW TARGET"
    print(f"\nATS score: {report.score}/100  ({status}, {result.iterations} iteration(s))\n")
    for name, value in report.subscores.items():
        print(f"  {name:<14}{value:>6}/{report.max_subscores[name]:g}")
    if report.missing_keywords:
        print(f"\nStill missing keywords: {', '.join(report.missing_keywords[:10])}")
    for suggestion in report.suggestions:
        print(f"  - {suggestion}")
    for note in result.notes:
        print(f"note: {note}")
    print(f"\nPDF:    {result.pdf_path}")
    print(f"TeX:    {result.tex_path}")
    if result.cover_letter_pdf_path:
        print(f"Cover:  {result.cover_letter_pdf_path}")
    print(f"Report: {Path(result.pdf_path).parent / 'score_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
