from __future__ import annotations

import json
import logging
from dataclasses import replace

import anthropic

from jobscout.evaluation.prompt import SCORE_CAP, SCORE_FLOOR, SYSTEM_PROMPT, build_prompt
from jobscout.models import EvaluationResult, ScoredJob, UserProfile

logger = logging.getLogger(__name__)

# Output ceiling for one evaluation. Named rather than inline because what it has to
# cover lives in another module: the response now carries one trace entry per entry in
# prompt.RULE_IDS, and each firing entry adds an evidence quote, so adding a rule to
# the rubric raises the floor this has to clear.
#
# 512, not 256: the graded ramp-up-risk rubric (spec 4 / #29) makes Haiku write longer
# reasoning and gaps lists, and at 256 the JSON was truncated mid-string on ~76% of a
# live freelancermap pool (stop_reason=max_tokens), failing the parse. Measured 6/25
# parseable at 256 vs 24/25 at 512. The residual overflow still fails loudly and sorts
# last, it does not crash.
#
# 2560, not 512: #95's score_trace re-opened that failure - completely. Measured on one
# live freelancermap pool of 25 (2026-08-03), same cached pool for every arm:
#
#   512   0/25 parseable, 25/25 truncated at the ceiling
#   1536  16/25 parseable, 10/25 truncated
#   2560  25/25 parseable, 0/25 truncated, output tokens 818/1059/1294 (min/mean/max)
#
# So 0/25 at 512 vs 25/25 at 2560 - the same shape as the 6/25-vs-24/25 result that set
# the previous value, and it clears the 24/25 the pre-trace prompt managed at 512.
#
# The headroom over the 1294 observed maximum is deliberate and is not slack. An
# earlier arm of the same prompt - differing only in a duplicated `score_trace` bullet
# since removed - measured 24/25 with a 1666-token maximum, so ~370 tokens of spread
# sits between two near-identical prompts on one pool. Trace length scales with how
# many rules fire, and this is one day's listings.
MAX_OUTPUT_TOKENS = 2560


async def evaluate_jobs(
    jobs: list[ScoredJob],
    profile: UserProfile,
    client: anthropic.AsyncAnthropic,
    model: str,
    top_n: int,
    reeval_below: int = 4,
) -> list[ScoredJob]:
    """Evaluate top_n jobs with an Anthropic model and return them with LLM scores attached.

    Jobs are evaluated sequentially. On any failure the job is retained with
    llm_score=None and final_score=None rather than being dropped.

    Jobs whose first score falls below reeval_below are evaluated a second time;
    the higher of the two scores is kept.

    The score each job comes back with is checked against the trace the model returned
    for it (`check_score_trace`). A job whose arithmetic does not reconcile is logged at
    WARNING and carries the reasons in `trace_warnings` - it is never dropped for it.

    Args:
        jobs: Ranked ScoredJobs (embedding_score populated, sorted descending).
        profile: User profile for prompt construction.
        client: Async Anthropic client.
        model: Model ID to use (e.g. 'claude-haiku-4-5-20251001').
        top_n: Maximum number of jobs to evaluate and return — the LLM pool bound.
            Required (no default): it is owned by config.py and injected by run.py, so
            the constant lives in exactly one place.
        reeval_below: Re-evaluate jobs whose match_score is strictly below this value.

    Returns:
        top_n ScoredJobs with llm_score, final_score, and evaluation populated
        where the model succeeded, sorted descending by final_score (tiebroken by
        embedding_score; failed evaluations last).
    """
    candidates = jobs[:top_n]
    results: list[ScoredJob] = []

    for job in candidates:
        evaluated = await _evaluate_one(job, profile, client, model)
        if evaluated.evaluation and evaluated.evaluation.match_score < reeval_below:
            logger.debug(
                "Re-evaluating %s (%s): first score %d < %d",
                job.listing.id,
                job.listing.title,
                evaluated.evaluation.match_score,
                reeval_below,
            )
            second = await _evaluate_one(job, profile, client, model)
            if second.evaluation and second.evaluation.match_score > evaluated.evaluation.match_score:
                logger.debug(
                    "Re-eval improved score: %d -> %d",
                    evaluated.evaluation.match_score,
                    second.evaluation.match_score,
                )
                evaluated = second
        # Deliberately here, and not inside _evaluate_one. That function's bare
        # `except Exception` returns the job unevaluated, and format_digest then drops
        # unevaluated rows entirely - so an arithmetic check that raised in there would
        # delete the row it was meant to flag, which is the opposite of what #95 asks
        # for. Here the response has already been parsed and kept; all this can do is
        # attach a warning. It also runs on the surviving evaluation after re-eval, so
        # a discarded first sample is not flagged.
        results.append(_flag_score_trace(evaluated))

    # The stage that produces the score is the stage that orders by it — which makes
    # formatter.py's "assumed sorted by final_score descending" docstring true rather
    # than aspirational (F #9 decision 9). Sort key details are load-bearing:
    #   - Descending by final_score, tiebroken by embedding_score. llm_score takes at
    #     most ten distinct values across a pool of twenty-five, so ties dominate;
    #     state the tiebreak rather than relying on the stable sort to preserve the
    #     (accidentally correct) embedding order.
    #   - final_score is None when evaluation failed. Those sort last so one bad Haiku
    #     response neither crashes the run nor displaces a real result (format_digest
    #     filters them out downstream anyway).
    def _sort_key(job: ScoredJob) -> tuple[int, float, float]:
        has_score = job.final_score is not None
        return (
            0 if has_score else 1,
            -(job.final_score if has_score else 0.0),
            -job.embedding_score,
        )

    return sorted(results, key=_sort_key)


