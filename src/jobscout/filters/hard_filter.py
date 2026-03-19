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
    return (
        _passes_seniority(job, profile)
        and _passes_company(job, profile)
        and _passes_exclude_keywords(job, profile)
        and _passes_require_keywords(job, profile)
        and _passes_salary(job, profile)
        and _passes_location(job, profile)
    )


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------

def _passes_seniority(job: JobListing, profile: UserProfile) -> bool:
    if job.seniority is None or job.seniority == "not_specified":
        return True
    return job.seniority not in profile.seniority.exclude


def _passes_company(job: JobListing, profile: UserProfile) -> bool:
    if not profile.dealbreakers.exclude_companies:
        return True
    job_company = job.company.lower()
    return job_company not in {c.lower() for c in profile.dealbreakers.exclude_companies}


def _passes_exclude_keywords(job: JobListing, profile: UserProfile) -> bool:
    if not profile.dealbreakers.exclude_keywords:
        return True
    text = f"{job.title} {job.description}".lower()
    return not any(kw.lower() in text for kw in profile.dealbreakers.exclude_keywords)


def _passes_require_keywords(job: JobListing, profile: UserProfile) -> bool:
    if not profile.dealbreakers.require_any_keyword:
        return True
    text = f"{job.title} {job.description}".lower()
    return any(
        re.search(rf"\b{re.escape(kw.lower())}\b", text)
        for kw in profile.dealbreakers.require_any_keyword
    )


def _passes_salary(job: JobListing, profile: UserProfile) -> bool:
    if job.salary_max is None:
        return True
    return job.salary_max >= profile.salary.minimum_annual_eur


def _passes_location(job: JobListing, profile: UserProfile) -> bool:
    if job.remote_policy == "remote":
        return True
    if job.remote_policy == "not_specified":
        # Trust the location string — if it mentions Germany, keep it
        return any(
            country.lower() in job.location.lower()
            for country in profile.location.target_countries
        )
    return any(
        country.lower() in job.location.lower()
        for country in profile.location.target_countries
    )
