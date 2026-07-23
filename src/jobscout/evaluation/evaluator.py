from __future__ import annotations

import json
import logging
from dataclasses import replace

import anthropic

from jobscout.evaluation.prompt import SYSTEM_PROMPT, build_prompt
from jobscout.models import EvaluationResult, ScoredJob, UserProfile

logger = logging.getLogger(__name__)


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
                    "Re-eval improved score: %d → %d",
                    evaluated.evaluation.match_score,
                    second.evaluation.match_score,
                )
                evaluated = second
        results.append(evaluated)

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


async def _evaluate_one(
    job: ScoredJob,
    profile: UserProfile,
    client: anthropic.AsyncAnthropic,
    model: str,
) -> ScoredJob:
    try:
        response = await client.messages.create(
            # 512, not 256: the graded ramp-up-risk rubric (spec 4 / #29) makes Haiku
            # write longer reasoning and gaps lists, and at 256 the JSON was truncated
            # mid-string on ~76% of a live freelancermap pool (stop_reason=max_tokens),
            # failing the parse. Measured 6/25 parseable at 256 vs 24/25 at 512. The
            # residual overflow still fails loudly and sorts last, it does not crash.
            model=model,
            max_tokens=512,
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
