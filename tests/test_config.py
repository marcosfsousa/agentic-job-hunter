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

from jobscout.config import _PROJECT_ROOT, get_config, reset_config

SHIPPED_PROFILE = _PROJECT_ROOT / "profile.yaml"


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

    def test_misspelled_rate_key_raises(self, tmp_path):
        def mutate(data: dict) -> None:
            data["rate"]["min_hourly"] = data["rate"].pop("minimum_hourly")

        path = _profile_with(tmp_path, mutate)
        with pytest.raises(ValidationError, match="min_hourly"):
            get_config(profile_path=path)
