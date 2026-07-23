"""Tests for behaviour on the core models.

`JobListing` is otherwise a plain dataclass with nothing to assert, so this module
covers the one field that is computed rather than stored: `remote_policy`.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from pydantic import ValidationError

from jobscout.models import (
    EvaluationResult,
    FeedbackEntry,
    JobListing,
    LocationConfig,
)


def _make_job(**overrides) -> JobListing:
    defaults = dict(
        id="job-1",
        source="freelancermap",
        title="ML Engineer",
        company="Acme GmbH",
        description="Contract work on machine learning systems.",
        location="Berlin, Germany",
        url="https://example.com/job/1",
        posted_date=datetime(2026, 3, 18, 9, 30, 0),
        fetched_at=datetime(2026, 3, 18, 12, 0, 0),
        raw_data={},
    )
    defaults.update(overrides)
    return JobListing(**defaults)


class TestRemotePolicyDerivation:
    """The percentage is authoritative; the text inference is a fallback only."""

    def test_unknown_percentage_falls_back_to_text(self):
        job = _make_job(remote_percentage=None, remote_policy_text="hybrid")
        assert job.remote_policy == "hybrid"

    def test_fully_remote_percentage_is_remote(self):
        assert _make_job(remote_percentage=100).remote_policy == "remote"

    def test_zero_percentage_is_onsite(self):
        assert _make_job(remote_percentage=0).remote_policy == "onsite"

    @pytest.mark.parametrize("percentage", [1, 50, 60, 99])
    def test_partial_percentage_is_hybrid(self, percentage):
        assert _make_job(remote_percentage=percentage).remote_policy == "hybrid"

    def test_percentage_wins_when_it_contradicts_the_text(self):
        """The whole reason the property exists: the two cannot disagree."""
        job = _make_job(remote_percentage=100, remote_policy_text="onsite")
        assert job.remote_policy == "remote"

    def test_percentage_wins_even_when_text_claims_remote(self):
        job = _make_job(remote_percentage=0, remote_policy_text="remote")
        assert job.remote_policy == "onsite"

    def test_defaults_to_not_specified(self):
        """A source that publishes neither signal says so, rather than guessing."""
        assert _make_job().remote_policy == "not_specified"

    @pytest.mark.parametrize("percentage,expected", [(-10, "onsite"), (120, "remote")])
    def test_out_of_range_percentages_clamp_to_the_nearest_end(self, percentage, expected):
        """>= and <= rather than ==, so a malformed source value cannot land in hybrid."""
        assert _make_job(remote_percentage=percentage).remote_policy == expected


class TestStrictnessIsScopedToTheProfile:
    """Profile models reject unknown keys; models fed from outside the repo do not.

    The distinction is the point, not an accident of which models happened to get
    `extra="forbid"`. `profile.yaml` is ours and a typo in it must fail loudly;
    Haiku's JSON and `feedback.yaml` are not, and a provider adding a response
    field must not break the pipeline.
    """

    # All three go through `model_validate`, which is the production path for the
    # two permissive models — evaluator.py parses Haiku's JSON and run.py reads
    # feedback.yaml, neither of which arrives as keyword arguments.

    def test_profile_model_rejects_an_unknown_key(self):
        with pytest.raises(ValidationError):
            LocationConfig.model_validate(
                {"target_countries": ["Germany"], "remote_acceptable": True}
            )

    def test_evaluation_result_ignores_an_unknown_key(self):
        result = EvaluationResult.model_validate({
            "match_score": 7,
            "matching_skills": ["RAG"],
            "gaps": [],
            "explanation": "Good fit.",
            "confidence": "high",        # a field Haiku might start returning
        })
        assert result.match_score == 7

    def test_feedback_entry_ignores_an_unknown_key(self):
        entry = FeedbackEntry.model_validate({
            "id": "job-1",
            "source": "freelancermap",
            "status": "applied",
            "noted_on": "2026-07-22",    # a column a future feedback.yaml might add
        })
        assert entry.status == "applied"
