"""freelancermap adapter — the pipeline's only source.

Ingest route
------------
freelancermap publishes no API. Its project search page embeds a `react-on-rails`
component named ``ProjectSearch`` whose props are a fully typed JSON payload, so
this adapter parses one JSON blob per request rather than scraping rendered markup.
The payload carries the full ``description``, which is why no per-project hydration
request is needed.

Coverage comes from queries, not pages
--------------------------------------
The anonymous view returns 22 results per query and **nothing reaches result 23**.
Four bare page parameters and the site's own canonical paginator URL — replayed
verbatim, all ~30 params — were each measured inert, with ``currentPage`` stuck at
1 and three "pages" yielding one 22-id set. **The pagination question is closed; do
not reopen it.** If coverage proves insufficient the answer is more entries in
``profile.freelancermap_queries``, which is why that list is the adapter's sole
coverage mechanism rather than a targeting convenience.

Binding constraints (issue #11)
-------------------------------
Ingesting this source at all was accepted conditionally, and these three mitigations
*are* the risk acceptance rather than good intentions around it:

1. **Never authenticate.** The account and the adapter stay strictly separate.
2. **Honest User-Agent.** Identify JobScout; do not impersonate a browser, so the
   source's block button keeps working.
3. **Hard request cap in code**, not by convention.

`tests/test_freelancermap.py::TestBindingConstraints` asserts all three against the
outgoing requests. Their failure mode is legal rather than functional, so nothing
else in the system would notice their absence — that is why they are tested.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, get_args

import httpx

from jobscout.adapters.base import (
    JobAdapter,
    JobScoutAdapterError,
    JobScoutSourceIntegrityError,
    filter_by_since,
)
from jobscout.config import AppConfig
from jobscout.models import ContractType, JobListing

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.freelancermap.de"
_SEARCH_PATH = "/projekte"

# Use .de, not .com — the same query returns 116 results against 22.
# `/projektboerse.html` is the wrong endpoint: it accepts `query` and silently
# ignores it, returning the whole board for any term including nonsense.
_SEARCH_URL = f"{_BASE_URL}{_SEARCH_PATH}"

# Honest identification, per constraint 2. Deliberately not a browser string.
_USER_AGENT = (
    "JobScout/0.1 (personal job-matching tool; "
    "+https://github.com/marcosfsousa/agentic-job-hunter)"
)

# Germany, in freelancermap's own country vocabulary. Pushed server-side so the
# request returns less rather than being filtered down locally — the no-overload
# duty in §4(1)(a) is served by asking for less, not by discarding more.
_COUNTRY_GERMANY = "1"

_REQUEST_TIMEOUT = 30.0

# The payload is the props of the `ProjectSearch` component. Matched on the
# component name rather than on position or class, because the page carries
# several react-on-rails components and their order is not ours to rely on.
_PAYLOAD_PATTERN = re.compile(
    r'<script[^>]*\bdata-component-name="ProjectSearch"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# `beginningText` values that mean "now". "nach Vereinbarung" is deliberately
# absent — it means the start is negotiable, which is not the same as immediate.
_IMMEDIATE_START_TERMS = frozenset({"sofort", "ab sofort", "asap", "immediately"})

# German day-first, then ISO. `start_text` keeps the raw value either way, so a
# format this misses costs precision and never information.
_EXACT_DAY_FORMATS = ("%d.%m.%Y", "%Y-%m-%d")

_KNOWN_CONTRACT_TYPES: frozenset[str] = frozenset(get_args(ContractType))


class FreelancermapAdapter(JobAdapter):
    """Ingest DACH contract projects from freelancermap's embedded search payload."""

    def __init__(
        self,
        config: AppConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """
        Args:
            config: The loaded `AppConfig`. Unlike the FTE adapters this one reads
                it in `fetch()` — the query list, the request cap and the raw floor
                all live there.
            transport: Test seam. Injected into the `httpx.AsyncClient` so the
                request loop can be exercised offline. Production passes nothing.

                This exists because the coverage logic *is* the request loop: it
                issues N queries, unions, dedupes, enforces a cap and raises below
                a floor. Two of the three binding constraints above are only
                observable on an outgoing request, so a seam that cannot see the
                request cannot assert them.
        """
        super().__init__(config)
        self._transport = transport

    @property
    def source(self) -> str:
        return "freelancermap"

    # -----------------------------------------------------------------
    # Fetch
    # -----------------------------------------------------------------

    async def fetch(
        self,
        max_results: int = 100,
        since: date | None = None,
    ) -> list[JobListing]:
        """Fetch one page per configured query, union the results, and normalise.

        Raises:
            JobScoutAdapterError: Transient network trouble — a timeout, a 429, a
                5xx. Recoverable, so the orchestrator degrades to an empty list.
            JobScoutSourceIntegrityError: The payload no longer parses, or the
                distinct-id yield collapsed. Not recoverable, and not caught
                anywhere — the run fails.
        """
        queries = self._budgeted_queries()

        # Keyed by project id so overlapping queries — which is the normal case,
        # since "LLM" and "Generative AI" describe much the same market — produce
        # one listing rather than several. This is exact-id dedup and runs before
        # the pipeline's fuzzy title|company fingerprint dedup, which does
        # different work.
        raw_by_id: dict[str, dict[str, Any]] = {}

        async with httpx.AsyncClient(
            transport=self._transport,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as client:
            for query in queries:
                for raw in await self._fetch_query(client, query):
                    project_id = _project_id(raw)
                    if project_id is not None:
                        raw_by_id.setdefault(project_id, raw)

        # The floor is on DISTINCT ids and is measured here — after the union, and
        # deliberately before the `since` filter. Both halves matter:
        #
        #   * Distinct, not summed. If query differentiation broke and every request
        #     came back with the same page, a summed count would sit healthily at
        #     n_queries × 22 while the real yield was 22. That collapse presents
        #     exactly as a quiet market, so the summed count would miss the one
        #     failure this alarm exists for.
        #   * Before `since`, so a genuinely quiet week cannot trip an alarm about a
        #     broken source. A healthy raw count that the hard filter then rejects
        #     down to nothing stays silent for the same reason.
        logger.info(
            "freelancermap raw yield: %d distinct project(s) across %d quer%s",
            len(raw_by_id), len(queries), "y" if len(queries) == 1 else "ies",
        )
        floor = self._config.freelancermap_min_raw_ingest
        if len(raw_by_id) < floor:
            raise JobScoutSourceIntegrityError(
                f"freelancermap returned {len(raw_by_id)} distinct project(s) across "
                f"{len(queries)} quer{'y' if len(queries) == 1 else 'ies'}, below the "
                f"floor of {floor}. This is a broken source, not a quiet market — the "
                "anonymous view returns up to 22 rows per query, so a healthy union "
                "sits far above this. Check whether the search response shape or the "
                "query parameter changed."
            )

        listings = [self._normalize(raw) for raw in raw_by_id.values()]
        if since is not None:
            listings = filter_by_since(listings, since)
        return listings[:max_results]

    def _budgeted_queries(self) -> list[str]:
        """The configured queries, truncated to the request cap.

        One request per query, so the cap on requests is a cap on queries. Dropping
        any is logged by name — a silent truncation would read downstream as full
        coverage of a smaller market.
        """
        queries = list(self._config.profile.freelancermap_queries)
        cap = self._config.freelancermap_max_requests
        if len(queries) <= cap:
            return queries

        dropped = queries[cap:]
        logger.warning(
            "freelancermap request cap (%d) is below the %d configured queries — "
            "dropping %s. Coverage is reduced: raise freelancermap_max_requests or "
            "shorten freelancermap_queries.",
            cap, len(queries), ", ".join(repr(q) for q in dropped),
        )
        return queries[:cap]

    async def _fetch_query(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> list[dict[str, Any]]:
        """One request; the search payload's results, unnormalised."""
        params = {"query": query, "countries[0]": _COUNTRY_GERMANY}
        try:
            response = await client.get(_SEARCH_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Transient by assumption. A shape change surfaces below as an
            # integrity error instead, which is the failure we refuse to swallow.
            raise JobScoutAdapterError(
                f"freelancermap request failed for query {query!r}: {exc}"
            ) from exc

        results = _extract_results(response.text)
        logger.debug("freelancermap query %r returned %d result(s)", query, len(results))
        return results

    # -----------------------------------------------------------------
    # Normalisation
    # -----------------------------------------------------------------

    def _normalize(self, raw: dict[str, Any]) -> JobListing:
        """Map one raw search result onto the contract `JobListing`."""
        contract_block = raw.get("projectContractType") or {}
        start_date, start_is_immediate, start_text = _parse_start(raw)

        return JobListing(
            id=_project_id(raw) or "",
            source=self.source,
            title=raw.get("title") or "",
            # The poster, which on an intermediated listing is the agency. The
            # end-client is not stored even when `endcustomer` names one.
            company=raw.get("company") or "",
            description=raw.get("description") or "",
            location=_location(raw),
            url=_absolute_url(raw.get("url")),
            posted_date=_parse_created(raw.get("created")),
            fetched_at=datetime.now(timezone.utc),
            raw_data=raw,

            # The authoritative remote signal, published as a number on every row.
            # The `None` branch is defensive, not expected: `remoteInPercent` was
            # measured 22/22 on the page and 115/115 against the pool aggregation.
            remote_percentage=_coerce_int(contract_block.get("remoteInPercent")),
            # freelancermap publishes no free-text remote policy, so the derived
            # `remote_policy` always resolves off the percentage above.
            remote_policy_text="not_specified",

            # Rate is left empty unconditionally — see `_normalize`'s note below.
            # `budget` is NEVER parsed, even when populated.
            rate_min=None,
            rate_max=None,
            rate_unit=None,
            rate_currency=None,

            contract_type=_contract_type(contract_block.get("type")),
            client_type="direct" if raw.get("endcustomer") is True else "unknown",

            duration_months=_coerce_int(raw.get("duration")),
            # Never positively observed on this source, so asserting it would be
            # inventing signal. `duration_months=None` with this False reads
            # honestly as "length unknown" rather than as "open-ended".
            duration_is_open_ended=False,
            duration_text=raw.get("durationText") or None,

            start_date=start_date,
            start_is_immediate=start_is_immediate,
            start_text=start_text,
        )


# ---------------------------------------------------------------------------
# Payload extraction
# ---------------------------------------------------------------------------

def _extract_results(page_html: str) -> list[dict[str, Any]]:
    """Pull `initialResults` out of the embedded `ProjectSearch` payload.

    Every failure here raises rather than degrading to an empty list. That inverts
    the FTE adapters' habit deliberately: with one source, an empty list is
    delivered to the user as "no matches today" and the pipeline exits 0.
    """
    match = _PAYLOAD_PATTERN.search(page_html)
    if match is None:
        raise JobScoutSourceIntegrityError(
            "No ProjectSearch payload found in the freelancermap response. The page "
            "structure changed, or the response was not the search page at all "
            "(a consent wall or a block page would also land here)."
        )

    payload = _parse_payload(match.group(1))
    results = payload.get("initialResults")
    if not isinstance(results, list):
        raise JobScoutSourceIntegrityError(
            "The ProjectSearch payload has no `initialResults` list "
            f"(got {type(results).__name__}). The payload shape changed."
        )
    return [r for r in results if isinstance(r, dict)]


def _parse_payload(script_body: str) -> dict[str, Any]:
    """Parse the script tag's contents, tolerating HTML-escaped JSON.

    react-on-rails may emit the props HTML-escaped so a `</script>` inside a string
    cannot close the tag early. Plain JSON is tried first: unescaping unconditionally
    would rewrite a literal `&amp;` sitting inside a project description.
    """
    try:
        payload = json.loads(script_body)
    except json.JSONDecodeError:
        try:
            payload = json.loads(html.unescape(script_body))
        except json.JSONDecodeError as exc:
            raise JobScoutSourceIntegrityError(
                f"The ProjectSearch payload is not valid JSON: {exc}"
            ) from exc

    if not isinstance(payload, dict):
        raise JobScoutSourceIntegrityError(
            f"The ProjectSearch payload is a {type(payload).__name__}, expected an object."
        )
    return payload


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _project_id(raw: dict[str, Any]) -> str | None:
    """The project id as a string, or None if the row carries none.

    A row without an id cannot be deduped or marked seen, so it is dropped rather
    than admitted under a synthetic key that would re-deliver it every day.
    """
    value = raw.get("id")
    return str(value) if value is not None else None


def _absolute_url(url: str | None) -> str:
    if not url:
        return _BASE_URL
    return url if url.startswith("http") else f"{_BASE_URL}{url}"


def _location(raw: dict[str, Any]) -> str:
    """City and country, as a display string.

    The country is included because it is what `target_countries` matches against
    on rows the remote gate does not decide.
    """
    parts = [str(raw[key]) for key in ("city", "country") if raw.get(key)]
    return ", ".join(parts)


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _contract_type(value: Any) -> ContractType:
    """The engagement form, 1:1 where recognised.

    An unrecognised value becomes `unknown` rather than an error: freelancermap can
    add to its vocabulary at any time, and the hard filter's blocklist passes
    `unknown`, so a new value costs precision on one row instead of dropping it.
    """
    return value if value in _KNOWN_CONTRACT_TYPES else "unknown"


def _parse_created(value: Any) -> datetime | None:
    """`created` as a timezone-aware datetime; the offset is kept, not normalised."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.debug("freelancermap: unparseable `created` value %r", value)
        return None


def _parse_start(raw: dict[str, Any]) -> tuple[date | None, bool, str | None]:
    """Resolve the three start cases in precedence order.

    Returns `(start_date, start_is_immediate, start_text)`.

    Precedence is immediate → exact day → month-granular. The month-granular case
    **never** populates `start_date`: "Ab September 2026" does not tell us a day,
    and synthesising the 1st would present an invented date as a known one.
    `start_text` carries the raw value in every case, so a parse that misses
    degrades precision rather than losing information.
    """
    beginning_text = raw.get("beginningText") or None
    start_text = beginning_text or _synthesised_start_text(raw)

    if beginning_text and beginning_text.strip().lower() in _IMMEDIATE_START_TERMS:
        return None, True, start_text

    if beginning_text:
        for fmt in _EXACT_DAY_FORMATS:
            try:
                return datetime.strptime(beginning_text.strip(), fmt).date(), False, start_text
            except ValueError:
                continue

    return None, False, start_text


def _synthesised_start_text(raw: dict[str, Any]) -> str | None:
    """A month-granular `start_text` for rows where `beginningText` is blank.

    Keeps the month/year signal reachable by the LLM evaluator without letting it
    reach `start_date`, which would need a day the source never gave us.
    """
    month = _coerce_int(raw.get("beginningMonth"))
    year = _coerce_int(raw.get("beginningYear"))
    if year is None:
        return None
    return f"{month:02d}/{year}" if month is not None else str(year)
