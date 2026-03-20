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
    top_n: int = 25,
) -> list[ScoredJob]:
    """Evaluate top_n jobs with Claude and return them with LLM scores attached.

    Jobs are evaluated sequentially. On any failure the job is retained with
    llm_score=None and final_score=None rather than being dropped.

    Args:
        jobs: Ranked ScoredJobs (embedding_score populated, sorted descending).
        profile: User profile for prompt construction.
        client: Async Anthropic client.
        model: Model ID to use (e.g. 'claude-haiku-4-5-20251001').
        top_n: Maximum number of jobs to evaluate and return.

    Returns:
        top_n ScoredJobs with llm_score, final_score, and evaluation populated
        where Haiku succeeded.
    """
    candidates = jobs[:top_n]
    results: list[ScoredJob] = []

    for job in candidates:
        evaluated = await _evaluate_one(job, profile, client, model)
        results.append(evaluated)

    return results


async def _evaluate_one(
    job: ScoredJob,
    profile: UserProfile,
    client: anthropic.AsyncAnthropic,
    model: str,
) -> ScoredJob:
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(job.listing, profile)}],
        )
        raw = response.content[0].text
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
    final_score = 0.4 * job.embedding_score + 0.6 * llm_score

    return replace(job, llm_score=llm_score, final_score=final_score, evaluation=evaluation)
