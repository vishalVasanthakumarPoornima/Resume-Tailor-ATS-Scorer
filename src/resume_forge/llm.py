"""LLM backends for structured (Pydantic-validated) output.

Three backends implement the same ``LLM`` protocol:

- :class:`OpenAICompatLLM` — any OpenAI-compatible chat-completions API. Presets
  for the FREE GLM models from z.ai / Zhipu (get a key at https://z.ai or
  https://open.bigmodel.cn). Much faster than a local model: seconds per call.
- :class:`OllamaLLM` — a local model via the Ollama server. Structured output is
  enforced with Ollama's JSON-schema ``format`` parameter. No API key, fully
  offline.
- :class:`AnthropicLLM` — the Anthropic API via ``messages.parse``.

Selection (``default_llm``): explicit ``RESUME_FORGE_LLM_BACKEND`` wins
(``zai | glm | openai | ollama | anthropic``); otherwise ``zai`` is auto-picked
when a ``ZAI_API_KEY``/``GLM_API_KEY`` is set, falling back to local Ollama.
Model via ``RESUME_FORGE_MODEL``. Tests inject fakes through the protocol.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .exceptions import LLMError

T = TypeVar("T", bound=BaseModel)


def load_env_file(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (no overrides).

    Tiny by design — enough for API keys without a python-dotenv dependency.
    """
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
# Tried in order when RESUME_FORGE_MODEL is unset; falls back to any installed model.
# Light-first: qwen2.5:3b (~2 GB) handles schema-constrained JSON well and leaves
# the rest of the machine usable; heavier models only if no light one is installed.
PREFERRED_OLLAMA_MODELS = (
    "qwen2.5:3b",
    "llama3.2:3b",
    "qwen2.5:7b",
    "llama3.1",
    "qwen2.5:14b",
    "mistral",
    "llama3",
)

# Quality-first order for the ONE-TIME resume ingest (result is cached, and the
# model is unloaded immediately after via keep_alive=0, so a heavier model here
# costs seconds once — not sustained memory or per-job latency).
INGEST_PREFERRED_OLLAMA_MODELS = (
    "qwen2.5:14b",
    "qwen2.5:7b",
    "llama3.1",
    "llama3",
    "mistral",
    "qwen2.5:3b",
    "llama3.2:3b",
)

# OpenAI-compatible cloud providers. All expose POST /chat/completions and
# json_object output mode, so one backend serves them all. The listed free tiers
# are plenty for resume-forge (a full run with the optimize loop is ~10 calls).
# Each takes seconds per call vs. tens of seconds for a local model.
OPENAI_COMPAT_PROVIDERS: dict[str, dict] = {
    "zai": {
        "label": "z.ai (GLM)",
        "base_url": "https://api.z.ai/api/paas/v4",
        "model": "glm-4.5-flash",  # free; glm-4.7-flash also free
        "key_envs": ("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY"),
        "signup": "https://z.ai/model-api",
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "key_envs": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "signup": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_envs": ("GROQ_API_KEY",),
        "signup": "https://console.groq.com/keys",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "z-ai/glm-4.5-flash",
        "key_envs": ("OPENROUTER_API_KEY",),
        "signup": "https://openrouter.ai/keys",
    },
    "cerebras": {
        "label": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b",
        "key_envs": ("CEREBRAS_API_KEY",),
        "signup": "https://cloud.cerebras.ai",
    },
    # Generic escape hatch: any OpenAI-compatible endpoint. Requires
    # RESUME_FORGE_OPENAI_BASE_URL + RESUME_FORGE_MODEL (+ a key env).
    "openai": {
        "label": "OpenAI-compatible",
        "base_url": None,
        "model": None,
        "key_envs": ("OPENAI_API_KEY", "RESUME_FORGE_API_KEY"),
        "signup": "",
    },
}

# Priority order for auto-detecting a backend from a present API key. z.ai first
# (the documented default), then the other strong free tiers.
_AUTODETECT_ORDER = ("zai", "gemini", "groq", "openrouter", "cerebras")

