"""LaTeX escaping and template rendering tests."""

from resume_forge.latex import escape_latex, render_tex


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
