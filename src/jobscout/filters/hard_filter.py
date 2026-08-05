from __future__ import annotations

import logging
import re

from jobscout.filters.employee_leasing import classify_employee_leasing
from jobscout.models import JobListing, UserProfile

logger = logging.getLogger(__name__)


def apply_hard_filter(jobs: list[JobListing], profile: UserProfile) -> list[JobListing]:
    """Drop jobs that fail any hard rule. Returns surviving jobs."""
    before = len(jobs)
    result = [j for j in jobs if _passes_all(j, profile)]
    logger.info("Hard filter: %d -> %d jobs passed", before, len(result))
    return result


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def _passes_all(job: JobListing, profile: UserProfile) -> bool:
    # Every predicate is a pure AND, so order is not semantically significant.
    # `_passes_contract_type` goes first only because it is the cheapest — one
    # membership test, no string scan — and rejects roughly 19% of the pool, so
    # putting it ahead of the keyword predicates that build and lowercase the
    # full job text is free. By the same reasoning `_passes_employee_leasing`
    # goes behind them: it scans the same full text but rejects a far smaller
    # share of the pool, being the residue its own metadata gate let through.
    return (
        _passes_contract_type(job, profile)
        and _passes_company(job, profile)
        and _passes_exclude_keywords(job, profile)
        and _passes_require_keywords(job, profile)
        and _passes_employee_leasing(job, profile)
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


def _passes_employee_leasing(job: JobListing, profile: UserProfile) -> bool:
    """Reject leasing-only work the source's own tag did not declare.

    The prose half of the same gate `_passes_contract_type` implements in
    metadata, and armed by the same config key rather than by a constant of its
    own: scanning for leasing prose while the user permits `employee_leasing`
    would drop rows they asked to see. One switch, both layers — so the day
    `employee_leasing` leaves `exclude_contract_types`, this stops too.

    Only `exclusive` drops. `optional` and `unknown` pass untouched, and the
    classification is not carried anywhere — surfacing `optional` needs a field
    on `JobListing` and a channel to the digest, which is drop-observability work.
    """
    if "employee_leasing" not in profile.dealbreakers.exclude_contract_types:
        return True

    verdict = classify_employee_leasing(_job_text(job))
    if verdict.state != "exclusive":
        return True

    # The one place a drop is visible today. `_passes_all` short-circuits and no
    # predicate returns a reason, so a row already rejected upstream never reaches
    # here to be logged — the general fix is the drop ledger, not a log line here.
    # The cue reaches the stream as a value rather than as a literal, which is what
    # keeps German text out of this module's ASCII-only sink literals.
    logger.info(
        "Hard filter drop: job %s is employee-leasing only, matched cue %r",
        job.id, verdict.cue,
    )
    return False


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