# Friendly aliases accepted for RESUME_FORGE_LLM_BACKEND / --backend.
_PROVIDER_ALIASES = {"glm": "zai", "zhipu": "zai", "z.ai": "zai", "google": "gemini"}

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _find_api_key(envs: tuple[str, ...]) -> str | None:
    for name in envs:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _extract_json(content: str) -> str:
    """Pull a JSON object out of a model reply that may wrap it in prose/fences."""
    content = content.strip()
    fenced = _JSON_FENCE_RE.search(content)
    if fenced:
        content = fenced.group(1).strip()
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        return content[start : end + 1]
    return content


class LLM(Protocol):
    """Anything that can turn a prompt into a validated Pydantic model."""

    def parse(self, *, system: str, prompt: str, output_type: type[T]) -> T:  # pragma: no cover
        ...


def _require_all_properties(schema: object) -> None:
    """Recursively mark every object property as required, in place.

    Ollama's grammar-constrained decoding emits JSON keys in schema declaration
    order and can only SKIP optional keys, never revisit them. If a resume lists
    its sections in a different order than the schema (e.g. Education first),
    the model skips everything "before" that point and silently drops skills /
    experience / projects. Forcing every key to be present eliminates that
    entire failure class — models emit empty arrays/nulls when truly absent.
    """
    if isinstance(schema, dict):
        if isinstance(schema.get("properties"), dict):
            schema["required"] = list(schema["properties"].keys())
        for value in schema.values():
            _require_all_properties(value)
    elif isinstance(schema, list):
        for value in schema:
            _require_all_properties(value)


class OllamaLLM:
    """Local LLM via the Ollama server (default backend).

    Uses ``POST /api/chat`` with ``format=<json schema>`` so the model is
    constrained to the schema, then validates with Pydantic. On validation
    failure the error is fed back and the call retried (``max_retries``).
    """

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        *,
        num_ctx: int = 8192,
        max_retries: int = 2,
        timeout: float = 600.0,
        keep_alive: str | int | None = None,
        prefer: tuple[str, ...] = PREFERRED_OLLAMA_MODELS,
        http_client=None,
    ):
        import httpx

        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST).rstrip("/")
        if not self.host.startswith("http"):
            self.host = f"http://{self.host}"
        self.num_ctx = int(os.environ.get("RESUME_FORGE_OLLAMA_NUM_CTX", num_ctx))
        self.max_retries = max_retries
        self.keep_alive = keep_alive
        self._prefer = prefer
        self._client = http_client or httpx.Client(base_url=self.host, timeout=timeout)
        self.model = model or os.environ.get("RESUME_FORGE_MODEL") or self._pick_model()

    def _installed_models(self) -> list[str]:
        import httpx

        try:
            response = self._client.get("/api/tags")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Could not reach the Ollama server at {self.host}: {exc}\n"
                "Is Ollama running? Install from https://ollama.com and start it, "
                "or set RESUME_FORGE_LLM_BACKEND=anthropic to use the Anthropic API."
            ) from exc
        return [m["name"] for m in response.json().get("models", [])]

    def _pick_model(self) -> str:
        models = self._installed_models()
        if not models:
            raise LLMError(
                "No models installed in Ollama. Pull one first, e.g.: ollama pull llama3.1:8b"
            )
        for preferred in self._prefer:
            for name in models:
                if name.startswith(preferred):
                    return name
        # skip embedding-only models if possible
        non_embed = [m for m in models if "embed" not in m]
        return (non_embed or models)[0]

    def parse(self, *, system: str, prompt: str, output_type: type[T]) -> T:
        import httpx

        schema = output_type.model_json_schema()
        _require_all_properties(schema)
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"{prompt}\n\nRespond ONLY with JSON matching the required schema.",
            },
        ]

        # Size the context to the prompt so long resumes are never silently
        # truncated (~3 chars/token heuristic + headroom for schema and output).
        needed_ctx = (len(system) + len(prompt)) // 3 + 4096
        num_ctx = max(self.num_ctx, min(32768, needed_ctx)) if needed_ctx > self.num_ctx else self.num_ctx

        payload_extra: dict = {}
        if self.keep_alive is not None:
            payload_extra["keep_alive"] = self.keep_alive

        last_error: Exception | None = None
        for _attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(
                    "/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "format": schema,
                        "options": {"temperature": 0, "num_ctx": num_ctx},
                        **payload_extra,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = ""
                try:
                    detail = exc.response.json().get("error", "")
                except Exception:
                    pass
                if "not found" in detail.lower():
                    available = ", ".join(self._installed_models()) or "none"
                    raise LLMError(
                        f"Ollama model '{self.model}' is not installed (available: {available}). "
                        f"Run: ollama pull {self.model}, or set RESUME_FORGE_MODEL."
                    ) from exc
                raise LLMError(f"Ollama request failed: {detail or exc}") from exc
            except httpx.HTTPError as exc:
                raise LLMError(
                    f"Could not reach the Ollama server at {self.host}: {exc}. Is Ollama running?"
                ) from exc

            content = response.json().get("message", {}).get("content", "")
            try:
                return output_type.model_validate_json(content)
            except ValidationError as exc:
                last_error = exc
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "That JSON did not validate against the schema. Fix these errors and "
                            f"respond with corrected JSON only:\n{exc}"
                        ),
                    }
                )

        raise LLMError(
            f"Ollama model '{self.model}' failed to produce schema-valid JSON after "
            f"{self.max_retries + 1} attempts: {last_error}"
        )


