"""Cover letter tests: sanitation, rendering, escaping. LLM mocked."""

import datetime

from resume_forge.cover import render_cover_letter_tex, write_cover_letter
from resume_forge.models import CoverLetter
from tests.conftest import FakeLLM


class TestWriteCoverLetter:
    def test_paragraphs_pass_through(self, sample_profile, sample_job):
        letter = CoverLetter(paragraphs=["I am excited to apply.", "My Python work at Acme fits."])
        result = write_cover_letter(sample_profile, sample_job, llm=FakeLLM({CoverLetter: letter}))
        assert len(result.paragraphs) == 2

    def test_salutations_and_signoffs_stripped(self, sample_profile, sample_job):
        letter = CoverLetter(
            paragraphs=[
                "Dear Hiring Manager,",
                "I am excited to apply for this role.",
                "Sincerely, Jordan",
            ]
        )
        result = write_cover_letter(sample_profile, sample_job, llm=FakeLLM({CoverLetter: letter}))
        assert result.paragraphs == ["I am excited to apply for this role."]

    def test_placeholders_removed(self, sample_profile, sample_job):
        letter = CoverLetter(paragraphs=["I want to join [Company Name] as an engineer."])
        result = write_cover_letter(sample_profile, sample_job, llm=FakeLLM({CoverLetter: letter}))
        assert result.paragraphs == ["I want to join as an engineer."]

    def test_prompt_carries_profile_and_job(self, sample_profile, sample_job):
        llm = FakeLLM({CoverLetter: CoverLetter(paragraphs=["Body."])})
        write_cover_letter(sample_profile, sample_job, llm=llm)
        prompt = llm.calls[0]["prompt"]
        assert "Acme Analytics" in prompt and "Initech" in prompt
        assert "NEVER invent" in llm.calls[0]["system"]


class TestRenderCoverLetter:
    def test_renders_with_company_salutation_and_escaping(self, sample_profile, sample_job, tmp_path):
        letter = CoverLetter(paragraphs=["Cut costs 30% & shipped p99_latency fixes."])
        tex = render_cover_letter_tex(
            letter,
            sample_profile.contact,
            sample_job,
            tmp_path / "cover.tex",
            date=datetime.date(2026, 7, 6),
        )
        content = tex.read_text()
        assert "Dear Initech Hiring Team," in content
        assert r"Cut costs 30\% \& shipped p99\_latency fixes." in content
        assert "July 6, 2026" in content
        assert "Jordan Rivera" in content
        assert "Re: Backend Engineer" in content

    def test_generic_salutation_without_company(self, sample_profile, sample_job, tmp_path):
        sample_job.company = None
        tex = render_cover_letter_tex(
            CoverLetter(paragraphs=["Body."]), sample_profile.contact, sample_job, tmp_path / "c.tex"
        )
        assert "Dear Hiring Manager," in tex.read_text()
