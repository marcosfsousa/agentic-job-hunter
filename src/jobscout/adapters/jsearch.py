from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Literal

import httpx
from pydantic import BaseModel

from jobscout.adapters.base import JobAdapter, JobScoutAdapterError, filter_by_since
from jobscout.adapters.inference import (
    _infer_remote_policy,
    _infer_seniority,
    _parse_date,
)
from jobscout.models import JobListing

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.openwebninja.com/jsearch/search"


_DatePostedBucket = Literal["today", "3days", "week", "month"]


def _since_to_date_posted(since: date) -> _DatePostedBucket:
    """Map a since date to the nearest JSearch date_posted enum value.

    JSearch only accepts fixed buckets: today, 3days, week, month.
    We pick the tightest bucket that still covers the requested date.
    """
    days = (date.today() - since).days
    if days <= 0:
        return "today"
    if days <= 3:
        return "3days"
    if days <= 7:
        return "week"
    return "month"


def _highlights_to_text(highlights: dict | None) -> str:
    """Flatten JSearch job_highlights dict into plain text.

    job_highlights looks like:
        {"Qualifications": ["5+ years...", "Python"], "Responsibilities": [...]}
    Returns each section joined with semicolons, sections separated by newlines.
    """
    if not highlights:
        return ""
    parts = []
    for section, items in highlights.items():
        if isinstance(items, list) and items:
            parts.append(f"{section}: " + "; ".join(str(i) for i in items))
    return "\n".join(parts)
_RESULTS_PER_PAGE = 10
_MAX_PAGES = 20  # JSearch API hard limit; also caps free-tier quota usage


# ---------------------------------------------------------------------------
# Pydantic model for raw JSearch response validation
# ---------------------------------------------------------------------------

class _JSearchJobRaw(BaseModel):
    job_id: str
    job_title: str
    employer_name: str = "Unknown"
    job_description: str | None = None
    job_highlights: dict | None = None
    job_apply_link: str = ""
    job_is_remote: bool = False
    job_posted_at_datetime_utc: str | None = None
    job_city: str | None = None
    job_country: str | None = None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class JSearchAdapter(JobAdapter):
    """Fetches ML/AI job listings from JSearch via the OpenWebNinja API."""

    @property
    def source(self) -> str:
        return "jsearch"

    async def fetch(self, max_results: int = 100, since: date | None = None) -> list[JobListing]:
        """Fetch and normalise up to ``max_results`` listings from JSearch.

        Uses ``num_pages`` to retrieve multiple pages in a single API call,
        minimising quota usage on free-tier plans.

        Args:
            max_results: Upper bound on listings to return.
            since: If provided, maps to the nearest date_posted bucket
                (today/3days/week/month) to tighten the API query, then
                enforces the exact cutoff in a post-filter. Listings with
                no posted_date are always kept.

        Raises:
            JobScoutAdapterError: On rate-limiting (429) or server errors (5xx).
            httpx.HTTPStatusError: On auth failure (401) — not retriable.
        """
        if not self._config.open_web_ninja_api_key:
            logger.info("JSearchAdapter: no API key configured — skipping")
            return []

        num_pages = min(max(1, (max_results + _RESULTS_PER_PAGE - 1) // _RESULTS_PER_PAGE), _MAX_PAGES)

        params = {
            "query": "machine learning engineer in Germany",
            "country": "de",
            "date_posted": _since_to_date_posted(since) if since is not None else "week",
            "employment_types": "FULLTIME",
            "page": 1,
            "num_pages": num_pages,
        }
        headers = {"x-api-key": self._config.open_web_ninja_api_key}

        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.debug("Fetching JSearch (num_pages=%d, max=%d)", num_pages, max_results)
            try:
                response = await client.get(_BASE_URL, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                raise JobScoutAdapterError("JSearch request timed out") from exc
            except httpx.ConnectError as exc:
                raise JobScoutAdapterError("Could not connect to JSearch API") from exc

            if response.status_code == 429:
                raise JobScoutAdapterError("JSearch rate limit reached (429). Quota exhausted.")
            if response.status_code >= 500:
                raise JobScoutAdapterError(f"JSearch server error {response.status_code}")
            response.raise_for_status()

        raw_listings: list[dict] = response.json().get("data", [])
        collected: list[JobListing] = []

        for raw in raw_listings[:max_results]:
            try:
                validated = _JSearchJobRaw.model_validate(raw)
                collected.append(self._normalize(validated, raw))
            except Exception as exc:
                listing_id = raw.get("job_id", "<unknown>")
                logger.warning("Skipping JSearch listing %s: %s", listing_id, exc)

        if since is not None:
            before = len(collected)
            collected = filter_by_since(collected, since)
            logger.debug("JSearchAdapter --since filter: %d → %d listings", before, len(collected))

        logger.info("JSearchAdapter fetched %d listings", len(collected))
        return collected

    def _normalize(self, raw: _JSearchJobRaw, raw_dict: dict) -> JobListing:
        """Translate a validated JSearch listing into the canonical JobListing."""
        location = raw.job_city or "Germany"
        if "germany" not in location.lower() and "deutschland" not in location.lower():
            location = f"{location}, Germany"

        description = raw.job_description or _highlights_to_text(raw.job_highlights) or ""
        if not raw.job_description and raw.job_highlights:
            logger.debug("JSearch listing %s: used job_highlights fallback", raw.job_id)
        remote_policy = "remote" if raw.job_is_remote else _infer_remote_policy(
            raw.job_title, description, location
        )

        return JobListing(
            id=raw.job_id,
            source=self.source,
            title=raw.job_title,
            company=raw.employer_name,
            description=description,
            location=location,
            remote_policy=remote_policy,
            salary_min=None,
            salary_max=None,
            seniority=_infer_seniority(raw.job_title, description),
            url=raw.job_apply_link,
            posted_date=_parse_date(raw.job_posted_at_datetime_utc),
            fetched_at=datetime.now(timezone.utc),
            raw_data=raw_dict,
        )