def check_score_trace(evaluation: EvaluationResult) -> list[str]:
    """Return the reasons a score_trace fails to justify its own match_score.

    An empty list is the healthy case: the arithmetic reconciles, every rule the model
    reported as fired cites evidence for it, and no entry contradicts itself.

    This is the check D2, D3 and D4 went twelve days without. In all three the model
    comprehended a rule, named it in its own prose, and then did not move the score -
    invisible while the score arrived as a bare integer.

    Pure and non-raising by construction. The caller runs it outside the evaluator's
    swallowing `except`, so it must not need a `try` of its own; the caller's job is to
    keep the row and attach what comes back.
    """
    trace = evaluation.score_trace
    if trace is None:
        return ["no score_trace returned, so the score is unverifiable"]

    problems: list[str] = []

    total = trace.start + sum(a.delta for a in trace.adjustments)

    # The model reports its own sum too. Recomputing it here rather than trusting it is
    # the point of the exercise, but comparing the two separates two different faults:
    # a wrong `total` is arithmetic the model got wrong, while a right `total` that
    # match_score disagrees with is the model overriding a sum it had already worked
    # out - which is the D2/D3/D4 shape.
    if trace.total is not None and trace.total != total:
        problems.append(
            f"reported total {trace.total} is not start {trace.start} plus the deltas ({total})"
        )

    # Bounded, not the bare sum. The floor is the one that bites: a listing starting at
    # 2 that takes the remote (-3) and ramp-up (-3) penalties sums to -4, which is
    # exactly D6's shape - several hard blockers at once - and match_score cannot go
    # there. Comparing the raw sum would flag a correctly scored row on every run, and a
    # check that cries wolf on its most important cases is a check somebody switches
    # off. The cap is unreachable by the rubric's own maxima (start 6 plus three 1-pt
    # boosts = 9) and is applied only because step 3 states it; a trace summing above it
    # means a boost was invented, which is worth flagging. Both bounds are the rubric's
    # own, which is why they are imported from prompt.py rather than re-typed here.
    expected = min(max(total, SCORE_FLOOR), SCORE_CAP)
    if expected != evaluation.match_score:
        deltas = ", ".join(f"{a.rule_id}{a.delta:+d}" for a in trace.adjustments if a.delta)
        problems.append(
            f"arithmetic mismatch: start {trace.start} with {deltas or 'no adjustments'} "
            f"gives {total} (bounded {expected}), but match_score is {evaluation.match_score}"
        )

    for adj in trace.adjustments:
        if adj.fired and not (adj.evidence or "").strip():
            problems.append(f"{adj.rule_id} fired with no evidence")
        # The two halves of a contradiction the arithmetic cannot see: a rule reported
        # as fired that moved the score by nothing is D3 exactly (the handoff's worked
        # example is `penalty_remote, fired: true, delta: 0`), and a rule reported as
        # not fired that moved the score is an adjustment with no rule behind it. Both
        # sum correctly, so only this catches them.
        if adj.fired and adj.delta == 0:
            problems.append(f"{adj.rule_id} fired but contributed 0")
        if not adj.fired and adj.delta != 0:
            problems.append(f"{adj.rule_id} did not fire but contributed {adj.delta:+d}")

    return problems


def _flag_score_trace(job: ScoredJob) -> ScoredJob:
    """Log and attach any reason this job's score is not justified by its trace.

    The row is returned either way - flagged, never dropped.
    """
    if job.evaluation is None:
        return job  # already logged by _evaluate_one, and there is nothing to check

    problems = check_score_trace(job.evaluation)
    if not problems:
        return job

    logger.warning(
        "Score trace does not justify score %d/10 for job %s (%s): %s",
        job.evaluation.match_score,
        job.listing.id,
        job.listing.title,
        "; ".join(problems),
    )
    return replace(job, trace_warnings=tuple(problems))


async def _evaluate_one(
    job: ScoredJob,
    profile: UserProfile,
    client: anthropic.AsyncAnthropic,
    model: str,
) -> ScoredJob:
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(job.listing, profile)}],
        )
        raw = response.content[0].text
        if raw is None:
            raise ValueError("model returned empty content")
        raw = raw.strip()
        if raw.startswith("```"):
            # Haiku wraps JSON in code fences despite explicit instructions
            raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0].strip()
        evaluation = EvaluationResult.model_validate(json.loads(raw))
    except Exception as exc:
        logger.warning(
            "Evaluation failed for job %s (%s): %s",
            job.listing.id,
            job.listing.title,
            exc,
        )
        return job

    llm_score = evaluation.match_score / 10
    # No blend: the reranker's judgement orders the digest, the retriever only picked
    # the pool. The old 0.4/0.6 was ~27/73 by spread, no measurement justified it, and
    # blending a possibly-cross-language-broken cosine into final ordering spread
    # language risk out of recall and into the digest (F #9 decision 9).
    final_score = llm_score

    return replace(job, llm_score=llm_score, final_score=final_score, evaluation=evaluation)
