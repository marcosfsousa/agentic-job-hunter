"""Tests for evaluation/evaluator.py and evaluation/prompt.py.

No real API calls — Haiku responses are mocked via unittest.mock.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from jobscout.delivery.formatter import format_digest
from jobscout.evaluation.evaluator import check_score_trace, evaluate_jobs
from jobscout.evaluation.prompt import (
    RULE_IDS,
    SCORE_CAP,
    SCORE_FLOOR,
    SYSTEM_PROMPT,
    build_prompt,
)
from jobscout.models import (
    DealbreakersConfig,
    EvaluationResult,
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


def _trace(start: int, fired: dict[str, int] | None = None) -> dict:
    """Build a score_trace in the shape SYSTEM_PROMPT asks for.

    `fired` maps rule_id to a signed non-zero delta; every other rule in RULE_IDS is
    emitted as a non-firing entry, because the prompt asks for one entry per rule
    whether or not it fired. Evidence is filled in for the firing entries only, which
    is what `check_score_trace` requires.
    """
    fired = fired or {}
    return {
        "start": start,
        "adjustments": [
            {
                "rule_id": rule_id,
                "fired": rule_id in fired,
                "delta": fired.get(rule_id, 0),
                "evidence": f"listing states the {rule_id} cue" if rule_id in fired else None,
            }
            for rule_id in RULE_IDS
        ],
        "total": start + sum(fired.values()),
    }


def _adj(trace: dict, rule_id: str) -> dict:
    """The adjustment entry for `rule_id`, so a test can bend one rule out of shape.

    `next` rather than a scan-and-skip loop deliberately: a renamed or mistyped id
    raises here, instead of leaving the trace untouched and the test asserting against
    a shape it never actually built.
    """
    return next(a for a in trace["adjustments"] if a["rule_id"] == rule_id)


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
            # 6 + 1 + 1 == 8. The default response is the healthy one, so the default
            # trace has to reconcile — otherwise every test using it drags a warning
            # along and the flag stops meaning anything (#95).
            "score_trace": _trace(6, {"boost_core_stack": 1, "boost_llm_ownership": 1}),
        }
        message = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])
        client.messages.create = AsyncMock(return_value=message)
    return client


# ---------------------------------------------------------------------------
# evaluator tests
# ---------------------------------------------------------------------------

class TestEvaluateJobs:
    async def test_populates_llm_score_and_final_score(self, profile):
        # embedding_score deliberately != llm_score so final == llm is a real assertion:
        # under the old 0.4*emb + 0.6*llm blend this would have been 0.4*0.3 + 0.6*0.8 = 0.6.
        jobs = [_make_scored_job("job-1", embedding_score=0.3)]
        client = _mock_client()

        results = await evaluate_jobs(jobs, profile, client, model="mock-model", top_n=25)

        assert len(results) == 1
        result = results[0]
        assert result.llm_score == pytest.approx(0.8)          # match_score=8 → 8/10
        assert result.final_score == pytest.approx(0.8)        # == llm_score, no blend
        assert result.final_score == result.llm_score
        assert result.evaluation is not None
        assert result.evaluation.match_score == 8

    async def test_on_api_failure_job_retained_without_llm_score(self, profile):
        jobs = [_make_scored_job("job-2")]
        client = _mock_client(raise_exc=Exception("API error"))

        results = await evaluate_jobs(jobs, profile, client, model="mock-model", top_n=25)

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

        results = await evaluate_jobs([_make_scored_job("fence-1")], profile, client, model="mock-model", top_n=25)

        assert results[0].evaluation is not None
        assert results[0].evaluation.match_score == 7

    async def test_on_invalid_json_job_retained_without_llm_score(self, profile):
        client = MagicMock()
        bad_message = SimpleNamespace(content=[SimpleNamespace(text="not valid json {")])
        client.messages.create = AsyncMock(return_value=bad_message)

        results = await evaluate_jobs(
            [_make_scored_job("job-3")], profile, client, model="mock-model", top_n=25
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
        results = await evaluate_jobs([], profile, client, model="mock-model", top_n=25)
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
        results = await evaluate_jobs(jobs, profile, client, model="mock-model", top_n=25)

        assert results[0].llm_score == pytest.approx(0.7)
        assert results[1].llm_score is None

    async def test_temperature_reaches_the_api_and_defaults_to_zero(self, profile):
        """The sampling temperature is sent, and defaults to 0 when nobody passes one.

        Asserted because the defect was an ABSENCE: `messages.create` never carried a
        `temperature` at all, so the API default of 1.0 applied silently — to the daily
        digest as much as to the eval harness. Nothing failed, nothing logged, and the
        pipeline's "same day = same digest" requirement was quietly unmeetable.
        A regression here would look exactly the same, so the assertion is that the
        keyword is PRESENT, not merely that some value is right.
        """
        payload = {"match_score": 6, "matching_skills": [], "gaps": [], "explanation": "Fine."}
        client = _mock_client(response_payload=payload)

        await evaluate_jobs(
            [_make_scored_job("temp-1")], profile, client, model="mock-model", top_n=25
        )

        kwargs = client.messages.create.call_args.kwargs
        assert "temperature" in kwargs, (
            "messages.create was called without a temperature — the API default of 1.0 "
            "then applies, which is the defect this test exists for"
        )
        assert kwargs["temperature"] == 0.0

    async def test_temperature_is_passed_through_when_set(self, profile):
        """A caller-supplied temperature reaches the API unchanged.

        The harness deliberately raises it to measure the spread, so the pin must be a
        default rather than a hardcode.
        """
        payload = {"match_score": 6, "matching_skills": [], "gaps": [], "explanation": "Fine."}
        client = _mock_client(response_payload=payload)

        await evaluate_jobs(
            [_make_scored_job("temp-2")], profile, client, model="mock-model", top_n=25,
            temperature=1.0,
        )

        assert client.messages.create.call_args.kwargs["temperature"] == 1.0

    async def test_reeval_fires_when_score_below_threshold(self, profile):
        """First score 3 < reeval_below=4 triggers a second call; higher score (7) wins."""
        low_payload = {"match_score": 3, "matching_skills": [], "gaps": ["LLMs"], "explanation": "Weak."}
        high_payload = {"match_score": 7, "matching_skills": ["RAG"], "gaps": [], "explanation": "Good."}
        low_msg = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(low_payload))])
        high_msg = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(high_payload))])

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[low_msg, high_msg])

        results = await evaluate_jobs(
            [_make_scored_job("reeval-1")], profile, client, model="mock-model", top_n=25, reeval_below=4
        )

        assert client.messages.create.call_count == 2
        assert results[0].evaluation is not None
        assert results[0].evaluation.match_score == 7

    async def test_reeval_not_called_when_score_at_or_above_threshold(self, profile):
        """Score == reeval_below (4) should NOT trigger a second call."""
        payload = {"match_score": 4, "matching_skills": ["Python"], "gaps": [], "explanation": "Fine."}
        client = _mock_client(response_payload=payload)

        results = await evaluate_jobs(
            [_make_scored_job("no-reeval-1")], profile, client, model="mock-model", top_n=25, reeval_below=4
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
            [_make_scored_job("keep-first-1")], profile, client, model="mock-model", top_n=25, reeval_below=4
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
            [_make_scored_job("reeval-fail-1")], profile, client, model="mock-model", top_n=25, reeval_below=4
        )

        assert client.messages.create.call_count == 2
        assert results[0].evaluation is not None
        assert results[0].evaluation.match_score == 3


class TestSortOrder:
    """evaluate_jobs sorts its return descending by final_score.

    This is the stage that produces the score, so it is the stage that orders by it —
    which is what formatter.py's docstring has always presupposed and what nothing
    did before (F #9 decision 9). reeval_below=1 disables re-evaluation (match_score
    is never < 1) so each job consumes exactly one mocked response.
    """

    @staticmethod
    def _msg(match_score: int) -> SimpleNamespace:
        payload = {
            "match_score": match_score,
            "matching_skills": [],
            "gaps": [],
            "explanation": "x",
        }
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])

    async def test_returns_descending_by_final_score(self, profile):
        # Input order does not match score order — the sort must reorder.
        jobs = [
            _make_scored_job("low", embedding_score=0.9),
            _make_scored_job("high", embedding_score=0.5),
        ]
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[self._msg(4), self._msg(9)])

        results = await evaluate_jobs(jobs, profile, client, model="mock-model", top_n=25, reeval_below=1)

        assert [r.listing.id for r in results] == ["high", "low"]

    async def test_ties_broken_by_embedding_score_descending(self, profile):
        # Equal LLM scores → the higher embedding_score must come first. Ties dominate
        # at ten distinct llm values across a pool of twenty-five, so this is the case
        # that matters most; a stable sort would silently preserve input order instead.
        jobs = [
            _make_scored_job("lower-emb", embedding_score=0.4),
            _make_scored_job("higher-emb", embedding_score=0.8),
        ]
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[self._msg(7), self._msg(7)])

        results = await evaluate_jobs(jobs, profile, client, model="mock-model", top_n=25, reeval_below=1)

        assert results[0].llm_score == results[1].llm_score
        assert [r.listing.id for r in results] == ["higher-emb", "lower-emb"]

    async def test_failed_evaluation_sorts_last_without_raising(self, profile):
        # A failed eval leaves final_score=None; a naive sort key would raise TypeError
        # and take the run down on one bad Haiku response. It must sort last instead.
        jobs = [
            _make_scored_job("fails", embedding_score=0.95),
            _make_scored_job("ok", embedding_score=0.2),
        ]
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[Exception("boom"), self._msg(6)])

        results = await evaluate_jobs(jobs, profile, client, model="mock-model", top_n=25, reeval_below=1)

        assert [r.listing.id for r in results] == ["ok", "fails"]
        assert results[-1].final_score is None

    async def test_top_n_read_from_argument(self, profile):
        # top_n now lives in config.py and is passed through run.py; the evaluator still
        # honours it as the pool bound.
        jobs = [_make_scored_job(f"job-{i}") for i in range(10)]
        client = _mock_client()

        results = await evaluate_jobs(jobs, profile, client, model="mock-model", top_n=4)

        assert len(results) == 4


# ---------------------------------------------------------------------------
# score_trace — the arithmetic check (#95)
# ---------------------------------------------------------------------------

def _evaluation(match_score: int, trace: dict | None) -> EvaluationResult:
    """An EvaluationResult built the way the evaluator builds one: from model JSON."""
    payload = {
        "match_score": match_score,
        "matching_skills": [],
        "gaps": [],
        "explanation": "x",
    }
    if trace is not None:
        payload["score_trace"] = trace
    return EvaluationResult.model_validate(payload)


class TestScoreTraceSurvivesValidation:
    """EvaluationResult does not inherit _StrictProfileModel, so Pydantic's default
    extra="ignore" applied and a score_trace the model returned was silently dropped
    on the floor. The field has to exist for anything downstream to check it."""

    def test_trace_is_parsed_rather_than_discarded(self):
        evaluation = _evaluation(8, _trace(6, {"boost_core_stack": 1, "boost_llm_ownership": 1}))

        assert evaluation.score_trace is not None
        assert evaluation.score_trace.start == 6
        assert [a.rule_id for a in evaluation.score_trace.adjustments] == list(RULE_IDS)
        fired = [a for a in evaluation.score_trace.adjustments if a.fired]
        assert {a.rule_id for a in fired} == {"boost_core_stack", "boost_llm_ownership"}
        assert all(a.evidence for a in fired)

    async def test_trace_reaches_the_scored_job_through_the_evaluator(self, profile):
        results = await evaluate_jobs(
            [_make_scored_job("trace-1")], profile, _mock_client(), model="mock-model", top_n=25
        )

        assert results[0].evaluation is not None
        assert results[0].evaluation.score_trace is not None
        assert results[0].trace_warnings == ()

    def test_a_malformed_trace_degrades_instead_of_raising(self):
        """Optional covers an *absent* trace. A present one of the wrong shape would
        still raise — inside the swallowing except, costing the row it was meant to
        flag. It has to come back as a flag, not an exception."""
        trace = _trace(6, {"boost_core_stack": 1})
        _adj(trace, "boost_core_stack")["delta"] = "plus one"   # not an int

        evaluation = _evaluation(7, trace)

        assert evaluation.score_trace is None
        assert evaluation.score_trace_error is not None
        assert "delta" in evaluation.score_trace_error
        assert any(
            "could not be read" in w for w in check_score_trace(evaluation)
        )

    def test_a_malformed_trace_is_not_reported_as_a_missing_one(self):
        """The two are different faults: nothing sent means the instruction was ignored,
        an unreadable one means the model tried and got the shape wrong."""
        absent = check_score_trace(_evaluation(7, None))
        malformed = check_score_trace(_evaluation(7, {"start": "six"}))

        assert absent != malformed
        assert any("no score_trace returned" in w for w in absent)
        assert not any("no score_trace returned" in w for w in malformed)

    def test_the_model_cannot_set_the_error_field_itself(self):
        """It is the validator's verdict on the response, not part of the response."""
        payload = {
            "match_score": 7,
            "matching_skills": [],
            "gaps": [],
            "explanation": "x",
            "score_trace": _trace(6, {"boost_core_stack": 1}),
            "score_trace_error": "nothing to see here",
        }

        evaluation = EvaluationResult.model_validate(payload)

        assert evaluation.score_trace is not None
        assert evaluation.score_trace_error is None

    # That adding score_trace did not turn EvaluationResult strict is covered by
    # TestStrictnessIsScopedToTheProfile in tests/test_models.py, which owns that
    # invariant for all three permissive models at once. A second copy here would
    # split the story across two files and need two edits to change.


