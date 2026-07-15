"""Shared test fixtures: a fake LLM and canned models. No network, no API key."""

from __future__ import annotations

import pytest

# Provider key env vars that would otherwise leak into backend-selection tests.
_PROVIDER_KEY_ENVS = (
    "RESUME_FORGE_LLM_BACKEND",
    "RESUME_FORGE_MODEL",
    "RESUME_FORGE_API_KEY",
    "RESUME_FORGE_OPENAI_BASE_URL",
    "ZAI_API_KEY",
    "GLM_API_KEY",
    "ZHIPU_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "PUTER_API_KEY",
    "PUTER_AUTH_TOKEN",
    "OPENROUTER_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Keep tests hermetic.

    ``default_llm()`` calls ``load_env_file()``, which setdefaults keys from the
    developer's real .env -- so without this, backend-selection tests quietly
    depend on which API keys happen to be sitting in that file (they passed only
    while no GROQ key existed, then broke the moment one was added). Stub the
    loader and clear provider keys so every test sees the same empty environment,
    matching CI, where no .env exists.
    """
    monkeypatch.setattr("resume_forge.llm.load_env_file", lambda *a, **k: None)
    for var in _PROVIDER_KEY_ENVS:
        monkeypatch.delenv(var, raising=False)

from resume_forge.models import (
    Contact,
    EducationItem,
    ExperienceItem,
    Job,
    MasterProfile,
    ProjectItem,
    SkillGroup,
    TailoredResume,
)


class FakeLLM:
    """Returns pre-registered objects keyed by output type; records prompts.

    A list value acts as a queue: successive calls for that type pop from the
    front (the last element repeats), enabling retry-behavior tests.
    """

    def __init__(self, responses: dict[type, object] | None = None):
        self.responses = responses or {}
        self.calls: list[dict] = []

    def parse(self, *, system: str, prompt: str, output_type: type):
        self.calls.append({"system": system, "prompt": prompt, "output_type": output_type})
        try:
            value = self.responses[output_type]
        except KeyError:  # pragma: no cover
            raise AssertionError(f"FakeLLM has no response registered for {output_type}")
        if isinstance(value, list):
            return value.pop(0) if len(value) > 1 else value[0]
        return value


@pytest.fixture
def sample_profile() -> MasterProfile:
    return MasterProfile(
        contact=Contact(
            name="Jordan Rivera",
            email="jordan.rivera@example.com",
            phone="(408) 555-0192",
            location="San Jose, CA",
            github="github.com/jrivera",
        ),
        summary="Software engineer with 3 years building backend services in Python.",
        skills=[
            SkillGroup(category="Languages", items=["Python", "SQL", "Go"]),
            SkillGroup(category="Tools", items=["Docker", "PostgreSQL", "AWS"]),
        ],
        experience=[
            ExperienceItem(
                company="Acme Analytics",
                title="Software Engineer",
                location="San Jose, CA",
                start="Jun 2022",
                end="Present",
                bullets=[
                    "Built REST APIs in Python serving 2M requests/day",
                    "Reduced query latency 40% by adding PostgreSQL indexes",
                ],
            )
        ],
        projects=[
            ProjectItem(
                name="LogPipe",
                technologies=["Python", "Kafka"],
                bullets=["Developed a streaming log processor handling 50k events/sec"],
            )
        ],
        education=[
            EducationItem(
                institution="San Jose State University",
                degree="B.S.",
                field="Computer Science",
                end="2022",
            )
        ],
        certifications=["AWS Certified Developer"],
    )


@pytest.fixture
def sample_job() -> Job:
    return Job(
        title="Backend Engineer",
        company="Initech",
        required_skills=["Python", "PostgreSQL", "REST APIs"],
        preferred_skills=["Docker", "Kubernetes"],
        keywords=["microservices", "CI/CD"],
        responsibilities=["Design and build backend services"],
    )


@pytest.fixture
def sample_tailored(sample_profile) -> TailoredResume:
    return TailoredResume(**sample_profile.model_dump())
