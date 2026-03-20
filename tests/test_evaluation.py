"""Tests for evaluation/evaluator.py and evaluation/prompt.py.

No real API calls — Haiku responses are mocked via unittest.mock.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from jobscout.evaluation.evaluator import evaluate_jobs
from jobscout.evaluation.prompt import build_prompt
from jobscout.models import (
    DealbreakersConfig,
    JobListing,
    LocationConfig,
    SalaryConfig,
    SeniorityConfig,
    SkillsConfig,
    ScoredJob,
    UserProfile,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def profile() -> UserProfile:
    return UserProfile(
        name="Marcos",
        target_roles=["ML Engineer", "AI Engineer"],
        skills=SkillsConfig(
            strong=["RAG systems", "LangChain", "LLM application development"],
            working_knowledge=["Python", "PyTorch", "Docker"],
        ),
        location=LocationConfig(
            target_countries=["Germany"],
            preferred_cities=["Berlin"],
            remote_acceptable=True,
            eu_work_authorization=True,
        ),
        salary=SalaryConfig(minimum_annual_eur=50_000.0, target_annual_eur=65_000.0),
        seniority=SeniorityConfig(target=["junior", "mid"], exclude=["intern"]),
        dealbreakers=DealbreakersConfig(),
    )


def _make_scored_job(id: str, embedding_score: float = 0.8) -> ScoredJob:
    listing = JobListing(
        id=id,
        source="test",
        title="ML Engineer",
        company="Test GmbH",
        description="Build and deploy machine learning models using PyTorch and LangChain.",
        location="Berlin, Germany",
        remote_policy="hybrid",
        salary_min=55_000.0,
        salary_max=75_000.0,
        seniority="mid",
        url=f"https://example.com/job/{id}",
        posted_date=date(2026, 3, 20),
        fetched_at=datetime(2026, 3, 20, 12, 0, 0),
        raw_data={},
    )
    return ScoredJob(listing=listing, embedding_score=embedding_score)


def _mock_client(response_payload: dict | None = None, raise_exc: Exception | None = None):
    """Return a mock AsyncOpenAI client.

    If raise_exc is set, the chat.completions.create call raises that exception.
    Otherwise it returns a response with response_payload as JSON text.
    """
    client = MagicMock()
    if raise_exc is not None:
        client.chat.completions.create = AsyncMock(side_effect=raise_exc)
    else:
        payload = response_payload or {
            "match_score": 8,
            "matching_skills": ["LangChain", "PyTorch"],
            "gaps": ["MLOps"],
            "explanation": "Strong match on core LLM skills.",
        }
        message = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
        ])
        client.chat.completions.create = AsyncMock(return_value=message)
    return client


# ---------------------------------------------------------------------------
# evaluator tests
# ---------------------------------------------------------------------------

class TestEvaluateJobs:
    async def test_populates_llm_score_and_final_score(self, profile):
        jobs = [_make_scored_job("job-1", embedding_score=0.8)]
        client = _mock_client()

        results = await evaluate_jobs(jobs, profile, client, model="mock-model")

        assert len(results) == 1
        result = results[0]
        assert result.llm_score == pytest.approx(0.8)          # match_score=8 → 8/10
        assert result.final_score == pytest.approx(0.4 * 0.8 + 0.6 * 0.8)
        assert result.evaluation is not None
        assert result.evaluation.match_score == 8

    async def test_on_api_failure_job_retained_without_llm_score(self, profile):
        jobs = [_make_scored_job("job-2")]
        client = _mock_client(raise_exc=Exception("API error"))

        results = await evaluate_jobs(jobs, profile, client, model="mock-model")

        assert len(results) == 1
        assert results[0].llm_score is None
        assert results[0].final_score is None
        assert results[0].evaluation is None

    async def test_on_invalid_json_job_retained_without_llm_score(self, profile):
        client = MagicMock()
        bad_message = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content="not valid json {"))
        ])
        client.chat.completions.create = AsyncMock(return_value=bad_message)

        results = await evaluate_jobs(
            [_make_scored_job("job-3")], profile, client, model="mock-model"
        )

        assert results[0].llm_score is None

    async def test_top_n_slices_input(self, profile):
        jobs = [_make_scored_job(f"job-{i}") for i in range(10)]
        client = _mock_client()

        results = await evaluate_jobs(jobs, profile, client, model="mock-model", top_n=3)

        assert len(results) == 3
        assert client.chat.completions.create.call_count == 3

    async def test_empty_input_returns_empty(self, profile):
        client = _mock_client()
        results = await evaluate_jobs([], profile, client, model="mock-model")
        assert results == []
        client.chat.completions.create.assert_not_called()

    async def test_partial_failure_mixed_results(self, profile):
        """First job succeeds, second fails — both are returned."""
        good_payload = {
            "match_score": 7,
            "matching_skills": ["Python"],
            "gaps": [],
            "explanation": "Good fit.",
        }
        good_msg = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(good_payload)))
        ])
        fail_exc = Exception("timeout")

        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=[good_msg, fail_exc])

        jobs = [_make_scored_job("ok-1"), _make_scored_job("fail-1")]
        results = await evaluate_jobs(jobs, profile, client, model="mock-model")

        assert results[0].llm_score == pytest.approx(0.7)
        assert results[1].llm_score is None


# ---------------------------------------------------------------------------
# prompt tests
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_contains_job_title(self, profile):
        job = _make_scored_job("j1").listing
        prompt = build_prompt(job, profile)
        assert "ML Engineer" in prompt

    def test_contains_strong_skills(self, profile):
        job = _make_scored_job("j1").listing
        prompt = build_prompt(job, profile)
        assert "LangChain" in prompt
        assert "RAG systems" in prompt

    def test_contains_target_roles(self, profile):
        job = _make_scored_job("j1").listing
        prompt = build_prompt(job, profile)
        assert "ML Engineer" in prompt
        assert "AI Engineer" in prompt