class TestCheckScoreTrace:
    def test_reconciling_trace_reports_nothing(self):
        evaluation = _evaluation(4, _trace(6, {"penalty_remote": -3, "boost_core_stack": 1}))
        assert check_score_trace(evaluation) == []

    def test_arithmetic_mismatch_is_reported(self):
        # The D2/D3/D4 shape: the rule is named in the trace, and the score ignores it.
        evaluation = _evaluation(6, _trace(6, {"penalty_remote": -3}))

        problems = check_score_trace(evaluation)

        assert len(problems) == 1
        assert "arithmetic mismatch" in problems[0]
        assert "penalty_remote-3" in problems[0]
        assert "match_score is 6" in problems[0]

    def test_total_below_the_floor_is_not_reported(self):
        """D6's shape — several hard blockers at once — sums below 1, and match_score
        cannot go there. Flagging it would fire on correctly scored rows every run."""
        evaluation = _evaluation(
            SCORE_FLOOR, _trace(2, {"penalty_remote": -3, "penalty_ramp_up_risk": -3})
        )
        assert check_score_trace(evaluation) == []

    def test_total_above_the_cap_is_reported(self):
        """Unreachable under the rubric's own maxima, so a trace that gets there
        invented an adjustment — and the cap does not excuse it."""
        evaluation = _evaluation(
            10, _trace(9, {"boost_core_stack": 1})
        )
        problems = check_score_trace(evaluation)

        assert len(problems) == 1
        assert f"bounded {SCORE_CAP}" in problems[0]

    def test_reported_total_that_does_not_match_the_deltas_is_reported(self):
        """A wrong `total` is the model failing at addition; a right `total` that
        match_score disagrees with is the model overriding its own sum. Different
        faults, and the digest should not present them as one."""
        trace = _trace(6, {"penalty_remote": -3})
        trace["total"] = 5                                   # 6 - 3 is 3, not 5

        problems = check_score_trace(_evaluation(3, trace))

        assert problems == ["reported total 5 is not start 6 plus the deltas (3)"]

    def test_an_absent_total_is_not_itself_a_problem(self):
        """The sum is recomputed regardless — `total` is a cross-check, not the source
        of truth, so a response that omits it is still fully verifiable."""
        trace = _trace(6, {"penalty_remote": -3})
        del trace["total"]

        assert check_score_trace(_evaluation(3, trace)) == []

    def test_missing_trace_is_reported(self):
        problems = check_score_trace(_evaluation(7, None))

        assert len(problems) == 1
        assert "no score_trace" in problems[0]

    @pytest.mark.parametrize("evidence", [None, "", "   "])
    def test_fired_rule_without_evidence_is_reported(self, evidence):
        trace = _trace(6, {"penalty_remote": -3})
        _adj(trace, "penalty_remote")["evidence"] = evidence

        problems = check_score_trace(_evaluation(3, trace))

        assert problems == ["penalty_remote fired with no evidence"]

    def test_fired_rule_contributing_nothing_is_reported(self):
        """The handoff's worked example for D3 verbatim: the model reports the remote
        penalty as fired and then moves the score by zero. The arithmetic reconciles,
        so this is the only check that sees it."""
        trace = _trace(6)
        _adj(trace, "penalty_remote").update(
            fired=True, delta=0, evidence="two days a week in Munich"
        )

        problems = check_score_trace(_evaluation(6, trace))

        assert problems == ["penalty_remote fired but contributed 0"]

    def test_unfired_rule_contributing_a_delta_is_reported(self):
        """The mirror image: an adjustment with no rule behind it. Also sums correctly."""
        trace = _trace(6)
        _adj(trace, "penalty_remote")["delta"] = -3
        trace["total"] = 3      # consistent with the deltas, to isolate the fired flag

        problems = check_score_trace(_evaluation(3, trace))

        assert problems == ["penalty_remote did not fire but contributed -3"]

    def test_every_problem_is_reported_not_just_the_first(self):
        trace = _trace(6, {"penalty_remote": -3, "boost_core_stack": 1})
        _adj(trace, "boost_core_stack")["evidence"] = None

        problems = check_score_trace(_evaluation(9, trace))

        assert len(problems) == 2
        assert any("arithmetic mismatch" in p for p in problems)
        assert "boost_core_stack fired with no evidence" in problems


