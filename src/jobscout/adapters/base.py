from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from jobscout.config import AppConfig
from jobscout.models import JobListing


def filter_by_since(listings: list[JobListing], since: date) -> list[JobListing]:
    """Return listings posted on or after ``since``. Listings with no posted_date are kept."""
    return [j for j in listings if j.posted_date is None or j.posted_date >= since]


class JobScoutAdapterError(Exception):
    """Raised by adapters for recoverable API failures (rate limits, timeouts,
    5xx responses). Unexpected errors (auth failures, bugs) bubble up as-is.
    The pipeline orchestrator catches this type for retry / graceful fallback.
    """


class JobAdapter(ABC):
    """Abstract base class for all job source adapters.

    Each concrete adapter handles one data source (e.g. Adzuna, JSearch),
    translates its API response into the common ``JobListing`` schema, and
    returns a flat list to the pipeline. The pipeline never imports a concrete
    adapter directly — it works through this interface.

    Subclassing convention
    ----------------------
    Implement ``source`` (a fixed string identifier, e.g. ``"adzuna_de"``) and
    ``fetch()``. Implement a private ``_normalize(raw: dict) -> JobListing``
    method to keep normalization logic separate from HTTP logic — this makes
    normalization independently testable without making network calls.

    Example skeleton::

        class AdzunaAdapter(JobAdapter):
            @property
            def source(self) -> str:
                return "adzuna_de"

            async def fetch(self, max_results: int = 100, since: date | None = None) -> list[JobListing]:
                results = []
                async with httpx.AsyncClient() as client:
                    # paginate until max_results reached ...
                    pass
                return results

            def _normalize(self, raw: dict) -> JobListing:
                ...
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    @abstractmethod
    def source(self) -> str:
        """A stable string identifier for this data source.

        Used as the ``source`` field on every ``JobListing`` produced by this
        adapter and as part of the deduplication key in the seen-jobs cache.
        Must be unique across all registered adapters (e.g. ``"adzuna_de"``).
        """

    @abstractmethod
    async def fetch(self, max_results: int = 100, since: date | None = None) -> list[JobListing]:
        """Fetch, paginate, and normalise job listings from this source.

        Args:
            max_results: Upper bound on the number of listings to return.
                Adapters should stop paginating once this limit is reached.
                Default (100) is appropriate for production daily runs.
                Pass a smaller value during development or ``--dry-run`` mode
                to avoid exhausting free-tier API quotas.
            since: If provided, only return listings posted on or after this
                date. Listings with no posted_date are always kept.

        Returns:
            A flat list of normalised ``JobListing`` objects. May be empty if
            the source returns no results for the current profile / market.

        Raises:
            JobScoutAdapterError: For recoverable API failures such as rate
                limiting, transient 5xx responses, or network timeouts.
        """
