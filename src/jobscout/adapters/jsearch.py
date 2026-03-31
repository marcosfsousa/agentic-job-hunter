from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Literal
from urllib.parse import urlencode, urlparse

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

# Job boards known to block direct links (Cloudflare / login walls).
# For these, _resolve_url constructs a Google search URL instead so the
# link in the digest is always clickable.
_BLOCKED_DOMAINS = {"stepstone.de", "xing.com", "monster.de"}


def _resolve_url(apply_link: str, title: str, company: str) -> str:
    """Return apply_link, or a Google fallback if the domain blocks scrapers."""
    if not apply_link:
        return apply_link
    host = urlparse(apply_link).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    if host in _BLOCKED_DOMAINS:
        return "https://www.google.com/search?" + urlencode({"q": f"{title} {company} site:{host}"})
    return apply_link


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
        """Fetch and normalise listings from JSearch across all configured queries.

        Runs each query in ``profile.jsearch_queries`` sequentially. ``max_results``
        is the per-query cap; overlap across queries is handled by downstream dedup.

        Args:
            max_results: Upper bound on listings to fetch per query.
            since: If provided, maps to the nearest date_posted bucket
                (today/3days/week/month) to tighten each API query, then
                enforces the exact cutoff in a post-filter. Listings with
                no posted_date are always kept.

        Raises:
            JobScoutAdapterError: On rate-limiting (429) or server errors (5xx).
            httpx.HTTPStatusError: On auth failure (401) — not retriable.
        """
        if not self._config.open_web_ninja_api_key:
            logger.info("JSearchAdapter: no API key configured — skipping")
            return []

        queries = self._config.profile.jsearch_queries
        all_collected: list[JobListing] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for query in queries:
                batch = await self._fetch_query(query, max_results, since, client)
                all_collected.extend(batch)

        logger.info(
            "JSearchAdapter fetched %d listings across %d queries",
            len(all_collected),
            len(queries),
        )
        return all_collected

    async def _fetch_query(
        self,
        query: str,
        max_results: int,
        since: date | None,
        client: httpx.AsyncClient,
    ) -> list[JobListing]:
        """Fetch listings for a single JSearch query string."""
        num_pages = min(max(1, (max_results + _RESULTS_PER_PAGE - 1) // _RESULTS_PER_PAGE), _MAX_PAGES)

        params = {
            "query": query,
            "country": "de",
            "date_posted": _since_to_date_posted(since) if since is not None else "week",
            "employment_types": "FULLTIME",
            "page": 1,
            "num_pages": num_pages,
        }
        headers = {"x-api-key": self._config.open_web_ninja_api_key}

        logger.debug("Fetching JSearch query=%r (num_pages=%d, max=%d)", query, num_pages, max_results)
        try:
            response = await client.get(_BASE_URL, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise JobScoutAdapterError(f"JSearch request timed out (query={query!r})") from exc
        except httpx.ConnectError as exc:
            raise JobScoutAdapterError(f"Could not connect to JSearch API (query={query!r})") from exc

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
            logger.debug(
                "JSearchAdapter --since filter (query=%r): %d → %d listings",
                query, before, len(collected),
            )

        logger.debug("JSearch query=%r returned %d listings", query, len(collected))
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
            url=_resolve_url(raw.job_apply_link, raw.job_title, raw.employer_name),
            posted_date=_parse_date(raw.job_posted_at_datetime_utc),
            fetched_at=datetime.now(timezone.utc),
            raw_data=raw_dict,
        )
