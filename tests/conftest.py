"""Shared test fixtures: a fake LLM and canned models. No network, no API key."""

from __future__ import annotations

import pytest

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
    """Returns pre-registered objects keyed by output type; records prompts."""

    def __init__(self, responses: dict[type, object] | None = None):
        self.responses = responses or {}
        self.calls: list[dict] = []

    def parse(self, *, system: str, prompt: str, output_type: type):
        self.calls.append({"system": system, "prompt": prompt, "output_type": output_type})
        try:
            return self.responses[output_type]
        except KeyError:  # pragma: no cover
            raise AssertionError(f"FakeLLM has no response registered for {output_type}")


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
