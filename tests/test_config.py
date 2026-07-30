"""Tests for config loading — the `profile.yaml` → `UserProfile` seam.

Strict validation is asserted through `get_config(profile_path=...)` rather than
through `UserProfile.model_validate` on a dict, because the behaviour under test is
*this YAML file meets the schema* and the half that actually breaks in production is
the file. A dict-level test would skip it.

The failure mode being closed is silent: a key misspelled in `profile.yaml` falls back
to its Pydantic default, two hard gates quietly change what gets filtered, and every
other test in the suite still passes because they build `UserProfile` in code.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
import yaml
from pydantic import ValidationError

from jobscout.config import get_config, reset_config

# Located the same way tests/test_repo_invariants.py locates repo files, rather than
# by importing config.py's private root — the point here is to load the file that
# actually ships.
SHIPPED_PROFILE = Path(__file__).resolve().parent.parent / "profile.yaml"


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch):
    """`get_config` caches into a module singleton — clear it either side."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    reset_config()
    yield
    reset_config()


def _profile_with(tmp_path: Path, mutate: Callable[[dict], None]) -> Path:
    """Write a copy of the shipped profile with one mutation applied.

    Mutating the real file keeps the failure realistic: an otherwise-valid profile
    with one key wrong, not a junk document that any validation would reject.
    """
    data = yaml.safe_load(SHIPPED_PROFILE.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The shipped profile
# ---------------------------------------------------------------------------

class TestShippedProfileLoads:
    """With strictness on, this is what fails when the file and the model drift."""

    def test_real_profile_validates(self):
        profile = get_config(profile_path=SHIPPED_PROFILE).profile
        assert profile.name

    def test_real_profile_declares_the_two_new_gates(self):
        dealbreakers = get_config(profile_path=SHIPPED_PROFILE).profile.dealbreakers
        assert dealbreakers.exclude_contract_types == [
            "employee_leasing",
            "permanent_position",
        ]
        assert dealbreakers.minimum_remote_percentage == 100

    def test_real_profile_seeds_german_and_english_queries(self):
        queries = get_config(profile_path=SHIPPED_PROFILE).profile.freelancermap_queries
        assert "Machine Learning" in queries
        assert "Maschinelles Lernen" in queries

    def test_real_profile_states_hourly_and_daily_independently(self):
        rate = get_config(profile_path=SHIPPED_PROFILE).profile.rate
        assert rate.minimum_hourly is not None
        assert rate.minimum_daily is not None
        assert rate.currency == "EUR"


class TestPoolBoundConfig:
    """`top_n` is the sole constant carrying CLAUDE.md's 'top 20–30 jobs only', and the
    scale-coupled `embedding_min_score` cosine floor is gone with no replacement."""

    def test_top_n_present_with_sane_default(self):
        config = get_config(profile_path=SHIPPED_PROFILE)
        assert config.top_n == 25

    def test_embedding_min_score_no_longer_exists(self):
        config = get_config(profile_path=SHIPPED_PROFILE)
        assert not hasattr(config, "embedding_min_score")


class TestReevalBelowIsDecoupled:
    """`reeval_below` (re-eval cost floor) and `email_min_score` (digest gate) are two
    knobs that used to share one value. Raising the gate must no longer move the
    re-eval floor — the coupling this closes is issue #45."""

    def test_defaults_to_standalone_constant_not_email_min_score(self):
        # Shipped email_min_score is 4 today, so a passing assert would be ambiguous
        # if the two were still coupled. Pin against the constant, and the next test
        # breaks the tie by moving email_min_score away from it.
        from jobscout.config import DEFAULT_REEVAL_BELOW

        config = get_config(profile_path=SHIPPED_PROFILE)
        assert config.reeval_below == DEFAULT_REEVAL_BELOW

    def test_email_min_score_does_not_drag_reeval_below(self, tmp_path):
        from jobscout.config import DEFAULT_REEVAL_BELOW

        profile_path = _profile_with(tmp_path, lambda d: d.__setitem__("email_min_score", 9))
        config = get_config(profile_path=profile_path)
        assert config.profile.email_min_score == 9
        assert config.reeval_below == DEFAULT_REEVAL_BELOW  # unmoved

    def test_reeval_below_env_override_is_honoured(self, monkeypatch):
        monkeypatch.setenv("REEVAL_BELOW", "6")
        config = get_config(profile_path=SHIPPED_PROFILE)
        assert config.reeval_below == 6

    def test_reeval_below_zero_is_honoured_not_treated_as_unset(self, monkeypatch):
        # The nit folded in from the PR #42 review: a deliberate REEVAL_BELOW=0 (disable
        # re-evaluation) must survive, not be coerced back to a default by an `or`.
        monkeypatch.setenv("REEVAL_BELOW", "0")
        config = get_config(profile_path=SHIPPED_PROFILE)
        assert config.reeval_below == 0


# ---------------------------------------------------------------------------
# Strict validation
# ---------------------------------------------------------------------------

class TestUnrecognisedKeysAreRejected:
    """A typo must fail at load, not fall back to a default that changes filtering."""

    def test_misspelled_dealbreaker_key_raises(self, tmp_path):
        def mutate(data: dict) -> None:
            data["dealbreakers"]["minimum_remote_pct"] = data["dealbreakers"].pop(
                "minimum_remote_percentage"
            )

        path = _profile_with(tmp_path, mutate)
        with pytest.raises(ValidationError, match="minimum_remote_pct"):
            get_config(profile_path=path)

    def test_misspelled_contract_type_key_raises(self, tmp_path):
        def mutate(data: dict) -> None:
            data["dealbreakers"]["exclude_contract_type"] = data["dealbreakers"].pop(
                "exclude_contract_types"
            )

        path = _profile_with(tmp_path, mutate)
        with pytest.raises(ValidationError, match="exclude_contract_type"):
            get_config(profile_path=path)

    def test_stale_salary_block_raises(self, tmp_path):
        """A section left behind from the FTE era must not sit there doing nothing."""
        def mutate(data: dict) -> None:
            data["salary"] = {"minimum_annual_eur": 70000, "target_annual_eur": 85000}

        path = _profile_with(tmp_path, mutate)
        with pytest.raises(ValidationError, match="salary"):
            get_config(profile_path=path)

    def test_stale_location_field_raises(self, tmp_path):
        def mutate(data: dict) -> None:
            data["location"]["remote_acceptable"] = True

        path = _profile_with(tmp_path, mutate)
        with pytest.raises(ValidationError, match="remote_acceptable"):
            get_config(profile_path=path)

    def test_misspelled_query_list_raises(self, tmp_path):
        def mutate(data: dict) -> None:
            data["freelancer_map_queries"] = data.pop("freelancermap_queries")

        path = _profile_with(tmp_path, mutate)
        with pytest.raises(ValidationError, match="freelancer_map_queries"):
            get_config(profile_path=path)

    def test_out_of_range_remote_floor_raises(self, tmp_path):
        """A percentage outside 0-100 is unsatisfiable — it must not fail silently.

        The key is spelled right here, so strictness alone would not catch it; a
        floor of 1000 would simply reject every listing and produce an empty digest
        that looks like a quiet day.
        """
        def mutate(data: dict) -> None:
            data["dealbreakers"]["minimum_remote_percentage"] = 1000

        path = _profile_with(tmp_path, mutate)
        with pytest.raises(ValidationError, match="minimum_remote_percentage"):
            get_config(profile_path=path)

    def test_null_remote_floor_is_allowed(self, tmp_path):
        """Disabling the gate stays expressible without deleting the key."""
        def mutate(data: dict) -> None:
            data["dealbreakers"]["minimum_remote_percentage"] = None

        path = _profile_with(tmp_path, mutate)
        profile = get_config(profile_path=path).profile
        assert profile.dealbreakers.minimum_remote_percentage is None

    def test_misspelled_rate_key_raises(self, tmp_path):
        def mutate(data: dict) -> None:
            data["rate"]["min_hourly"] = data["rate"].pop("minimum_hourly")

        path = _profile_with(tmp_path, mutate)
        with pytest.raises(ValidationError, match="min_hourly"):
            get_config(profile_path=path)
