"""Thin wrapper around the Anthropic SDK for structured (Pydantic-validated) output.

All LLM use in the pipeline goes through the ``LLM`` protocol so tests can
inject a fake without any network access.
"""

from __future__ import annotations

import os
from typing import Protocol, TypeVar

from pydantic import BaseModel

from .exceptions import LLMError

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-4-8"


class LLM(Protocol):
    """Anything that can turn a prompt into a validated Pydantic model."""

    def parse(self, *, system: str, prompt: str, output_type: type[T]) -> T:  # pragma: no cover
        ...


class AnthropicLLM:
    """Production LLM backed by the Anthropic API.

    Uses ``client.messages.parse`` with a Pydantic ``output_format`` so the API
    enforces the JSON schema and the SDK returns a validated model instance.
    """

    def __init__(self, model: str | None = None, client=None, max_tokens: int = 16000):
        import anthropic

        self.model = model or os.environ.get("RESUME_FORGE_MODEL", DEFAULT_MODEL)
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


def default_llm() -> AnthropicLLM:
    return AnthropicLLM()
