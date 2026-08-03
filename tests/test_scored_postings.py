"""The A2 regression corpus (#96) — hand-scored postings, asserted at band level.

Nothing in the suite before this asserted anything about *scoring quality*.
`test_evaluation.py` mocks Haiku and checks plumbing — score propagation, fence
stripping, sort order — so all eight defects in § 1 of the scoring handoff were found
by hand-reading a digest, twelve days after the first one shipped. This file is the
corpus that makes the ninth one cost a test run instead.

TWO MODES, AND WHY

*Offline* (default, and what CI runs). The assertion is `band(recorded tool score) ==
expected band` — no network, no API key, no posting text. What it guards is not the
model: it is the record. Six cases are marked `baseline: fail` and xfail **strictly**,
so the day a Wave C change moves one into its band, the XPASS turns the suite red and
someone has to re-record the score and flip the flag. A silent improvement and a silent
regression are equally impossible.

*Live* (`JOBSCOUT_LIVE_EVAL=1`, needs `ANTHROPIC_API_KEY` and the gitignored posting
text). Re-scores through the real `evaluate_jobs` and asserts the same bands against a
fresh draw. This is the mode that measures a calibration change; the offline mode
records what it measured.

THE FIDELITY LIMIT. An excerpt-scored fixture is **not** the conditions the human score
was assigned under: the human read the whole posting, the scorer sees a fragment. So a
live result on a `provenance: excerpt` fixture is evidence about **the rule** — did the
clause fire, in the direction the rule states — and not about **the score**. It does not
support "the tool would now score this posting correctly", and no rule should be tuned
until an excerpt reproduces a human number. The limit is structural, not a caveat to be
engineered away: removing it means keeping the full posting text, which is the thing the
excerpting rule exists to prevent. `text_provenance` records the shape per case, each
excerpt file repeats it in its front matter, and `_read_posting` fails if the two
disagree. The offline baseline is unaffected — it asserts against a tool score produced
from the full posting in a real run, and never reads the text at all.

BAND, NOT EXACT SCORE — #96's scope, restated because it is the constraint most likely
to be "improved" away: the goal is catching a 1 scored as a 5, not arguing 6 vs 6.5.
Exact-score assertions on a stochastic model get disabled within a month.

WHAT THE BAND CANNOT SEE. Two of the eight confirmed defects (D1 on #3004625, D4 on
#3028920) move the score by less than a band, so they are `pass_with_known_defect`:
they will pass here forever and be caught by #97 and #98 against the fields and the
trace, not the band. `test_sub_band_defects_are_recorded_and_invisible_here` asserts
that state deliberately, so a green run never reads as "all eight are covered".

`reeval_below` IS PINNED TO 0. Production re-evaluates anything below 4 and keeps the
**higher** of two draws (`evaluator.py:51-66`). Six of the eight cases sit in that
range, so unpinned they would be scored by max-of-two and a band assertion would flake
on the second draw. The pin is asserted twice — as a constant, and behaviourally against
the real evaluator.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from jobscout.evaluation.evaluator import evaluate_jobs
from jobscout.models import JobListing, ScoredJob

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_MANIFEST_PATH = _FIXTURE_DIR / "scored_postings.yaml"

# Gitignored: third-party posting text, held locally only. See the manifest header.
_POSTING_TEXT_DIR = _FIXTURE_DIR / "scored_postings"

# 0 disables re-evaluation entirely — no score can be below 0 (`match_score` is
# `ge=1`). Not `1`: the sibling pin in test_evaluation.py's TestSortOrder uses 1 for
# the same effect, but 0 is the value config.py documents as "disables re-evaluation",
# and this harness wants the documented off switch rather than an equivalent one.
HARNESS_REEVAL_BELOW = 0

_LIVE_ENV_VAR = "JOBSCOUT_LIVE_EVAL"

# Verbatim and shared, so `grep` finds every assertion a band cannot decide — here and
# in whatever #97 and #98 add. Non-strict on purpose: these two assertions *pass* today
# and would pass with D1 and D4 unfixed, which is the whole point. Marking them xfail
# says "this assertion cannot decide this case"; strict would demand they fail, which
# they do not and should not. They report as XPASS, and XPASS is not an error here.
BAND_BLIND_REASON = "band assertion cannot detect this defect; needs score_trace (#95)"

# § 6 lists fourteen cases. Pinned as a number so a dropped row is a failure rather
# than a smaller parametrisation nobody notices.
_EXPECTED_CASE_COUNT = 14


# ---------------------------------------------------------------------------
# Manifest loading and banding
# ---------------------------------------------------------------------------

def _load_manifest() -> dict:
    # Explicit utf-8 for the same reason config.py gives: the manifest carries German
    # posting titles and em dashes, and a bare open() decodes them via cp1252 on
    # Windows while Linux CI never notices (#55).
    with _MANIFEST_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


_MANIFEST = _load_manifest()
_BANDS: dict[str, dict[str, float]] = _MANIFEST["bands"]
_CASES: list[dict] = _MANIFEST["cases"]


def band_of(score: float) -> str | None:
    """Return the band a score falls in, or None if it falls between bands.

    The cut points come from the manifest, not from constants here, so #96's
    `hard_skip <= 4.5 / marginal 5-6.5 / apply >= 7` is stated once. Returning None
    rather than raising keeps the gaps (4.5-5.0, 6.5-7.0) visible as data: an integer
    `match_score` can never land in one, so a None is always a manifest error, and
    `test_every_score_lands_in_a_band` is where that is reported.
    """
    for name, bounds in _BANDS.items():
        low = bounds.get("min")
        high = bounds.get("max")
        if (low is None or score >= low) and (high is None or score <= high):
            return name
    return None


def _case_id(case: dict) -> str:
    """Test id: the manifest key plus the rule, so a failure names what broke."""
    return f"{case['id']}-{case['label'].replace(' ', '-')}"


def _cases_with(baseline: str) -> list[dict]:
    return [c for c in _CASES if c["baseline"] == baseline]


def _recorded_cases() -> list[dict]:
    """Cases carrying a recorded tool score, xfail-marked from the manifest.

    The marker is driven by the declared `baseline` field and **not** by comparing the
    scores — deriving it would make the assertion self-fulfilling and the test would
    pass no matter what the manifest said.
    """
    params = []
    for case in _CASES:
        if case["tool_score"] is None:
            continue
        marks = []
        if case["baseline"] == "pass_with_known_defect":
            marks.append(pytest.mark.xfail(reason=BAND_BLIND_REASON))
        if case["baseline"] == "fail":
            marks.append(
                pytest.mark.xfail(
                    strict=True,
                    reason=(
                        f"recorded baseline failure: tool scored {case['tool_score']} "
                        f"({band_of(case['tool_score'])}), human scored "
                        f"{case['human_score']} ({case['expected_band']}) — "
                        f"exercises {case['exercises']}"
                    ),
                )
            )
        params.append(pytest.param(case, marks=marks, id=_case_id(case)))
    return params


# ---------------------------------------------------------------------------
# Manifest integrity — the corpus itself, before any scoring
# ---------------------------------------------------------------------------

class TestCorpusIntegrity:
    def test_all_fourteen_section_6_cases_are_present(self):
        assert len(_CASES) == _EXPECTED_CASE_COUNT

    def test_case_ids_are_unique(self):
        ids = [c["id"] for c in _CASES]
        assert len(set(ids)) == len(ids)

    def test_every_case_names_the_rule_it_exercises(self):
        """#96's second acceptance criterion. A fixture that does not say what it is
        for becomes a fixture nobody dares delete and nobody can act on."""
        unlabelled = [c["id"] for c in _CASES if not str(c.get("exercises", "")).strip()]
        assert unlabelled == []

    def test_every_case_declares_a_known_band(self):
        assert {c["expected_band"] for c in _CASES} <= set(_BANDS)

    def test_every_score_lands_in_a_band(self):
        """Catches a transcription error into one of the two gaps between bands."""
        stranded = [
            (c["id"], c["human_score"])
            for c in _CASES
            if band_of(c["human_score"]) is None
        ]
        assert stranded == []

    def test_human_score_agrees_with_its_declared_band(self):
        """The band is derived from the human score, so a row where they disagree is a
        typo in one of the two — and it would silently redefine what the case tests."""
        disagreeing = [
            (c["id"], c["human_score"], c["expected_band"], band_of(c["human_score"]))
            for c in _CASES
            if band_of(c["human_score"]) != c["expected_band"]
        ]
        assert disagreeing == []

    def test_every_baseline_value_is_one_of_the_three(self):
        assert {c["baseline"] for c in _CASES} <= {
            "fail",
            "pass_with_known_defect",
            "unrecorded",
        }

    def test_every_case_declares_its_text_provenance(self):
        """`excerpt`, `full` or `absent` — what the local text file is, if any.

        Recorded per case because it bounds what a live result means: an excerpt is
        not the conditions the human score was assigned under. See the fidelity limit
        in the module docstring.
        """
        assert {c["text_provenance"] for c in _CASES} <= {"excerpt", "full", "absent"}

    def test_provenance_and_live_rescorability_agree(self):
        """A case is live-rescorable exactly when there is text to score it against.

        The two are separate fields because they answer different questions — "is
        there a local file" and "what is in it" — and a row where they disagree either
        silently skips a case that has text, or promises a live run that cannot happen.
        """
        for case in _CASES:
            has_text = case["text_provenance"] != "absent"
            assert bool(case.get("live_rescorable")) == has_text, case["id"]

    def test_unrecorded_cases_carry_no_tool_score_and_scored_cases_do(self):
        """`unrecorded` means § 6 left the Tool column empty. The two must not drift:
        a tool score on an `unrecorded` row would be silently excluded from the band
        assertion below, which is exactly the coverage gap this corpus exists to close."""
        for case in _CASES:
            if case["baseline"] == "unrecorded":
                assert case["tool_score"] is None, case["id"]
            else:
                assert case["tool_score"] is not None, case["id"]


# ---------------------------------------------------------------------------
# The offline baseline
# ---------------------------------------------------------------------------

class TestRecordedBaseline:
    """Band assertions against the score the tool last recorded.

    Runs with no network, no API key and no posting text — which is what lets it run
    in CI at all, given the posting text cannot be committed.
    """

    @pytest.mark.parametrize("case", _recorded_cases())
    def test_recorded_tool_score_is_in_band(self, case):
        actual = band_of(case["tool_score"])
        assert actual == case["expected_band"], (
            f"{case['id']} ({case['label']}): tool scored {case['tool_score']} "
            f"-> {actual}, human scored {case['human_score']} -> "
            f"{case['expected_band']}. Exercises: {case['exercises']}."
        )

    def test_the_baseline_is_six_band_visible_failures(self):
        """#96 says eight failures; band assertions see six of them.

        Stated as a number here so the count cannot drift quietly in either direction —
        a fix that lands without re-recording, or a new case slipped in as expected-red.
        The other two are the sub-band pair below. This is the "recorded as an expected
        baseline and visible as such" criterion: `pytest -q` reports `6 xfailed`, and
        this test is where the 8-vs-6 arithmetic is written down.
        """
        assert len(_cases_with("fail")) == 6
        assert len(_cases_with("pass_with_known_defect")) == 2

    def test_every_baseline_failure_really_does_miss_its_band(self):
        """Guards the xfail markers, which are declared rather than derived.

        A row marked `baseline: fail` whose recorded score is actually in band would
        xpass — strict, so it fails loudly — but only when someone runs the suite. This
        says it directly, and names the row.
        """
        wrongly_marked = [
            c["id"]
            for c in _cases_with("fail")
            if band_of(c["tool_score"]) == c["expected_band"]
        ]
        assert wrongly_marked == []

    def test_sub_band_defects_are_recorded_and_invisible_here(self):
        """D1 (#3004625) and D4 (#3028920) are confirmed defects that pass at band level.

        Both move the score by less than a band, so no band assertion can ever catch
        them — D1 is a defect in the *contents* of `gaps`, D4 in the *provenance label*
        on a language penalty, and neither moves magnitude. Their band assertions carry
        `BAND_BLIND_REASON` and report as XPASS, which is the honest signal: the
        assertion runs, passes, and decides nothing. Asserting that state explicitly
        stops a green run from reading as "all eight § 1 defects are covered" — they are
        not. The real assertions land with #97 (`gaps` contents) and #98 (rule evidence
        provenance).
        """
        sub_band = _cases_with("pass_with_known_defect")
        assert {c["id"] for c in sub_band} == {"3004625", "3028920"}
        for case in sub_band:
            assert band_of(case["tool_score"]) == case["expected_band"], case["id"]
            assert str(case.get("sub_band_defect", "")).strip(), (
                f"{case['id']} is marked pass_with_known_defect but does not say what "
                "the defect is — the marking is the only record that it exists"
            )

    def test_unrecorded_controls_are_reported_not_silently_absent(self):
        """Six cases have no tool score, so the offline mode cannot assert anything
        about them. Three are the corpus's only positive controls — without them a
        change that drives every score down looks like six fixed failures."""
        unrecorded = _cases_with("unrecorded")
        assert len(unrecorded) == 6
        positive_controls = [c for c in unrecorded if c["expected_band"] == "apply"]
        assert len(positive_controls) == 3


# ---------------------------------------------------------------------------
# The reeval pin
# ---------------------------------------------------------------------------

class TestReevalPin:
    """`reeval_below` is pinned to 0 for every scoring run this file performs.

    Production keeps the higher of two draws for anything below 4 (`evaluator.py:51-66`,
    `config.py:23,82`). Six of the eight recorded cases target `hard_skip`, which sits
    inside that range, so under the production default those fixtures would be scored by
    max-of-two — and a band assertion on a stochastic model would flake on the second
    draw. #96 requires the pin; these two tests are it.
    """

    def test_harness_pins_reeval_below_to_zero(self):
        assert HARNESS_REEVAL_BELOW == 0

    async def test_the_pin_actually_suppresses_the_second_draw(self):
        """Behavioural, not declarative: asserting the constant only proves the constant.

        A score of 1 is as far below the production floor of 4 as a score can be, so
        under the default this job would be evaluated twice. With the pin it is
        evaluated once, and the low score survives instead of being replaced by a
        luckier draw.
        """
        low = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text='{"match_score": 1, "matching_skills": [], "gaps": [], '
                    '"explanation": "Blocked."}'
                )
            ]
        )
        lucky = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text='{"match_score": 8, "matching_skills": [], "gaps": [], '
                    '"explanation": "Second draw."}'
                )
            ]
        )
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[low, lucky])

        job = ScoredJob(listing=_stub_listing("pin-1"), embedding_score=0.5)
        results = await evaluate_jobs(
            [job],
            _stub_profile(),
            client,
            model="mock-model",
            top_n=1,
            reeval_below=HARNESS_REEVAL_BELOW,
        )

        assert client.messages.create.call_count == 1
        assert results[0].evaluation is not None
        assert results[0].evaluation.match_score == 1
        assert band_of(results[0].evaluation.match_score) == "hard_skip"


def _stub_listing(id: str) -> JobListing:
    """Minimal listing for the pin test, which is about call counts, not content."""
    return JobListing(
        id=id,
        source="test",
        title="ML Engineer",
        company="Test GmbH",
        description="Irrelevant — the mocked client never reads it.",
        location="Berlin, Germany",
        url=f"https://example.com/job/{id}",
        posted_date=datetime(2026, 8, 3, 9, 0, 0),
        fetched_at=datetime(2026, 8, 3, 12, 0, 0),
        raw_data={},
    )


def _stub_profile():
    from jobscout.models import (
        DealbreakersConfig,
        LocationConfig,
        RateConfig,
        SkillsConfig,
        UserProfile,
    )

    return UserProfile(
        name="Marcos",
        target_roles=["AI Engineer"],
        skills=SkillsConfig(strong=["RAG systems"], working_knowledge=["Python"]),
        location=LocationConfig(target_countries=["Germany"]),
        rate=RateConfig(),
        dealbreakers=DealbreakersConfig(),
        freelancermap_queries=["Machine Learning"],
    )


# ---------------------------------------------------------------------------
# Live re-scoring — opt-in, never in CI
# ---------------------------------------------------------------------------

def _live_cases() -> list:
    """The cases whose posting text exists locally, xfail-marked as offline."""
    params = []
    for case in _CASES:
        if not case.get("live_rescorable"):
            continue
        marks = []
        if case["baseline"] == "fail":
            marks.append(
                pytest.mark.xfail(
                    strict=True,
                    reason=f"recorded baseline failure — exercises {case['exercises']}",
                )
            )
        params.append(pytest.param(case, marks=marks, id=_case_id(case)))
    return params


# Required in every excerpt's front matter, and deliberately not defaulted.
# `build_prompt` puts title, company and location in the request (prompt.py:126-128),
# so an absent company would be scored as "unknown" — and for #3028920 that is the
# input under test, not decoration: the German penalty fired on language inferred from
# the company and the location, which is the inference the rule carves out. A default
# there would silently anonymise the signal and leave a case that passes without
# testing anything. Fail instead.
_REQUIRED_FRONT_MATTER = ("title", "company", "location", "provenance")


def _read_posting(case: dict) -> tuple[dict, str]:
    """Parse `<id>.md`: YAML front matter between `---` fences, then the excerpt."""
    path = _POSTING_TEXT_DIR / f"{case['id']}.md"
    if not path.exists():
        pytest.skip(
            f"{path} is missing. It is gitignored on purpose — third-party posting text "
            "is not committed to this repo (see the manifest header). Live mode needs "
            "the local copy."
        )
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        pytest.fail(f"{path} has no YAML front matter — see the manifest header format")
    _, front_matter_text, body = text.split("---", 2)
    front_matter = yaml.safe_load(front_matter_text) or {}

    missing = [k for k in _REQUIRED_FRONT_MATTER if not str(front_matter.get(k, "")).strip()]
    if missing:
        pytest.fail(
            f"{path} is missing required front matter: {', '.join(missing)}. "
            "Keep the company and the location unanonymised — they reach the model and "
            f"for some cases they are the signal. See `excerpt_must_keep` on this case "
            "in the manifest."
        )

    # The file states what it is, and the manifest states what it should be. Checked
    # rather than trusted: a full posting sitting behind a case declared `excerpt` would
    # quietly turn a rule-level result into a score-level claim, which is the one
    # inference the fidelity limit forbids. Drift in the other direction — an excerpt
    # behind a `full` declaration — overstates the result the same way.
    declared = front_matter["provenance"]
    if declared != case["text_provenance"]:
        pytest.fail(
            f"{path} declares `provenance: {declared}` but the manifest records "
            f"`text_provenance: {case['text_provenance']}` for {case['id']}. One of "
            "them is wrong, and which one changes what a live result here means."
        )
    return front_matter, body.strip()


@pytest.mark.skipif(
    os.environ.get(_LIVE_ENV_VAR) != "1",
    reason=(
        f"live re-scoring is opt-in: set {_LIVE_ENV_VAR}=1 with ANTHROPIC_API_KEY and "
        "the local posting text. Never enabled in CI — it costs money and it is not "
        "deterministic."
    ),
)
class TestLiveRescoring:
    """Re-score the six postings whose text exists locally, through the real evaluator.

    One real API call per case, `reeval_below` pinned so it is exactly one. The offline
    baseline records what this measured; this is what does the measuring — and it is
    what Wave C runs before and after a prompt change.
    """

    @pytest.fixture(scope="class")
    def config(self):
        from jobscout.config import get_config, reset_config

        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY is not set")
        reset_config()  # the singleton may hold a fixture profile from another module
        try:
            yield get_config()
        finally:
            reset_config()

    @pytest.mark.parametrize("case", _live_cases())
    async def test_posting_scores_in_band(self, case, config):
        import anthropic

        front_matter, body = _read_posting(case)
        listing = JobListing(
            id=case["id"],
            source="freelancermap",
            title=front_matter["title"],
            company=front_matter["company"],
            description=body,
            location=front_matter["location"],
            url=front_matter.get("url", ""),
            posted_date=None,
            fetched_at=datetime.now(),
            raw_data={},
            remote_percentage=front_matter.get("remote_percentage"),
        )

        client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        results = await evaluate_jobs(
            [ScoredJob(listing=listing, embedding_score=0.0)],
            config.profile,
            client,
            model=config.llm_model,
            top_n=1,
            reeval_below=HARNESS_REEVAL_BELOW,
        )

        assert results[0].evaluation is not None, (
            f"{case['id']}: the model returned nothing parseable — that is an evaluator "
            "failure, not a scoring one"
        )
        score = results[0].evaluation.match_score
        # The caveat travels with the result rather than living only in the docstring:
        # this message is what someone reads at the moment they are deciding what the
        # number means, which is the moment the fidelity limit is easiest to forget.
        fidelity = (
            "Scored against an EXCERPT — the clauses the rule reads, not the posting "
            "the human scored. Read this as evidence about the rule, not about the "
            "score."
            if front_matter["provenance"] == "excerpt"
            else "Scored against the full posting text."
        )
        assert band_of(score) == case["expected_band"], (
            f"{case['id']} ({case['label']}): live score {score} -> {band_of(score)}, "
            f"human scored {case['human_score']} -> {case['expected_band']}. "
            f"Exercises: {case['exercises']}. {fidelity}"
        )
