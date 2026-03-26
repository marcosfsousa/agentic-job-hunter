from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date
from pathlib import Path
import openai
import yaml

from jobscout.adapters.adzuna import AdzunaAdapter
from jobscout.adapters.base import JobScoutAdapterError
from jobscout.adapters.jsearch import JSearchAdapter
from jobscout.config import get_config
from jobscout.delivery.email_sender import send_digest
from jobscout.delivery.formatter import format_digest
from jobscout.delivery.writer import write_digest
from jobscout.evaluation.evaluator import evaluate_jobs
from jobscout.filters.dedup import deduplicate_listings
from jobscout.filters.hard_filter import apply_hard_filter
from jobscout.models import FeedbackEntry, JobListing, ScoredJob
from jobscout.ranking.embedder import ProfileEmbedder
from jobscout.ranking.scorer import rank_jobs
from jobscout.storage.db import JobDatabase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feedback helpers
# ---------------------------------------------------------------------------

def _run_review(review_date: date) -> None:
    """Interactively label jobs from a given date and write feedback to yaml + DB."""
    config = get_config()
    feedback_path = config.feedback_path

    with JobDatabase(config.db_path) as db:
        jobs = db.get_unreviewed_for_digest(review_date)
        if not jobs:
            print(f"No digest jobs recorded for {review_date.isoformat()}.")
            print("Either no jobs met the score threshold, or this date predates digest tracking.")
            return

        print(f"\nReviewing {len(jobs)} job(s) from {review_date.isoformat()}.")
        print("Labels: [a]pplied  [r]ejected  [i]nterested  [s]kip\n")

        status_map = {"a": "applied", "r": "rejected", "i": "interested", "s": "skipped"}
        yaml_entries: list[dict] = []
        all_entries: list[FeedbackEntry] = []

        for idx, (job_id, source, title, company) in enumerate(jobs, start=1):
            label_str = f"{title} — {company}" if company else title
            while True:
                raw = input(f"{idx}. {label_str}\n   [a/r/i/s]: ").strip().lower()
                if raw in ("a", "r", "i", "s"):
                    break
                print("   Please enter a, r, i, or s.")

            status = status_map[raw]
            entry = FeedbackEntry(id=job_id, source=source, status=status)
            all_entries.append(entry)
            if status != "skipped":
                yaml_entries.append({"id": job_id, "source": source, "status": status})

        # Write a/r/i entries to feedback.yaml
        if yaml_entries:
            try:
                existing = yaml.safe_load(feedback_path.read_text(encoding="utf-8")) or []
            except FileNotFoundError:
                existing = []
            feedback_path.write_text(
                yaml.dump(existing + yaml_entries, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )

        # Upsert all (including skipped) to DB
        db.upsert_feedback(all_entries)

    labeled = sum(1 for e in all_entries if e.status != "skipped")
    skipped = len(all_entries) - labeled
    print(f"\nDone — {labeled} labeled, {skipped} skipped.")


def _sync_feedback(db: "JobDatabase", feedback_path: Path) -> None:
    """Load feedback.yaml and upsert entries into DB. No-op if file is absent."""
    try:
        with feedback_path.open() as f:
            raw = yaml.safe_load(f) or []
    except FileNotFoundError:
        logger.info("No feedback file found at %s — skipping", feedback_path)
        return
    entries: list[FeedbackEntry] = []
    for item in raw:
        try:
            entries.append(FeedbackEntry.model_validate(item))
        except Exception as exc:
            logger.warning("Skipping invalid feedback entry %s: %s", item, exc)
    db.upsert_feedback(entries)
    logger.info("Feedback synced: %d entries", len(entries))


# All registered adapters run on every pipeline execution.
# An adapter self-disables if its API key is absent from .env.
_ADAPTER_REGISTRY = {
    "germany": AdzunaAdapter,
    "jsearch": JSearchAdapter,
}


async def run_pipeline(
    dry_run: bool = False,
    max_results: int = 100,
    since: date | None = None,
) -> list[ScoredJob]:
    """Run the full pipeline: fetch → deduplicate → filter.

    Args:
        dry_run: If True, skip all database writes.
        max_results: Maximum listings to fetch per adapter.
        since: If provided, only keep listings posted on or after this date.

    Returns:
        Filtered job listings ready for ranking.
    """
    config = get_config()
    feedback_path = config.feedback_path

    # ------------------------------------------------------------------
    # Ingest — all registered adapters fetched concurrently.
    # Each adapter self-disables when its API key is absent.
    # To add/remove a source: update _ADAPTER_REGISTRY and .env.
    # ------------------------------------------------------------------
    if since is not None:
        logger.info("Running with --since %s — filtering to jobs posted on or after that date", since)

    async def _fetch(adapter_cls) -> list[JobListing]:
        try:
            return await adapter_cls(config).fetch(max_results=max_results, since=since)
        except JobScoutAdapterError as exc:
            logger.warning("%s failed — skipping: %s", adapter_cls.__name__, exc)
            return []

    results = await asyncio.gather(*(_fetch(cls) for cls in _ADAPTER_REGISTRY.values()))
    all_jobs: list[JobListing] = [job for batch in results for job in batch]

    # ------------------------------------------------------------------
    # Deduplicate + feedback filter (skip on dry-run)
    # ------------------------------------------------------------------
    embedder = ProfileEmbedder()

    if dry_run:
        actionable = all_jobs
        feedback_docs: list[str] = []
        logger.info("Dry-run: skipping deduplication and feedback filter (%d jobs)", len(actionable))
    else:
        with JobDatabase(config.db_path) as db:
            _sync_feedback(db, feedback_path)
            unseen = db.filter_unseen(all_jobs)
            db.mark_seen_bulk(unseen)
            unseen = deduplicate_listings(unseen)
            actionable = db.filter_feedback(unseen)
            feedback_docs = db.get_interested_descriptions()

    if feedback_docs:
        logger.info("Feedback centroid: %d interested job(s) loaded", len(feedback_docs))

    # ------------------------------------------------------------------
    # Hard filter + rank
    # ------------------------------------------------------------------
    filtered = apply_hard_filter(actionable, config.profile)
    ranked = rank_jobs(
        filtered, config.profile, embedder,
        feedback_docs=feedback_docs,
        feedback_weight=config.feedback_weight,
    )

    # ------------------------------------------------------------------
    # LLM evaluate (top 25 only)
    # ------------------------------------------------------------------
    client = openai.AsyncOpenAI(api_key=config.openai_api_key)
    evaluated = await evaluate_jobs(ranked, config.profile, client, config.llm_model)

    # ------------------------------------------------------------------
    # Deliver
    # ------------------------------------------------------------------
    run_date = date.today()
    digest = format_digest(evaluated, run_date)
    write_digest(digest, config.digests_dir, run_date)
    if not dry_run:
        min_score = config.profile.email_min_score
        email_jobs = [j for j in evaluated if j.evaluation and j.evaluation.match_score >= min_score]
        with JobDatabase(config.db_path) as db:
            db.mark_in_digest([(j.listing.id, j.listing.source) for j in email_jobs], run_date)
        if email_jobs:
            email_digest = format_digest(email_jobs, run_date)
            await send_digest(email_digest, config, run_date)
        else:
            logger.info("Email skipped — no jobs scored >= %d/10", min_score)

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
    parser.add_argument(
        "--apply-feedback",
        action="store_true",
        help="Sync feedback.yaml to DB and exit without running the pipeline.",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        default=None,
        help="Only include jobs posted on or after this date (e.g. 2026-03-21).",
    )
    parser.add_argument(
        "--review",
        nargs="?",
        const="today",
        metavar="YYYY-MM-DD",
        help="Interactively label jobs from a given date (default: today).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    if args.apply_feedback:
        cfg = get_config()
        with JobDatabase(cfg.db_path) as db:
            _sync_feedback(db, cfg.feedback_path)
    elif args.review is not None:
        review_date = date.today() if args.review == "today" else date.fromisoformat(args.review)
        _run_review(review_date)
    else:
        asyncio.run(run_pipeline(dry_run=args.dry_run, max_results=args.max_results, since=args.since))
