"""Tests for evaluation/evaluator.py and evaluation/prompt.py.

No real API calls — Haiku responses are mocked via unittest.mock.
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from jobscout.evaluation.evaluator import evaluate_jobs
from jobscout.evaluation.prompt import build_prompt
from jobscout.models import (
    DealbreakersConfig,
    JobListing,
    LocationConfig,
    RateConfig,
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
        location=LocationConfig(target_countries=["Germany"]),
        rate=RateConfig(),
        dealbreakers=DealbreakersConfig(),
        freelancermap_queries=["Machine Learning"],
    )


def _make_scored_job(id: str, embedding_score: float = 0.8) -> ScoredJob:
    listing = JobListing(
        id=id,
        source="test",
        title="ML Engineer",
        company="Test GmbH",
        description="Build and deploy machine learning models using PyTorch and LangChain.",
        location="Berlin, Germany",
        remote_percentage=50,
        url=f"https://example.com/job/{id}",
        posted_date=datetime(2026, 3, 20, 9, 30, 0),
        fetched_at=datetime(2026, 3, 20, 12, 0, 0),
        raw_data={},
    )
    return ScoredJob(listing=listing, embedding_score=embedding_score)


def _mock_client(response_payload: dict | None = None, raise_exc: Exception | None = None):
    """Return a mock AsyncAnthropic client.

    If raise_exc is set, the messages.create call raises that exception.
    Otherwise it returns a response with response_payload as JSON text.
    """
    client = MagicMock()
    if raise_exc is not None:
        client.messages.create = AsyncMock(side_effect=raise_exc)
    else:
        payload = response_payload or {
            "match_score": 8,
            "matching_skills": ["LangChain", "PyTorch"],
            "gaps": ["MLOps"],
            "explanation": "Strong match on core LLM skills.",
        }
        message = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])
        client.messages.create = AsyncMock(return_value=message)
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

    async def test_json_in_code_fence_is_parsed_correctly(self, profile):
        """Haiku wraps JSON in markdown code fences — strip them before parsing."""
        payload = {"match_score": 7, "matching_skills": ["RAG"], "gaps": [], "explanation": "Good."}
        fenced = f"```json\n{json.dumps(payload)}\n```"
        client = MagicMock()
        client.messages.create = AsyncMock(
            return_value=SimpleNamespace(content=[SimpleNamespace(text=fenced)])
        )

        results = await evaluate_jobs([_make_scored_job("fence-1")], profile, client, model="mock-model")

        assert results[0].evaluation is not None
        assert results[0].evaluation.match_score == 7

    async def test_on_invalid_json_job_retained_without_llm_score(self, profile):
        client = MagicMock()
        bad_message = SimpleNamespace(content=[SimpleNamespace(text="not valid json {")])
        client.messages.create = AsyncMock(return_value=bad_message)

        results = await evaluate_jobs(
            [_make_scored_job("job-3")], profile, client, model="mock-model"
        )

        assert results[0].llm_score is None

    async def test_top_n_slices_input(self, profile):
        jobs = [_make_scored_job(f"job-{i}") for i in range(10)]
        client = _mock_client()

        results = await evaluate_jobs(jobs, profile, client, model="mock-model", top_n=3)

        assert len(results) == 3
        assert client.messages.create.call_count == 3

    async def test_empty_input_returns_empty(self, profile):
        client = _mock_client()
        results = await evaluate_jobs([], profile, client, model="mock-model")
        assert results == []
        client.messages.create.assert_not_called()

    async def test_partial_failure_mixed_results(self, profile):
        """First job succeeds, second fails — both are returned."""
        good_payload = {
            "match_score": 7,
            "matching_skills": ["Python"],
            "gaps": [],
            "explanation": "Good fit.",
        }
        good_msg = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(good_payload))])
        fail_exc = Exception("timeout")

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[good_msg, fail_exc])

        jobs = [_make_scored_job("ok-1"), _make_scored_job("fail-1")]
        results = await evaluate_jobs(jobs, profile, client, model="mock-model")

        assert results[0].llm_score == pytest.approx(0.7)
        assert results[1].llm_score is None

    async def test_reeval_fires_when_score_below_threshold(self, profile):
        """First score 3 < reeval_below=4 triggers a second call; higher score (7) wins."""
        low_payload = {"match_score": 3, "matching_skills": [], "gaps": ["LLMs"], "explanation": "Weak."}
        high_payload = {"match_score": 7, "matching_skills": ["RAG"], "gaps": [], "explanation": "Good."}
        low_msg = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(low_payload))])
        high_msg = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(high_payload))])

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[low_msg, high_msg])

        results = await evaluate_jobs(
            [_make_scored_job("reeval-1")], profile, client, model="mock-model", reeval_below=4
        )

        assert client.messages.create.call_count == 2
        assert results[0].evaluation is not None
        assert results[0].evaluation.match_score == 7

    async def test_reeval_not_called_when_score_at_or_above_threshold(self, profile):
        """Score == reeval_below (4) should NOT trigger a second call."""
        payload = {"match_score": 4, "matching_skills": ["Python"], "gaps": [], "explanation": "Fine."}
        client = _mock_client(response_payload=payload)

        results = await evaluate_jobs(
            [_make_scored_job("no-reeval-1")], profile, client, model="mock-model", reeval_below=4
        )

        assert client.messages.create.call_count == 1
        assert results[0].evaluation is not None
        assert results[0].evaluation.match_score == 4

    async def test_reeval_keeps_first_when_second_is_lower(self, profile):
        """First score 3 triggers re-eval, but second score (2) is lower — first result kept."""
        first_payload = {"match_score": 3, "matching_skills": [], "gaps": ["LLMs"], "explanation": "Weak."}
        second_payload = {"match_score": 2, "matching_skills": [], "gaps": ["LLMs", "Python"], "explanation": "Worse."}
        first_msg = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(first_payload))])
        second_msg = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(second_payload))])

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[first_msg, second_msg])

        results = await evaluate_jobs(
            [_make_scored_job("keep-first-1")], profile, client, model="mock-model", reeval_below=4
        )

        assert client.messages.create.call_count == 2
        assert results[0].evaluation is not None
        assert results[0].evaluation.match_score == 3

    async def test_reeval_second_pass_failure_keeps_first_result(self, profile):
        """First score 3 triggers re-eval, but second call fails — first result is kept."""
        first_payload = {"match_score": 3, "matching_skills": [], "gaps": ["LLMs"], "explanation": "Weak."}
        first_msg = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(first_payload))])

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[first_msg, Exception("network error")])

        results = await evaluate_jobs(
            [_make_scored_job("reeval-fail-1")], profile, client, model="mock-model", reeval_below=4
        )

        assert client.messages.create.call_count == 2
        assert results[0].evaluation is not None
        assert results[0].evaluation.match_score == 3


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
