from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from jobscout.adapters.base import JobAdapter, JobScoutAdapterError, filter_by_since
from jobscout.adapters.inference import (
    _infer_remote_policy,
    _infer_seniority,
    _parse_date,
)
from jobscout.config import AppConfig
from jobscout.models import JobListing

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.adzuna.com/v1/api/jobs/de/search/{page}"
_RESULTS_PER_PAGE = 50


# ---------------------------------------------------------------------------
# Pydantic models for raw Adzuna response validation
# ---------------------------------------------------------------------------

class _AdzunaCompany(BaseModel):
    display_name: str = "Unknown"


class _AdzunaLocation(BaseModel):
    display_name: str = ""
    area: list[str] = []


class AdzunaJobRaw(BaseModel):
    id: str
    title: str
    description: str
    redirect_url: str
    created: str
    company: _AdzunaCompany = _AdzunaCompany()
    location: _AdzunaLocation = _AdzunaLocation()
    salary_min: float | None = None
    salary_max: float | None = None
    salary_is_predicted: int = 0
    contract_type: str | None = None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class AdzunaAdapter(JobAdapter):
    """Fetches ML/AI job listings from the Adzuna Germany API."""

    @property
    def source(self) -> str:
        return "adzuna_de"

    async def fetch(self, max_results: int = 100, since: date | None = None) -> list[JobListing]:
        """Fetch and normalise up to ``max_results`` listings from Adzuna Germany.

        Paginates from page 1 until an under-full page is returned or
        ``max_results`` is reached. Skips individual malformed listings with
        a warning rather than aborting the entire batch.

        Args:
            max_results: Upper bound on listings to return.
            since: If provided, only keep listings posted on or after this date.
                Passed to the API as ``max_days_old`` to reduce pages fetched,
                then enforced precisely in a post-filter. Listings with no
                posted_date are always kept.

        Raises:
            JobScoutAdapterError: On rate-limiting (429) or server errors (5xx).
            httpx.HTTPStatusError: On auth failure (401) — not retriable.
        """
        profile = self._config.profile

        base_params: dict[str, Any] = {
            "app_id": self._config.adzuna_app_id,
            "app_key": self._config.adzuna_app_key,
            # what_or: any matching word is sufficient — hard filter handles precision
            "what_or": "machine learning MLOps NLP AI engineer data scientist",
            "category": "it-jobs",
            "results_per_page": _RESULTS_PER_PAGE,
        }

        if since is not None:
            base_params["max_days_old"] = (date.today() - since).days

        collected: list[JobListing] = []
        page = 1

        async with httpx.AsyncClient(timeout=30.0) as client:
            while len(collected) < max_results:
                url = _BASE_URL.format(page=page)
                logger.debug("Fetching Adzuna page %d (collected %d so far)", page, len(collected))

                try:
                    response = await client.get(url, params=base_params)
                except httpx.TimeoutException as exc:
                    raise JobScoutAdapterError(f"Adzuna request timed out on page {page}") from exc
                except httpx.ConnectError as exc:
                    raise JobScoutAdapterError(f"Could not connect to Adzuna on page {page}") from exc

                if response.status_code == 429:
                    raise JobScoutAdapterError("Adzuna rate limit reached (429). Daily quota exhausted.")
                if response.status_code >= 500:
                    raise JobScoutAdapterError(
                        f"Adzuna server error {response.status_code} on page {page}"
                    )
                # 401 auth failure — raise as-is, not retriable
                response.raise_for_status()

                data = response.json()
                raw_listings: list[dict] = data.get("results", [])

                if not raw_listings:
                    logger.debug("Adzuna returned empty results on page %d — stopping", page)
                    break

                for raw in raw_listings:
                    if len(collected) >= max_results:
                        break
                    try:
                        validated = AdzunaJobRaw.model_validate(raw)
                        collected.append(self._normalize(validated, raw))
                    except Exception as exc:
                        listing_id = raw.get("id", "<unknown>")
                        logger.warning("Skipping Adzuna listing %s: %s", listing_id, exc)

                logger.debug("Page %d: got %d results", page, len(raw_listings))

                # Stop if this was the last page
                if len(raw_listings) < _RESULTS_PER_PAGE:
                    break

                page += 1

        if since is not None:
            before = len(collected)
            collected = filter_by_since(collected, since)
            logger.debug("AdzunaAdapter --since filter: %d → %d listings", before, len(collected))

        logger.info("AdzunaAdapter fetched %d listings", len(collected))
        return collected

    def _normalize(self, raw: AdzunaJobRaw, raw_dict: dict) -> JobListing:
        """Translate a validated Adzuna listing into the canonical JobListing."""
        # Discard predicted salaries — they are Adzuna estimates, not disclosed
        salary_min = raw.salary_min if raw.salary_is_predicted == 0 else None
        salary_max = raw.salary_max if raw.salary_is_predicted == 0 else None

        location_str = raw.location.display_name
        # All results from this adapter are Germany jobs (/de/ endpoint).
        # Normalise to always include "Germany" so the location filter works.
        if location_str and "germany" not in location_str.lower() and "deutschland" not in location_str.lower():
            location_str = f"{location_str}, Germany"
        elif not location_str:
            location_str = "Germany"
        location_str = location_str.replace("Deutschland", "Germany").replace("deutschland", "Germany")
        remote_policy = _infer_remote_policy(raw.title, raw.description, location_str)
        seniority = _infer_seniority(raw.title, raw.description)

        return JobListing(
            id=raw.id,
            source=self.source,
            title=raw.title,
            company=raw.company.display_name,
            description=raw.description,
            location=location_str,
            remote_policy=remote_policy,
            salary_min=salary_min,
            salary_max=salary_max,
            seniority=seniority,
            url=raw.redirect_url,
            posted_date=_parse_date(raw.created),
            fetched_at=datetime.now(timezone.utc),
            raw_data=raw_dict,
        )
