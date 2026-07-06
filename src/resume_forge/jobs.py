"""Step 2: obtain the job description (URL or pasted text) and structure it.

A bad URL never hard-fails the pipeline: if fetching or content extraction
fails, we fall back to ``job_description_text`` when provided, or raise
:class:`JobFetchError` with actionable guidance to paste the JD.

Note on scraping: many job boards (LinkedIn, Indeed, Glassdoor) prohibit
automated scraping in their Terms of Service and actively block bots. This
module only does a single polite HTTP GET; for those sites, expect the fetch
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


def extract_job(
    url_or_text: str,
    *,
    job_description_text: str | None = None,
    llm: LLM | None = None,
    http_client: httpx.Client | None = None,
) -> Job:
    """Return a structured :class:`Job` from a URL or pasted job description.

    If ``url_or_text`` is a URL and fetching fails, ``job_description_text`` is
    used as the fallback source. If neither yields text, raises JobFetchError.
    """
    fetch_note: str | None = None
    if _looks_like_url(url_or_text):
        try:
            jd_text = fetch_job_posting(url_or_text, http_client=http_client)
        except JobFetchError as exc:
            if job_description_text and job_description_text.strip():
                jd_text = job_description_text
                fetch_note = str(exc)
            else:
                raise JobFetchError(
                    f"{exc}\n\nWorkaround: paste the job description text directly "
                    "(CLI: pass '-' as --job and pipe the text on stdin, or use --job-text; "
                    "API/MCP: pass job_description_text)."
                ) from exc
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
