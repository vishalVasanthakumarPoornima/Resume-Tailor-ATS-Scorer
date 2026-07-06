"""Pydantic models shared across the resume-forge pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Contact(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class ExperienceItem(BaseModel):
    company: str
    title: str
    location: str | None = None
    start: str | None = Field(default=None, description="Start date as written, e.g. 'Jun 2023'")
    end: str | None = Field(default=None, description="End date as written, or 'Present'")
    bullets: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str
    technologies: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    link: str | None = None


class EducationItem(BaseModel):
    institution: str
    location: str | None = None
    degree: str | None = None
    field: str | None = None
    start: str | None = None
    end: str | None = None
    gpa: str | None = None
    details: list[str] = Field(default_factory=list)


class SkillGroup(BaseModel):
    category: str = Field(description="e.g. 'Languages', 'Frameworks', 'Tools'")
    items: list[str] = Field(default_factory=list)


class MasterProfile(BaseModel):
    """Everything true about the candidate, parsed once from the master resume."""

    contact: Contact
    summary: str | None = None
    skills: list[SkillGroup] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class Job(BaseModel):
    """Structured representation of a job posting."""

    title: str
    company: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(
        default_factory=list,
        description="Other ATS-relevant terms: methodologies, domain terms, tools",
    )
    responsibilities: list[str] = Field(default_factory=list)


class TailoredResume(BaseModel):
    """Resume content tailored to one job. Same shape as the profile, reordered/reworded."""

    contact: Contact
    summary: str | None = None
    skills: list[SkillGroup] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class ScoreReport(BaseModel):
    score: float = Field(description="0-100 overall ATS score")
    subscores: dict[str, float] = Field(default_factory=dict)
    max_subscores: dict[str, float] = Field(default_factory=dict)
    missing_keywords: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ForgeResult(BaseModel):
    pdf_path: str
    tex_path: str
    report: ScoreReport
    iterations: int
    achieved_target: bool
    notes: list[str] = Field(default_factory=list)
