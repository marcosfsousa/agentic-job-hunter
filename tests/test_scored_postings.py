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
import re
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
# The reason named #95 while `score_trace` was still unbuilt; #95 has since landed, so it
# now names #97/#98 — the assertions that consume the trace — which is when this comes off.
BAND_BLIND_REASON = (
    "band assertion cannot detect this defect; needs the score_trace assertions (#97/#98)"
)

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


# A listing whose every field is fixed, used only to render `build_prompt` for the
# fingerprint below. Its contents are irrelevant and deliberately carry no posting text
# — it is a constant, so anything that moves the fingerprint moved on the *profile* or
# `SYSTEM_PROMPT` side, which is the whole point.
_FINGERPRINT_STUB = JobListing(
    id="fingerprint-stub", source="none", title="stub", company="stub",
    description="stub", location="stub", url="", posted_date=None,
    fetched_at=datetime(2026, 1, 1), raw_data={},
)


def _input_fingerprint() -> str:
    """Hash of everything `build_prompt` sends the model — not just `SYSTEM_PROMPT`.

    A `SYSTEM_PROMPT`-only fingerprint would have missed #100 entirely. That PR changed
    `skills.strong` in profile.yaml, `build_prompt` sends `skills.strong` on every call
    (prompt.py), and it silently invalidated an in-flight baseline on another branch —
    the second time a merge to main has done that. #117's draft convention does not
    catch this class: #100 had no open decision, it simply changed an input a different
    branch was measuring against.

    So the fingerprint is taken over the *rendered* prompt rather than an enumerated
    list of fields. Anything `build_prompt` starts sending later is covered without
    anyone remembering to add it here — which is the failure mode an enumerated list
    would eventually have.

    Reads profile.yaml directly rather than through `get_config`, because that requires
    a non-empty ANTHROPIC_API_KEY and this has to work in CI with no key at all.
    """
    import hashlib

    from jobscout.evaluation.prompt import SYSTEM_PROMPT, build_prompt
    from jobscout.models import UserProfile

    profile_path = Path(__file__).resolve().parent.parent / "profile.yaml"
    with profile_path.open(encoding="utf-8") as f:
        profile = UserProfile.model_validate(yaml.safe_load(f))

    rendered = SYSTEM_PROMPT + "\n" + build_prompt(_FINGERPRINT_STUB, profile)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:12]


# Every key a case may carry. The manifest records the score and the case's identity;
# the posting itself lives only in the gitignored fixture directory. Adding a key here
# is a deliberate act — see `test_the_manifest_carries_no_posting_text`.
_ALLOWED_CASE_KEYS = frozenset({
    # identity and the human's judgement
    "id", "label", "human_score", "human_score_approximate",
    "expected_band",
    # what the tool did, and what that makes this case
    "tool_score", "baseline", "defects", "sub_band_defect",
    # what the case is for
    "exercises", "rules", "issues", "sequencing_constraint",
    # where the text is, and whether it can be re-scored
    "text_provenance", "live_rescorable",
    # what the rules did on the excerpt, under a named prompt (#96 amendment)
    "live_baseline",
    # rules that must NOT fire on this case once its issues' fixes have landed
    "must_not_fire",
    # why a case cannot be expressed yet (see #110)
    "expressibility_gap",
    # commentary on the tool's behaviour and on score provenance — never on the posting
    "notes",
})


