"""Cross-source and within-source deduplication by title+company fingerprint."""
from __future__ import annotations

import logging
import re
import string

from jobscout.models import JobListing

logger = logging.getLogger(__name__)

_ABBREV = {
    r"\bsr\b": "senior",
    r"\bjr\b": "junior",
    r"\bml\b": "machine learning",
    r"\bnlp\b": "natural language processing",
}


def _fingerprint(title: str, company: str) -> str:
    def normalize(s: str) -> str:
        s = s.lower()
        s = s.translate(str.maketrans(string.punctuation, " " * len(string.punctuation)))
        for pattern, replacement in _ABBREV.items():
            s = re.sub(pattern, replacement, s)
        return " ".join(s.split())

    return f"{normalize(title)}|{normalize(company)}"


def deduplicate_listings(jobs: list[JobListing]) -> list[JobListing]:
    """Return one listing per title+company fingerprint, keeping the longest description."""
    groups: dict[str, list[JobListing]] = {}
    for job in jobs:
        key = _fingerprint(job.title, job.company)
        groups.setdefault(key, []).append(job)

    winners: list[JobListing] = []
    dup_groups = 0
    dropped_total = 0

    for key, group in groups.items():
        if len(group) == 1:
            winners.append(group[0])
            continue

        dup_groups += 1
        dropped_total += len(group) - 1
        best = max(group, key=lambda j: len(j.description))

        kept_src = best.source
        dropped_srcs = [j.source for j in group if j is not best]
        logger.debug(
            "Duplicate group: %r — kept %s (%d chars), dropped %s",
            key,
            kept_src,
            len(best.description),
            ", ".join(dropped_srcs),
        )
        winners.append(best)

    if dup_groups:
        logger.info(
            "Deduplication: %d duplicate group(s) found — %d listing(s) dropped",
            dup_groups,
            dropped_total,
        )

    # Preserve original input order
    seen_ids = {id(j) for j in winners}
    return [j for j in jobs if id(j) in seen_ids]