class TestTraceCheckRunsOutsideTheSwallowingExcept:
    """The check must not be able to delete the row it is flagging.

    `_evaluate_one`'s bare `except Exception` returns the job unevaluated, and
    `format_digest` filters unevaluated rows out entirely — so a check raising in there
    would do the opposite of #95's "keep the row, flag it". These pin the placement by
    its consequence rather than by where the call happens to sit.
    """

    @staticmethod
    def _mismatched_client() -> MagicMock:
        return _mock_client({
            "match_score": 6,
            "matching_skills": ["LangChain"],
            "gaps": ["onsite presence"],
            "explanation": "Two days a week onsite in Munich.",
            "score_trace": _trace(6, {"penalty_remote": -3}),   # 6 - 3 = 3, not 6
        })

    async def test_failing_check_still_yields_a_row_in_the_digest(self, profile):
        results = await evaluate_jobs(
            [_make_scored_job("mismatch-1")], profile, self._mismatched_client(),
            model="mock-model", top_n=25, reeval_below=0,
        )

        assert results[0].llm_score == pytest.approx(0.6)     # scored, not dropped
        assert results[0].trace_warnings                      # and flagged

        digest = format_digest(results)
        assert "mismatch-1" in digest
        assert "**UNVERIFIED SCORE:**" in digest

    async def test_mismatch_logs_at_warning_with_the_listing_id(self, profile, caplog):
        with caplog.at_level(logging.WARNING, logger="jobscout.evaluation.evaluator"):
            await evaluate_jobs(
                [_make_scored_job("mismatch-2")], profile, self._mismatched_client(),
                model="mock-model", top_n=25, reeval_below=0,
            )

        records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(records) == 1
        assert "mismatch-2" in records[0].getMessage()
        assert "arithmetic mismatch" in records[0].getMessage()

    async def test_missing_trace_flags_rather_than_drops(self, profile):
        """A response with no trace at all still parses — making score_trace required
        would raise inside the swallowing except and cost the row."""
        payload = {
            "match_score": 7,
            "matching_skills": [],
            "gaps": [],
            "explanation": "No trace returned.",
        }
        client = _mock_client(response_payload=payload)

        results = await evaluate_jobs(
            [_make_scored_job("no-trace-1")], profile, client, model="mock-model", top_n=25
        )

        assert results[0].llm_score == pytest.approx(0.7)
        assert any("no score_trace" in w for w in results[0].trace_warnings)

    async def test_malformed_trace_flags_rather_than_drops(self, profile):
        """The one input the check exists to catch is a model that got the trace wrong,
        and until the validator tolerated it that was the one input that deleted its own
        evidence: a wrong-shaped trace raised at model_validate, inside the except, and
        format_digest then filtered the unevaluated row out of the digest entirely."""
        trace = _trace(6, {"boost_core_stack": 1})
        # Keyed by rule_id instead of listed — the shape a model reaches for when it
        # decides a per-rule list "is" a mapping. Chosen over a fired/delta
        # transposition because that one is only sometimes this fault: lax mode coerces
        # 0 and 1 to bool and nothing else, so a transposed ±1 boost validates and is
        # caught downstream as arithmetic, while a transposed −3 penalty lands here.
        # An input whose path depends on the delta would pin neither check.
        trace["adjustments"] = {a["rule_id"]: a for a in trace["adjustments"]}
        payload = {
            "match_score": 7,
            "matching_skills": [],
            "gaps": [],
            "explanation": "Shape is wrong.",
            "score_trace": trace,
        }

        results = await evaluate_jobs(
            [_make_scored_job("bad-shape-1")], profile, _mock_client(payload),
            model="mock-model", top_n=25, reeval_below=0,
        )

        assert results[0].evaluation is not None                  # not swallowed
        assert results[0].llm_score == pytest.approx(0.7)
        assert any("could not be read" in w for w in results[0].trace_warnings)

        digest = format_digest(results)
        assert "bad-shape-1" in digest
        assert "**UNVERIFIED SCORE:**" in digest

    async def test_a_failed_evaluation_is_not_also_flagged(self, profile):
        """Nothing came back to check, and _evaluate_one has already logged it. A second
        warning would read as a scoring fault rather than an API one."""
        client = _mock_client(raise_exc=Exception("API error"))

        results = await evaluate_jobs(
            [_make_scored_job("failed-1")], profile, client, model="mock-model", top_n=25
        )

        assert results[0].evaluation is None
        assert results[0].trace_warnings == ()

    async def test_the_kept_sample_is_the_one_checked(self, profile):
        """Re-evaluation keeps the higher of two samples. The check runs on the survivor,
        so a bad trace on a discarded first draw must not flag the row that shipped."""
        bad_first = {
            "match_score": 3,
            "matching_skills": [],
            "gaps": [],
            "explanation": "Weak.",
            "score_trace": _trace(4, {"penalty_remote": -3}),   # 4 - 3 = 1, not 3
        }
        good_second = {
            "match_score": 7,
            "matching_skills": ["RAG"],
            "gaps": [],
            "explanation": "Good.",
            "score_trace": _trace(6, {"boost_core_stack": 1}),  # 6 + 1 = 7
        }
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[
            SimpleNamespace(content=[SimpleNamespace(text=json.dumps(bad_first))]),
            SimpleNamespace(content=[SimpleNamespace(text=json.dumps(good_second))]),
        ])

        results = await evaluate_jobs(
            [_make_scored_job("reeval-trace-1")], profile, client,
            model="mock-model", top_n=25, reeval_below=4,
        )

        assert results[0].evaluation is not None
        assert results[0].evaluation.match_score == 7
        assert results[0].trace_warnings == ()


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

    def test_carries_deprioritise_entries_but_not_five_years(self):
        """The rewritten profile prose reaches Haiku, and the deleted penalty's config
        half does not — this catches removing the prompt line but not the YAML line."""
        profile = UserProfile(
            name="Marcos",
            background="Application-layer builder.",
            ideal_role="Ship LLM applications end to end.",
            deprioritise=[
                "Requires German at CEFR C1 or above as a deliberately stated, non-optional condition",
                "Primarily model research or academic role",
            ],
            target_roles=["ML Engineer"],
            skills=SkillsConfig(strong=["RAG systems"], working_knowledge=["Python"]),
            location=LocationConfig(target_countries=["Germany"]),
            rate=RateConfig(),
            dealbreakers=DealbreakersConfig(),
            freelancermap_queries=["Machine Learning"],
        )
        prompt = build_prompt(_make_scored_job("j1").listing, profile)

        assert "Requires German at CEFR C1 or above" in prompt
        assert "Primarily model research or academic role" in prompt
        assert "5+ years" not in prompt

    def test_system_prompt_drops_year_count_penalties(self):
        """The 2–4yr and 5+yr penalties fired on nearly a senior-skewing pool; gone."""
        assert "5+ years" not in SYSTEM_PROMPT
        assert "2–4 years" not in SYSTEM_PROMPT
        assert "€80k" not in SYSTEM_PROMPT

    def test_system_prompt_grades_ramp_up_risk(self):
        """The year-count trigger is replaced by a graded deliverable-evidence judgement."""
        assert "RAMP-UP RISK" in SYSTEM_PROMPT

    def test_system_prompt_german_penalty_anchored_at_c1(self):
        """Kept, but re-aimed (#44): the candidate is B2, so the FULL penalty fires only on
        a DELIBERATELY STATED requirement at C1 or above — not on implied German (location/
        company/posting language), which was firing on 80% of a DACH corpus and compressing
        the scale. B2-or-below German is explicitly not penalised; level-unstated German
        costs 1 rather than 0 only when the listing declares German as the working language
        (#54 — the band itself is pinned by the test below)."""
        assert "CEFR C1 or above" in SYSTEM_PROMPT
        # The individual carve-outs are pinned by TestGermanClauseParity in
        # tests/test_config.py, which checks them against profile.yaml at the same time.
        # Asserting them here too would mean a fifth carve-out has to be added in two
        # places — the drift this whole guard exists to prevent (#55).
        # The old vague binary wording is gone.
        assert "requires fluent German as a stated condition" not in SYSTEM_PROMPT.lower()

    def test_system_prompt_ranks_optional_qualifier_over_c1_cue(self):
        """#51: "verhandlungssicheres Deutsch von Vorteil" matches the fire list AND the
        carve-out list at once. Without a stated precedence Haiku's call there is
        undefined, so the prompt names a winner: an optional qualifier beats the level."""
        assert "PRECEDENCE" in SYSTEM_PROMPT
        assert "verhandlungssicheres Deutsch von Vorteil" in SYSTEM_PROMPT
        # #54 made the clause graded, so precedence has to cover the 1-pt band too.
        assert "EITHER band" in SYSTEM_PROMPT
        # #65: every example under a rule must be an INSTANCE of it. The 1-pt band's
        # example was "Projektsprache Deutsch, Englisch ebenfalls möglich" — a second
        # declared language, which is not an optional qualifier on the same requirement.
        # Listing 3030001 fired the band on exactly that shape, so the example claimed a
        # suppression the rubric never had. Replaced with a real instance, and the
        # two-languages case is now stated as firing rather than left to be inferred.
        assert "Deutsch als Projektsprache von Vorteil" in SYSTEM_PROMPT
        # #67/#89: the precedence paragraph keeps the point that is genuinely about
        # precedence — a second language is not an optional qualifier, so it does not
        # suppress anything. What that implies for FIRING now lives in the 1-pt band
        # itself (asserted in the band test below), because a rule that only appears
        # in the precedence paragraph is a rule the band definition contradicts.
        assert "A SECOND declared language is NOT an optional qualifier" in SYSTEM_PROMPT

    def test_system_prompt_grades_declared_working_language_below_c1(self):
        """#54: `Projektsprache: Deutsch` states a language but no level, so it hit the
        clause's "no level stated" carve-out on paper while Haiku penalised it 2 anyway
        (2 of 7 fires on the 2026-07-30 corpus). The rubric was the wrong half: a declared
        working language IS a deliberate operational statement. It now costs 1 — enough to
        keep #44's premise that an unstated level never buys the full 2."""
        # #65: the header range has to include the no-fire band the body defines, the
        # way the sibling RAMP-UP RISK clause writes "0–3". Stating "1–2" over a body
        # whose lowest band is 0 invites reading 1 as a floor — i.e. penalising any
        # German signal at all, which is the over-firing #44 and #54 both removed.
        assert "REDUCE by 0–2 pts for a GERMAN-LANGUAGE REQUIREMENT" in SYSTEM_PROMPT
        assert "0 pts — everything else" in SYSTEM_PROMPT
        assert '"Projektsprache: Deutsch"' in SYSTEM_PROMPT
        # #67: the band defined German as "THE language the work is conducted in" while
        # the precedence paragraph said "a language" and fired on two. Haiku already read
        # it the wide way (listing 3030001), so this pins the widening at the band — the
        # definite article is what a two-language listing contradicts.
        assert "DECLARES German as a language the work is conducted in" in SYSTEM_PROMPT
        # Pins the band's OWN sentence, not the bare example string: the example also
        # appears in the precedence paragraph, so asserting it alone would pass against
        # the pre-#67 prompt and guard nothing.
        assert (
            'German declared ALONGSIDE another language ("Projektsprache: Deutsch und '
            'Englisch") fires this band too'
        ) in SYSTEM_PROMPT
        # The bands must be exclusive: without this a C1+ listing that also declares a
        # working language reads as 2+1, restoring over-firing through a third door.
        assert "The bands are exclusive" in SYSTEM_PROMPT


