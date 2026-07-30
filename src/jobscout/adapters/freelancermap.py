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
from html.parser import HTMLParser
from typing import Annotated, Any, cast, get_args

import httpx
from pydantic import BaseModel, BeforeValidator, ValidationError

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

# Germany's id in freelancermap's own `countries` filter vocabulary — an opaque
# vendor id, not a name, which is why it is not derived from
# `profile.location.target_countries`: that list holds display names ("Germany",
# "Deutschland") the source's filter would not accept, and the mapping between the
# two is the adapter's business rather than the user's. Pushed server-side so the
# request returns less rather than being filtered down locally — the no-overload
# duty in §4(1)(a) is served by asking for less, not by discarding more.
_COUNTRY_GERMANY = "1"

_REQUEST_TIMEOUT = 30.0

# Statuses worth shrugging at: a rate limit or a server-side wobble is a transient
# bad day. Everything else non-200 — a 403 block page, a 404 moved endpoint, a 3xx
# to somewhere else — means the route we were given no longer works, which is a
# broken source and must not degrade to an empty digest.
_RECOVERABLE_STATUSES = frozenset({408, 429})

# The anonymous view returns at most this many rows per query (see the module
# docstring and `config.freelancermap_min_raw_ingest`, whose `gt=22` rests on the
# same fact). Named here because the floor's diagnostics reason arithmetically about
# it: a below-floor union that the answering queries alone should have cleared points
# at a dropped-rows shape change, not at whichever queries merely rate-limited.
_ROWS_PER_QUERY = 22

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


# ---------------------------------------------------------------------------
# Raw payload models
# ---------------------------------------------------------------------------
#
# Validation of the source's own shape, per the repo's "Pydantic for external API
# validation" convention. These are not the pipeline's model — `JobListing` is —
# they exist so the mapping below reads typed attributes instead of untyped
# `dict.get` chains, and so a shape change is caught at one named place.
#
# Permissive on purpose, in two different directions, and the distinction matters:
#
#   * Unknown keys are ignored. The payload carries ~35 fields and freelancermap
#     may add more; that is not our business and must not fail a run. (Contrast
#     `profile.yaml`, where an unknown key IS an error — that file is ours.)
#   * Every field is optional and un-coercible values degrade to None rather than
#     failing the row, because these are optional metadata on a listing whose
#     title and description we can still use. What is left able to fail is a
#     structural break — a result that is not an object at all — which is exactly
#     the case that should stop the run.

def _nullable_int(value: Any) -> Any:
    """Coerce to int, or to None. Never raises.

    `bool` is excluded deliberately: it is an `int` subclass in Python, so without
    this a `True` would silently arrive as a duration of 1.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _nullable_str(value: Any) -> Any:
    """Stringify a scalar, or None. A numeric id or title should not fail a row.

    Scalars only. A list or an object reaching a text field is a shape change, and
    rendering its `repr` into `title` or `description` would put Python syntax in
    front of the user and into the embedding.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _as_mapping(value: Any) -> Any:
    """Nested blocks arrive absent, null, or as an object. Normalise the first two."""
    return value if isinstance(value, dict) else {}


_NullableInt = Annotated[int | None, BeforeValidator(_nullable_int)]
_NullableStr = Annotated[str | None, BeforeValidator(_nullable_str)]


class _RawContractBlock(BaseModel):
    """`projectContractType` — the engagement form and the remote percentage."""

    type: _NullableStr = None
    remoteInPercent: _NullableInt = None


class _RawCountry(BaseModel):
    """`country` is an object, not a string: `{"id": 1, "name": "Deutschland",
    "iso2": "DE", "nameDe": ..., "nameEn": ...}`. `name` is the German form, which
    is what `target_countries` already lists alongside "Germany"."""

    name: _NullableStr = None


class _RawLinks(BaseModel):
    """`links.project` is the real project path.

    The top-level `url` field exists but is null on every row measured, so the
    canonical link lives here instead. Reading `url` and stopping is how every
    listing ended up pointing at the homepage.
    """

    project: _NullableStr = None


