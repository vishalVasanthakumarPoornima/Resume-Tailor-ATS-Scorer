"""ATS scorer logic tests (on extracted text — no PDFs, no network)."""

from resume_forge.ats import keyword_found, score_resume_text

GOOD_RESUME_TEXT = """Jordan Rivera
San Jose, CA | (408) 555-0192 | jordan.rivera@example.com

SUMMARY
Backend engineer with 3 years building Python microservices and REST APIs.

SKILLS
Languages: Python, SQL, Go
Tools: Docker, PostgreSQL, AWS, CI/CD

EXPERIENCE
Software Engineer — Acme Analytics, Jun 2022 - Present
Built REST APIs in Python serving 2M requests per day
Reduced query latency 40% by adding PostgreSQL indexes
Deployed microservices with Docker and automated CI/CD pipelines

EDUCATION
San Jose State University, B.S. in Computer Science, 2022
"""


class TestKeywordMatching:
    def test_word_boundary(self):
        assert keyword_found("expert in java and sql", "java")
        assert not keyword_found("javascript developer", "java")

    def test_symbol_terms(self):
        assert keyword_found("wrote c++ and c# services", "c++")
        assert keyword_found("wrote c++ and c# services", "c#")
        assert keyword_found("node.js apis", "node.js")

    def test_multiword(self):
        assert keyword_found("designed rest apis daily", "rest apis")


class TestScorer:
    def test_good_resume_scores_high(self, sample_job):
        report = score_resume_text(GOOD_RESUME_TEXT, 1, sample_job)
        assert report.score >= 80
        assert "kubernetes" in report.missing_keywords
        assert "python" not in report.missing_keywords

    def test_empty_text_scores_near_zero(self, sample_job):
        report = score_resume_text("", 1, sample_job)
        assert report.score < 15
        assert report.suggestions  # actionable feedback for a broken parse

    def test_missing_keywords_required_first(self, sample_job):
        text = "Jordan Rivera\nEXPERIENCE\nEDUCATION\nSKILLS\nBuilt things with Docker."
        report = score_resume_text(text, 1, sample_job)
        # required (weight 2) terms sort before preferred/keywords
        n_required_missing = len([k for k in ("python", "postgresql", "rest apis") if k in report.missing_keywords])
        assert report.missing_keywords[:n_required_missing] == [
            k for k in report.missing_keywords if k in ("python", "postgresql", "rest apis")
        ][:n_required_missing]

    def test_contact_detection(self, sample_job):
        report = score_resume_text(GOOD_RESUME_TEXT, 1, sample_job)
        assert report.subscores["contact"] == 10.0
        no_contact = score_resume_text("EXPERIENCE\nEDUCATION\nSKILLS\nworked hard", 1, sample_job)
        assert no_contact.subscores["contact"] == 0.0
        assert any("contact" in s.lower() for s in no_contact.suggestions)

    def test_sections_detected(self, sample_job):
        report = score_resume_text(GOOD_RESUME_TEXT, 1, sample_job)
        assert report.subscores["sections"] == 15.0

    def test_length_penalizes_many_pages(self, sample_job):
        one_page = score_resume_text(GOOD_RESUME_TEXT, 1, sample_job)
        four_pages = score_resume_text(GOOD_RESUME_TEXT, 4, sample_job)
        assert one_page.subscores["length"] > four_pages.subscores["length"]

    def test_subscores_sum_to_score(self, sample_job):
        report = score_resume_text(GOOD_RESUME_TEXT, 1, sample_job)
        assert abs(sum(report.subscores.values()) - report.score) < 0.01

    def test_no_keywords_in_job_gives_full_keyword_credit(self):
        from resume_forge.models import Job

        job = Job(title="Anything")
        report = score_resume_text(GOOD_RESUME_TEXT, 1, job)
        assert report.subscores["keywords"] == 40.0
