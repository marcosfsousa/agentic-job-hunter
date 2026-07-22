"""Tests for behaviour on the core models.

`JobListing` is otherwise a plain dataclass with nothing to assert, so this module
covers the one field that is computed rather than stored: `remote_policy`.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from jobscout.models import JobListing


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

    @pytest.mark.parametrize("percentage", [-10, 120])
    def test_out_of_range_percentages_clamp_to_the_ends(self, percentage):
        """>= and <= rather than == , so a malformed source value cannot land in hybrid."""
        assert _make_job(remote_percentage=percentage).remote_policy in ("remote", "onsite")
