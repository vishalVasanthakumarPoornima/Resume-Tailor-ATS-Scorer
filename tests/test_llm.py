"""LLM backend tests: structured output, retry-on-invalid, error hints. No server."""

import json

import httpx
import pytest
from pydantic import BaseModel

from resume_forge.exceptions import LLMError
from resume_forge.llm import OllamaLLM, OpenAICompatLLM, default_llm


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

    def test_all_properties_forced_required(self):
        """Optional keys get skipped forever by Ollama's ordered grammar decoding —
        every property (top-level and nested) must be marked required."""
        from resume_forge.models import MasterProfile

        captured = {}

        def handler(request):
            captured.update(json.loads(request.content))
            return _chat_response(
                '{"contact": {"name": "x", "email": null, "phone": null, "location": null,'
                ' "linkedin": null, "github": null, "website": null}, "summary": null,'
                ' "skills": [], "experience": [], "projects": [], "education": [], "certifications": []}'
            )

        llm = OllamaLLM(model="testmodel", http_client=_client(handler))
        llm.parse(system="s", prompt="p", output_type=MasterProfile)
        schema = captured["format"]
        assert set(schema["required"]) == set(schema["properties"].keys())
        exp = schema["$defs"]["ExperienceItem"]
        assert set(exp["required"]) == set(exp["properties"].keys())

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


def _oai_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.z.ai/api/paas/v4")


def _oai_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


class TestOpenAICompatParse:
    def test_valid_json_and_request_shape(self):
        captured = {}

        def handler(request):
            captured["path"] = request.url.path
            captured["auth"] = request.headers.get("authorization")
            captured["body"] = json.loads(request.content)
            return _oai_response('{"name": "widget", "count": 3}')

        llm = OpenAICompatLLM(provider="zai", api_key="k-123", http_client=_oai_client(handler))
        result = llm.parse(system="sys", prompt="go", output_type=Answer)
        assert result == Answer(name="widget", count=3)
        assert captured["path"].endswith("/chat/completions")
        assert captured["auth"] == "Bearer k-123"
        assert captured["body"]["response_format"] == {"type": "json_object"}
        assert captured["body"]["model"] == "glm-4.5-flash"

    def test_strips_markdown_fences(self):
        def handler(request):
            return _oai_response('```json\n{"name": "x", "count": 1}\n```')

        llm = OpenAICompatLLM(provider="zai", api_key="k", http_client=_oai_client(handler))
        assert llm.parse(system="s", prompt="p", output_type=Answer).count == 1

    def test_extracts_json_amid_prose(self):
        def handler(request):
            return _oai_response('Sure! Here you go: {"name": "y", "count": 2} Hope that helps.')

        llm = OpenAICompatLLM(provider="zai", api_key="k", http_client=_oai_client(handler))
        assert llm.parse(system="s", prompt="p", output_type=Answer).name == "y"

    def test_retries_on_invalid_then_succeeds(self):
        replies = ['{"name": "x"}', '{"name": "x", "count": 5}']
        calls = {"n": 0}

        def handler(request):
            body = _oai_response(replies[calls["n"]])
            calls["n"] += 1
            return body

        llm = OpenAICompatLLM(provider="zai", api_key="k", http_client=_oai_client(handler))
        assert llm.parse(system="s", prompt="p", output_type=Answer).count == 5
        assert calls["n"] == 2

    def test_400_falls_back_to_no_json_mode(self):
        modes = []

        def handler(request):
            body = json.loads(request.content)
            modes.append("response_format" in body)
            if "response_format" in body:
                return httpx.Response(400, json={"error": {"message": "response_format unsupported"}})
            return _oai_response('{"name": "x", "count": 1}')

        llm = OpenAICompatLLM(provider="zai", api_key="k", http_client=_oai_client(handler))
        assert llm.parse(system="s", prompt="p", output_type=Answer).count == 1
        assert modes == [True, False]  # first with json mode (400), then without

    def test_api_error_surfaces_message(self):
        def handler(request):
            return httpx.Response(401, json={"error": {"message": "invalid api key"}})

        llm = OpenAICompatLLM(provider="zai", api_key="bad", http_client=_oai_client(handler))
        with pytest.raises(LLMError, match="invalid api key"):
            llm.parse(system="s", prompt="p", output_type=Answer)

    def test_missing_key_gives_signup_hint(self, monkeypatch):
        for var in ("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(LLMError, match=r"z\.ai.*manage-apikey"):
            OpenAICompatLLM(provider="zai")

    def test_generic_openai_needs_base_url(self, monkeypatch):
        monkeypatch.delenv("RESUME_FORGE_OPENAI_BASE_URL", raising=False)
        with pytest.raises(LLMError, match="base URL"):
            OpenAICompatLLM(provider="openai", api_key="k", model="x")

    def test_generic_openai_allows_no_key(self, monkeypatch):
        # keyless / self-hosted endpoints: no key, no Authorization header sent
        for var in ("OPENAI_API_KEY", "RESUME_FORGE_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        captured = {}

        def handler(request):
            captured["auth"] = request.headers.get("authorization")
            return _oai_response('{"name": "x", "count": 1}')

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:1234/v1")
        llm = OpenAICompatLLM(
            provider="openai", base_url="http://localhost:1234/v1", model="local", http_client=client
        )
        assert llm.parse(system="s", prompt="p", output_type=Answer).count == 1
        assert captured["auth"] is None  # no auth header when keyless


class TestBackendSelection:
    def test_unknown_backend_rejected(self):
        with pytest.raises(LLMError, match="Unknown LLM backend"):
            default_llm("gpt4all")

    def test_explicit_zai_backend(self, monkeypatch):
        monkeypatch.setenv("ZAI_API_KEY", "k")
        llm = default_llm("zai")
        assert isinstance(llm, OpenAICompatLLM)
        assert llm.provider == "zai"

    def test_glm_alias_maps_to_zai(self, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "k")
        assert default_llm("glm").provider == "zai"

    def test_autodetect_prefers_present_cloud_key(self, monkeypatch):
        for var in ("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv("RESUME_FORGE_LLM_BACKEND", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        llm = default_llm()
        assert isinstance(llm, OpenAICompatLLM)
        assert llm.provider == "gemini"
