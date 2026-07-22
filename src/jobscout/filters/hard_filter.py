from __future__ import annotations

import logging
import re

from jobscout.models import JobListing, UserProfile

logger = logging.getLogger(__name__)


def apply_hard_filter(jobs: list[JobListing], profile: UserProfile) -> list[JobListing]:
    """Drop jobs that fail any hard rule. Returns surviving jobs."""
    before = len(jobs)
    result = [j for j in jobs if _passes_all(j, profile)]
    logger.info("Hard filter: %d → %d jobs passed", before, len(result))
    return result


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def _passes_all(job: JobListing, profile: UserProfile) -> bool:
    # Every predicate is a pure AND, so order is not semantically significant.
    # `_passes_contract_type` goes first only because it is the cheapest — one
    # membership test, no string scan — and rejects roughly 19% of the pool, so
    # putting it ahead of the keyword predicates that build and lowercase the
    # full job text is free.
    return (
        _passes_contract_type(job, profile)
        and _passes_company(job, profile)
        and _passes_exclude_keywords(job, profile)
        and _passes_require_keywords(job, profile)
        and _passes_location(job, profile)
    )


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------

def _job_text(job: JobListing) -> str:
    return f"{job.title} {job.description}"


def _passes_company(job: JobListing, profile: UserProfile) -> bool:
    if not profile.dealbreakers.exclude_companies:
        return True
    job_company = job.company.lower()
    return job_company not in {c.lower() for c in profile.dealbreakers.exclude_companies}


def _passes_exclude_keywords(job: JobListing, profile: UserProfile) -> bool:
    if not profile.dealbreakers.exclude_keywords:
        return True
    text = _job_text(job).lower()
    return not any(kw.lower() in text for kw in profile.dealbreakers.exclude_keywords)


def _passes_require_keywords(job: JobListing, profile: UserProfile) -> bool:
    if not profile.dealbreakers.require_any_keyword:
        return True
    text = _job_text(job).lower()
    return any(
        re.search(rf"\b{re.escape(kw.lower())}\b", text)
        for kw in profile.dealbreakers.require_any_keyword
    )


def _passes_contract_type(job: JobListing, profile: UserProfile) -> bool:
    """Reject the engagement forms the user has named. Everything else passes.

    A blocklist, never an allowlist. An allowlist of ["contracting"] would silently
    delete every `unknown` row the day a source that cannot determine the engagement
    form is added — so this fails *open* (an unwanted leasing row reaches eval)
    rather than *closed* (a silently empty digest). An empty list rejects nothing.
    """
    return job.contract_type not in profile.dealbreakers.exclude_contract_types


def _passes_location(job: JobListing, profile: UserProfile) -> bool:
    """Gate on how remote the work is, falling back to where it is.

    Two axes, and which one applies depends on what the source actually told us.
    """
    pct = job.remote_percentage
    floor = profile.dealbreakers.minimum_remote_percentage

    if pct is not None and floor is not None:
        # The percentage is the better signal, so it decides alone: meeting the
        # floor is a country-blind pass (a remote project is not rejected for being
        # posted from the wrong city), and falling short is a reject even in a
        # target country (the floor outranks location).
        return pct >= floor

    # The floor did not decide — either the source published no percentage, or the
    # gate is switched off. The REMOTE axis fails open (the job is not rejected for
    # being insufficiently remote), but fully-remote work is still exempt from the
    # country check. This reaches `remote_policy` rather than the raw percentage so
    # that a text-only source saying "remote" is read too. It cannot contradict the
    # branch above, which returned whenever both values were present.
    if job.remote_policy == "remote":
        return True

    # ...and the LOCATION axis still applies. This is the half that keeps
    # `target_countries` live: "fails open" is scoped to remoteness, not to the
    # whole predicate. Reading it as an unconditional pass would make the only
    # surviving location field dead config.
    return any(
        country.lower() in job.location.lower()
        for country in profile.location.target_countries
    )