class AnthropicLLM:
    """Anthropic API backend (opt-in: RESUME_FORGE_LLM_BACKEND=anthropic).

    Uses ``client.messages.parse`` with a Pydantic ``output_format`` so the API
    enforces the JSON schema and the SDK returns a validated model instance.
    """

    def __init__(self, model: str | None = None, client=None, max_tokens: int = 16000):
        import anthropic

        self.model = model or os.environ.get("RESUME_FORGE_MODEL", DEFAULT_ANTHROPIC_MODEL)
        self.max_tokens = max_tokens
        self._client = client or anthropic.Anthropic()

    def parse(self, *, system: str, prompt: str, output_type: type[T]) -> T:
        import anthropic

        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=output_type,
            )
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Could not reach the Anthropic API: {exc}") from exc

        if response.stop_reason == "refusal":
            raise LLMError("The model refused this request (stop_reason=refusal).")
        if response.parsed_output is None:
            raise LLMError("The model did not return output matching the expected schema.")
        return response.parsed_output


class OpenAICompatLLM:
    """Any OpenAI-compatible chat-completions API (z.ai/GLM, Gemini, Groq, ...).

    Structured output via ``response_format={"type": "json_object"}`` with the
    schema embedded in the prompt, validated with Pydantic and retried on
    mismatch. Markdown fences are stripped; if a provider rejects json_object
    mode with a 400, it retries without it (schema-in-prompt still guides it).
    """

    def __init__(
        self,
        provider: str = "openai",
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        max_retries: int = 2,
        timeout: float = 120.0,
        http_client=None,
    ):
        import httpx

        preset = OPENAI_COMPAT_PROVIDERS.get(provider, OPENAI_COMPAT_PROVIDERS["openai"])
        self.provider = provider
        self.label = preset["label"]

        self.base_url = (
            base_url or os.environ.get("RESUME_FORGE_OPENAI_BASE_URL") or preset["base_url"]
        )
        if not self.base_url:
            raise LLMError(
                f"No base URL for backend {provider!r}. Set RESUME_FORGE_OPENAI_BASE_URL "
                "to your provider's OpenAI-compatible endpoint."
            )
        self.base_url = self.base_url.rstrip("/")

        self.model = model or os.environ.get("RESUME_FORGE_MODEL") or preset["model"]
        if not self.model:
            raise LLMError(f"No model set for backend {provider!r}. Set RESUME_FORGE_MODEL.")

        self.api_key = api_key or _find_api_key(preset["key_envs"])
        if not self.api_key:
            envs = " or ".join(preset["key_envs"])
            signup = f" Get a free key at {preset['signup']}." if preset["signup"] else ""
            raise LLMError(f"No API key for {self.label}. Set {envs}.{signup}")

        self.max_retries = max_retries
        self._auth_headers = {"Authorization": f"Bearer {self.api_key}"}
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=timeout)

    @staticmethod
    def _err_detail(response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict):
                err = body.get("error")
                if isinstance(err, dict) and err.get("message"):
                    return err["message"]
                if isinstance(err, str):
                    return err
            return json.dumps(body)[:300]
        except Exception:
            return response.text[:300]

    def parse(self, *, system: str, prompt: str, output_type: type[T]) -> T:
        import httpx

        schema = output_type.model_json_schema()
        _require_all_properties(schema)
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\nReturn ONLY a single JSON object matching this schema "
                    f"(no markdown, no commentary):\n{json.dumps(schema)}"
                ),
            },
        ]

        use_json_mode = True
        last_error: Exception | None = None
        for _attempt in range(self.max_retries + 1):
            payload: dict = {"model": self.model, "messages": messages, "temperature": 0}
            if use_json_mode:
                payload["response_format"] = {"type": "json_object"}
            try:
                response = self._client.post(
                    "/chat/completions", json=payload, headers=self._auth_headers
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 400 and use_json_mode:
                    use_json_mode = False  # provider may not support json_object
                    continue
                raise LLMError(
                    f"{self.label} API error ({exc.response.status_code}): "
                    f"{self._err_detail(exc.response)}"
                ) from exc
            except httpx.HTTPError as exc:
                raise LLMError(f"Could not reach {self.label} at {self.base_url}: {exc}") from exc

            body = response.json()
            try:
                content = body["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(
                    f"{self.label} returned an unexpected response shape: {json.dumps(body)[:300]}"
                ) from exc

            try:
                return output_type.model_validate_json(_extract_json(content))
            except ValidationError as exc:
                last_error = exc
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "That JSON did not validate against the schema. Fix these errors "
                            f"and respond with corrected JSON only:\n{exc}"
                        ),
                    }
                )

        raise LLMError(
            f"{self.label} model {self.model!r} failed to produce schema-valid JSON after "
            f"{self.max_retries + 1} attempts: {last_error}"
        )