class TestSystemPromptConstrainsTheGapsField:
    """#97 / B1. `gaps` carried no constraint at all while `matching_skills` carried
    four, so all the discipline went to the field that cannot mislead. It is also the
    ONLY durable record a human reads: `storage/db.py` persists no evaluation field,
    and `score_trace` never reaches the digest — only `trace_warnings` do.
    """

    def test_gaps_are_capped_at_five_in_total(self):
        assert "Return at most 5 IN TOTAL" in SYSTEM_PROMPT

    def test_every_gap_must_name_the_profile_section_it_is_absent_from(self):
        """A gap that cannot be grounded is not emitted. The sections named here are
        exactly the labelled lines `build_prompt` emits, so "name the section" is a
        closed choice rather than an open-ended instruction."""
        assert (
            "Target roles, Background, Ideal role, Strong skills, or Working knowledge"
            in SYSTEM_PROMPT
        )
        assert "do not emit it at all" in SYSTEM_PROMPT

    def test_a_gap_may_be_an_absence_or_a_conflict(self):
        """Measured, not assumed. The first draft asked only for the section a gap is
        ABSENT from — but `penalty_german_language`, `penalty_remote` and
        `penalty_ramp_up_risk` fire when the profile STATES something the job
        contradicts (B2 German, a remote preference), which is not an absence.

        Live, the model resolved that by grounding those gaps against the JOB instead
        ("stated explicitly as a non-optional alternative in 'Sprachen'") — the exact
        profile-relative framing this issue exists to establish, inverted. So the rule
        names both shapes, and insists both point at the profile.
        """
        assert "ABSENT" in SYSTEM_PROMPT and "CONFLICT" in SYSTEM_PROMPT
        assert "Background states B2" in SYSTEM_PROMPT
        assert (
            "a gap justified only by quoting the job posting is not grounded"
            in SYSTEM_PROMPT
        )

    def test_the_framing_is_about_the_profile_not_the_candidate(self):
        """#100 is why this is not pedantry: three entries on #3004625 were skills the
        candidate held and had simply not listed, and they read as deficiencies."""
        assert "never about the candidate" in SYSTEM_PROMPT
        assert "silence is not evidence of inability" in SYSTEM_PROMPT

    def test_rule_mandated_gaps_outrank_discretionary_ones(self):
        """The cap has to say which entries lose when it binds, or the field it drops
        is arbitrary — and a dropped rule-mandated gap deletes the only human-visible
        record that the rule fired on an absence."""
        assert "first every gap a scoring rule below tells you to put in gaps" in SYSTEM_PROMPT

    def test_rule_mandated_gaps_cannot_overflow_the_cap(self):
        """The structural half of the precedence decision, and the reason `5` is safe.

        Six rules mandate a gap, which is one more than the cap — but
        `penalty_degree_mandatory` ("hard mandatory requirement with no alternative
        path") and `penalty_degree_preferred` ("preferred but comparable experience is
        explicitly accepted") describe mutually exclusive states of one listing, so at
        most five can fire together.

        This asserts that arithmetic rather than trusting it. A seventh gaps-mandating
        rule, or a change that makes the degree pair co-fireable, breaks this test and
        forces the cap to be revisited instead of silently dropping evidence.

        Detection is on the bare phrase "in gaps", NOT on a list of marker strings.
        The first draft of this test looked for "include in gaps" or "name it in
        gaps" and missed `penalty_ramp_up_risk`, which says "Name the missing
        deliverable in gaps" — a third phrasing. The prompt's own precedence sentence
        had the same bug for the same reason and was reworded to be phrasing-
        independent alongside this.
        """
        from jobscout.evaluation.prompt import _RUBRIC

        bullets = re.split(r"\n\s*- (?=\[)", _RUBRIC)
        mandating = {
            match.group(1)
            for bullet in bullets
            if (match := re.match(r"\[([a-z][a-z0-9_]*)\]", bullet.strip()))
            and "in gaps" in bullet.lower()
        }

        assert mandating == {
            "penalty_degree_mandatory",
            "penalty_degree_preferred",
            "penalty_german_language",
            "penalty_ramp_up_risk",
            "penalty_cloud_core",
            "penalty_remote",
        }, (
            "the set of gaps-mandating rules changed; the cap of 5 was justified "
            "against this exact set — see the docstring"
        )

        mutually_exclusive = {"penalty_degree_mandatory", "penalty_degree_preferred"}
        max_simultaneous = len(mandating - mutually_exclusive) + 1
        assert max_simultaneous <= 5, (
            f"{max_simultaneous} rule-mandated gaps can fire at once against a cap of "
            "5, so the cap can now drop one. Raise the cap or re-scope the rules."
        )


