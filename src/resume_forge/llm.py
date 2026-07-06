"""LLM backends for structured (Pydantic-validated) output.

Two backends implement the same ``LLM`` protocol:

- :class:`OllamaLLM` (default) — a local model via the Ollama server. Structured
  output is enforced with Ollama's JSON-schema ``format`` parameter and
  validated with Pydantic, retrying with the validation error on a mismatch.
  No API key, no network beyond localhost.
- :class:`AnthropicLLM` (opt-in) — the Anthropic API via ``messages.parse``.

Selection: ``RESUME_FORGE_LLM_BACKEND=ollama|anthropic`` (default: ollama),
model via ``RESUME_FORGE_MODEL``. Tests inject fakes through the protocol.
"""

from __future__ import annotations

import json
import os
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .exceptions import LLMError

T = TypeVar("T", bound=BaseModel)

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
# Tried in order when RESUME_FORGE_MODEL is unset; falls back to any installed model.
PREFERRED_OLLAMA_MODELS = ("llama3.1", "qwen2.5:14b", "qwen2.5:7b", "mistral", "llama3")


class LLM(Protocol):
    """Anything that can turn a prompt into a validated Pydantic model."""

    def parse(self, *, system: str, prompt: str, output_type: type[T]) -> T:  # pragma: no cover
        ...


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
        num_ctx: int = 16384,
        max_retries: int = 2,
        timeout: float = 600.0,
        http_client=None,
    ):
        import httpx

        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST).rstrip("/")
        if not self.host.startswith("http"):
            self.host = f"http://{self.host}"
        self.num_ctx = int(os.environ.get("RESUME_FORGE_OLLAMA_NUM_CTX", num_ctx))
        self.max_retries = max_retries
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
        for preferred in PREFERRED_OLLAMA_MODELS:
            for name in models:
                if name.startswith(preferred):
                    return name
        # skip embedding-only models if possible
        non_embed = [m for m in models if "embed" not in m]
        return (non_embed or models)[0]

    def parse(self, *, system: str, prompt: str, output_type: type[T]) -> T:
        import httpx

        schema = output_type.model_json_schema()
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"{prompt}\n\nRespond ONLY with JSON matching the required schema.",
            },
        ]

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
                        "options": {"temperature": 0, "num_ctx": self.num_ctx},
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


def default_llm(backend: str | None = None, model: str | None = None) -> LLM:
    """Build the configured backend. Default: local Ollama (no API key needed)."""
    backend = (backend or os.environ.get("RESUME_FORGE_LLM_BACKEND", "ollama")).lower()
    if backend == "anthropic":
        return AnthropicLLM(model=model)
    if backend == "ollama":
        return OllamaLLM(model=model)
    raise LLMError(f"Unknown LLM backend {backend!r}. Use 'ollama' or 'anthropic'.")
