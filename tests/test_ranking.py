"""Tests for ranking/embedder.py and ranking/scorer.py.

Verifies that an ML-focused job ranks above a generic Software Engineer job
when scored against an ML-focused profile. No network calls — model loads
from local cache via a module-scoped fixture.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from jobscout.models import (
    DealbreakersConfig,
    JobListing,
    LocationConfig,
    SalaryConfig,
    SeniorityConfig,
    SkillsConfig,
    UserProfile,
)
from jobscout.ranking.embedder import ProfileEmbedder
from jobscout.ranking.scorer import rank_jobs


# ---------------------------------------------------------------------------
# Module-level job fixtures
# ---------------------------------------------------------------------------

def _make_job(id: str, title: str, description: str) -> JobListing:
    return JobListing(
        id=id,
        source="test",
        title=title,
        company="Test GmbH",
        description=description,
        location="Berlin, Germany",
        remote_policy="hybrid",
        salary_min=55_000.0,
        salary_max=75_000.0,
        seniority="mid",
        url=f"https://example.com/job/{id}",
        posted_date=date(2026, 3, 19),
        fetched_at=datetime(2026, 3, 19, 12, 0, 0),
        raw_data={},
    )


ML_JOB = _make_job(
    id="ml-1",
    title="ML Engineer",
    description=(
        "Build and deploy machine learning models at scale. "
        "Experience with PyTorch, HuggingFace Transformers, and LLM fine-tuning required. "
        "Work on RAG pipelines, vector databases, and LLM application development. "
        "Familiarity with MLOps tooling and model serving a strong plus."
    ),
)

SWE_JOB = _make_job(
    id="swe-1",
    title="Software Engineer",
    description=(
        "Design and build scalable backend services and REST APIs. "
        "Strong experience with Java or Go, microservices architecture, and CI/CD pipelines. "
        "Work closely with product teams on system design and code reviews. "
        "Experience with Docker, Kubernetes, and cloud infrastructure preferred."
    ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def embedder() -> ProfileEmbedder:
    return ProfileEmbedder()


@pytest.fixture(scope="module")
def ml_profile() -> UserProfile:
    return UserProfile(
        name="Marcos",
        target_roles=["ML Engineer", "AI Engineer"],
        skills=SkillsConfig(
            strong=[
                "RAG systems",
                "LangChain",
                "LLM application development",
                "Sentence Transformers",
                "HuggingFace ecosystem",
            ],
            working_knowledge=["Python", "PyTorch", "Docker", "REST APIs"],
        ),
        location=LocationConfig(
            target_countries=["Germany"],
            preferred_cities=["Berlin"],
            remote_acceptable=True,
            eu_work_authorization=True,
        ),
        salary=SalaryConfig(minimum_annual_eur=50_000.0, target_annual_eur=65_000.0),
        seniority=SeniorityConfig(target=["junior", "mid"], exclude=["intern", "director"]),
        dealbreakers=DealbreakersConfig(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRankJobs:
    def test_ml_job_ranks_above_swe_job(self, embedder, ml_profile):
        results = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder)
        assert results[0].listing.id == "ml-1", (
            f"ML job should rank first for an ML profile, got '{results[0].listing.id}' "
            f"(scores: ml={results[0].embedding_score:.4f} not first)"
        )

    def test_results_are_sorted_descending(self, embedder, ml_profile):
        results = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder)
        scores = [r.embedding_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_scores_are_valid_cosine_similarity(self, embedder, ml_profile):
        results = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder)
        for r in results:
            assert -1.0 <= r.embedding_score <= 1.0

    def test_empty_input_returns_empty(self, embedder, ml_profile):
        assert rank_jobs([], ml_profile, embedder) == []

    def test_single_job_returns_one_result(self, embedder, ml_profile):
        results = rank_jobs([ML_JOB], ml_profile, embedder)
        assert len(results) == 1
        assert results[0].listing.id == "ml-1"
