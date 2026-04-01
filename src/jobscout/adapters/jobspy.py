"""JobSpy adapter — scrapes LinkedIn and Indeed via python-jobspy.

JobSpy is sync-only, so fetch() runs each scrape_jobs call in a thread pool
executor to stay non-blocking. Requests are made sequentially (queries × sites)
with a 2-second pause between each call to reduce rate-limit risk.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import itertools
import json
import logging
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from jobscout.adapters.base import JobAdapter, filter_by_since
from jobscout.adapters.inference import _infer_remote_policy, _infer_seniority
from jobscout.models import JobListing

logger = logging.getLogger(__name__)

try:
    from jobspy import scrape_jobs
    import pandas as pd
except ImportError:
    logger.error(
        "python-jobspy is not installed — JobSpyAdapter will produce no results. "
        "Run: pip install python-jobspy"
    )
    scrape_jobs = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Location post-filter
# ---------------------------------------------------------------------------

_GERMAN_SIGNAL = {
    "germany", "deutschland", "berlin", "munich", "münchen",
    "hamburg", "frankfurt", "cologne", "köln", "stuttgart",
}


def _is_german(location: str) -> bool:
    if not location:
        return False
    return any(s in location.lower() for s in _GERMAN_SIGNAL)


# Job board domains that are Germany-scoped in our scrape calls.
# LinkedIn has no .de domain — all our calls use location="Germany" so any
# linkedin.com result is implicitly German-targeted.
_GERMAN_JOB_DOMAINS = frozenset({"de.indeed.com", "indeed.de", "linkedin.com"})


def _is_german_domain(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return any(host == d or host.endswith("." + d) for d in _GERMAN_JOB_DOMAINS)


# ---------------------------------------------------------------------------
# Pandas NaN defence
# ---------------------------------------------------------------------------

def _sanitize_raw(row) -> dict:
    """Convert a DataFrame row to a plain JSON-safe dict.

    row.to_dict() may contain pandas/numpy types (Timestamp, int64, NaN, NaT)
    that are not JSON-serializable. Two-pass sanitization:
      1. Replace NaN/NaT/NA with None (same try/except guard as _safe).
      2. JSON round-trip with default=str to coerce remaining numpy scalars
         and any other non-serializable types to strings.
    """
    raw: dict = {}
    for k, v in row.to_dict().items():
        try:
            raw[k] = None if pd.isna(v) else v  # type: ignore[union-attr]
        except (TypeError, ValueError):
            raw[k] = str(v)  # array-like or unhashable — stringify
    return json.loads(json.dumps(raw, default=str))


def _safe(row, key: str, default=None):
    """Return row[key], substituting default for None/NaN/NaT values.

    pd.isna() raises ValueError for array-like values (e.g. Location namedtuple)
    and TypeError for unhashable types — both are caught and the value returned as-is.
    """
    val = row.get(key)
    try:
        return default if pd.isna(val) else val  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return val  # array-like or unhashable — return as-is


# ---------------------------------------------------------------------------
# Seniority mapping from LinkedIn job_level field
# ---------------------------------------------------------------------------

_JOB_LEVEL_MAP = {
    "internship": "junior",
    "entry level": "junior",
    "associate": "junior",
    "mid-senior level": "mid",
    "director": "lead",
    "executive": "lead",
}


def _map_job_level(job_level: str | None) -> str | None:
    if not job_level:
        return None
    return _JOB_LEVEL_MAP.get(job_level.lower())


# ---------------------------------------------------------------------------
# hours_old conversion
# ---------------------------------------------------------------------------

def _since_to_hours_old(since: date) -> int:
    """Convert a since date to hours_old with a 6-hour buffer and 24h floor.

    The 6-hour buffer compensates for imprecise job board timestamps.
    The 24h floor prevents under-requesting on same-day reruns.
    URL-hash deduplication in the DB handles any resulting cross-run overlap.
    """
    today = date.today()
    hours_requested = (today - since).total_seconds() / 3600
    return max(int(hours_requested) + 6, 24)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class JobSpyAdapter(JobAdapter):
    """Scrapes LinkedIn and Indeed via python-jobspy."""

    @property
    def source(self) -> str:
        return "jobspy"

    async def fetch(self, max_results: int = 100, since: date | None = None) -> list[JobListing]:
        """Fetch listings sequentially across all configured queries and sites.

        Runs queries × sites sequentially with a 2-second pause between calls
        to reduce rate-limit risk on LinkedIn and Indeed. Each scrape_jobs call
        is dispatched to a thread pool executor to stay non-blocking.

        Args:
            max_results: Ignored — per-site caps are set in profile.yaml
                (jobspy_sites.<site>.results_wanted). Kept for interface compat.
            since: If provided, converted to hours_old (with a 6h buffer and
                24h floor) and passed to scrape_jobs. A post-filter then enforces
                the exact cutoff; listings with no posted_date are always kept.
        """
        if scrape_jobs is None:
            return []

        queries: list[str] = self._config.profile.jobspy_queries
        sites: dict = self._config.profile.jobspy_sites

        if not queries or not sites:
            logger.info("JobSpyAdapter: no queries or sites configured — skipping")
            return []

        hours_old = _since_to_hours_old(since) if since is not None else 72
        loop = asyncio.get_running_loop()
        all_listings: list[JobListing] = []

        for call_idx, (query, (site_name, site_cfg)) in enumerate(
            itertools.product(queries, sites.items())
        ):
            if call_idx > 0:
                await asyncio.sleep(2)

            results_wanted: int = site_cfg.get("results_wanted", 25)
            kwargs: dict = {
                "site_name": [site_name],
                "search_term": query,
                "location": "Germany",
                "results_wanted": results_wanted,
                "hours_old": hours_old,
            }
            if site_name == "indeed":
                kwargs["country_indeed"] = site_cfg.get("country_indeed", "Germany")
            if site_name == "linkedin":
                kwargs["linkedin_fetch_description"] = site_cfg.get("fetch_description", False)

            try:
                df = await loop.run_in_executor(
                    None, lambda kw=kwargs: scrape_jobs(**kw)
                )
            except Exception as exc:
                logger.warning("JobSpyAdapter %s query=%r failed — skipping: %s", site_name, query, exc, exc_info=True)
                continue

            logger.info(
                "jobspy/%s query=%r returned %d results",
                site_name, query, len(df),
            )

            for _, row in df.iterrows():
                try:
                    listing = self._normalize(row)
                except Exception as exc:
                    logger.warning(
                        "JobSpyAdapter: skipping row (site=%s, error=%s)", site_name, exc
                    )
                    continue

                if not _is_german(listing.location):
                    if listing.remote_policy == "remote" and _is_german_domain(listing.url):
                        listing = dataclasses.replace(listing, location="Remote, Germany")
                        logger.debug(
                            "JobSpyAdapter: remote listing with no location kept — %s (%s)",
                            listing.title, listing.company,
                        )
                    else:
                        continue

                all_listings.append(listing)

        if since is not None:
            all_listings = filter_by_since(all_listings, since)

        logger.info(
            "JobSpyAdapter fetched %d listings across %d queries × %d sites",
            len(all_listings), len(queries), len(sites),
        )
        return all_listings

    def _normalize(self, row) -> JobListing:
        """Translate a JobSpy DataFrame row into the canonical JobListing."""
        job_url = _safe(row, "job_url", default="")
        listing_id = "jobspy_" + hashlib.sha256(job_url.encode()).hexdigest()[:16]

        title = _safe(row, "title", default="")
        company = _safe(row, "company", default="Unknown")
        description = _safe(row, "description", default="")

        # Compose location from city + country signal
        location_obj = _safe(row, "location")
        city = ""
        if location_obj is not None:
            city = getattr(location_obj, "city", None) or ""
        location = f"{city}, Germany".lstrip(", ") if city else ""

        # Remote policy: is_remote flag first, then infer from text
        is_remote = _safe(row, "is_remote", default=False)
        if is_remote:
            remote_policy = "remote"
        else:
            remote_policy = _infer_remote_policy(title, description or "", location)

        # Salary: only trust yearly figures
        salary_min: float | None = None
        salary_max: float | None = None
        if _safe(row, "interval") == "yearly":
            raw_min = _safe(row, "min_amount")
            raw_max = _safe(row, "max_amount")
            salary_min = float(raw_min) if raw_min is not None else None
            salary_max = float(raw_max) if raw_max is not None else None

        # Seniority: LinkedIn job_level first, fall back to text inference
        job_level = _safe(row, "job_level")
        seniority = _map_job_level(job_level) or _infer_seniority(title, description or "")

        # Date: handle date, datetime, or NaT
        posted_date: date | None = None
        raw_date = _safe(row, "date_posted")
        if isinstance(raw_date, datetime):
            posted_date = raw_date.date()
        elif isinstance(raw_date, date):
            posted_date = raw_date

        return JobListing(
            id=listing_id,
            source=self.source,
            title=title,
            company=company,
            description=description,
            location=location,
            remote_policy=remote_policy,
            salary_min=salary_min,
            salary_max=salary_max,
            seniority=seniority,
            url=job_url,
            posted_date=posted_date,
            fetched_at=datetime.now(timezone.utc),
            raw_data=_sanitize_raw(row),
        )
