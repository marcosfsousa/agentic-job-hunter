from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from jobscout.adapters.base import JobAdapter, JobScoutAdapterError
from jobscout.config import AppConfig
from jobscout.models import JobListing, RemotePolicy, Seniority

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
# Inference helpers — module-level so they are independently testable
# ---------------------------------------------------------------------------

def _infer_remote_policy(title: str, description: str, location: str) -> RemotePolicy:
    """Infer remote work policy from title, description, and location text."""
    combined = f"{title} {description} {location}".lower()

    hybrid_keywords = ["hybrid", "teilweise remote", "partly remote", "partial remote"]
    remote_keywords = ["remote", "homeoffice", "home office", "work from home", "wfh", "fully remote"]
    onsite_keywords = ["on-site", "onsite", "vor ort", "office only", "in-office"]

    # Check hybrid first — it often contains "remote" too, so order matters
    if any(kw in combined for kw in hybrid_keywords):
        return "hybrid"
    if any(kw in combined for kw in remote_keywords):
        return "remote"
    if any(kw in combined for kw in onsite_keywords):
        return "onsite"
    return "not_specified"


def _infer_seniority(title: str, description: str) -> Seniority | None:
    """Infer seniority level from title and description text."""
    combined = f"{title} {description}".lower()

    lead_keywords = ["lead", "principal", "director", "head of", "staff engineer", "chapter lead"]
    senior_keywords = ["senior", "sr ", "sr.", " sr "]
    mid_keywords = ["mid-level", "mid level", "intermediate", "medior"]
    junior_keywords = ["junior", "jr ", "jr.", "graduate", "entry-level", "entry level", "trainee", "werkstudent"]

    if any(kw in combined for kw in lead_keywords):
        return "lead"
    if any(kw in combined for kw in senior_keywords):
        return "senior"
    if any(kw in combined for kw in mid_keywords):
        return "mid"
    if any(kw in combined for kw in junior_keywords):
        return "junior"
    return None


def _parse_date(created: str) -> date | None:
    """Parse Adzuna ISO 8601 timestamp to a date. Returns None on failure."""
    try:
        return datetime.fromisoformat(created.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class AdzunaAdapter(JobAdapter):
    """Fetches ML/AI job listings from the Adzuna Germany API."""

    @property
    def source(self) -> str:
        return "adzuna_de"

    async def fetch(self, max_results: int = 100) -> list[JobListing]:
        """Fetch and normalise up to ``max_results`` listings from Adzuna Germany.

        Paginates from page 1 until an under-full page is returned or
        ``max_results`` is reached. Skips individual malformed listings with
        a warning rather than aborting the entire batch.

        Raises:
            JobScoutAdapterError: On rate-limiting (429) or server errors (5xx).
            httpx.HTTPStatusError: On auth failure (401) — not retriable.
        """
        profile = self._config.profile
        what = " ".join(profile.target_roles)

        base_params: dict[str, Any] = {
            "app_id": self._config.adzuna_app_id,
            "app_key": self._config.adzuna_app_key,
            "what": what,
            "category": "it-jobs",
            "results_per_page": _RESULTS_PER_PAGE,
        }

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

        logger.info("AdzunaAdapter fetched %d listings", len(collected))
        return collected

    def _normalize(self, raw: AdzunaJobRaw, raw_dict: dict) -> JobListing:
        """Translate a validated Adzuna listing into the canonical JobListing."""
        # Discard predicted salaries — they are Adzuna estimates, not disclosed
        salary_min = raw.salary_min if raw.salary_is_predicted == 0 else None
        salary_max = raw.salary_max if raw.salary_is_predicted == 0 else None

        location_str = raw.location.display_name
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
