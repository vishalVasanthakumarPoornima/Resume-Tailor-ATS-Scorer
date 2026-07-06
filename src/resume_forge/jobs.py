"""Step 2: obtain the job description (URL or pasted text) and structure it.

A bad URL never hard-fails the pipeline: if fetching or content extraction
fails, we fall back to ``job_description_text`` when provided, or raise
:class:`JobFetchError` with actionable guidance to paste the JD.

Fallback chain for URLs: plain HTTP GET → headless browser (optional Playwright
extra, for JS-rendered pages) → pasted text.

Note on scraping: many job boards (LinkedIn, Indeed, Glassdoor) prohibit
automated scraping in their Terms of Service and actively block bots. This
module does a single polite fetch per attempt — no login automation, no
CAPTCHA/bot-wall evasion, no retry hammering. For those sites, expect fetching
to fail and use the pasted-text fallback instead.
"""

from __future__ import annotations

import re

import httpx

from .exceptions import JobFetchError
from .llm import LLM, default_llm
from .models import Job

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Below this many characters we assume extraction returned nav/junk, not a JD.
MIN_JD_CHARS = 300

JOB_SYSTEM = """You are an expert at analyzing job postings for ATS optimization.
Extract the posting into the provided schema.

Guidance:
- required_skills: hard requirements (languages, frameworks, tools, years of experience).
- preferred_skills: nice-to-haves ("bonus", "preferred", "a plus").
- keywords: other ATS-relevant terms a recruiter would search for (methodologies,
  domain terms, certifications, cloud platforms) not already listed as skills.
- Keep each skill/keyword short (1-4 words), as it appears in the posting.
- Do NOT include experience durations ("2+ years", "5 years of...") as skills —
  extract the underlying skill itself (e.g. "Python", not "2+ years of Python").
- Deduplicate across lists; do not repeat a required skill under keywords."""


def _looks_like_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value.strip(), re.IGNORECASE))


def _extract_main_text(html: str) -> str:
    """Pull readable text out of HTML: trafilatura first, BeautifulSoup fallback."""
    try:
        import trafilatura

        extracted = trafilatura.extract(html, include_comments=False, include_tables=True)
        if extracted and len(extracted.strip()) >= MIN_JD_CHARS:
            return extracted.strip()
    except Exception:
        pass

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    return text


def fetch_job_posting_browser(url: str, *, timeout: float = 30.0) -> str:
    """Fetch a JS-heavy job posting with a headless browser (optional Playwright path).

    Requires the ``browser`` extra: ``uv sync --extra browser`` then
    ``uv run playwright install chromium``.
    """
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise JobFetchError(
            "Playwright is not installed. Install the browser extra "
            "(uv sync --extra browser && uv run playwright install chromium) "
            "or paste the job description text instead."
        ) from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                page.wait_for_timeout(2000)  # give client-side rendering a moment
                html = page.content()
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise JobFetchError(f"Headless browser could not load {url}: {exc}") from exc

    text = _extract_main_text(html)
    if len(text) < MIN_JD_CHARS:
        raise JobFetchError(
            f"Rendered {url} in a headless browser but still could not extract a usable "
            f"job description (got {len(text)} characters — likely behind a login or bot wall)."
        )
    return text


def fetch_job_posting(url: str, *, timeout: float = 20.0, http_client: httpx.Client | None = None) -> str:
    """Fetch a job posting URL and return its readable text.

    Raises :class:`JobFetchError` if the page can't be fetched or the extracted
    text is too short to plausibly be a job description.
    """
    client = http_client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout
    )
    owns_client = http_client is None
    try:
        response = client.get(url)
        response.raise_for_status()
        html = response.text
    except httpx.HTTPError as exc:
        raise JobFetchError(f"Could not fetch {url}: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    text = _extract_main_text(html)
    if len(text) < MIN_JD_CHARS:
        raise JobFetchError(
            f"Fetched {url} but could not extract a usable job description "
            f"(got {len(text)} characters — likely a JavaScript-rendered page or a bot wall)."
        )
    return text


def _browser_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def extract_job(
    url_or_text: str,
    *,
    job_description_text: str | None = None,
    llm: LLM | None = None,
    http_client: httpx.Client | None = None,
    use_browser: bool = True,
) -> Job:
    """Return a structured :class:`Job` from a URL or pasted job description.

    Fallback chain for URLs: plain HTTP fetch → headless browser (if Playwright
    is installed and ``use_browser``) → ``job_description_text``. If nothing
    yields text, raises JobFetchError with guidance. Pasted text is used as-is.
    """
    fetch_note: str | None = None
    if _looks_like_url(url_or_text):
        jd_text = None
        try:
            jd_text = fetch_job_posting(url_or_text, http_client=http_client)
        except JobFetchError as exc:
            fetch_note = str(exc)
            if use_browser and _browser_available():
                try:
                    jd_text = fetch_job_posting_browser(url_or_text)
                    fetch_note += " — recovered with the headless-browser fallback."
                except JobFetchError as browser_exc:
                    fetch_note += f" Browser fallback also failed: {browser_exc}"
        if jd_text is None:
            if job_description_text and job_description_text.strip():
                jd_text = job_description_text
            else:
                raise JobFetchError(
                    f"{fetch_note}\n\nWorkaround: paste the job description text directly "
                    "(CLI: pass '-' as --job and pipe the text on stdin, or use --job-text; "
                    "API/MCP: pass job_description_text). For JS-heavy pages, install the "
                    "browser extra: uv sync --extra browser && uv run playwright install chromium."
                )
    else:
        jd_text = url_or_text
        if len(jd_text.strip()) < 50:
            raise JobFetchError(
                "The provided job description text is too short to analyze. "
                "Paste the full posting."
            )

    llm = llm or default_llm()
    job = llm.parse(
        system=JOB_SYSTEM,
        prompt=f"Extract this job posting:\n\n<job_posting>\n{jd_text}\n</job_posting>",
        output_type=Job,
    )
    if fetch_note:
        # surfaced by callers that log; the Job model itself stays clean
        job.__dict__.setdefault("_fetch_note", fetch_note)
    return job