class _RawProject(BaseModel):
    """One entry of the search payload's `initialResults`."""

    id: _NullableStr = None
    slug: _NullableStr = None
    title: _NullableStr = None
    company: _NullableStr = None
    description: _NullableStr = None
    city: _NullableStr = None
    created: _NullableStr = None

    country: Annotated[_RawCountry, BeforeValidator(_as_mapping)] = _RawCountry()
    links: Annotated[_RawLinks, BeforeValidator(_as_mapping)] = _RawLinks()

    # Null on every row measured. Kept because it is the field the payload
    # advertises for this, and reading it costs nothing if it ever starts working.
    url: _NullableStr = None

    projectContractType: Annotated[_RawContractBlock, BeforeValidator(_as_mapping)] = (
        _RawContractBlock()
    )

    # A tri-state on purpose: None means the source did not say, which is not the
    # same as False. Only an explicit True yields `client_type="direct"`.
    endcustomer: bool | None = None

    duration: _NullableInt = None
    durationText: _NullableStr = None

    beginningText: _NullableStr = None
    beginningMonth: _NullableInt = None
    beginningYear: _NullableInt = None


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

        Transient per-query trouble — a timeout, a 429, a 5xx — is caught *here*,
        logged, and degrades that one query rather than the whole fetch. Earlier
        queries' rows stay in the union, and the distinct-id floor below is the
        single arbiter of run health: a partial union that still clears the floor
        is a fine day, and one that does not fails loud via
        `JobScoutSourceIntegrityError`. This is what stops a persistently
        rate-limiting or flapping source from presenting as a quiet market — the
        floor's own failure mode, otherwise reachable through the recoverable path
        (issue #43). The failed query still consumed its one request, so the cap
        semantics are unchanged.

        Raises:
            JobScoutSourceIntegrityError: The route or the payload no longer works
                — a block page, a moved endpoint, an unparseable payload, or a
                distinct-id yield below the floor (whether the source changed shape
                or every query degraded transiently). Not caught anywhere; the run
                fails rather than delivering a silent empty digest.
        """
        queries = self._budgeted_queries()

        # Keyed by project id so overlapping queries — which is the normal case,
        # since "LLM" and "Generative AI" describe much the same market — produce
        # one listing rather than several. This is exact-id dedup and runs before
        # the pipeline's fuzzy title|company fingerprint dedup, which does
        # different work.
        raw_by_id: dict[str, dict[str, Any]] = {}

        # Queries that degraded on a transient failure this run. Kept so the floor's
        # raise below can say *why* the union is thin — a rate-limited source and a
        # changed payload both land there, and ops needs to tell them apart.
        degraded: list[str] = []

        async with httpx.AsyncClient(
            transport=self._transport,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
            # Both of these keep a binding constraint honest rather than merely
            # tidy, so neither is a default worth "simplifying" back.
            #
            # No redirect following: the cap counts queries, and only "one query =
            # exactly one outgoing request" makes that a cap on requests. A
            # redirect chain would multiply real requests behind a cap that still
            # reads as satisfied. A 3xx is therefore an error (the route moved),
            # not something to chase.
            follow_redirects=False,
        ) as client:
            for index, query in enumerate(queries):
                try:
                    results = await self._fetch_query(client, query)
                except JobScoutAdapterError as exc:
                    # A transient per-query failure (a 429, a 5xx, a timeout)
                    # degrades this one query, not the whole fetch. Propagating
                    # here — the old behaviour — discarded rows already unioned
                    # from earlier queries AND skipped the floor check below, so a
                    # mid-union 429 exited 0 with a silent empty digest (issue #43).
                    # A `JobScoutSourceIntegrityError` (a block page, a moved
                    # endpoint) is deliberately NOT caught: it must still fail loud.
                    degraded.append(query)
                    logger.warning(
                        "freelancermap query %r degraded transiently - continuing "
                        "with the remaining queries; the distinct-id floor decides "
                        "run health: %s",
                        query, exc,
                    )
                    if exc.status == 429:
                        # A 429 is the source *explicitly* asking us to slow down —
                        # unlike a 5xx or a timeout, which say nothing about our
                        # request rate. Firing the remaining queries anyway would
                        # hammer a server that just throttled us, and freelancermap
                        # access rests on staying a well-behaved anonymous client
                        # (issue #11: a no-overload duty, and account termination as
                        # the realistic downside). So stop issuing requests. The
                        # skipped queries are marked degraded too, so the floor below
                        # still arbitrates run health from the full picture — the
                        # fail-loud guarantee is unchanged, we simply gather less.
                        remaining = queries[index + 1:]
                        if remaining:
                            degraded.extend(remaining)
                            logger.warning(
                                "freelancermap: 429 - not issuing the remaining %s "
                                "(%s); backing off rather than hammering a source that "
                                "asked us to slow down.",
                                _queries(len(remaining)),
                                ", ".join(repr(q) for q in remaining),
                            )
                        break
                    continue
                finally:
                    # Never carry state between requests, on every path including
                    # a failed one. `AsyncClient` persists `Set-Cookie` across a
                    # session by default, which would let the source start a
                    # session we then present on every later request — the opposite
                    # of "the adapter never authenticates". Anonymity has to mean
                    # each request stands alone.
                    client.cookies.clear()

                for raw in results:
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
        # Degraded queries contributed nothing to the union, so the denominator an
        # operator greps first must be the number that actually *answered*, not the
        # number configured. "3 distinct across 5 of 8 queries" is honest where
        # "across 8 queries" reads as a near-total collapse of a healthy run.
        answered = len(queries) - len(degraded)
        degraded_list = ", ".join(repr(q) for q in degraded)
        if degraded:
            yield_summary = (
                f"{len(raw_by_id)} distinct project(s) across "
                f"{answered} of {_queries(len(queries))}"
            )
            logger.warning(
                "freelancermap: %s degraded transiently this run (%s); the "
                "distinct-id floor decides run health from the %d that answered.",
                _queries(len(degraded)), degraded_list, answered,
            )
        else:
            yield_summary = f"{len(raw_by_id)} distinct project(s) across {_queries(len(queries))}"
        logger.info("freelancermap raw yield: %s", yield_summary)

        floor = self._config.freelancermap_min_raw_ingest
        if len(raw_by_id) < floor:
            # Why the union is thin decides what an operator should check. A changed
            # payload is a bug in us; a run where transient failures starved the
            # union is a bad-source day. Both must fail loud — the point of the fix
            # for #43 is that neither exits 0 with an empty digest — but the message
            # must not misdirect, and it can misdirect in *either* direction: naming
            # only a shape change when the source merely rate-limited, or — the
            # subtler trap — naming only rate-limiting when a shape change silently
            # dropped the answered rows. The arbiter is arithmetic: the queries that
            # answered return up to `_ROWS_PER_QUERY` rows each, so if they alone
            # should have cleared the floor, degradations cannot explain the
            # shortfall and the shape-check hint has to stay.
            shape_hint = (
                "Check whether the search response shape or the query parameter changed."
            )
            if not degraded:
                cause = (
                    "This is a broken source, not a quiet market - the anonymous view "
                    f"returns up to {_ROWS_PER_QUERY} rows per query, so a healthy union "
                    f"sits far above this. {shape_hint}"
                )
            elif answered * _ROWS_PER_QUERY >= floor:
                # The answering queries alone should have cleared the floor, so the
                # transient degradations are not the whole story — something dropped
                # their rows too, and that is a shape/parameter change. Naming only
                # the degradation here is the misdirection this branch exists to avoid.
                cause = (
                    f"{_queries(len(degraded))} degraded transiently this run "
                    f"({degraded_list}), but the {answered} that answered should have "
                    f"cleared the floor on their own (up to {_ROWS_PER_QUERY} rows "
                    f"each) - so a rate-limited source does not explain this. {shape_hint}"
                )
            else:
                # Few enough queries answered that the degradations alone account for
                # the thin union — a bad-source day, not a shape change. Don't send
                # ops hunting a change that need not have happened.
                cause = (
                    f"{_queries(len(degraded))} degraded transiently this run "
                    f"({degraded_list}), so a rate-limited or flapping source - not "
                    "necessarily a changed payload - may be the cause. Either way the "
                    "run fails rather than delivering a silent empty digest."
                )
            raise JobScoutSourceIntegrityError(
                f"freelancermap returned {yield_summary}, below the floor of {floor}. "
                f"{cause}"
            )

        listings = [self._normalize(raw) for raw in raw_by_id.values()]
        if since is not None:
            listings = filter_by_since(listings, since)

        if len(listings) > max_results:
            # Never silently, for the same reason the request cap logs: the rows
            # dropped here are whichever queries ran last, so a truncating run makes
            # *adding* a query cost coverage instead of adding it — the exact
            # opposite of what the query list is for. Five seeded queries can union
            # past `run.py`'s default of 100.
            logger.warning(
                "freelancermap: %d listings truncated to max_results=%d - the %d dropped "
                "row(s) are from the queries that ran last. Raise max_results rather than "
                "shortening freelancermap_queries.",
                len(listings), max_results, len(listings) - max_results,
            )
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
            "freelancermap request cap (%d) is below the %d configured queries - "
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
        """Exactly one request; the search payload's results, unnormalised."""
        params = {"query": query, "countries[0]": _COUNTRY_GERMANY}
        try:
            response = await client.get(_SEARCH_URL, params=params)
        except httpx.HTTPError as exc:
            # A timeout or a connection failure — the network, not the source.
            raise JobScoutAdapterError(
                f"freelancermap request failed for query {query!r}: {exc}"
            ) from exc

        # Which exception a bad status becomes is the whole point, so it is decided
        # here rather than by `raise_for_status`, whose one error type would put a
        # 403 block page and a 503 wobble in the same bucket — and the recoverable
        # bucket is the one that degrades to an empty digest.
        if response.status_code in _RECOVERABLE_STATUSES or response.status_code >= 500:
            raise JobScoutAdapterError(
                f"freelancermap returned {response.status_code} for query {query!r} "
                "- treating as transient.",
                status=response.status_code,
            )
        if response.status_code != 200:
            raise JobScoutSourceIntegrityError(
                f"freelancermap returned {response.status_code} for query {query!r}. "
                "A block, a moved endpoint or an unexpected redirect - the ingest "
                "route no longer works, which is not something to deliver as an "
                "empty digest."
            )

        results = _extract_results(response.text)
        logger.debug("freelancermap query %r returned %d result(s)", query, len(results))
        return results

    # -----------------------------------------------------------------
    # Normalisation
    # -----------------------------------------------------------------

    def _normalize(self, raw: dict[str, Any]) -> JobListing:
        """Map one raw search result onto the contract `JobListing`.

        Takes the untyped dict rather than the validated model because `raw_data`
        must keep the payload exactly as it arrived — a mapping question should be
        answerable later without a new request — and because this is the seam
        `base.py` documents for every adapter.
        """
        try:
            project = _RawProject.model_validate(raw)
        except ValidationError as exc:
            raise JobScoutSourceIntegrityError(
                f"A freelancermap result did not validate: {exc}. Optional fields "
                "degrade to None rather than failing, so reaching here means the "
                "result's structure changed, not merely its contents."
            ) from exc

        start_date, start_is_immediate, start_text = _parse_start(project)

        return JobListing(
            id=project.id or "",
            source=self.source,
            title=project.title or "",
            # The poster, which on an intermediated listing is the agency. The
            # end-client is not stored even when `endcustomer` says there is one.
            company=project.company or "",
            # Flattened from the source's editor HTML. `raw_data` keeps the marked-up
            # original, so nothing is lost.
            description=_plain_text(project.description),
            location=_location(project),
            url=_project_url(project),
            posted_date=_parse_created(project.created),
            fetched_at=datetime.now(timezone.utc),
            # The payload verbatim, including the fields nothing maps — notably
            # freelancermap's own 1024-dim `embedding`, which is incompatible with
            # our 384-dim asymmetric model and must reach no model field.
            raw_data=raw,

            # The authoritative remote signal, published as a number on every row.
            # The `None` branch is defensive, not expected: `remoteInPercent` was
            # measured 22/22 on the page and 115/115 against the pool aggregation.
            remote_percentage=project.projectContractType.remoteInPercent,
            # freelancermap publishes no free-text remote policy, so the derived
            # `remote_policy` always resolves off the percentage above.
            remote_policy_text="not_specified",

            # Never populated, and `budget` is never parsed even when it carries a
            # value. Its unit is not determinable from the payload, and a rate whose
            # scale is guessed is worse than no rate: it would compare silently
            # against an hourly or daily floor that means something else.
            rate_min=None,
            rate_max=None,
            rate_unit=None,
            rate_currency=None,

            contract_type=_contract_type(project.projectContractType.type),
            client_type="direct" if project.endcustomer is True else "unknown",

            duration_months=project.duration,
            # Never positively observed on this source, so asserting it would be
            # inventing signal. `duration_months=None` with this False reads
            # honestly as "length unknown" rather than as "open-ended".
            duration_is_open_ended=False,
            duration_text=project.durationText or None,

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

class _DescriptionTextExtractor(HTMLParser):
    """Flattens a description's markup to readable text.

    freelancermap's `description` is not prose — it is editor HTML: `<br />` on
    19/22 rows, `<div class="ql-editor">` and `<span style="color: rgb(0,0,0)">`
    wrappers on most, `<ul>/<li>` requirement lists on 13/22.

    That markup reaches three places and is wrong in all of them: the digest shows
    it to a human, the LLM evaluator reads it as part of the listing, and the
    embedding tokenises it inside a 512-token window the descriptions already
    overflow — so `<span style="color: rgb(0, 0, 0);">` would displace requirements
    text that would otherwise have fit.

    Stdlib rather than a parser dependency, per the repo's stdlib-first convention.
    Tag-shaped text inside a listing is a non-issue: `HTMLParser` drops it, which is
    the same thing a browser does with the page these came from.
    """

    # Tags that end a line of text. Without this the flattened output runs list
    # items and paragraphs together into one unreadable sentence.
    _BREAKING = frozenset({
        "br", "p", "div", "li", "ul", "ol", "tr", "table", "blockquote",
        "h1", "h2", "h3", "h4", "h5", "h6",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._BREAKING:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BREAKING:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    @property
    def text(self) -> str:
        return "".join(self._parts)


def _plain_text(value: str | None) -> str:
    """Markup-free description text, with blank-line runs collapsed."""
    if not value:
        return ""
    parser = _DescriptionTextExtractor()
    parser.feed(value)
    parser.close()

    lines = [line.strip() for line in parser.text.splitlines()]
    return "\n".join(line for i, line in enumerate(lines) if line or (i and lines[i - 1])).strip()


def _queries(count: int) -> str:
    """"3 queries" / "1 query" — pluralised once, used in the log and the raise."""
    return f"{count} quer{'y' if count == 1 else 'ies'}"


def _project_id(raw: dict[str, Any]) -> str | None:
    """The project id as a string, or None if the row carries none.

    A row without an id cannot be deduped or marked seen, so it is dropped rather
    than admitted under a synthetic key that would re-deliver it every day.

    Reads the untyped dict rather than `_RawProject` because it runs during the
    union, before normalisation — the id is what the union is keyed on.

    Coerces through `_nullable_str` so this agrees with `_RawProject.id`, which the
    same row reaches moments later. A bare `str()` here would disagree: a structured
    id would key the union as `"[1, 2]"` while normalisation rejected it and produced
    `JobListing.id == ""` — a listing that can be neither deduped nor marked seen,
    which is precisely what dropping the row is supposed to prevent.
    """
    return _nullable_str(raw.get("id")) or None


def _project_url(project: _RawProject) -> str:
    """The canonical project link.

    Three sources in descending order of directness. The top-level `url` field is
    tried first because it is the one the payload advertises for this — but it was
    null on every row measured, so `links.project` is what actually carries the
    path, and `slug` reconstructs it if that ever moves too. Falling back to the
    homepage means a digest entry nobody can open, which is why there are three.
    """
    for path in (project.url, project.links.project):
        if path:
            return path if path.startswith("http") else f"{_BASE_URL}{path}"
    if project.slug:
        return f"{_BASE_URL}/projekt/{project.slug}"
    return _BASE_URL


def _location(project: _RawProject) -> str:
    """City and country, as a display string.

    The country is included because it is what `target_countries` matches against
    on rows the remote gate does not decide — and `city` alone is not enough for
    that, since it holds free text the poster typed. It is often a real city, but
    "D" turns up too, meaning Deutschland.

    That last case is also why the city is dropped when it merely restates the
    country: "D, Deutschland" is noise, and `location` is read by a human in the
    digest as well as by the gate.
    """
    city, country = project.city, project.country.name
    if not country:
        return city or ""
    if not city or city.strip().lower() in {country.lower(), country[:1].lower()}:
        return country
    return f"{city}, {country}"


def _contract_type(value: str | None) -> ContractType:
    """The engagement form, 1:1 where recognised.

    An unrecognised value becomes `unknown` rather than an error: freelancermap can
    add to its vocabulary at any time, and the hard filter's blocklist passes
    `unknown`, so a new value costs precision on one row instead of dropping it.
    """
    if value in _KNOWN_CONTRACT_TYPES:
        # The membership test is the check; `cast` only tells the type checker so,
        # since it cannot narrow a `str` through a runtime set. Deriving the set
        # from `ContractType` keeps this in step with the model automatically,
        # which restating the literals here would not.
        return cast(ContractType, value)
    return "unknown"


def _parse_created(value: str | None) -> datetime | None:
    """`created` as a timezone-aware datetime; the offset is kept, not normalised."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.debug("freelancermap: unparseable `created` value %r", value)
        return None


def _parse_start(project: _RawProject) -> tuple[date | None, bool, str | None]:
    """Resolve the three start cases in precedence order.

    Returns `(start_date, start_is_immediate, start_text)`.

    Precedence is immediate → exact day → month-granular. The month-granular case
    **never** populates `start_date`: "Ab September 2026" does not tell us a day,
    and synthesising the 1st would present an invented date as a known one.
    `start_text` carries the raw value in every case, so a parse that misses
    degrades precision rather than losing information.
    """
    beginning_text = project.beginningText or None
    start_text = beginning_text or _synthesised_start_text(project)

    if beginning_text and beginning_text.strip().lower() in _IMMEDIATE_START_TERMS:
        return None, True, start_text

    if beginning_text:
        for fmt in _EXACT_DAY_FORMATS:
            try:
                return datetime.strptime(beginning_text.strip(), fmt).date(), False, start_text
            except ValueError:
                continue

    return None, False, start_text


def _synthesised_start_text(project: _RawProject) -> str | None:
    """A month-granular `start_text` for rows where `beginningText` is blank.

    Keeps the month/year signal reachable by the LLM evaluator without letting it
    reach `start_date`, which would need a day the source never gave us.
    """
    month, year = project.beginningMonth, project.beginningYear
    if year is None:
        return None
    return f"{month:02d}/{year}" if month is not None else str(year)
