"""No-fabrication guard and truthful-skill backfill tests."""

from resume_forge.models import EducationItem, ExperienceItem, Job, SkillGroup
from resume_forge.tailor import backfill_truthful_skills, enforce_no_fabrication


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
        # education is always the master's, verbatim — invented MIT entry gone
        assert [e.institution for e in cleaned.education] == ["San Jose State University"]
        assert cleaned.certifications == ["AWS Certified Developer"]
        assert any("CISSP" in v for v in violations)

    def test_education_never_reworded(self, sample_tailored, sample_profile):
        # Model rephrased an in-progress degree as completed — must be discarded
        sample_tailored.education[0].details = ["Completed a Master's degree in CS"]
        cleaned, _ = enforce_no_fabrication(sample_tailored, sample_profile)
        assert cleaned.education[0] == sample_profile.education[0]

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


class TestFuzzyMatchingAndRestore:
    def test_cosmetic_company_drift_is_not_dropped(self, sample_tailored, sample_profile):
        # Model appended location to the employer name — must still match
        sample_tailored.experience[0].company = "Acme Analytics, San Jose, CA"
        cleaned, violations = enforce_no_fabrication(sample_tailored, sample_profile)
        assert violations == []
        assert cleaned.experience[0].company == "Acme Analytics, San Jose, CA"

    def test_legal_suffix_drift_matches(self, sample_tailored, sample_profile):
        sample_profile.experience[0].company = "Perficient, Inc."
        sample_tailored.experience[0].company = "Perficient"
        cleaned, violations = enforce_no_fabrication(sample_tailored, sample_profile)
        assert violations == []
        assert len(cleaned.experience) == 1

    def test_omitted_employer_is_restored(self, sample_tailored, sample_profile):
        # Model deleted the entire work history — the guard must put it back
        sample_tailored.experience = []
        cleaned, violations = enforce_no_fabrication(sample_tailored, sample_profile)
        assert [e.company for e in cleaned.experience] == ["Acme Analytics"]
        assert cleaned.experience[0].bullets == sample_profile.experience[0].bullets
        assert any("Restored omitted employer" in v for v in violations)

    def test_omitted_education_is_restored(self, sample_tailored, sample_profile):
        sample_tailored.education = []
        cleaned, violations = enforce_no_fabrication(sample_tailored, sample_profile)
        assert [e.institution for e in cleaned.education] == ["San Jose State University"]

    def test_all_projects_omitted_are_restored(self, sample_tailored, sample_profile):
        sample_tailored.projects = []
        cleaned, _ = enforce_no_fabrication(sample_tailored, sample_profile)
        assert [p.name for p in cleaned.projects] == ["LogPipe"]

    def test_empty_summary_falls_back_to_master(self, sample_tailored, sample_profile):
        sample_tailored.summary = None
        cleaned, _ = enforce_no_fabrication(sample_tailored, sample_profile)
        assert cleaned.summary == sample_profile.summary

    def test_genuinely_different_company_still_dropped(self, sample_tailored, sample_profile):
        sample_tailored.experience[0].company = "Google"
        cleaned, violations = enforce_no_fabrication(sample_tailored, sample_profile)
        # Google dropped as invented, Acme restored from master
        assert [e.company for e in cleaned.experience] == ["Acme Analytics"]
        assert any("Dropped invented employer" in v for v in violations)


class TestBackfillTruthfulSkills:
    def test_dropped_profile_skill_from_jd_is_restored(self, sample_tailored, sample_profile, sample_job):
        # Model over-trimmed: Docker (in profile AND in JD preferred) got dropped
        sample_tailored.skills = [SkillGroup(category="Languages", items=["Python", "SQL"])]
        result, added = backfill_truthful_skills(sample_tailored, sample_profile, sample_job)
        assert "Docker" in added
        tools = next(g for g in result.skills if g.category == "Tools")
        assert "Docker" in tools.items

    def test_never_adds_skill_absent_from_profile(self, sample_tailored, sample_profile, sample_job):
        # Kubernetes is in the JD but NOT in the profile — must never be backfilled
        sample_tailored.skills = []
        result, added = backfill_truthful_skills(sample_tailored, sample_profile, sample_job)
        all_items = [item for g in result.skills for item in g.items]
        assert "Kubernetes" not in all_items
        assert "Kubernetes" not in added

    def test_no_change_when_skills_already_present(self, sample_tailored, sample_profile, sample_job):
        result, added = backfill_truthful_skills(sample_tailored, sample_profile, sample_job)
        assert added == []
        assert result.skills == sample_tailored.skills

    def test_skill_mentioned_in_bullets_counts_as_present(self, sample_tailored, sample_profile):
        job = Job(title="X", required_skills=["PostgreSQL"])
        sample_tailored.skills = []  # not in the skills section...
        # ...but the bullet "Reduced query latency 40% by adding PostgreSQL indexes" covers it
        result, added = backfill_truthful_skills(sample_tailored, sample_profile, job)
        assert added == []
