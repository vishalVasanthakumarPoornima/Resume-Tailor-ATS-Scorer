"""Job extraction tests: URL fallback path with mocked network and LLM."""

import httpx
import pytest

from resume_forge.exceptions import JobFetchError
from resume_forge.jobs import extract_job, fetch_job_posting
from resume_forge.models import Job
from tests.conftest import FakeLLM

JD_TEXT = """Backend Engineer at Initech.
We are looking for an engineer with strong Python and PostgreSQL experience
to design and build REST APIs and microservices. Docker and Kubernetes a plus.
You will own services end to end and improve our CI/CD pipelines.
"""


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _fake_llm(sample_job) -> FakeLLM:
    return FakeLLM({Job: sample_job})


class TestFetch:
    def test_fetch_error_raises_jobfetcherror(self):
        def handler(request):
            return httpx.Response(403, text="Forbidden")

        with pytest.raises(JobFetchError, match="Could not fetch"):
            fetch_job_posting("https://jobs.example.com/1", http_client=_mock_client(handler))

    def test_junk_page_raises_jobfetcherror(self):
        def handler(request):
            return httpx.Response(200, text="<html><body><nav>Home</nav></body></html>")

        with pytest.raises(JobFetchError, match="could not extract"):
            fetch_job_posting("https://jobs.example.com/1", http_client=_mock_client(handler))

    def test_good_page_returns_text(self):
        html = f"<html><body><article><h1>Backend Engineer</h1><p>{JD_TEXT * 3}</p></article></body></html>"

        def handler(request):
            return httpx.Response(200, text=html)

        text = fetch_job_posting("https://jobs.example.com/1", http_client=_mock_client(handler))
        assert "PostgreSQL" in text


class TestExtractJob:
    def test_pasted_text_skips_network(self, sample_job):
        llm = _fake_llm(sample_job)
        job = extract_job(JD_TEXT, llm=llm)
        assert job.title == "Backend Engineer"
        assert JD_TEXT.strip()[:40] in llm.calls[0]["prompt"]

    def test_bad_url_falls_back_to_pasted_text(self, sample_job):
        def handler(request):
            return httpx.Response(500)

        llm = _fake_llm(sample_job)
        job = extract_job(
            "https://jobs.example.com/1",
            job_description_text=JD_TEXT,
            llm=llm,
            http_client=_mock_client(handler),
        )
        assert job.required_skills == ["Python", "PostgreSQL", "REST APIs"]
        # the JD text (not the failed URL) is what got analyzed
        assert "PostgreSQL" in llm.calls[0]["prompt"]

    def test_bad_url_without_fallback_raises_with_guidance(self, sample_job):
        def handler(request):
            return httpx.Response(500)

        with pytest.raises(JobFetchError, match="paste the job description"):
            extract_job(
                "https://jobs.example.com/1",
                llm=_fake_llm(sample_job),
                http_client=_mock_client(handler),
            )

    def test_too_short_pasted_text_rejected(self, sample_job):
        with pytest.raises(JobFetchError, match="too short"):
            extract_job("python dev", llm=_fake_llm(sample_job))


class TestBrowserFallback:
    """The Playwright path is exercised via monkeypatching — no real browser in CI."""

    def _failing_client(self):
        return _mock_client(lambda request: httpx.Response(500))

    def test_browser_recovers_js_heavy_page(self, sample_job, monkeypatch):
        import resume_forge.jobs as jobs_module

        monkeypatch.setattr(jobs_module, "_browser_available", lambda: True)
        monkeypatch.setattr(jobs_module, "fetch_job_posting_browser", lambda url: JD_TEXT)

        llm = _fake_llm(sample_job)
        job = extract_job("https://jobs.example.com/1", llm=llm, http_client=self._failing_client())
        assert job.title == "Backend Engineer"
        assert "PostgreSQL" in llm.calls[0]["prompt"]  # browser text was analyzed

    def test_browser_failure_falls_through_to_pasted_text(self, sample_job, monkeypatch):
        import resume_forge.jobs as jobs_module

        def browser_fails(url):
            raise JobFetchError("bot wall")

        monkeypatch.setattr(jobs_module, "_browser_available", lambda: True)
        monkeypatch.setattr(jobs_module, "fetch_job_posting_browser", browser_fails)

        job = extract_job(
            "https://jobs.example.com/1",
            job_description_text=JD_TEXT,
            llm=_fake_llm(sample_job),
            http_client=self._failing_client(),
        )
        assert job.title == "Backend Engineer"

    def test_use_browser_false_skips_playwright(self, sample_job, monkeypatch):
        import resume_forge.jobs as jobs_module

        def must_not_be_called(url):  # pragma: no cover
            raise AssertionError("browser fetch should have been skipped")

        monkeypatch.setattr(jobs_module, "_browser_available", lambda: True)
        monkeypatch.setattr(jobs_module, "fetch_job_posting_browser", must_not_be_called)

        with pytest.raises(JobFetchError):
            extract_job(
                "https://jobs.example.com/1",
                llm=_fake_llm(sample_job),
                http_client=self._failing_client(),
                use_browser=False,
            )

    def test_playwright_missing_gives_install_hint(self, sample_job, monkeypatch):
        import resume_forge.jobs as jobs_module

        monkeypatch.setattr(jobs_module, "_browser_available", lambda: False)
        with pytest.raises(JobFetchError, match="uv sync --extra browser"):
            extract_job(
                "https://jobs.example.com/1",
                llm=_fake_llm(sample_job),
                http_client=self._failing_client(),
            )
