#!/usr/bin/env bash
# start.sh — one command to run resume-forge locally.
#
#   ./start.sh              # build frontend if needed, serve everything on :8756
#   ./start.sh --port 9000  # use a different port
#   ./start.sh --dev        # also run the Vite dev server (hot reload) on :5173
#   ./start.sh --rebuild    # force a fresh frontend build
#
# In normal (non---dev) mode the Python server serves BOTH the API and the built
# UI, so one process = the whole app. That mirrors how it runs in production.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PORT="${PORT:-8756}"
DEV=0
REBUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --dev) DEV=1; shift ;;
    --rebuild) REBUILD=1; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done

info() { printf '\033[36m→\033[0m %s\n' "$1"; }
warn() { printf '\033[33m!\033[0m %s\n' "$1"; }
die()  { printf '\033[31m✗\033[0m %s\n' "$1" >&2; exit 1; }

# ── Prerequisites ────────────────────────────────────────────────────────────
command -v uv >/dev/null || die "uv is not installed. Install it: https://docs.astral.sh/uv/"
command -v tectonic >/dev/null || warn "tectonic not found — PDF compilation will fail. Install: brew install tectonic"

# ── Python deps ──────────────────────────────────────────────────────────────
# --inexact: install what's needed to RUN the app without pruning anything else
# already in the venv. Plain `uv sync` removes packages outside the default
# deps, which silently uninstalls the dev extras (pytest) on every start.
info "Syncing Python dependencies…"
uv sync --inexact --quiet

# ── Frontend build (skipped when already current, or in --dev mode) ───────────
if [[ $DEV -eq 0 ]]; then
  if [[ $REBUILD -eq 1 || ! -d frontend/dist ]]; then
    command -v npm >/dev/null || die "npm is not installed (needed to build the UI). Install Node.js."
    [[ -d frontend/node_modules ]] || { info "Installing frontend dependencies…"; npm install --prefix frontend --silent; }
    info "Building the frontend…"
    npm run build --prefix frontend --silent
  else
    info "Using existing frontend build (--rebuild to force a fresh one)."
  fi
fi

# ── LLM backend check (non-fatal: local Ollama is a valid fallback) ───────────
[[ -f .env ]] || { [[ -f .env.example ]] && cp .env.example .env && info "Created .env from .env.example."; }
if ! grep -qE '^[A-Z_]*(ZAI|GLM|GEMINI|GROQ|PUTER|OPENROUTER|CEREBRAS|ANTHROPIC|OPENAI)[A-Z_]*=..' .env 2>/dev/null; then
  warn "No cloud API key found in .env — falling back to local Ollama (slower)."
  warn "For fast, free inference add ONE key to .env, e.g. PUTER_API_KEY=… or ZAI_API_KEY=…"
fi

# ── Launch ───────────────────────────────────────────────────────────────────
if [[ $DEV -eq 1 ]]; then
  command -v npm >/dev/null || die "npm is not installed (needed for --dev). Install Node.js."
  [[ -d frontend/node_modules ]] || { info "Installing frontend dependencies…"; npm install --prefix frontend --silent; }
  info "Starting API on :$PORT and the Vite dev server on :5173…"
  # Make the Vite proxy point at whatever port the API is actually on.
  BACKEND_PORT="$PORT" npm run dev --prefix frontend &
  VITE_PID=$!
  # Stop the dev server when this script exits, however it exits.
  trap 'kill "$VITE_PID" 2>/dev/null || true' EXIT INT TERM
  uv run resume-forge-server --port "$PORT"
else
  info "resume-forge is starting on http://127.0.0.1:$PORT  (Ctrl-C to stop)"
  exec uv run resume-forge-server --port "$PORT"
fi
