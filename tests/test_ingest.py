"""Master-resume ingestion: text extraction and caching (LLM mocked)."""

from pathlib import Path

from resume_forge.ingest import extract_resume_text, ingest_master_resume
from resume_forge.models import MasterProfile
from tests.conftest import FakeLLM

FIXTURES = Path(__file__).parent / "fixtures"


class TestExtractText:
    def test_txt(self):
        text = extract_resume_text(FIXTURES / "sample_resume.txt")
        assert "Jordan Rivera" in text
        assert "PostgreSQL" in text

    def test_unsupported_format(self, tmp_path):
        import pytest

        from resume_forge.exceptions import IngestError

        bad = tmp_path / "resume.rtf"
        bad.write_text("hi")
        with pytest.raises(IngestError, match="Unsupported"):
            extract_resume_text(bad)


class TestContactBackfill:
    def test_dropped_contact_recovered_from_text(self, sample_profile, tmp_path):
        # Simulate a small model losing email/phone during parsing
        lossy = sample_profile.model_copy(deep=True)
        lossy.contact.email = None
        lossy.contact.phone = None
        llm = FakeLLM({MasterProfile: lossy})

        profile = ingest_master_resume(
            FIXTURES / "sample_resume.txt", llm=llm, cache_dir=tmp_path
        )
        assert profile.contact.email == "jordan.rivera@example.com"
        assert "555-0192" in profile.contact.phone


class TestCaching:
    def test_second_call_uses_cache_not_llm(self, sample_profile, tmp_path):
        llm = FakeLLM({MasterProfile: sample_profile})
        resume = FIXTURES / "sample_resume.txt"

        first = ingest_master_resume(resume, llm=llm, cache_dir=tmp_path)
        assert len(llm.calls) == 1

        second = ingest_master_resume(resume, llm=llm, cache_dir=tmp_path)
        assert len(llm.calls) == 1  # served from cache
        assert second == first

    def test_use_cache_false_reparses(self, sample_profile, tmp_path):
        llm = FakeLLM({MasterProfile: sample_profile})
        resume = FIXTURES / "sample_resume.txt"
        ingest_master_resume(resume, llm=llm, cache_dir=tmp_path)
        ingest_master_resume(resume, llm=llm, cache_dir=tmp_path, use_cache=False)
        assert len(llm.calls) == 2

    def test_changed_file_busts_cache(self, sample_profile, tmp_path):
        llm = FakeLLM({MasterProfile: sample_profile})
        resume = tmp_path / "resume.txt"
        resume.write_text("Jordan Rivera\nEngineer at Acme")
        ingest_master_resume(resume, llm=llm, cache_dir=tmp_path)
        resume.write_text("Jordan Rivera\nEngineer at Acme\nNew bullet added")
        ingest_master_resume(resume, llm=llm, cache_dir=tmp_path)
        assert len(llm.calls) == 2
