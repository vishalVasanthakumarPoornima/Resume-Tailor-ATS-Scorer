"""Ollama backend tests: structured output, retry-on-invalid, error hints. No server."""

import json

import httpx
import pytest
from pydantic import BaseModel

from resume_forge.exceptions import LLMError
from resume_forge.llm import OllamaLLM, default_llm


class Answer(BaseModel):
    name: str
    count: int


def _client(handler) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
    )


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


class TestOllamaParse:
    def test_valid_json_parsed(self):
        captured = {}

        def handler(request):
            if request.url.path == "/api/chat":
                captured.update(json.loads(request.content))
                return _chat_response('{"name": "widget", "count": 3}')
            raise AssertionError(request.url.path)

        llm = OllamaLLM(model="testmodel", http_client=_client(handler))
        result = llm.parse(system="sys", prompt="go", output_type=Answer)
        assert result == Answer(name="widget", count=3)
        # schema constraint was sent to Ollama
        assert captured["format"]["properties"]["count"]["type"] == "integer"
        assert captured["options"]["temperature"] == 0

    def test_retries_on_invalid_then_succeeds(self):
        responses = ['{"name": "widget"}', '{"name": "widget", "count": 3}']
        calls = {"n": 0}

        def handler(request):
            body = _chat_response(responses[calls["n"]])
            calls["n"] += 1
            return body

        llm = OllamaLLM(model="testmodel", http_client=_client(handler))
        result = llm.parse(system="sys", prompt="go", output_type=Answer)
        assert result.count == 3
        assert calls["n"] == 2

    def test_gives_up_after_retries(self):
        def handler(request):
            return _chat_response("not json at all")

        llm = OllamaLLM(model="testmodel", max_retries=1, http_client=_client(handler))
        with pytest.raises(LLMError, match="failed to produce schema-valid JSON"):
            llm.parse(system="sys", prompt="go", output_type=Answer)

    def test_missing_model_error_lists_available(self):
        def handler(request):
            if request.url.path == "/api/chat":
                return httpx.Response(404, json={"error": "model 'nope' not found"})
            return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})

        llm = OllamaLLM(model="nope", http_client=_client(handler))
        with pytest.raises(LLMError, match="available: llama3.1:8b"):
            llm.parse(system="sys", prompt="go", output_type=Answer)

    def test_server_down_gives_actionable_error(self):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        llm = OllamaLLM(model="testmodel", http_client=_client(handler))
        with pytest.raises(LLMError, match="Is Ollama running"):
            llm.parse(system="sys", prompt="go", output_type=Answer)

    def test_auto_picks_preferred_installed_model(self):
        def handler(request):
            return httpx.Response(
                200,
                json={"models": [{"name": "nomic-embed-text:latest"}, {"name": "llama3.1:8b-instruct-q4_K_M"}]},
            )

        llm = OllamaLLM(http_client=_client(handler))
        assert llm.model == "llama3.1:8b-instruct-q4_K_M"

    def test_auto_pick_prefers_light_model_over_heavy(self):
        def handler(request):
            return httpx.Response(
                200,
                json={"models": [{"name": "llama3.1:8b-instruct-q4_K_M"}, {"name": "qwen2.5:3b"}]},
            )

        llm = OllamaLLM(http_client=_client(handler))
        assert llm.model == "qwen2.5:3b"


class TestBackendSelection:
    def test_unknown_backend_rejected(self):
        with pytest.raises(LLMError, match="Unknown LLM backend"):
            default_llm("gpt4all")
