"""LaTeX escaping, template rendering, and one-page-fit tests."""

from pathlib import Path

from resume_forge.latex import (
    DENSITY_LEVELS,
    FIT_DENSITIES,
    _trim_one,
    build_one_page_pdf,
    escape_latex,
    render_tex,
)


class TestEscapeLatex:
    def test_all_special_characters(self):
        assert escape_latex("50% & $10 #1 a_b") == r"50\% \& \$10 \#1 a\_b"
        assert escape_latex("{curly}") == r"\{curly\}"
        assert escape_latex("~home") == r"\textasciitilde{}home"
        assert escape_latex("x^2") == r"x\textasciicircum{}2"

    def test_backslash_escaped_without_double_escaping(self):
        assert escape_latex(r"C:\temp") == r"C:\textbackslash{}temp"
        # A backslash followed by a special char must not merge into a command
        assert escape_latex(r"\&") == r"\textbackslash{}\&"

    def test_plain_text_untouched(self):
        assert escape_latex("Python, SQL and Go") == "Python, SQL and Go"

    def test_none_and_empty(self):
        assert escape_latex("") == ""
        assert escape_latex(None) == ""

    def test_unicode_punctuation_transliterated(self):
        # These chars silently vanish under T1 encoding if left as-is
        assert escape_latex("Engineer — Initech") == "Engineer --- Initech"
        assert escape_latex("2022–2024") == "2022--2024"
        assert escape_latex("Initech’s “growth”…") == "Initech's ``growth''..."


class TestRenderTex:
    def test_renders_escaped_content(self, sample_tailored, tmp_path):
        sample_tailored.experience[0].bullets.append("Cut costs 30% & improved p99_latency")
        tex_path = render_tex(sample_tailored, tmp_path / "resume.tex")
        content = tex_path.read_text()
        assert r"Cut costs 30\% \& improved p99\_latency" in content
        assert "Jordan Rivera" in content
        assert r"\begin{document}" in content and r"\end{document}" in content

    def test_optional_sections_omitted(self, sample_tailored, tmp_path):
        sample_tailored.certifications = []
        sample_tailored.projects = []
        content = render_tex(sample_tailored, tmp_path / "r.tex").read_text()
        assert "Certifications" not in content
        assert r"\section*{Projects}" not in content

    def test_no_unescaped_ampersand_from_content(self, sample_tailored, tmp_path):
        sample_tailored.experience[0].company = "Barnes & Noble"
        content = render_tex(sample_tailored, tmp_path / "r.tex").read_text()
        assert r"Barnes \& Noble" in content

    def test_single_sided_and_density_applied(self, sample_tailored, tmp_path):
        content = render_tex(sample_tailored, tmp_path / "r.tex", density=DENSITY_LEVELS[4]).read_text()
        assert "oneside" in content  # single-sided guaranteed
        assert "9pt,oneside" in content  # density level 4 is 9pt


class TestTrimOne:
    def test_removes_bullet_from_fullest_section_first(self, sample_tailored):
        sample_tailored.experience[0].bullets = ["a", "b", "c", "d"]
        sample_tailored.projects[0].bullets = ["x"]
        trimmed = _trim_one(sample_tailored)
        assert len(trimmed.experience[0].bullets) == 3  # fullest section trimmed
        assert len(trimmed.projects[0].bullets) == 1  # untouched

    def test_never_reduces_a_section_below_one_bullet(self, sample_tailored):
        sample_tailored.experience[0].bullets = ["only one"]
        sample_tailored.projects[0].bullets = ["p"]
        # nothing has >1 bullet -> falls through to dropping a trailing project
        trimmed = _trim_one(sample_tailored)
        assert trimmed.experience[0].bullets == ["only one"]
        assert trimmed.projects == []

    def test_drops_summary_last_then_returns_none(self, sample_tailored):
        sample_tailored.experience[0].bullets = ["one"]
        sample_tailored.projects = []
        assert sample_tailored.summary  # present
        trimmed = _trim_one(sample_tailored)
        assert trimmed.summary is None
        # now nothing left to trim (work history/education are never removed)
        assert _trim_one(trimmed) is None


class TestBuildOnePage:
    def _fake_compile(self, tex_path):
        pdf = Path(tex_path).with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-fake")
        return pdf

    def test_picks_first_density_that_fits(self, sample_tailored, tmp_path):
        pages = iter([2, 2, 1, 1, 1, 1])
        compiles = []

        def fake_compile(tex_path):
            compiles.append(Path(tex_path).read_text())
            return self._fake_compile(tex_path)

        pdf = build_one_page_pdf(
            sample_tailored, tmp_path / "r.tex",
            compile_fn=fake_compile, page_count_fn=lambda _p: next(pages),
        )
        assert pdf.exists()
        assert len(compiles) == 3  # stopped at the first fitting density
        # sweep is compact-first (FIT_DENSITIES); the 3rd level is 9pt
        marker = f"{FIT_DENSITIES[2]['cls_size']}pt,oneside"
        assert marker in compiles[2]

    def test_trims_content_when_all_densities_overflow(self, sample_tailored, tmp_path):
        sample_tailored.experience[0].bullets = [f"bullet {i}" for i in range(8)]
        sample_tailored.projects[0].bullets = ["p"]
        calls = {"n": 0}

        def fake_count(_pdf):
            calls["n"] += 1
            # every density level overflows, then fits after 3 trims
            return 2 if calls["n"] < len(FIT_DENSITIES) + 3 else 1

        pdf = build_one_page_pdf(
            sample_tailored, tmp_path / "r.tex",
            compile_fn=self._fake_compile, page_count_fn=fake_count,
        )
        final_items = (tmp_path / "r.tex").read_text().count(r"\item")
        assert final_items == 6  # 8 exp bullets - 3 trimmed = 5, + 1 project bullet
        assert calls["n"] == len(FIT_DENSITIES) + 3
