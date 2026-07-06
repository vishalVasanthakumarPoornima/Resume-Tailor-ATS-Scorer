"""No-fabrication guard tests."""

from resume_forge.models import EducationItem, ExperienceItem
from resume_forge.tailor import enforce_no_fabrication


class TestEnforceNoFabrication:
    def test_clean_resume_passes_through(self, sample_tailored, sample_profile):
        cleaned, violations = enforce_no_fabrication(sample_tailored, sample_profile)
        assert violations == []
        assert len(cleaned.experience) == 1

    def test_invented_employer_dropped(self, sample_tailored, sample_profile):
        sample_tailored.experience.append(
            ExperienceItem(company="Google", title="Staff Engineer", bullets=["Did great things"])
        )
        cleaned, violations = enforce_no_fabrication(sample_tailored, sample_profile)
        assert len(cleaned.experience) == 1
        assert any("Google" in v for v in violations)

    def test_invented_degree_and_cert_dropped(self, sample_tailored, sample_profile):
        sample_tailored.education.append(EducationItem(institution="MIT", degree="PhD"))
        sample_tailored.certifications.append("CISSP")
        cleaned, violations = enforce_no_fabrication(sample_tailored, sample_profile)
        assert [e.institution for e in cleaned.education] == ["San Jose State University"]
        assert cleaned.certifications == ["AWS Certified Developer"]
        assert len(violations) == 2

    def test_contact_always_reset_to_master(self, sample_tailored, sample_profile):
        sample_tailored.contact.email = "invented@fake.com"
        cleaned, _ = enforce_no_fabrication(sample_tailored, sample_profile)
        assert cleaned.contact.email == "jordan.rivera@example.com"

    def test_rewording_and_reordering_allowed(self, sample_tailored, sample_profile):
        # Same employer, reworded bullets — must survive untouched
        sample_tailored.experience[0].bullets = ["Engineered Python microservices at scale"]
        cleaned, violations = enforce_no_fabrication(sample_tailored, sample_profile)
        assert violations == []
        assert cleaned.experience[0].bullets == ["Engineered Python microservices at scale"]