class TestSystemPromptAsksForTheScoreTrace:
    """#95. The Python check is only as good as what the model is asked to return."""

    def test_score_trace_is_a_required_field(self):
        assert "- score_trace:" in SYSTEM_PROMPT
        assert "Score trace" in SYSTEM_PROMPT

    def test_the_trace_is_asked_for_before_the_score(self):
        """Field order is generation order, and that is the difference between an
        instrument that measures the arithmetic and one that only decorates it.

        Asked for after match_score, the trace can only rationalise a score already
        written: measured 15 of 16 parseable responses failing the arithmetic check,
        the model scoring above its own total nearly every time. Asked for first, the
        score is read off a total the model has already committed to.
        """
        assert SYSTEM_PROMPT.index("- score_trace:") < SYSTEM_PROMPT.index("- match_score:")
        assert "IN THIS ORDER" in SYSTEM_PROMPT
        assert "Emit it FIRST, before match_score" in SYSTEM_PROMPT

    def test_every_rule_carries_a_stable_id(self):
        """One id per boost and per penalty. The count is asserted so a rule added
        without a tag — which would leave it un-traceable and un-checkable — fails
        here rather than going quiet."""
        assert len(RULE_IDS) == 12
        assert len(set(RULE_IDS)) == len(RULE_IDS)
        # The two the handoff wrote its worked examples against, by name.
        assert "boost_core_stack" in RULE_IDS
        assert "penalty_remote" in RULE_IDS

    def test_the_id_list_handed_to_the_model_is_derived_from_the_tags(self):
        """RULE_IDS is read back out of the rubric's own tags, so a renamed rule cannot
        leave the trace spec asking for the old id.

        Each id appears at least twice — once tagging its rule, once in the list the
        trace spec interpolates. The two used in the worked example appear a third
        time, which is why this is a floor rather than an equality.
        """
        for rule_id in RULE_IDS:
            assert f"[{rule_id}]" in SYSTEM_PROMPT
            assert SYSTEM_PROMPT.count(rule_id) >= 2, (
                f"{rule_id} tags a rule but is missing from the trace-spec id list"
            )
        # The list itself is interpolated, never hand-written — the guard against the
        # drift this whole arrangement exists to prevent.
        assert ", ".join(RULE_IDS) in SYSTEM_PROMPT

    def test_the_total_is_asked_for_as_an_integer_and_the_floor_is_stated(self):
        """Both pin a live parse failure, not a hypothetical.

        Told to sum the deltas with nowhere to put the answer, Haiku wrote
        `"total": 6 + 1 + 1 - 2 - 1 - 3` — an expression, not JSON — on 6 of 25
        listings. And the rubric's step 3 states a cap but no floor, so a trace
        totalling 0 was emitted as `match_score: 0`, which `Field(ge=1)` then rejected,
        costing the row. Asking for one integer, and naming the floor, fixes both.
        """
        assert "ONE integer that you have already worked out" in SYSTEM_PROMPT
        assert "never as an expression" in SYSTEM_PROMPT
        assert "below 1 report 1, above 9 report 9" in SYSTEM_PROMPT

    def test_the_arithmetic_and_evidence_contracts_are_stated(self):
        """These are what check_score_trace enforces; asking for something else in the
        prompt would make every response a false positive."""
        assert '"delta" is SIGNED' in SYSTEM_PROMPT
        assert 'MUST carry non-empty "evidence"' in SYSTEM_PROMPT
        assert 'match_score is "total" bounded into 1–9' in SYSTEM_PROMPT
        assert 'Never report "fired": true with "delta": 0.' in SYSTEM_PROMPT

    def test_the_rubric_wording_is_untouched_by_the_tags(self):
        """#95 must not reword or re-weight a rule — that is C1/C2/C3. The tags sit at
        the head of each bullet for exactly this reason: every rule sentence still
        starts at its original first word."""
        assert "[penalty_remote] REDUCE by 3 pts: the role is not fully remote" in SYSTEM_PROMPT
        assert "[boost_core_stack] BOOST by 1 pt: stack explicitly mentions" in SYSTEM_PROMPT
        assert "[penalty_german_language] REDUCE by 0–2 pts" in SYSTEM_PROMPT
        assert "[penalty_ramp_up_risk] REDUCE by 0–3 pts" in SYSTEM_PROMPT
