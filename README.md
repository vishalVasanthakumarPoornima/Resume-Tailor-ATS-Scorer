# resume-forge

Given a job posting (URL or pasted text) and your existing resume, **resume-forge** produces an
ATS-optimized, LaTeX-generated PDF resume tailored to that job, iterating against a **local ATS
scorer** until it scores ≥ 80 (configurable), and returns the PDF plus a JSON score report.

Three layers, all in this repo:

1. **`resume_forge`** — a core Python package with a clean programmatic API
2. **MCP server** — exposes the pipeline as tools so agents/Claude can call it
3. **CLI** — `resume-forge --job <url|-> --resume <path> --out <dir>`

**No fabrication, by design.** Tailoring = emphasis + rewording + keyword alignment. The tailoring
prompt forbids inventing employers, titles, dates, degrees, certifications, or metrics — and a
programmatic guard (`enforce_no_fabrication`) drops any employer/school/project/certification that
doesn't exist in your master resume, and always restores your real contact info.

## Setup

Requirements: Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and a LaTeX engine —
[`tectonic`](https://tectonic-typesetting.github.io/) is preferred (single binary, fetches packages
on demand); `pdflatex` works as a fallback.

```bash
brew install tectonic          # macOS; see tectonic docs for other platforms
git clone https://github.com/vishalVasanthakumarPoornima/Resume-Tailor-ATS-Scorer.git
cd Resume-Tailor-ATS-Scorer
uv sync --extra dev

cp .env.example .env           # then put your ANTHROPIC_API_KEY in it
export ANTHROPIC_API_KEY=sk-ant-...
```

The Anthropic API is used for (a) parsing your resume and the JD into structured data and
(b) tailoring content. Scoring is **fully local** — no network, no LLM.

## CLI

```bash
# From a job posting URL
uv run resume-forge --job "https://boards.greenhouse.io/acme/jobs/123" \
    --resume ~/Documents/resume.pdf --out output/

# From pasted JD text on stdin (most reliable — see "Scraping & ToS" below)
pbpaste | uv run resume-forge --job - --resume ~/Documents/resume.pdf --out output/

# URL with a text-file fallback in case the fetch fails
uv run resume-forge --job "https://..." --job-text jd.txt --resume resume.pdf

# Options
#   --target 80           target ATS score (default 80)
#   --max-iterations 5    cap on tailor→score rounds (default 5)
#   --model <id>          override the Anthropic model (default claude-opus-4-8)
#   --no-cache            re-parse the master resume, ignoring the cache
```

Outputs in `--out`: `resume_tailored.pdf`, `resume_tailored.tex`, `score_report.json`, plus
per-iteration `resume_iterN.{tex,pdf}` for inspection.

## Python API

```python
from resume_forge import forge

result = forge(
    "https://boards.greenhouse.io/acme/jobs/123",   # or the pasted JD text
    "~/Documents/resume.pdf",
    "output/",
    target_score=80,
)
print(result.report.score, result.report.missing_keywords)
print(result.pdf_path)
```

Or compose the pipeline steps yourself — each is independently importable and testable:

```python
from resume_forge import (
    ingest_master_resume,   # 1. resume file -> MasterProfile (cached as JSON)
    extract_job,            # 2. URL/text -> Job {title, required_skills, keywords, ...}
    tailor,                 # 3. (profile, job) -> TailoredResume  (no fabrication)
    render_tex,             # 4. TailoredResume -> .tex (LaTeX specials escaped)
    compile_pdf,            # 5. .tex -> .pdf via tectonic/pdflatex
    score_ats,              # 6. (pdf, job) -> ScoreReport {score, subscores, missing_keywords}
    optimize,               # 7. loop 3-6 until target score or max iterations
)

profile = ingest_master_resume("resume.pdf")
job = extract_job("https://...", job_description_text=open("jd.txt").read())
result = optimize(profile, job, "output/", target_score=80, max_iterations=5)
```

## MCP server

The server exposes: `tailor_resume` (full pipeline), `extract_job_posting`, `score_resume`
(score any existing PDF against a JD), and `ingest_resume`.

Register with Claude Code:

```bash
claude mcp add resume-forge -- uv run --directory /path/to/Resume-Tailor-ATS-Scorer resume-forge-mcp
```

Or in any MCP client config (stdio transport):

```json
{
  "mcpServers": {
    "resume-forge": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/Resume-Tailor-ATS-Scorer", "resume-forge-mcp"],
      "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
    }
  }
}
```

Example agent usage: *"Tailor `~/resume.pdf` to this posting: <paste JD>"* → the agent calls
`tailor_resume(job_url_or_text=..., master_resume_path=...)` and gets back the PDF path and report.

## ATS scoring (local, deterministic)

| Dimension     | Weight | What it measures |
|---------------|-------:|------------------|
| keywords      | 40 | JD skill/keyword coverage (required skills weigh 2×) |
| parseability  | 15 | clean text extraction from the PDF (no `(cid:)` junk, enough text/page) |
| sections      | 15 | standard Experience / Education / Skills headers |
| bullets       | 15 | action-verb starts + quantified results |
| contact       | 10 | detectable email + phone |
| length        |  5 | 1–2 pages, reasonable word count |

Report shape: `{score, subscores, max_subscores, missing_keywords, suggestions}`.
`missing_keywords` and the weakest subscores are fed back into the tailoring prompt on each
optimize iteration — while still respecting the no-fabrication rule, so keywords your profile
can't truthfully support will remain missing (the report's `notes` call this out).

## Scraping & Terms of Service — read this

Many job boards (**LinkedIn, Indeed, Glassdoor**, and others) **prohibit automated scraping in
their ToS** and actively block bots. resume-forge does a single polite HTTP GET with a normal
browser user agent — no headless-browser evasion, no login, no retry hammering. For those sites,
expect the fetch to fail; the supported path is to **paste the JD text** (`--job -` on stdin,
`--job-text file`, or `job_description_text` in the API/MCP tools). Direct company career pages
(Greenhouse, Lever, Ashby) usually fetch fine. A Playwright path for JS-heavy pages was
deliberately left out for now — say the word if you want it added.

## Development

```bash
uv run pytest            # scorer logic, LaTeX escaping, JD-fallback path, no-fabrication guard,
                         # optimize loop, ingest caching — all with mocked LLM + network
```

Layout:

```
src/resume_forge/
  models.py        # Pydantic models (MasterProfile, Job, TailoredResume, ScoreReport, ...)
  llm.py           # Anthropic wrapper: strict JSON via messages.parse + Pydantic validation
  ingest.py        # step 1: resume file -> MasterProfile, cached by content hash
  jobs.py          # step 2: URL/text -> Job (httpx + trafilatura/bs4, pasted-text fallback)
  tailor.py        # step 3: tailoring + no-fabrication guard
  latex.py         # steps 4-5: escaping, Jinja template rendering, tectonic/pdflatex
  ats.py           # step 6: local scorer
  pipeline.py      # steps 7-8: optimize loop + forge() entry point
  cli.py           # CLI
  mcp_server.py    # MCP server (FastMCP, stdio)
  templates/resume.tex.j2   # ATS-friendly template: single column, no graphics/tables
tests/             # pytest suite, fully offline
```
