from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

from jobscout.config import AppConfig
from jobscout.models import JobListing


def _as_date(value: date) -> date:
    """Narrow a date-or-datetime to a calendar date.

    ``posted_date`` is a full timestamp but ``--since`` is day-granular, and
    Python raises TypeError on a datetime-to-date comparison rather than
    coercing. Both sides are narrowed so the cutoff means "posted on or after
    this day" regardless of which type reaches it.
    """
    return value.date() if isinstance(value, datetime) else value


def filter_by_since(listings: list[JobListing], since: date) -> list[JobListing]:
    """Return listings posted on or after ``since``. Listings with no posted_date are kept."""
    cutoff = _as_date(since)
    return [
        j for j in listings
        if j.posted_date is None or _as_date(j.posted_date) >= cutoff
    ]


class JobScoutAdapterError(Exception):
    """Raised by adapters for recoverable API failures (rate limits, timeouts,
    5xx responses). Unexpected errors (auth failures, bugs) bubble up as-is.
    The pipeline orchestrator catches this type for retry / graceful fallback.
    """


class JobScoutSourceIntegrityError(Exception):
    """Raised when a source is not merely unavailable but *broken* — its payload
    no longer parses, or its yield has collapsed to a level no live market explains.

    **Deliberately not a subclass of `JobScoutAdapterError`, and that is the whole
    mechanism.** `run.py`'s ingest catch is scoped to `JobScoutAdapterError`, so a
    recoverable failure degrades to an empty list with a warning while this
    propagates, exits the run non-zero, and trips the workflow's existing
    `if: failure()` alarm. No orchestration code knows this class exists.

    The distinction it encodes: a timeout or a 429 is a transient bad day and the
    right response is to shrug. A payload whose shape changed is a bug in *us* that
    will otherwise present as a quiet job market — indistinguishable, on a
    single-source roster, from there being nothing to send.
    """


class JobAdapter(ABC):
    """Abstract base class for all job source adapters.

    Each concrete adapter handles one data source (e.g. freelancermap, Upwork),
    translates its API response into the common ``JobListing`` schema, and
    returns a flat list to the pipeline. The pipeline never imports a concrete
    adapter directly — it works through this interface.

    Subclassing convention
    ----------------------
    Implement ``source`` (a fixed string identifier, e.g. ``"freelancermap"``)
    and ``fetch()``. Implement a private ``_normalize(raw: dict) -> JobListing``
    method to keep normalization logic separate from HTTP logic — this makes
    normalization independently testable without making network calls.

    ``_normalize`` owns the remote signal: set ``remote_percentage`` when the
    source publishes a number, and fall back to ``remote_policy_text`` only when
    it does not. ``JobListing.remote_policy`` is derived from the two and is not
    a constructor argument.

    Example skeleton::

        class FreelancermapAdapter(JobAdapter):
            @property
            def source(self) -> str:
                return "freelancermap"

            async def fetch(self, max_results: int = 100, since: date | None = None) -> list[JobListing]:
                results = []
                async with httpx.AsyncClient() as client:
                    # request, accumulate, and stop at max_results ...
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
        Must be unique across all registered adapters (e.g. ``"freelancermap"``).
        """

    @abstractmethod
    async def fetch(self, max_results: int = 100, since: date | None = None) -> list[JobListing]:
        """Fetch and normalise job listings from this source.

        How a source is covered is the adapter's own business — pages, repeated
        queries, or one request. freelancermap, for instance, cannot paginate at
        all and reaches the market by issuing one request per configured query.

        Args:
            max_results: Upper bound on the number of listings to return.
                Adapters should stop requesting once this limit is reached.
                Default (100) is appropriate for production daily runs.
                Pass a smaller value during development or ``--dry-run`` mode
                to keep a run cheap.
            since: If provided, only return listings posted on or after this
                date. Listings with no posted_date are always kept.

        Returns:
            A flat list of normalised ``JobListing`` objects. May be empty if
            the source returns no results for the current profile / market.

        Raises:
            JobScoutAdapterError: For recoverable API failures such as rate
                limiting, transient 5xx responses, or network timeouts.
            JobScoutSourceIntegrityError: For a source that is broken rather than
                unavailable. Not caught by the orchestrator — see that class.
        """