def _is_blank(value: object) -> bool:
    """Whether a YAML value counts as absent.

    `key:` with no value parses to `None`, and `str(None)` is the four truthy
    characters `None` — so the obvious `str(d.get(k, "")).strip()` reports a
    blank key as present. Every guard below that treats "declared but empty" as
    a false pass has to check the value, not its repr.
    """
    return value is None or not str(value).strip()


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
        unlabelled = [c["id"] for c in _CASES if _is_blank(c.get("exercises"))]
        assert unlabelled == []

    def test_the_manifest_carries_no_posting_text(self):
        """The manifest records the score, never the input that produced it.

        Enforced structurally — on the set of keys, not by trying to detect prose,
        because the failure this guards against does not look like posting text. It
        looks like a helpful field called `excerpt_must_keep` describing what a body
        should contain. A description is not a safe substitute for the clause either:
        B2's test turns on the word `oder`, and a described disjunction is not a
        disjunction, so a manifest that summarised it would read as though it
        documented the case while testing nothing.

        Anything a maintainer needs in order to *build* a body is a description of
        that body, and lives beside the fixtures in the gitignored directory.
        """
        stray = sorted({k for c in _CASES for k in c} - _ALLOWED_CASE_KEYS)
        assert stray == [], (
            f"{stray} are not allowed in the manifest. If a field describes, quotes or "
            f"summarises a posting body it belongs in {_POSTING_TEXT_DIR.name}/, which "
            "is gitignored. If it records a tool output or case metadata, add it to "
            "_ALLOWED_CASE_KEYS with a reason."
        )

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

    def test_live_rescorable_rows_have_text(self):
        """One direction: a row promising a live run must have text to score.

        This was an equivalence until the #96 amendment (2026-08-04). The reverse
        direction — text present therefore in rotation — had to go, because a row can
        now be withdrawn from live rotation for a reason that has nothing to do with
        whether its text exists: #2999393 exercises Wave D2, which is unfiled, so
        nothing in Waves A-C will move it and a live draw on it measures nothing.
        Forcing that row to declare `text_provenance: absent` to leave rotation would
        have made the manifest lie about a file that is sitting on disk.
        """
        for case in _CASES:
            if case.get("live_rescorable"):
                assert case["text_provenance"] != "absent", case["id"]

    def test_withdrawn_rows_say_why(self):
        """The compensating assertion for the direction dropped above.

        What the equivalence used to guarantee is that a row with text could not sit
        idle unnoticed. Losing that silently is worse than the lie it replaced: an
        unexplained `live_rescorable: false` on a row that HAS text is indistinguishable
        from a row someone disabled to quiet a failure. So it must say why, and the
        reason is a key rather than a comment — which is what finally makes the harness
        read `expressibility_gap`, an allowed key that until now no test consumed.
        """
        for case in _CASES:
            withdrawn = not case.get("live_rescorable")
            if withdrawn and case["text_provenance"] != "absent":
                assert case.get("expressibility_gap"), (
                    f"{case['id']} has posting text but is out of live rotation, and "
                    "does not say why. Record the reason in `expressibility_gap` — a "
                    "row withdrawn without one is indistinguishable from a failure "
                    "someone silenced."
                )

    def test_live_baselines_are_well_formed_and_name_real_rules(self):
        """`live_baseline` is data, so its shape is asserted rather than trusted.

        `fired` holds INTEGERS against a stated `n`, not "9/10" strings: `n` is recorded
        once on the row, so a k/n string would encode the denominator twice and let the
        two drift — and a string cannot be compared to a threshold without parsing it.

        Rule ids are checked against `RULE_IDS`, which the rubric derives from its own
        `[tag]`s. A typo'd id would otherwise sit in the manifest forever, matching
        nothing and quietly asserting nothing.
        """
        from jobscout.evaluation.prompt import RULE_IDS

        required = ("n", "prompt_commit", "input_fingerprint", "temperature", "recorded",
                    "fired", "scores")
        for case in _CASES:
            recorded = case.get("live_baseline")
            if not recorded:
                continue
            cid = case["id"]
            missing = [k for k in required if recorded.get(k) is None]
            assert not missing, f"{cid}: live_baseline missing {missing}"

            n = recorded["n"]
            assert len(recorded["scores"]) == n, (
                f"{cid}: live_baseline records {len(recorded['scores'])} scores but "
                f"claims n={n}. The score list IS the sample; a mismatch means one of "
                "the two was edited by hand."
            )
            for rule, k in recorded["fired"].items():
                assert isinstance(k, int) and 0 <= k <= n, (
                    f"{cid}: live_baseline fired[{rule}] is {k!r}, which is not an "
                    f"integer in 0..{n}. Frequencies are k-of-n integers, not strings."
                )
            unknown = sorted(set(recorded["fired"]) - set(RULE_IDS))
            assert not unknown, (
                f"{cid}: live_baseline names rules that no longer exist in the "
                f"rubric: {unknown}. Either the id is a typo, or the rule was renamed "
                "and this baseline needs re-recording under the current prompt."
            )

    def test_must_not_fire_lists_are_coherent(self):
        """`must_not_fire` is a standing guard, and it must not contradict its own row.

        WHY THE KEY EXISTS. The live comparison asserts on rules the baseline saw fire
        on every draw, which cannot express "this rule must be ABSENT". #98 drives
        `penalty_german_language` from firing to not firing — so after the fix it leaves
        the fired set entirely and nothing would assert on it again. The issue would
        ship with a one-time verdict and no regression guard: the rule could come back
        at 6/10 next month and the suite would stay green.

        Excluding partial-frequency rules from the *positive* assertions stays correct —
        asserting on `penalty_cloud_core` at 4/10 would fail on the sampler, not the
        rubric. But "not asserted because unstable" and "asserted to be absent" are
        different states, and only the first had a representation.

        POPULATED BY THE FIX, NOT BY THIS SCHEMA. Every list is empty today, because no
        fix has landed: declaring `penalty_german_language` must-not-fire while it still
        fires 10/10 would be a red the schema commit has no business creating. #98 and
        #101 each add their own rule here in their own PR, at the same time as they
        re-record `live_baseline` — so the guard becomes real exactly when the behaviour
        does. The assertion below is what stops those two facts from drifting apart.
        """
        from jobscout.evaluation.prompt import RULE_IDS

        for case in _CASES:
            forbidden = case.get("must_not_fire") or []
            unknown = sorted(set(forbidden) - set(RULE_IDS))
            assert not unknown, (
                f"{case['id']}: must_not_fire names rules not in the rubric: {unknown}"
            )
            recorded = case.get("live_baseline")
            if not recorded:
                continue
            contradicted = sorted(
                rule for rule in forbidden
                if recorded["fired"].get(rule, 0) == recorded["n"]
            )
            assert not contradicted, (
                f"{case['id']}: {contradicted} are declared must-not-fire, but this "
                f"row's own `live_baseline` records them firing on all "
                f"{recorded['n']} draws. Either the fix has not landed and the guard is "
                "premature, or it has and the baseline was never re-recorded. Both are "
                "the same bug: a guard and the evidence under it disagreeing."
            )

    def test_live_baselines_declare_the_temperature_they_were_taken_at(self):
        """A baseline taken at a temperature other than the pinned default says so.

        Recorded per baseline rather than assumed, because the whole reason these exist
        is that the pipeline spent its life at an unpinned 1.0 and nothing said so. A
        measurement of the sampler and a measurement of the rubric are different things
        and must not be confusable after the fact.
        """
        from jobscout.config import AppConfig

        pinned = AppConfig.model_fields["llm_temperature"].default
        for case in _CASES:
            recorded = case.get("live_baseline")
            if not recorded:
                continue
            assert recorded["temperature"] == pinned, (
                f"{case['id']}: live_baseline was taken at temperature "
                f"{recorded['temperature']}, not the pinned {pinned}. That is allowed — "
                "the harness raises it deliberately to measure spread — but such a "
                "baseline measures the sampler and must not be used as a rubric "
                "before/after. Record it elsewhere or re-take it pinned."
            )

    def test_live_baselines_are_not_stale(self):
        """A baseline recorded against different model inputs announces itself.

        This is the guard, and it is the point of the fingerprint. Twice now a merge to
        main has invalidated measurement in flight on another branch — #111, then #100,
        which changed `skills.strong` while this corpus was being measured against it.
        Neither was blocked on a decision, so #117's draft convention does not catch the
        class: the merge was legitimate and simply moved an input.

        Before, catching it depended on somebody noticing. Now the suite does.
        """
        current = _input_fingerprint()
        stale = [
            (c["id"], c["live_baseline"]["input_fingerprint"])
            for c in _CASES
            if c.get("live_baseline")
            and c["live_baseline"]["input_fingerprint"] != current
        ]
        assert not stale, (
            f"live_baseline is stale for {[s[0] for s in stale]} — recorded against "
            f"model inputs {[s[1] for s in stale]}, current is {current}. "
            "`SYSTEM_PROMPT` or profile.yaml has changed since these were measured, so "
            "they describe an input the model is no longer given. Re-measure before "
            "using them as a before/after; do NOT edit the fingerprint to match."
        )

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
            assert not _is_blank(case.get("sub_band_defect")), (
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

def _live_band_cases() -> list:
    """Live rows whose text is the WHOLE posting — the only rows a band can judge.

    The #96 amendment (2026-08-04) moved band assertions here and nowhere else. The
    2026-08-04 baseline measured four excerpt rows and not one band result said anything
    about the scorer: #3018325 passed its band *before* either fix existed, carried there
    by `penalty_mlops_core`, `penalty_cloud_core` and `penalty_ramp_up_risk` while both
    rules under test fired wrongly; #3004625 scored 9 against 6 on the full posting, and
    #2999393 scored 1 against 7. Starvation runs in both directions — strip the context
    and there is nothing left to penalise, or nothing left to reward.

    Today this selects nothing: #3028920 is the only `full` row and its text is still
    outstanding. That is the honest state, not a gap to paper over with excerpt rows.
    """
    params = []
    for case in _CASES:
        if not case.get("live_rescorable") or case["text_provenance"] != "full":
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


def _live_trace_cases() -> list:
    """Live rows scored against an excerpt — judged on which rules fired, not the score.

    A rule either fires on a clause or it does not, so this survives the starvation
    above in both directions. No xfail marks: these do not assert correctness, they
    assert *unchanged*, against `live_baseline`. See the test.
    """
    return [
        pytest.param(case, id=_case_id(case))
        for case in _CASES
        if case.get("live_rescorable") and case["text_provenance"] == "excerpt"
    ]


def _fired_rules(evaluation) -> set[str]:
    """The rule ids the model reported as firing, as a set.

    Read off `score_trace`, which #95 added. A rule reporting `fired: true` with
    `delta: 0` is still counted as fired — the rubric forbids that combination, and
    swallowing it here would hide the very non-adherence the trace exists to expose.
    """
    trace = evaluation.score_trace
    if trace is None:
        return set()
    return {adj.rule_id for adj in trace.adjustments if adj.fired}


def _fired_adjustment(evaluation, rule_id: str):
    """The `score_trace` entry for one fired rule, or None if it did not fire.

    `_fired_rules` answers "did it fire"; this answers "at what band, and on what
    evidence". Membership alone cannot tell a rule that fired for the stated reason
    apart from one that fired for a reason the rubric carves out — see
    `test_conjunction_still_fires_the_german_penalty`.
    """
    trace = evaluation.score_trace
    if trace is None:
        return None
    for adj in trace.adjustments:
        if adj.rule_id == rule_id and adj.fired:
            return adj
    return None


# The conjunction control's evidence must ground in the DECLARATION, not in the three
# cues the 0-pt band carves out (German location, German company name, German prose).
# Both alternatives are the rubric's OWN 1-pt cues, and that is what makes them safe:
# each names the declaration itself, and neither can appear in evidence reasoning about
# a location or a company name.
#
# `und` was here and is deliberately gone. A free-standing `und` matches confound-only
# evidence in almost any German sentence — joining two nouns is what the word is for, so
# evidence enumerating two carved-out cues ("deutscher Einsatzort und deutsche Firma")
# contains one nearly every time. That made the pattern fail in precisely the case this
# control exists to detect: a regression. `delta == -1` does not rescue it, because a
# confound firing can land on either band. Dropping it costs nothing — the conjunction is
# already asserted by `delta == -1`, since the 1-pt band IS the conjunction case. Matching
# the declaration is the right shape; matching the conjunction word never was.
#
# Deliberately NOT extended to English paraphrase ("working language", "project
# language"). That phrasing appears in confound reasoning too — "Berlin location implies
# German working language" is a string this pattern must reject — so the alternation
# would reintroduce the same false positive in weaker form. The residual gap, evidence
# that paraphrases in English instead of quoting the German cue, is real and tracked on
# #136; it costs a spurious red, where the confound match costs a missed regression.
_NAMES_THE_DECLARATION = re.compile(r"projektsprache|arbeitssprache", re.IGNORECASE)


def _live_cases_unmarked() -> list:
    """Every live case, carrying NO xfail marks.

    Sibling of `_live_trace_cases()` above, and deliberately a WIDER set: that one is
    excerpt-only because a rule-firing comparison is only meaningful against the text
    the baseline was recorded from, whereas the `gaps` shape assertions below hold on
    any posting the model can read. Not merged into one helper — the filters differ
    because the properties differ.

    Unmarked for the same reason it names: `_live_cases()`'s strict `baseline: fail`
    xfail is a statement about the **score band** — "this posting is recorded as
    landing in the wrong band". It says nothing about `gaps`. Reusing it inverts the
    meaning, and the three recorded band failures all PASS the gaps checks, which the
    strict marker then reports as XPASS — a red suite for four correct results.
    """
    return [
        pytest.param(case, id=_case_id(case))
        for case in _CASES
        if case.get("live_rescorable")
    ]

# Required in every excerpt's front matter, and deliberately not defaulted.
# `build_prompt` puts title, company and location in the request (prompt.py:126-128),
# so an absent company would be scored as "unknown" — and for #3028920 that is the
# input under test, not decoration: the German penalty fired on language inferred from
# the company and the location, which is the inference the rule carves out. A default
# there would silently anonymise the signal and leave a case that passes without
# testing anything. Fail instead.
_REQUIRED_FRONT_MATTER = ("title", "company", "location", "provenance")


# The labelled lines `build_prompt` emits for the profile. A grounded gap names one of
# them, which is what makes it a statement about the PROFILE rather than the candidate.
# Kept in lockstep with SYSTEM_PROMPT's own list by the test in test_evaluation.py.
_PROFILE_SECTIONS = (
    "target roles",
    "background",
    "ideal role",
    "strong skills",
    "working knowledge",
)


def _names_a_profile_section(gap: str) -> bool:
    return any(section in gap.lower() for section in _PROFILE_SECTIONS)


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

    missing = [k for k in _REQUIRED_FRONT_MATTER if _is_blank(front_matter.get(k))]
    if missing:
        pytest.fail(
            f"{path} is missing required front matter: {', '.join(missing)}. "
            "Keep the company and the location unanonymised — they reach the model and "
            f"for some cases they are the signal. Per-case guidance lives beside the "
            f"fixtures in {_POSTING_TEXT_DIR.name}/HOW-TO-BUILD.local.md, not in the "
            "manifest, which carries no posting text."
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
    """Re-score the postings whose text exists locally, through the real evaluator.

    One real API call per case, `reeval_below` pinned so it is exactly one. The offline
    baseline records what this measured; this is what does the measuring — and it is
    what Wave C runs before and after a prompt change.

    Since the #96 amendment the two assertions below judge different things, because
    the two kinds of fixture support different claims. A full posting can be judged on
    its band. An excerpt can only be judged on which rules fired.
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

    async def _score(self, case, config):
        """One real evaluation of one fixture. Returns (front_matter, evaluation)."""
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
        _fm, evaluation = await self._score_listing(case, listing, config)
        return front_matter, evaluation

    async def _score_listing(self, case, listing, config):
        """One real evaluation of an already-built listing.

        Split from `_score` so the synthetic conjunction control can reach the same
        evaluator path without inventing a fixture file for text that is not a posting.
        """
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        results = await evaluate_jobs(
            [ScoredJob(listing=listing, embedding_score=0.0)],
            config.profile,
            client,
            model=config.llm_model,
            top_n=1,
            reeval_below=HARNESS_REEVAL_BELOW,
            temperature=config.llm_temperature,
        )

        assert results[0].evaluation is not None, (
            f"{case['id']}: the model returned nothing parseable — that is an evaluator "
            "failure, not a scoring one"
        )
        return None, results[0].evaluation

    @pytest.mark.parametrize("case", _live_band_cases())
    async def test_posting_scores_in_band(self, case, config):
        """Full-posting rows only. See `_live_band_cases` for why."""
        _front_matter, evaluation = await self._score(case, config)
        score = evaluation.match_score
        assert band_of(score) == case["expected_band"], (
            f"{case['id']} ({case['label']}): live score {score} -> {band_of(score)}, "
            f"human scored {case['human_score']} -> {case['expected_band']}. "
            f"Exercises: {case['exercises']}. Scored against the full posting text."
        )

    @pytest.mark.parametrize("case", _live_trace_cases())
    async def test_excerpt_fires_the_rules_it_did_before(self, case, config):
        """Excerpt rows: which rules fired, against `live_baseline`'s recorded set.

        This asserts UNCHANGED, not CORRECT. It is a change detector, and going red is
        how a prompt edit announces which rules it moved — which is the measurement
        #98 and #101 need and the band could not give them. Read the diff, decide
        whether the change is the one you intended, then re-record `live_baseline`
        with the new prompt's SHA.

        The recorded set is not a verdict and carries no enum: `tool_score` and
        `baseline` remain the immutable record of what the scorer did on *real*
        postings, which is the evidence base all six § 1 defects were diagnosed from.
        """
        recorded = case.get("live_baseline")
        if not recorded:
            pytest.skip(
                f"{case['id']} has no `live_baseline` yet. Record one from a live run "
                "and store per-rule frequencies with the fingerprint they were measured "
                "under — a comparison needs a stated 'before'."
            )
        if recorded["input_fingerprint"] != _input_fingerprint():
            pytest.skip(
                f"{case['id']}: `live_baseline` predates the current prompt or profile "
                "— re-measure it before comparing. "
                "`test_live_baselines_are_not_stale` reports this as a failure; here it "
                "is a skip, because a live comparison against a stale 'before' is worse "
                "than no comparison."
            )

        _front_matter, evaluation = await self._score(case, config)
        fired = _fired_rules(evaluation)
        n = recorded["n"]
        drift = {
            rule: (k, rule in fired)
            for rule, k in recorded["fired"].items()
            # Only rules the baseline saw fire on EVERY draw are stable enough for one
            # post-change draw to say anything about. #3018325 measured
            # `penalty_cloud_core` at 4/10 and then 0/10 across two pinned-temperature
            # runs with no rule change between them, so asserting on a partial rule
            # would fail on the sampler rather than on the rubric.
            if k == n and rule not in fired
        }
        assert not drift, (
            f"{case['id']} ({case['label']}): rules that fired on all {n} baseline "
            f"draws did not fire here: {sorted(drift)}. Baseline {recorded['recorded']} "
            f"at commit {recorded['prompt_commit']}. Exercises: {case['exercises']}. "
            "ONE draw — if this is the change you intended, confirm it against the "
            "issue's pre-registered decision rule before re-recording, and do not read "
            "a single draw as the verdict."
        )

    async def test_conjunction_still_fires_the_german_penalty(self, config):
        """The other direction of #98's carve-out, on a SYNTHETIC listing.

        #98 stopped `penalty_german_language` firing on a DISJUNCTION — German offered
        as an alternative to a language the candidate holds. The obvious way for that
        fix to be wrong is to swallow the CONJUNCTION with it: "Projektsprache: Deutsch
        und Englisch" declares both languages and must still fire the 1-pt band. A
        carve-out that silently widened to cover `und` would look identical on
        #3018325 — the disjunction fixture cannot see it.

        The listing below is written here rather than drawn from the corpus, for two
        reasons. No § 6 case exercises the conjunction, and this text is MINE — a
        synthetic control is not third-party posting content, so it can live in a
        committed file where the excerpt fixtures cannot.

        Measured 2026-08-04 at 10 draws: fired 10/10 after the fix. Asserted at one
        draw here, which is a signal rather than a verdict — the same caveat every
        other single-draw live assertion carries.

        The STRENGTHENED form below was then measured the same way, also 2026-08-04:
        10/10 draws pass all three assertions, so the band holds at -1 and the evidence
        names the declaration every time. That second measurement is the point — a new
        assertion that passed once could still be flaky, and a flaky standing control is
        worse than none, because it trains whoever sees it red to re-run rather than read.

        Re-measured a third time, 2026-08-04, after `und` was dropped from
        `_NAMES_THE_DECLARATION` (see the comment there): 10/10 again. That run also
        settles a question the pattern could not answer on its own — the model quotes a
        GERMAN cue (`Projektsprache`/`Arbeitssprache`) rather than paraphrasing in
        English, in all ten draws. So the English-paraphrase gap left open there is
        theoretical against this listing rather than live, which is why it is tracked
        (#136) instead of closed by widening the pattern into confound territory.

        WHY THIS ASSERTS ON THE TRACE ENTRY AND NOT ON THE FIRED SET. The listing is
        German throughout — Berlin location, GmbH company, German prose — because a
        realistic conjunction posting is. Those are precisely the three cues the 0-pt
        band carves out, and D4 (#3028920) is standing evidence that the model fires
        the German penalty off them anyway. So membership in the fired set is
        satisfiable by the confound: the conjunction handling could be broken and this
        test would still pass, on a rule firing for a reason the rubric forbids. The
        band (`delta == -1`) and the evidence string are what discriminate, and they
        are the assertion the PR's "safe in both directions" claim actually rests on.
        """
        listing = JobListing(
            id="synthetic-conjunction", source="synthetic",
            title="AI Engineer (m/w/d)", company="Synthetic Control GmbH",
            description=(
                "Projektkontext\n"
                "Entwicklung von LLM-basierten Anwendungen mit RAG und LangChain.\n\n"
                "Rahmendaten:\n"
                "Projektsprache: Deutsch und Englisch\n"
                "Einsatzort: 100% remote\n"
            ),
            location="Berlin, Deutschland", url="", posted_date=None,
            fetched_at=datetime.now(), raw_data={}, remote_percentage=100,
        )
        case = {"id": "synthetic-conjunction", "label": "conjunction-control"}
        _fm, evaluation = await self._score_listing(case, listing, config)

        adjustment = _fired_adjustment(evaluation, "penalty_german_language")
        assert adjustment is not None, (
            "`Projektsprache: Deutsch und Englisch` did not fire "
            "penalty_german_language. #98's disjunction carve-out has widened to cover "
            "the conjunction, which it must not: `und` declares both languages and "
            "still earns the 1-pt band. The disjunction fixture (#3018325) cannot see "
            "this — it is why this control exists."
        )

        assert adjustment.delta == -1, (
            f"penalty_german_language fired at delta {adjustment.delta}, not the 1-pt "
            "band's -1. `Projektsprache: Deutsch und Englisch` states no level, so it "
            "earns the 1-pt band and nothing more; -2 means the 2-pt band claimed a "
            "level the listing never states, and 0 means the rule reported itself "
            f"fired while contributing nothing. Evidence: {adjustment.evidence!r}"
        )

        assert _NAMES_THE_DECLARATION.search(adjustment.evidence or ""), (
            "penalty_german_language fired at the right band but its evidence does not "
            "name the declaration — it cites neither `Projektsprache` nor "
            "`Arbeitssprache`, the rubric's own two 1-pt cues: "
            f"{adjustment.evidence!r}\n"
            "This listing is deliberately German throughout (Berlin location, GmbH "
            "company, German prose), which is exactly the trio the 0-pt band carves "
            "out and exactly what D4 (#3028920) is the standing evidence the model "
            "still fires on. So a bare membership assertion could pass while the "
            "conjunction handling was broken and the rule fired off the German "
            "surroundings instead. This assertion is what makes the control test the "
            "conjunction rather than the confound."
        )

    @pytest.mark.parametrize("case", _live_trace_cases())
    async def test_excerpt_does_not_fire_its_forbidden_rules(self, case, config):
        """The standing guard for rules a landed fix removed. See `must_not_fire`.

        The symmetric half of the test above: that one catches a rule that stopped
        firing, this one catches a rule that started again. Without it a fix's verdict
        is a one-time measurement — #98 drives `penalty_german_language` out of the
        fired set, and nothing would ever look at it again.

        Skips rather than passes vacuously when the list is empty, so a case whose fix
        has not landed reads as "no guard here yet" instead of as a green tick.
        """
        forbidden = case.get("must_not_fire") or []
        if not forbidden:
            pytest.skip(
                f"{case['id']} declares no must_not_fire rules. Populated by the PR that "
                "lands the fix, alongside re-recording `live_baseline`."
            )

        _front_matter, evaluation = await self._score(case, config)
        fired = _fired_rules(evaluation)
        violated = sorted(set(forbidden) & fired)
        assert not violated, (
            f"{case['id']} ({case['label']}): {violated} fired, and this case declares "
            "they must not. ONE draw, so this is a signal rather than a verdict — read "
            "it against the pre-registered decision rule on the issue that added them "
            f"(issues {case.get('issues') or 'unrecorded'}) before concluding the fix "
            "has regressed."
        )

    @pytest.mark.parametrize("case", _live_cases_unmarked())
    async def test_gaps_are_capped_and_grounded_in_the_profile(self, case, config):
        """#97 / B1 — the field-level assertion #96 deferred here.

        D1 is invisible to the band assertion above by construction (6 vs 6.5, both
        `marginal`), so `gaps` needs checking against the field itself or not at all.
        Two properties, both of which #97's SYSTEM_PROMPT edit asks for directly:

        - at most 5 entries. NOT vacuous: on a 25-listing live pool the pre-#97 prompt
          returned more than 5 on **8 of 25**, running to 9.
        - every entry names the profile section it is absent from, or conflicts with.
          Grounding on the same pool went 5% -> 83%; on the four fixtures here, 3% -> 90%.

        Deliberately NOT an exact-gap-contents assertion. Which gaps a posting yields
        varies between draws of an identical prompt, so pinning the strings would flake
        for the reason #96 gives for asserting bands over exact scores. These two
        properties hold across every draw measured.

        The 83% is why grounding is asserted per-case rather than globally: a single
        ungrounded entry is within observed behaviour, so this requires a MAJORITY per
        posting and reports the stragglers rather than failing on one.
        """
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
        evaluation = results[0].evaluation
        assert evaluation is not None, f"{case['id']}: nothing parseable returned"

        gaps = evaluation.gaps
        assert len(gaps) <= 5, (
            f"{case['id']}: {len(gaps)} gaps returned against a cap of 5 — "
            f"{gaps}"
        )

        ungrounded = [g for g in gaps if not _names_a_profile_section(g)]
        assert len(ungrounded) * 2 <= len(gaps), (
            f"{case['id']}: {len(ungrounded)} of {len(gaps)} gaps name no profile "
            f"section, so they read as claims about the CANDIDATE rather than about "
            f"the profile: {ungrounded}"
        )
