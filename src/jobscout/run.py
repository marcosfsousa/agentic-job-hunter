from __future__ import annotations

import argparse
import asyncio
import logging

import anthropic

from jobscout.adapters.adzuna import AdzunaAdapter
from jobscout.adapters.base import JobScoutAdapterError
from jobscout.config import get_config
from jobscout.evaluation.evaluator import evaluate_jobs
from jobscout.filters.hard_filter import apply_hard_filter
from jobscout.models import JobListing, ScoredJob
from jobscout.ranking.embedder import ProfileEmbedder
from jobscout.ranking.scorer import rank_jobs
from jobscout.storage.db import JobDatabase

logger = logging.getLogger(__name__)

# Maps profile.yaml markets.active entries to adapter classes
_ADAPTER_REGISTRY = {
    "germany": AdzunaAdapter,
}


async def run_pipeline(
    dry_run: bool = False,
    max_results: int = 100,
) -> list[ScoredJob]:
    """Run the full pipeline: fetch → deduplicate → filter.

    Args:
        dry_run: If True, skip all database writes.
        max_results: Maximum listings to fetch per adapter.

    Returns:
        Filtered job listings ready for ranking.
    """
    config = get_config()
    active_markets: list[str] = config.profile.markets.active

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------
    all_jobs: list[JobListing] = []

    for market in active_markets:
        adapter_cls = _ADAPTER_REGISTRY.get(market)
        if adapter_cls is None:
            logger.warning("No adapter registered for market '%s' — skipping", market)
            continue

        adapter = adapter_cls(config)
        try:
            jobs = await adapter.fetch(max_results=max_results)
            all_jobs.extend(jobs)
        except JobScoutAdapterError as exc:
            logger.warning("Adapter for '%s' failed — skipping: %s", market, exc)

    # ------------------------------------------------------------------
    # Deduplicate (skip on dry-run)
    # ------------------------------------------------------------------
    embedder = ProfileEmbedder()

    if dry_run:
        unseen = all_jobs
        logger.info("Dry-run: skipping deduplication (%d jobs)", len(unseen))
    else:
        with JobDatabase(config.db_path) as db:
            unseen = db.filter_unseen(all_jobs)
            db.mark_seen_bulk(unseen)

    # ------------------------------------------------------------------
    # Hard filter + rank
    # ------------------------------------------------------------------
    filtered = apply_hard_filter(unseen, config.profile)
    ranked = rank_jobs(filtered, config.profile, embedder)

    # ------------------------------------------------------------------
    # LLM evaluate (top 25 only)
    # ------------------------------------------------------------------
    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
    evaluated = await evaluate_jobs(ranked, config.profile, client, config.llm_model)
    logger.info("Pipeline complete — %d jobs evaluated", len(evaluated))
    return evaluated


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JobScout pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch, deduplicate, and filter — but skip all DB writes.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=100,
        metavar="N",
        help="Maximum listings to fetch per adapter (default: 100).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    asyncio.run(run_pipeline(dry_run=args.dry_run, max_results=args.max_results))
