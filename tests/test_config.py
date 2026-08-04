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

from jobscout.adapters.freelancermap import _ROWS_PER_QUERY
from jobscout.config import get_config, reset_config
from jobscout.evaluation.prompt import SYSTEM_PROMPT
from jobscout.run import DEFAULT_MAX_RESULTS

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


def _shipped_german_entry() -> str:
    """The one `deprioritise` entry that states the German-language condition."""
    entries = get_config(profile_path=SHIPPED_PROFILE).profile.deprioritise
    return next(e for e in entries if "CEFR C1 or above" in e)


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

    def test_real_profile_german_entry_states_the_rule(self):
        """The entry has to carry the condition itself; the carve-outs it shares with
        SYSTEM_PROMPT are pinned by TestGermanClauseParity below."""
        assert "non-optional" in _shipped_german_entry()

    def test_real_profile_loads_as_utf8_regardless_of_platform_default(self):
        """#55: `_load_config` used a bare open(), so on Windows (cp1252) the German
        entry's em dash decoded to 'â€"' and that mojibake went to Haiku. It never
        raised, and Linux CI defaults to utf-8, so nothing caught it. Asserting the
        mojibake is absent — not just that the dash is present — is what makes this
        fail on the platform that actually breaks."""
        german = _shipped_german_entry()
        assert "—" in german
        assert "â€" not in german

    def test_real_profile_states_hourly_and_daily_independently(self):
        rate = get_config(profile_path=SHIPPED_PROFILE).profile.rate
        assert rate.minimum_hourly is not None
        assert rate.minimum_daily is not None
        assert rate.currency == "EUR"


# ---------------------------------------------------------------------------
# profile.yaml ←→ SYSTEM_PROMPT parity
# ---------------------------------------------------------------------------

# Both strings reach Haiku inside a single prompt, so a carve-out present in one and
# absent from the other is a self-contradicting prompt, not a style mismatch. #51 found
# the profile entry had drifted to a strict subset; #55 found the test that was supposed
# to have caught that never read SYSTEM_PROMPT at all — it asserted substrings on the
# profile side only, so a carve-out dropped from the prompt alone still passed.
#
# The two are worded differently and deliberately (the prompt instructs, the profile
# states a preference), so they cannot be compared literally. This table is the seam: one
# row per carve-out, naming the substring that must survive on each side. A fifth carve-out
# is one row here and nowhere else.
#
# Markers must be unique to the carve-out they pin. "von Vorteil" alone is not — the
# PRECEDENCE example uses the same words — which is exactly how the previous guard came to
# be satisfied by the wrong sentence.
GERMAN_CARVE_OUTS = [
    # (SYSTEM_PROMPT marker,            profile.yaml marker)
    ("a German job location",           "job location"),
    ("a German company name",           "company name"),
    ("a posting written in German",     "posting language"),
    ('"nice to have"/"von Vorteil"',    "von Vorteil"),
    ("German stated at B2 or below",    "B2 or below"),
    ("no level stated",                 "no level stated"),
    ("PRECEDENCE",                      "optional qualifier wins"),
    ("DISJUNCTION",                     "ALTERNATIVE to a language already held"),
]

# #54 graded the penalty, so the clause now carries two magnitudes. These are *fire*
# cues, not carve-outs — a row here means "both sides must still name this band" — but
# they reach Haiku through the same two strings and drift the same way, so they get the
# same guard. Dropping the 1-pt band from one side alone is what would silently restore
# the pre-#54 behaviour the issue was filed about.
GERMAN_FIRE_BANDS = [
    # (SYSTEM_PROMPT marker,            profile.yaml marker)
    ("CEFR C1 or above",                "C1 or above"),
    ('"Projektsprache: Deutsch"',       "declared working language"),
]

GERMAN_CLAUSE_ROWS = GERMAN_CARVE_OUTS + GERMAN_FIRE_BANDS