def _auto_backend() -> str:
    """Pick a backend when none is configured: a present cloud key wins (fast,
    free), else local Ollama. Anthropic is never auto-selected (it costs money)."""
    for name in _AUTODETECT_ORDER:
        if _find_api_key(OPENAI_COMPAT_PROVIDERS[name]["key_envs"]):
            return name
    return "ollama"


def default_llm(backend: str | None = None, model: str | None = None) -> LLM:
    """Build the configured LLM backend.

    Resolution order: explicit ``backend`` arg → ``RESUME_FORGE_LLM_BACKEND`` →
    auto-detect from a present cloud API key (z.ai first) → local Ollama.
    """
    load_env_file()
    backend = (backend or os.environ.get("RESUME_FORGE_LLM_BACKEND") or _auto_backend()).lower()
    backend = _PROVIDER_ALIASES.get(backend, backend)

    if backend == "anthropic":
        return AnthropicLLM(model=model)
    if backend == "ollama":
        return OllamaLLM(model=model)
    if backend in OPENAI_COMPAT_PROVIDERS:
        return OpenAICompatLLM(provider=backend, model=model)

    known = ", ".join(["ollama", "anthropic", *OPENAI_COMPAT_PROVIDERS])
    raise LLMError(f"Unknown LLM backend {backend!r}. Use one of: {known}.")


def stronger_llm_for(base_llm: LLM) -> LLM | None:
    """Return a stronger fallback LLM for a failed structured parse, or None.

    Used by ingest as a last resort when a parse comes back empty: on Ollama it
    picks the best installed model (quality-first order), with keep_alive=0 so
    the heavier model unloads immediately after the single call. Override with
    RESUME_FORGE_INGEST_MODEL. Non-Ollama backends have no escalation path.
    """
    if not isinstance(base_llm, OllamaLLM):
        return None
    override = os.environ.get("RESUME_FORGE_INGEST_MODEL")
    stronger = OllamaLLM(
        model=override,
        host=base_llm.host,
        keep_alive=0,
        prefer=INGEST_PREFERRED_OLLAMA_MODELS,
    )
    if stronger.model == base_llm.model:
        return None  # nothing stronger installed
    return stronger
