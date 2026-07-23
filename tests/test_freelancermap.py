"""Tests for the freelancermap adapter.

Two things are under test here and they need different seams. The field mapping is
exercised through `_normalize`, following the convention the deleted FTE adapter
tests established. The request loop is exercised through `fetch()` with an injected
`httpx.MockTransport` — a first adapter-level departure, because the pagination
refutation moved the coverage logic *into* the loop: it issues N queries, unions,
dedupes, enforces a cap and raises below a floor, and none of that is reachable from
`_normalize`.

`TestBindingConstraints` guards a legal commitment rather than behaviour. Nothing
else in the system would ever notice if the User-Agent or the request cap
disappeared, which is exactly why those assertions exist — same reasoning as
`test_repo_invariants.py`. Do not "simplify" them away.

Everything runs offline. The corollary is that a real payload shape change is
invisible to this suite; catching that is the job of the integrity raise and the raw
floor at runtime.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from jobscout.adapters.base import JobScoutAdapterError, JobScoutSourceIntegrityError
from jobscout.adapters.freelancermap import FreelancermapAdapter, _extract_results
from jobscout.filters.hard_filter import apply_hard_filter
from jobscout.models import (
    DealbreakersConfig,
    LocationConfig,
    RateConfig,
    SkillsConfig,
    UserProfile,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_HTML = (FIXTURES_DIR / "freelancermap_search.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_config(
    queries: list[str] | None = None,
    max_requests: int = 10,
    min_raw_ingest: int = 30,
    profile: UserProfile | None = None,
) -> SimpleNamespace:
    """A stand-in for `AppConfig`.

    `config=None` will not do for this adapter — unlike the FTE ones it reads the
    query list, the request cap and the raw floor at fetch time.
    """
    if profile is None:
        # A real `UserProfile`, not a namespace: it is cheap to build and a renamed
        # field should fail here rather than pass against a stand-in.
        profile = _real_profile(queries=queries or ["Machine Learning"])
    return SimpleNamespace(
        profile=profile,
        freelancermap_max_requests=max_requests,
        freelancermap_min_raw_ingest=min_raw_ingest,
    )


def _raw_results() -> list[dict[str, Any]]:
    """The fixture's three raw results, via the adapter's own extraction step.

    Extraction is used rather than re-implemented here so every mapping test also
    exercises the script-tag wrapper, which is why the fixture keeps it.
    `TestPayloadExtraction` is what stops this from being circular.
    """
    return _extract_results(FIXTURE_HTML)


def _raw_by_id(project_id: str) -> dict[str, Any]:
    """Select a fixture row by id.

    Deliberately not positional. The deleted suite indexed `raw_listings[2]` for its
    predicted-salary case and needed a comment to explain why, which stops being true
    the moment anyone reorders the fixture.
    """
    for raw in _raw_results():
        if str(raw["id"]) == project_id:
            return raw
    raise AssertionError(f"fixture has no project {project_id}")


def _page(projects: list[dict[str, Any]]) -> str:
    """Wrap raw results in a minimal ProjectSearch page."""
    payload = json.dumps({"initialResults": projects, "initialPagination": {"currentPage": 1}})
    return (
        '<html><body><script type="application/json" '
        f'data-component-name="ProjectSearch">{payload}</script></body></html>'
    )


def _project(project_id: int, **overrides: Any) -> dict[str, Any]:
    """A minimal well-formed raw result, for building synthetic pages."""
    base = {
        "id": project_id,
        "title": f"Machine Learning Engineer {project_id}",
        "company": "Nexon IT Consulting GmbH",
        "description": "Aufbau von RAG-Pipelines und LLM-Anwendungen. Remote.",
        "city": "Berlin",
        "country": {"id": 1, "name": "Deutschland", "iso2": "DE"},
        "slug": f"ml-{project_id}",
        "url": None,
        "links": {"project": f"/projekt/ml-{project_id}"},
        "created": "2026-07-16T15:38:04+02:00",
        "projectContractType": {"type": "contracting", "remoteInPercent": 100},
        "endcustomer": False,
        "budget": None,
    }
    base.update(overrides)
    return base


def _adapter(
    handler,
    queries: list[str] | None = None,
    max_requests: int = 10,
    min_raw_ingest: int = 30,
    profile: UserProfile | None = None,
) -> FreelancermapAdapter:
    config = _make_config(queries, max_requests, min_raw_ingest, profile)
    return FreelancermapAdapter(config, transport=httpx.MockTransport(handler))


def _serving(pages_by_query: dict[str, str], recorder: list | None = None):
    """A transport handler serving a page per `query=` value."""
    def handler(request: httpx.Request) -> httpx.Response:
        if recorder is not None:
            recorder.append(request)
        query = request.url.params.get("query", "")
        return httpx.Response(200, text=pages_by_query.get(query, _page([])))
    return handler


# ---------------------------------------------------------------------------
# Payload extraction
# ---------------------------------------------------------------------------

class TestPayloadExtraction:
    """The step a JSON fixture would skip: finding the right blob on a real page."""

    def test_the_fixture_page_yields_its_four_projects(self):
        assert [str(r["id"]) for r in _extract_results(FIXTURE_HTML)] == [
            "3026737", "3026337", "3026469", "3026169",
        ]

    def test_another_react_component_on_the_page_is_not_mistaken_for_it(self):
        """The page carries several react-on-rails components and their order is not
        ours to rely on, so the payload is selected by component name. The fixture's
        `HeaderSearch` decoy carries its own `initialResults` to make that bite."""
        assert "HeaderSearch" in FIXTURE_HTML
        for raw in _extract_results(FIXTURE_HTML):
            assert raw["id"] != "decoy"

    def test_the_component_name_must_sit_inside_a_script_tag(self):
        """Matching the bare attribute anywhere on the page is not enough — the
        fixture's own HTML comment mentions it, and an unanchored pattern swallows
        the document from there to the first `</script>`."""
        page = (
            '<!-- see data-component-name="ProjectSearch" for the payload -->'
            '<script data-component-name="ProjectSearch">'
            '{"initialResults": [{"id": 7}]}</script>'
        )
        assert [r["id"] for r in _extract_results(page)] == [7]

    def test_html_escaped_json_is_still_parsed(self):
        """react-on-rails may escape the props so a `</script>` inside a string
        cannot close the tag early."""
        page = (
            '<script data-component-name="ProjectSearch">'
            '{&quot;initialResults&quot;: [{&quot;id&quot;: 7}]}</script>'
        )
        assert [r["id"] for r in _extract_results(page)] == [7]

    def test_a_literal_ampersand_in_a_description_is_not_rewritten(self):
        """Which is why plain JSON is tried before unescaping."""
        page = _page([_project(1, description="Research &amp; Development")])
        assert _extract_results(page)[0]["description"] == "Research &amp; Development"


# ---------------------------------------------------------------------------
# Field mapping — through _normalize, against the captured payload
# ---------------------------------------------------------------------------

class TestFieldMapping:
    def setup_method(self):
        self.adapter = FreelancermapAdapter(_make_config())

    def test_identity_fields_map_directly(self):
        listing = self.adapter._normalize(_raw_by_id("3026337"))
        assert listing.id == "3026337"
        assert listing.source == "freelancermap"
        assert listing.title == "Machine Learning Engineer (m/w/d)"
        assert listing.company == "Randstad Professional GmbH (vorm. GULP)"
        assert "RAG pipelines" in listing.description

    def test_posted_date_is_timezone_aware(self):
        """Incremental sync compares this against a previous run, so a naive
        timestamp would raise rather than compare. The source's own +02:00 offset is
        kept rather than normalised to UTC."""
        listing = self.adapter._normalize(_raw_by_id("3026337"))
        assert listing.posted_date == datetime(
            2026, 7, 22, 9, 23, 10, tzinfo=timezone(timedelta(hours=2))
        )

    def test_an_unparseable_created_value_yields_none_rather_than_raising(self):
        listing = self.adapter._normalize(_project(1, created="last Tuesday"))
        assert listing.posted_date is None

    def test_remote_percentage_comes_from_remote_in_percent(self):
        assert self.adapter._normalize(_raw_by_id("3026337")).remote_percentage == 100
        assert self.adapter._normalize(_raw_by_id("3026469")).remote_percentage == 60
        # Zero is a real value, not a missing one — the distinction the falsy
        # `or None` idiom would destroy.
        assert self.adapter._normalize(_raw_by_id("3026737")).remote_percentage == 0

    def test_remote_policy_text_is_constant_not_specified(self):
        """freelancermap publishes no free-text policy, so the derived
        `remote_policy` must always resolve off the percentage."""
        listing = self.adapter._normalize(_raw_by_id("3026469"))
        assert listing.remote_policy_text == "not_specified"
        assert listing.remote_policy == "hybrid"   # derived from 60, not from text

    def test_contract_type_maps_one_to_one(self):
        assert self.adapter._normalize(_raw_by_id("3026337")).contract_type == "contracting"
        assert self.adapter._normalize(_raw_by_id("3026469")).contract_type == "employee_leasing"

    def test_unrecognised_contract_type_becomes_unknown_not_an_error(self):
        """A new vocabulary value must cost precision on one row, not drop it."""
        listing = self.adapter._normalize(_raw_by_id("3026169"))
        assert listing.contract_type == "unknown"

    def test_duration_is_months(self):
        listing = self.adapter._normalize(_raw_by_id("3026337"))
        assert listing.duration_months == 6
        assert listing.duration_is_open_ended is False

    def test_missing_duration_reads_as_unknown_not_open_ended(self):
        listing = self.adapter._normalize(_raw_by_id("3026469"))
        assert listing.duration_months is None
        assert listing.duration_is_open_ended is False

    def test_duration_text_is_kept_even_when_there_is_no_integer(self):
        """"Auf Anfrage" is the whole of what the source said about length."""
        listing = self.adapter._normalize(_raw_by_id("3026737"))
        assert listing.duration_months is None
        assert listing.duration_text == "Auf Anfrage"

    def test_ambiguous_duration_text_survives_the_month_parse(self):
        """"3 MM" is plausibly Mannmonate, not three calendar months. The integer is
        taken at face value per the mapping, so `duration_text` is what makes the
        misread recoverable."""
        listing = self.adapter._normalize(_raw_by_id("3026169"))
        assert listing.duration_months == 3
        assert listing.duration_text == "3 MM"

    def test_freelancermap_embedding_is_not_mistaken_for_ours(self):
        """The source ships a 1024-dim vector; ours is 384-dim and asymmetric.
        It must reach no model field — only `raw_data`."""
        listing = self.adapter._normalize(_raw_by_id("3026737"))
        assert listing.raw_data["embedding"] == [0.014, -0.221, 0.098]

    def test_raw_payload_is_retained(self):
        listing = self.adapter._normalize(_raw_by_id("3026737"))
        assert listing.raw_data["pid"] == "P-3026737"


class TestProjectUrl:
    """The top-level `url` field is null on every row measured. Reading it and
    stopping is how every digest entry ends up pointing at the homepage."""

    def setup_method(self):
        self.adapter = FreelancermapAdapter(_make_config())

    def test_the_link_comes_from_links_project_when_url_is_null(self):
        listing = self.adapter._normalize(_raw_by_id("3026337"))
        assert listing.raw_data["url"] is None
        assert listing.url == (
            "https://www.freelancermap.de/projekt/machine-learning-engineer-m-w-d-3026337"
        )

    def test_no_listing_falls_back_to_the_bare_homepage(self):
        for raw in _raw_results():
            listing = self.adapter._normalize(raw)
            assert listing.url != "https://www.freelancermap.de"
            assert "/projekt/" in listing.url

    def test_the_slug_reconstructs_the_path_when_links_is_missing(self):
        listing = self.adapter._normalize(
            _project(1, url=None, links=None, slug="ml-engineer-1")
        )
        assert listing.url == "https://www.freelancermap.de/projekt/ml-engineer-1"

    def test_a_populated_url_field_still_wins(self):
        listing = self.adapter._normalize(_project(1, url="/projekt/from-url-field"))
        assert listing.url == "https://www.freelancermap.de/projekt/from-url-field"


class TestLocation:
    """`country` is an object, not a string, and `city` is free text the poster
    typed — both discovered against the live payload, not the written research."""

    def setup_method(self):
        self.adapter = FreelancermapAdapter(_make_config())

    def test_city_and_country_name_are_joined(self):
        listing = self.adapter._normalize(_raw_by_id("3026469"))
        assert listing.location == "Hamburg, Deutschland"

    def test_the_country_object_is_not_stringified_into_the_location(self):
        listing = self.adapter._normalize(_raw_by_id("3026469"))
        assert "iso2" not in listing.location

    def test_a_city_that_merely_restates_the_country_is_dropped(self):
        """"D" is a real value in this field and means Deutschland, so "D, Deutschland"
        would be noise in a string a human reads in the digest."""
        listing = self.adapter._normalize(_raw_by_id("3026737"))
        assert listing.location == "Deutschland"

    def test_the_country_is_present_for_the_gate_to_match_on(self):
        """`target_countries` is dormant while every row publishes a remote
        percentage, but it is not dead — it decides for a future text-only source,
        and it can only decide if the country reached `location` at all."""
        for raw in _raw_results():
            assert "Deutschland" in self.adapter._normalize(raw).location


class TestDescriptionIsFlattened:
    """The description is editor HTML, not the plain prose the written research
    described — <br /> on 19/22 live rows, ql-editor wrappers on 18/22, <ul> lists
    on 13/22. Left as-is it reaches the digest a human reads, the LLM evaluator,
    and an embedding window the descriptions already overflow.
    """

    def setup_method(self):
        self.adapter = FreelancermapAdapter(_make_config())

    def test_no_listing_carries_markup_through(self):
        for raw in _raw_results():
            description = self.adapter._normalize(raw).description
            for marker in ("<div", "<br", "<span", "<ul", "<li", "ql-editor", "rgb("):
                assert marker not in description, (raw["id"], marker)

    def test_the_text_itself_survives(self):
        listing = self.adapter._normalize(_raw_by_id("3026169"))
        assert "Prognosemodellen" in listing.description
        assert "scikit-learn" in listing.description

    def test_list_items_do_not_run_together(self):
        """Without break handling, "<li>Python</li><li>SQL</li>" flattens to
        "PythonSQL" — one token that matches neither."""
        listing = self.adapter._normalize(_raw_by_id("3026169"))
        assert "SQLErfahrung" not in listing.description
        assert "Gute Kenntnisse in Python & SQL" in listing.description

    def test_entities_are_decoded(self):
        listing = self.adapter._normalize(_raw_by_id("3026169"))
        assert "&amp;" not in listing.description
        assert " & " in listing.description

    def test_plain_text_passes_through_unharmed(self):
        listing = self.adapter._normalize(_raw_by_id("3026469"))
        assert listing.description.startswith("Wir bauen eine interne NLP-Plattform")

    def test_the_marked_up_original_is_still_in_raw_data(self):
        listing = self.adapter._normalize(_raw_by_id("3026169"))
        assert "ql-editor" in listing.raw_data["description"]

    def test_an_absent_description_becomes_empty_string(self):
        assert self.adapter._normalize(_project(1, description=None)).description == ""


class TestRateIsNeverParsed:
    """`budget` is unit-ambiguous, so parsing it risks the silent cross-scale
    comparison the four-field rate shape exists to prevent. No live row has ever
    carried one — project 2891236 exists so the rule is pinned anyway."""

    def setup_method(self):
        self.adapter = FreelancermapAdapter(_make_config())

    def test_populated_budget_still_yields_no_rate(self):
        raw = _raw_by_id("3026169")
        assert raw["budget"], "fixture must carry a populated budget for this to mean anything"

        listing = self.adapter._normalize(raw)
        assert listing.rate_min is None
        assert listing.rate_max is None
        assert listing.rate_unit is None
        assert listing.rate_currency is None

    def test_absent_budget_yields_no_rate(self):
        listing = self.adapter._normalize(_raw_by_id("3026737"))
        assert (listing.rate_min, listing.rate_max) == (None, None)


class TestStartPrecedence:
    """immediate → exact day → month-granular, in that order."""

    def setup_method(self):
        self.adapter = FreelancermapAdapter(_make_config())

    def test_immediate_start_sets_the_flag_and_no_date(self):
        listing = self.adapter._normalize(_raw_by_id("3026337"))
        assert listing.start_is_immediate is True
        assert listing.start_date is None
        assert listing.start_text == "ab sofort"

    def test_exact_day_is_parsed(self):
        listing = self.adapter._normalize(_raw_by_id("3026469"))
        assert listing.start_date == date(2026, 9, 1)
        assert listing.start_is_immediate is False
        assert listing.start_text == "01.09.2026"

    def test_month_granular_start_never_fakes_a_day(self):
        """"Ab September 2026" gives a month, not a day. Synthesising the 1st would
        present an invented date as a known one."""
        listing = self.adapter._normalize(_raw_by_id("3026169"))
        assert listing.start_date is None
        assert listing.start_is_immediate is False
        assert listing.start_text == "Ab September 2026"

    def test_string_month_and_year_are_synthesised_when_there_is_no_text(self):
        """`beginningMonth` / `beginningYear` arrive as strings ("01", "2024"), which
        is why they are coerced rather than trusted as integers."""
        raw = _raw_by_id("3026737")
        assert raw["beginningText"] is None
        assert raw["beginningMonth"] == "01"

        listing = self.adapter._normalize(raw)
        assert listing.start_text == "01/2024"
        assert listing.start_date is None

    def test_nach_vereinbarung_is_not_immediate(self):
        listing = self.adapter._normalize(_project(1, beginningText="nach Vereinbarung"))
        assert listing.start_is_immediate is False
        assert listing.start_date is None
        assert listing.start_text == "nach Vereinbarung"

    def test_immediate_wins_over_a_parseable_date_in_the_same_field(self):
        listing = self.adapter._normalize(_project(1, beginningText="ASAP"))
        assert listing.start_is_immediate is True

    def test_blank_beginning_text_falls_back_to_month_and_year(self):
        listing = self.adapter._normalize(
            _project(1, beginningText=None, beginningMonth=9, beginningYear=2026)
        )
        assert listing.start_text == "09/2026"
        assert listing.start_date is None

    def test_unparseable_start_text_is_preserved_rather_than_lost(self):
        listing = self.adapter._normalize(_project(1, beginningText="KW 38"))
        assert listing.start_text == "KW 38"
        assert listing.start_date is None


class TestClientTypeFromTheBoolean:
    """`endcustomer` is a boolean present on every row, not a nullable name.

    This pins an inversion of the original mapping, which read "present → agency /
    absent → unknown" — inapplicable to a field that is always present. The badge on
    the project page and the `endcustomer=0` search filter both say the flag marks a
    project posted by the end client itself, so True means `direct`.
    """

    def setup_method(self):
        self.adapter = FreelancermapAdapter(_make_config())

    def test_true_means_direct(self):
        listing = self.adapter._normalize(_raw_by_id("3026469"))
        assert listing.raw_data["endcustomer"] is True
        assert listing.client_type == "direct"

    def test_false_means_unknown(self):
        listing = self.adapter._normalize(_raw_by_id("3026737"))
        assert listing.client_type == "unknown"

    def test_agency_is_never_produced(self):
        """freelancermap cannot tell us the poster *is* an intermediary — only that
        it is not the end client, which is a weaker claim."""
        for raw in _raw_results():
            assert self.adapter._normalize(raw).client_type != "agency"


# ---------------------------------------------------------------------------
# Coverage — through fetch(), with an injected transport
# ---------------------------------------------------------------------------

class TestMultiQueryCoverage:
    """The anonymous view caps at 22 rows per query and nothing reaches result 23,
    so queries are the only coverage lever. These assertions are what prove coverage
    does not depend on pagination."""

    async def test_one_request_per_configured_query(self):
        requests: list[httpx.Request] = []
        adapter = _adapter(
            _serving({"LLM": _page([_project(1)]), "KI": _page([_project(2)])}, requests),
            queries=["LLM", "KI"],
            min_raw_ingest=1,
        )
        await adapter.fetch()

        assert len(requests) == 2
        assert [r.url.params["query"] for r in requests] == ["LLM", "KI"]

    async def test_results_are_unioned_across_queries(self):
        adapter = _adapter(
            _serving({
                "LLM": _page([_project(1), _project(2)]),
                "KI": _page([_project(3)]),
            }),
            queries=["LLM", "KI"],
            min_raw_ingest=1,
        )
        listings = await adapter.fetch()
        assert {j.id for j in listings} == {"1", "2", "3"}

    async def test_a_project_in_two_responses_yields_one_listing(self):
        adapter = _adapter(
            _serving({
                "LLM": _page([_project(1), _project(2)]),
                "Generative AI": _page([_project(2), _project(3)]),
            }),
            queries=["LLM", "Generative AI"],
            min_raw_ingest=1,
        )
        listings = await adapter.fetch()
        assert len(listings) == 3
        assert sorted(j.id for j in listings) == ["1", "2", "3"]

    async def test_germany_is_pushed_server_side(self):
        requests: list[httpx.Request] = []
        adapter = _adapter(
            _serving({"LLM": _page([_project(1)])}, requests),
            queries=["LLM"],
            min_raw_ingest=1,
        )
        await adapter.fetch()
        assert requests[0].url.params["countries[0]"] == "1"

    async def test_max_results_bounds_the_union(self):
        adapter = _adapter(
            _serving({"LLM": _page([_project(i) for i in range(10)])}),
            queries=["LLM"],
            min_raw_ingest=1,
        )
        assert len(await adapter.fetch(max_results=4)) == 4

    async def test_truncating_to_max_results_is_never_silent(self, caplog):
        """The dropped rows are whichever queries ran last, so a quiet truncation
        makes *adding* a query cost coverage rather than add it — the opposite of
        what the query list is for. Same no-silent-caps rule as the request cap."""
        adapter = _adapter(
            _serving({"LLM": _page([_project(i) for i in range(10)])}),
            queries=["LLM"],
            min_raw_ingest=1,
        )
        with caplog.at_level("WARNING"):
            await adapter.fetch(max_results=4)

        assert "truncated" in caplog.text
        assert "max_results=4" in caplog.text

    async def test_no_warning_when_everything_fits(self, caplog):
        """Guards the guard: proves the warning above tracks truncation rather than
        firing on every run."""
        adapter = _adapter(
            _serving({"LLM": _page([_project(i) for i in range(3)])}),
            queries=["LLM"],
            min_raw_ingest=1,
        )
        with caplog.at_level("WARNING"):
            await adapter.fetch(max_results=100)

        assert "truncated" not in caplog.text

    async def test_since_filters_after_the_union(self):
        adapter = _adapter(
            _serving({"LLM": _page([
                _project(1, created="2026-07-16T15:38:04+02:00"),
                _project(2, created="2026-06-01T09:00:00+02:00"),
            ])}),
            queries=["LLM"],
            min_raw_ingest=1,
        )
        listings = await adapter.fetch(since=date(2026, 7, 1))
        assert [j.id for j in listings] == ["1"]

    async def test_a_row_without_an_id_is_dropped(self):
        """It could be neither deduped nor marked seen, so admitting it under a
        synthetic key would re-deliver it every day."""
        page = _page([_project(1), {"title": "Orphan", "description": "no id"}])
        adapter = _adapter(_serving({"LLM": page}), queries=["LLM"], min_raw_ingest=1)
        listings = await adapter.fetch()
        assert [j.id for j in listings] == ["1"]

    async def test_a_structured_id_is_dropped_rather_than_stringified(self):
        """The union key and the normalised id must agree on what an id is.

        A bare `str()` in the union would key this row as "[1, 2]" while
        normalisation rejected the same value and produced `id == ""` — admitting
        exactly the un-dedupable listing the test above exists to keep out.
        """
        page = _page([_project(1), _project([1, 2])])
        adapter = _adapter(_serving({"LLM": page}), queries=["LLM"], min_raw_ingest=1)
        listings = await adapter.fetch()

        assert [j.id for j in listings] == ["1"]
        assert all(j.id for j in listings), "no listing may carry an empty id"


class TestBindingConstraints:
    """Issue #11's three adapter constraints, asserted on the outgoing requests.

    These guard a legal commitment, not behaviour: the mitigations *are* the risk
    acceptance under which ingesting this source was approved at all. Nothing else
    in the system would notice if they regressed, which is the entire reason they
    are tested here. Keep them together.
    """

    async def test_every_request_carries_an_honest_user_agent(self):
        requests: list[httpx.Request] = []
        adapter = _adapter(
            _serving({q: _page([_project(i)]) for i, q in enumerate(["LLM", "KI", "RAG"])},
                     requests),
            queries=["LLM", "KI", "RAG"],
            min_raw_ingest=1,
        )
        await adapter.fetch()

        assert len(requests) == 3
        for request in requests:
            user_agent = request.headers["User-Agent"]
            assert "JobScout" in user_agent, user_agent
            # Not a browser impersonation — the source's block button must keep working.
            assert "Mozilla" not in user_agent, user_agent

    async def test_no_request_authenticates(self):
        """The account and the adapter stay strictly separate. Anonymous ingest is
        a condition of the decision to ingest this source at all."""
        requests: list[httpx.Request] = []
        adapter = _adapter(
            _serving({"LLM": _page([_project(1)])}, requests),
            queries=["LLM"],
            min_raw_ingest=1,
        )
        await adapter.fetch()

        for request in requests:
            assert "Authorization" not in request.headers
            assert "Cookie" not in request.headers

    async def test_a_session_cookie_is_not_carried_to_the_next_request(self):
        """`AsyncClient` persists Set-Cookie across a session by default, so the
        source could start a session on request 1 that we then present on every
        request after it. That is authentication by another name."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                text=_page([_project(len(requests))]),
                headers={"Set-Cookie": "PHPSESSID=abc123; Path=/"},
            )

        adapter = _adapter(handler, queries=["LLM", "KI", "RAG"], min_raw_ingest=1)
        await adapter.fetch()

        assert len(requests) == 3
        for request in requests:
            assert "Cookie" not in request.headers, request.headers.get("Cookie")

    async def test_redirects_are_not_followed(self):
        """The cap counts queries, so "one query = exactly one request" is what makes
        it a cap on requests at all. A redirect chain would multiply real requests
        behind a cap that still reads as satisfied — so a 3xx is an error, not a
        hop to chase."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(302, headers={"Location": "https://elsewhere.example/x"})

        adapter = _adapter(handler, queries=["LLM"])
        with pytest.raises(JobScoutSourceIntegrityError):
            await adapter.fetch()

        assert len(requests) == 1

    async def test_the_request_cap_holds_even_with_more_queries_configured(self):
        """Capped in code rather than by convention, so a looping bug cannot turn a
        personal tool into a crawler."""
        requests: list[httpx.Request] = []
        many = [f"query-{i}" for i in range(20)]
        adapter = _adapter(
            _serving({q: _page([_project(i)]) for i, q in enumerate(many)}, requests),
            queries=many,
            max_requests=3,
            min_raw_ingest=1,
        )
        await adapter.fetch()
        assert len(requests) == 3

    async def test_dropping_queries_to_the_cap_is_never_silent(self, caplog):
        """A silent truncation reads downstream as full coverage of a smaller market."""
        many = ["kept-1", "kept-2", "dropped-3"]
        adapter = _adapter(
            _serving({q: _page([_project(i)]) for i, q in enumerate(many)}),
            queries=many,
            max_requests=2,
            min_raw_ingest=1,
        )
        with caplog.at_level("WARNING"):
            await adapter.fetch()

        assert "dropped-3" in caplog.text
        assert "kept-1" not in caplog.text


# ---------------------------------------------------------------------------
# Failing loudly
# ---------------------------------------------------------------------------

class TestSourceIntegrity:
    async def test_missing_payload_raises_rather_than_returning_empty(self):
        adapter = _adapter(
            lambda request: httpx.Response(200, text="<html><body>consent wall</body></html>"),
            queries=["LLM"],
        )
        with pytest.raises(JobScoutSourceIntegrityError):
            await adapter.fetch()

    async def test_unparseable_payload_raises(self):
        page = ('<script data-component-name="ProjectSearch">{not json,,}</script>')
        adapter = _adapter(lambda request: httpx.Response(200, text=page), queries=["LLM"])
        with pytest.raises(JobScoutSourceIntegrityError):
            await adapter.fetch()

    async def test_payload_without_initial_results_raises(self):
        page = ('<script data-component-name="ProjectSearch">{"aggregations": {}}</script>')
        adapter = _adapter(lambda request: httpx.Response(200, text=page), queries=["LLM"])
        with pytest.raises(JobScoutSourceIntegrityError):
            await adapter.fetch()

    async def test_yield_below_the_floor_raises(self):
        adapter = _adapter(
            _serving({"LLM": _page([_project(1), _project(2)])}),
            queries=["LLM"],
            min_raw_ingest=30,
        )
        with pytest.raises(JobScoutSourceIntegrityError):
            await adapter.fetch()

    async def test_integrity_errors_are_not_caught_as_adapter_errors(self):
        """The whole fail-loud mechanism is the type relationship: `run.py`'s ingest
        catch is scoped to `JobScoutAdapterError`, so making this a subclass would
        silently restore the swallow this spec exists to remove."""
        assert not issubclass(JobScoutSourceIntegrityError, JobScoutAdapterError)

        adapter = _adapter(
            lambda request: httpx.Response(200, text="<html>nothing here</html>"),
            queries=["LLM"],
        )
        with pytest.raises(JobScoutSourceIntegrityError):
            try:
                await adapter.fetch()
            except JobScoutAdapterError:  # pragma: no cover — the bug this guards
                pytest.fail("JobScoutSourceIntegrityError was caught as a recoverable error")

    async def test_a_row_that_is_structurally_wrong_raises(self):
        """`endcustomer` is tri-state and decides `client_type`, with no reading that
        degrades — so unlike the text and numeric fields it has no fallback, and a
        non-boolean there is a shape change worth failing the run over."""
        page = _page([_project(1, endcustomer=["not", "a", "bool"])])
        adapter = _adapter(_serving({"LLM": page}), queries=["LLM"], min_raw_ingest=1)
        with pytest.raises(JobScoutSourceIntegrityError):
            await adapter.fetch()

    def test_junk_in_an_optional_field_degrades_rather_than_dropping_the_row(self):
        """The other side of the same rule: a title and a description are still
        useful when the duration is unreadable."""
        adapter = FreelancermapAdapter(_make_config())
        listing = adapter._normalize(_project(1, duration="drei Monate", beginningYear="zwei"))
        assert listing.duration_months is None
        assert listing.title == "Machine Learning Engineer 1"

    def test_a_structured_value_in_a_text_field_is_dropped_not_repr_ed(self):
        """`str(["a", "b"])` in a description would put Python syntax in front of the
        user and into the embedding."""
        adapter = FreelancermapAdapter(_make_config())
        listing = adapter._normalize(_project(1, description={"de": "Beschreibung"}))
        assert listing.description == ""

    def test_a_boolean_duration_is_not_read_as_one_month(self):
        """`bool` is an `int` subclass in Python, so an un-guarded coercion would
        turn `True` into a one-month contract."""
        adapter = FreelancermapAdapter(_make_config())
        assert adapter._normalize(_project(1, duration=True)).duration_months is None


class TestStatusClassification:
    """Which route a bad status takes is pinned per class of status.

    Both routes now fail loud on a single-query run — that is the #43 fix, which
    removed the empty-digest escape from the recoverable path. The distinction that
    remains, and that these pin, is *how*: a recoverable status (429/5xx/timeout) is
    caught and degrades the query, so a single-query run reaches the floor and its
    raise names the transient cause ("degraded transiently"); a non-recoverable one
    (403/404) is a broken route and raises straight past the floor with the
    block/moved message. `TestTransientDegradation` shows the recoverable route
    degrading *gracefully* when other queries carry the union — the case that only
    exists because the status was classified recoverable rather than broken.
    """

    async def test_a_rate_limit_reaches_the_floor_rather_than_a_swallowable_error(self):
        """The #43 regression in one assertion: a 429 on the only query must NOT
        surface as a `JobScoutAdapterError` (which `run.py` would swallow into an
        empty digest). It degrades, starves the union, and fails loud via the floor."""
        adapter = _adapter(lambda request: httpx.Response(429), queries=["LLM"], min_raw_ingest=1)
        with pytest.raises(JobScoutSourceIntegrityError, match="degraded transiently"):
            await adapter.fetch()

    async def test_a_server_error_takes_the_recoverable_route(self):
        """A 503 is a bad day, not a broken source, so it degrades — and on a single
        query that leaves the union below the floor, which alarms rather than
        delivering silence."""
        adapter = _adapter(lambda request: httpx.Response(503), queries=["LLM"], min_raw_ingest=1)
        with pytest.raises(JobScoutSourceIntegrityError, match="degraded transiently"):
            await adapter.fetch()

    async def test_a_block_page_is_not_recoverable(self):
        """403 is the source telling us to stop. It is a broken route, so it raises
        straight past the floor — not via the degrade path, which is why the message
        is the block one, not the transient-cause one."""
        adapter = _adapter(lambda request: httpx.Response(403), queries=["LLM"])
        with pytest.raises(JobScoutSourceIntegrityError, match="no longer work"):
            await adapter.fetch()

    async def test_a_moved_endpoint_is_not_recoverable(self):
        adapter = _adapter(lambda request: httpx.Response(404), queries=["LLM"])
        with pytest.raises(JobScoutSourceIntegrityError, match="no longer work"):
            await adapter.fetch()

    async def test_a_timeout_takes_the_recoverable_route(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out", request=request)

        adapter = _adapter(handler, queries=["LLM"], min_raw_ingest=1)
        with pytest.raises(JobScoutSourceIntegrityError, match="degraded transiently"):
            await adapter.fetch()


class TestTransientDegradation:
    """A transient per-query failure degrades that one query, not the whole fetch,
    and the distinct-id floor is left as the single arbiter of run health.

    Before issue #43 a mid-union 429 propagated out of `fetch()`: it discarded rows
    already unioned from earlier queries AND skipped the floor entirely, so `run.py`
    swallowed it and exited 0 with a silent 'no matches today'. That reopened the
    exact hole the floor exists to close — a flapping source reading as a quiet
    market. These pin the closed door shut."""

    def _serving_with_failures(self, pages_by_query, status_by_query):
        """Serve a page per query, but return a bare status for named queries."""
        def handler(request: httpx.Request) -> httpx.Response:
            query = request.url.params.get("query", "")
            if query in status_by_query:
                return httpx.Response(status_by_query[query])
            return httpx.Response(200, text=pages_by_query.get(query, _page([])))
        return handler

    async def test_a_mid_union_transient_failure_keeps_earlier_queries(self):
        """The regression itself: a mid-union transient failure must not discard the
        rows queries before it already contributed to the union.

        Uses a 503 — a continue-class transient. A 429 would additionally back off
        the *remaining* queries (see `test_a_429_backs_off_the_remaining_queries`),
        which would confound "earlier rows survive" with "later rows skipped"; a 5xx
        keeps every query in play, so this isolates the union-spanning property."""
        handler = self._serving_with_failures(
            pages_by_query={
                "LLM": _page([_project(1)]),
                "KI": _page([_project(3)]),
            },
            status_by_query={"Generative AI": 503},
        )
        adapter = _adapter(handler, queries=["LLM", "Generative AI", "KI"], min_raw_ingest=1)

        listings = await adapter.fetch()
        assert {j.id for j in listings} == {"1", "3"}

    async def test_a_partial_union_that_clears_the_floor_is_a_fine_day(self):
        """Degradation is not failure. If the surviving queries clear the floor the
        run proceeds normally — no raise, no empty digest."""
        handler = self._serving_with_failures(
            pages_by_query={"LLM": _page([_project(1), _project(2)])},
            status_by_query={"KI": 503},
        )
        adapter = _adapter(handler, queries=["LLM", "KI"], min_raw_ingest=2)

        listings = await adapter.fetch()
        assert {j.id for j in listings} == {"1", "2"}

    async def test_a_transient_failure_below_the_floor_fails_loud_not_silent(self):
        """The other half of the fix: when transient failures leave the union below
        the floor, the run raises the fail-loud integrity error rather than
        returning an empty list. This is what `run.py` must not be able to swallow —
        so it must NOT be a `JobScoutAdapterError`."""
        handler = self._serving_with_failures(
            pages_by_query={},
            status_by_query={"LLM": 429, "KI": 429},
        )
        adapter = _adapter(handler, queries=["LLM", "KI"], min_raw_ingest=1)

        with pytest.raises(JobScoutSourceIntegrityError):
            try:
                await adapter.fetch()
            except JobScoutAdapterError:  # pragma: no cover — the #43 regression
                pytest.fail("a transient failure produced a swallowable empty digest")

    async def test_the_floor_raise_names_the_transient_cause(self):
        """A thin union from rate-limiting must not send an operator hunting a
        payload-shape change that did not happen — the raise says which it was."""
        handler = self._serving_with_failures(
            pages_by_query={},
            status_by_query={"LLM": 429, "KI": 503},
        )
        adapter = _adapter(handler, queries=["LLM", "KI"], min_raw_ingest=1)

        with pytest.raises(JobScoutSourceIntegrityError, match="degraded transiently"):
            await adapter.fetch()

    async def test_a_non_recoverable_status_mid_union_still_fails_loud(self):
        """The degradation catch is scoped to `JobScoutAdapterError`. A 403 block
        page on a later query is a `JobScoutSourceIntegrityError` and must still
        propagate even though earlier queries succeeded — degrading it would hide a
        block behind whatever the first queries happened to return."""
        handler = self._serving_with_failures(
            pages_by_query={"LLM": _page([_project(i) for i in range(30)])},
            status_by_query={"KI": 403},
        )
        adapter = _adapter(handler, queries=["LLM", "KI"], min_raw_ingest=1)

        with pytest.raises(JobScoutSourceIntegrityError):
            await adapter.fetch()

    async def test_a_degraded_query_still_consumed_its_request(self):
        """Cap semantics are unchanged: one request per query, whether it answered
        or degraded. A failed query does not free budget for a retry."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            query = request.url.params.get("query", "")
            if query == "KI":
                return httpx.Response(429)
            return httpx.Response(200, text=_page([_project(1)]))

        adapter = _adapter(handler, queries=["LLM", "KI"], min_raw_ingest=1)
        await adapter.fetch()
        assert [r.url.params["query"] for r in requests] == ["LLM", "KI"]

    async def test_a_degraded_query_is_logged_by_name(self, caplog):
        """Same no-silent-degradation rule as the request and truncation caps: a
        query that dropped out of coverage is named in the log."""
        handler = self._serving_with_failures(
            pages_by_query={"LLM": _page([_project(1)])},
            status_by_query={"KI": 429},
        )
        adapter = _adapter(handler, queries=["LLM", "KI"], min_raw_ingest=1)

        with caplog.at_level("WARNING"):
            await adapter.fetch()
        assert "degraded transiently" in caplog.text
        assert "'KI'" in caplog.text

    async def test_a_429_backs_off_the_remaining_queries(self):
        """A 429 is the source asking us to slow down, so — unlike a 5xx — the first
        one stops further requests rather than firing the rest of the queries at a
        server that just throttled us (issue #11: stay a well-behaved anonymous
        client). Earlier rows still survive; later queries are simply not issued."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            query = request.url.params.get("query", "")
            if query == "LLM":
                return httpx.Response(200, text=_page([_project(1)]))
            if query == "Generative AI":
                return httpx.Response(429)
            return httpx.Response(200, text=_page([_project(3)]))

        adapter = _adapter(
            handler, queries=["LLM", "Generative AI", "KI"], min_raw_ingest=1,
        )
        listings = await adapter.fetch()

        # LLM's row survives the 429 on the next query (the #43 guarantee), but KI is
        # never requested — the back-off, not a discard.
        assert {j.id for j in listings} == {"1"}
        assert [r.url.params["query"] for r in requests] == ["LLM", "Generative AI"]

    async def test_a_429_does_not_back_off_on_the_last_query(self):
        """The back-off only skips queries that remain. A 429 on the final query has
        nothing left to skip, so every query is still issued exactly once."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            query = request.url.params.get("query", "")
            if query == "KI":
                return httpx.Response(429)
            return httpx.Response(200, text=_page([_project(1)]))

        adapter = _adapter(handler, queries=["LLM", "KI"], min_raw_ingest=1)
        await adapter.fetch()
        assert [r.url.params["query"] for r in requests] == ["LLM", "KI"]

    async def test_a_5xx_does_not_back_off_the_remaining_queries(self):
        """The back-off is specific to 429. A 5xx says nothing about our request rate,
        so the remaining queries are still issued — the mirror of the 429 case."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            query = request.url.params.get("query", "")
            if query == "Generative AI":
                return httpx.Response(503)
            return httpx.Response(200, text=_page([_project(1)]))

        adapter = _adapter(
            handler, queries=["LLM", "Generative AI", "KI"], min_raw_ingest=1,
        )
        await adapter.fetch()
        assert [r.url.params["query"] for r in requests] == ["LLM", "Generative AI", "KI"]

    async def test_the_floor_raise_names_a_shape_change_when_answered_queries_should_have_cleared_it(self):
        """The misdirection this fix closes. One query degrades transiently, but the
        others answer 200 with rows that carry no id — a shape change silently drops
        them from the union. The answering queries alone should have cleared the
        floor, so the raise must NOT pin this on the one rate-limited query and drop
        the shape-check hint; that would steer ops away from the change that happened.
        """
        idless_page = _page([_project(i, id=None) for i in range(5)])
        handler = self._serving_with_failures(
            # 4 answering queries each serve a full page whose rows have no id;
            # 4 x 22 >= the floor, so degradation alone cannot explain the shortfall.
            pages_by_query={q: idless_page for q in ["A", "B", "C", "D"]},
            status_by_query={"E": 503},
        )
        adapter = _adapter(
            handler, queries=["A", "B", "C", "D", "E"], min_raw_ingest=30,
        )

        with pytest.raises(JobScoutSourceIntegrityError) as excinfo:
            await adapter.fetch()
        message = str(excinfo.value)
        assert "response shape or the query parameter" in message
        # It still records that a query degraded — it just refuses to blame it.
        assert "degraded transiently" in message
        assert "4 of 5 queries" in message

    async def test_the_floor_raise_blames_only_transients_when_they_alone_explain_it(self):
        """The other side of the arithmetic: when too few queries answered for them to
        have cleared the floor on their own, the degradations *are* a sufficient
        explanation, so the raise stays on the transient cause and does not send ops
        hunting a shape change that need not have happened."""
        handler = self._serving_with_failures(
            pages_by_query={"A": _page([_project(1)])},
            status_by_query={"B": 503, "C": 503},
        )
        # 1 answered x 22 = 22 < floor 30, so transients alone explain the shortfall.
        adapter = _adapter(handler, queries=["A", "B", "C"], min_raw_ingest=30)

        with pytest.raises(JobScoutSourceIntegrityError) as excinfo:
            await adapter.fetch()
        message = str(excinfo.value)
        assert "degraded transiently" in message
        assert "response shape or the query parameter" not in message


class TestCollapseSignature:
    async def test_identical_pages_across_queries_raise_despite_a_healthy_sum(self):
        """The failure mode the distinct-id floor exists for.

        If query differentiation broke — the parameter renamed, say — every request
        would return the same page. Summed, the raw count sits healthily at
        n_queries × page_size; distinct, it collapses to one page. A summed-count
        implementation passes every other test in this file and fails this one.
        """
        one_page = _page([_project(i) for i in range(22)])
        queries = [f"query-{i}" for i in range(5)]
        adapter = _adapter(
            lambda request: httpx.Response(200, text=one_page),
            queries=queries,
            min_raw_ingest=30,
        )

        # 5 queries × 22 rows = 110 summed, which clears the floor comfortably.
        with pytest.raises(JobScoutSourceIntegrityError, match="22 distinct"):
            await adapter.fetch()

    async def test_the_floor_cannot_be_configured_below_a_single_page(self):
        """A floor at or below 22 cannot tell the collapse signature above from one
        query answering normally, which defeats the design."""
        from jobscout.config import AppConfig

        with pytest.raises(ValueError):
            AppConfig.model_validate({
                "profile": _real_profile().model_dump(),
                "anthropic_api_key": "test-key",
                "freelancermap_min_raw_ingest": 22,
            })


class TestQuietMarketStaysSilent:
    async def test_healthy_yield_rejected_by_the_hard_filter_does_not_raise(self):
        """A raw count that survives ingest and then loses every row to the hard
        filter is a quiet market, not a broken source. The alarm has exactly one
        meaning and this is what keeps it from being muted."""
        profile = _real_profile()
        off_topic = [
            _project(
                i,
                title="SAP FI/CO Berater",
                description="Betreuung der SAP-Finanzbuchhaltung. Kein IT-Projekt im engeren Sinne.",
            )
            for i in range(30)
        ]
        adapter = _adapter(
            _serving({"Machine Learning": _page(off_topic)}),
            profile=profile,
            min_raw_ingest=30,
        )

        listings = await adapter.fetch()          # no raise: 30 distinct ids
        assert len(listings) == 30
        assert apply_hard_filter(listings, profile) == []


class TestRealListingsSurviveTheGates:
    def test_a_fully_remote_contracting_project_passes_the_hard_filter(self):
        adapter = FreelancermapAdapter(_make_config())
        profile = _real_profile()
        listings = [adapter._normalize(raw) for raw in _raw_results()]

        survivors = apply_hard_filter(listings, profile)

        assert [j.id for j in survivors] == ["3026337"]

    def test_the_employee_leasing_row_is_rejected_by_the_contract_gate(self):
        adapter = FreelancermapAdapter(_make_config())
        listing = adapter._normalize(_raw_by_id("3026469"))
        assert listing.contract_type in _real_profile().dealbreakers.exclude_contract_types

    def test_the_eighty_percent_row_is_rejected_by_the_remote_floor(self):
        """At `minimum_remote_percentage: 100` the gate is deterministic, and it is
        the single largest reduction in the pipeline (~50% of the German pool)."""
        adapter = FreelancermapAdapter(_make_config())
        listing = adapter._normalize(_raw_by_id("3026169"))
        assert listing.remote_percentage == 80
        assert apply_hard_filter([listing], _real_profile()) == []


def _real_profile(queries: list[str] | None = None) -> UserProfile:
    """A profile shaped like the committed `profile.yaml`, built in code."""
    return UserProfile(
        name="Marcos",
        target_roles=["ML Engineer"],
        skills=SkillsConfig(strong=["RAG systems"]),
        location=LocationConfig(target_countries=["Germany", "Deutschland"]),
        rate=RateConfig(),
        dealbreakers=DealbreakersConfig(
            require_any_keyword=["machine learning", "ML", "AI", "LLM", "RAG"],
            exclude_contract_types=["employee_leasing", "permanent_position"],
            minimum_remote_percentage=100,
        ),
        freelancermap_queries=queries or ["Machine Learning"],
    )