class TestGermanClauseParity:
    """Neither side may drop a clause row — carve-out or fire band — the other still names.

    Named for the union it is parametrised over, not for the carve-outs alone: a
    dropped fire band used to report as a dropped carve-out and send the reader to
    the wrong half of the prompt (#65)."""

    @pytest.mark.parametrize("prompt_marker, profile_marker", GERMAN_CLAUSE_ROWS)
    def test_clause_row_is_present_on_both_sides(self, prompt_marker, profile_marker):
        assert prompt_marker in SYSTEM_PROMPT, (
            f"SYSTEM_PROMPT dropped the {prompt_marker!r} rule that profile.yaml "
            f"still states as {profile_marker!r}"
        )
        assert profile_marker in _shipped_german_entry(), (
            f"profile.yaml dropped the {profile_marker!r} rule that SYSTEM_PROMPT "
            f"still states as {prompt_marker!r}"
        )

    @pytest.mark.parametrize("prompt_marker, profile_marker", GERMAN_CLAUSE_ROWS)
    def test_marker_pins_exactly_one_sentence_on_each_side(self, prompt_marker, profile_marker):
        """A marker that matches twice cannot pin the entry it claims to — the guard stays
        green while the sentence it was written for is deleted. Counted on both sides: the
        profile markers are the more generic of the two sets ('job location', 'company
        name'), so the half left uncounted is the half likelier to go ambiguous first."""
        assert SYSTEM_PROMPT.count(prompt_marker) == 1, (
            f"{prompt_marker!r} appears {SYSTEM_PROMPT.count(prompt_marker)} times in "
            f"SYSTEM_PROMPT — pick a marker unique to the clause row"
        )
        german = _shipped_german_entry()
        assert german.count(profile_marker) == 1, (
            f"{profile_marker!r} appears {german.count(profile_marker)} times in the "
            f"profile.yaml German entry — pick a marker unique to the clause row"
        )


class TestPoolBoundConfig:
    """`top_n` is the sole constant carrying CLAUDE.md's 'top 20–30 jobs only', and the
    scale-coupled `embedding_min_score` cosine floor is gone with no replacement."""

    def test_top_n_present_with_sane_default(self):
        config = get_config(profile_path=SHIPPED_PROFILE)
        assert config.top_n == 25

    def test_embedding_min_score_no_longer_exists(self):
        config = get_config(profile_path=SHIPPED_PROFILE)
        assert not hasattr(config, "embedding_min_score")


class TestFetchCeilingClearsTheSourceCeiling:
    """`DEFAULT_MAX_RESULTS` must exceed the most freelancermap can return in one run.

    Below that product the adapter truncates, and it drops whichever queries ran
    *last* — so appending a query costs coverage instead of adding it, which is the
    inverse of what adding one is for. The default was 100 while nine configured
    queries unioned to 132, and the four newest were exactly the ones being dropped.

    Derived from the real constants rather than restated: pinning the literal 250
    would keep passing if the request cap were raised, which is the one edit that
    can invalidate it.
    """

    def test_default_max_results_exceeds_requests_times_rows_per_query(self):
        config = get_config(profile_path=SHIPPED_PROFILE)
        ceiling = config.freelancermap_max_requests * _ROWS_PER_QUERY
        assert DEFAULT_MAX_RESULTS >= ceiling, (
            f"DEFAULT_MAX_RESULTS={DEFAULT_MAX_RESULTS} is below the {ceiling} rows "
            f"{config.freelancermap_max_requests} queries x {_ROWS_PER_QUERY} can yield; "
            "the adapter would truncate the last queries' rows."
        )

    def test_shipped_queries_fit_under_the_request_cap(self):
        """The spare-slot claim, asserted rather than left as prose."""
        config = get_config(profile_path=SHIPPED_PROFILE)
        n = len(config.profile.freelancermap_queries)
        assert n <= config.freelancermap_max_requests, (
            f"{n} configured queries exceed freelancermap_max_requests="
            f"{config.freelancermap_max_requests}; the surplus is dropped with a warning."
        )


class TestReevalBelowIsDecoupled:
    """`reeval_below` (re-eval cost floor) and `email_min_score` (digest gate) are two
    knobs that used to share one value. Raising the gate must no longer move the
    re-eval floor — the coupling this closes is issue #45."""

    def test_defaults_to_standalone_constant_not_email_min_score(self):
        # Shipped email_min_score is 5 and DEFAULT_REEVAL_BELOW is 4, so this assert
        # now distinguishes the two on the shipped profile alone. It did not always:
        # while the gate also sat at 4 the values coincided, and a still-coupled
        # config would have passed this. That is why the tie is broken independently
        # by the next test, which moves email_min_score in a tmp profile rather than
        # relying on the shipped one — it holds whatever the shipped gate is set to,
        # including if this one is ever lowered back onto the constant.
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
