"""Optimize-loop behavior with stubbed stages (no LLM, no LaTeX, no PDFs)."""

from pathlib import Path

from resume_forge.models import ScoreReport
from resume_forge.pipeline import optimize

WEIGHTS = {"keywords": 40, "parseability": 15, "sections": 15, "bullets": 15, "contact": 10, "length": 5}


def _report(score: float, missing=None) -> ScoreReport:
    return ScoreReport(
        score=score,
        subscores={"keywords": score * 0.4},
        max_subscores=WEIGHTS,
        missing_keywords=missing or [],
        suggestions=["add keywords"],
    )


def _stub_stages(tmp_path, scores):
    """Build stub tailor/render/compile/score functions driven by a score sequence."""
    state = {"i": 0, "feedbacks": []}

    def tailor_fn(profile, job, feedback):
        state["feedbacks"].append(feedback)
        from resume_forge.models import TailoredResume

        return TailoredResume(**profile.model_dump())

    def render_fn(tailored, out_path):
        Path(out_path).write_text("tex")
        return Path(out_path)

    def compile_fn(tex_path):
        pdf = Path(tex_path).with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-fake")
        return pdf

    def score_fn(pdf_path, job):
        report = scores[min(state["i"], len(scores) - 1)]
        state["i"] += 1
        return report

    return state, dict(tailor_fn=tailor_fn, render_fn=render_fn, compile_fn=compile_fn, score_fn=score_fn)


class TestOptimize:
    def test_stops_when_target_reached(self, sample_profile, sample_job, tmp_path):
        state, stubs = _stub_stages(tmp_path, [_report(70, ["kubernetes"]), _report(85)])
        result = optimize(sample_profile, sample_job, tmp_path, target_score=80, llm=object(), **stubs)
        assert result.iterations == 2
        assert result.achieved_target
        assert result.report.score == 85
        # Second call received feedback derived from the first report
        assert state["feedbacks"][0] is None
        assert state["feedbacks"][1]["missing_keywords"] == ["kubernetes"]
        assert Path(result.pdf_path).name == "resume_tailored.pdf"
        assert Path(result.pdf_path).exists()

    def test_caps_iterations_and_returns_best(self, sample_profile, sample_job, tmp_path):
        reports = [_report(60), _report(72, ["go"]), _report(65)]
        state, stubs = _stub_stages(tmp_path, reports)
        result = optimize(
            sample_profile, sample_job, tmp_path, target_score=80, max_iterations=3, llm=object(), **stubs
        )
        assert result.iterations == 3
        assert not result.achieved_target
        assert result.report.score == 72  # best, not last
        assert any("did not reach the target" in note for note in result.notes)

    def test_writes_score_report_json(self, sample_profile, sample_job, tmp_path):
        _, stubs = _stub_stages(tmp_path, [_report(90)])
        optimize(sample_profile, sample_job, tmp_path, llm=object(), **stubs)
        assert (tmp_path / "score_report.json").exists()
