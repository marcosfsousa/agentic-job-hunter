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
        profile = SimpleNamespace(freelancermap_queries=queries or ["Machine Learning"])
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
        "country": "Deutschland",
        "url": f"/projekt/ml-{project_id}",
        "created": "2026-07-16T15:38:04+02:00",
        "projectContractType": {"type": "contracting", "remoteInPercent": 100},
        "endcustomer": False,
        "budget": [],
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

    def test_the_fixture_page_yields_its_three_projects(self):
        assert [str(r["id"]) for r in _extract_results(FIXTURE_HTML)] == [
            "2891234", "2891235", "2891236",
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
        listing = self.adapter._normalize(_raw_by_id("2891234"))
        assert listing.id == "2891234"
        assert listing.source == "freelancermap"
        assert listing.title == "Machine Learning Engineer (LLM / RAG) — remote"
        assert listing.company == "Nexon IT Consulting GmbH"
        assert "RAG-Pipelines" in listing.description

    def test_relative_url_is_made_absolute(self):
        listing = self.adapter._normalize(_raw_by_id("2891234"))
        assert listing.url == (
            "https://www.freelancermap.de"
            "/projekt/machine-learning-engineer-llm-rag-remote-2891234"
        )

    def test_location_carries_the_country_the_gate_matches_on(self):
        listing = self.adapter._normalize(_raw_by_id("2891235"))
        assert listing.location == "München, Deutschland"

    def test_posted_date_is_timezone_aware(self):
        """Incremental sync compares this against a previous run, so a naive
        timestamp would raise rather than compare. The source's own +02:00 offset is
        kept rather than normalised to UTC."""
        listing = self.adapter._normalize(_raw_by_id("2891234"))
        assert listing.posted_date == datetime(
            2026, 7, 16, 15, 38, 4, tzinfo=timezone(timedelta(hours=2))
        )
        assert listing.posted_date.tzinfo is not None

    def test_an_unparseable_created_value_yields_none_rather_than_raising(self):
        listing = self.adapter._normalize(_project(1, created="last Tuesday"))
        assert listing.posted_date is None

    def test_remote_percentage_comes_from_remote_in_percent(self):
        assert self.adapter._normalize(_raw_by_id("2891234")).remote_percentage == 100
        assert self.adapter._normalize(_raw_by_id("2891235")).remote_percentage == 60

    def test_remote_policy_text_is_constant_not_specified(self):
        """freelancermap publishes no free-text policy, so the derived
        `remote_policy` must always resolve off the percentage."""
        listing = self.adapter._normalize(_raw_by_id("2891235"))
        assert listing.remote_policy_text == "not_specified"
        assert listing.remote_policy == "hybrid"   # derived from 60, not from text

    def test_contract_type_maps_one_to_one(self):
        assert self.adapter._normalize(_raw_by_id("2891234")).contract_type == "contracting"
        assert self.adapter._normalize(_raw_by_id("2891235")).contract_type == "employee_leasing"

    def test_unrecognised_contract_type_becomes_unknown_not_an_error(self):
        """A new vocabulary value must cost precision on one row, not drop it."""
        listing = self.adapter._normalize(_raw_by_id("2891236"))
        assert listing.contract_type == "unknown"

    def test_duration_is_months_with_the_raw_text_preserved(self):
        listing = self.adapter._normalize(_raw_by_id("2891234"))
        assert listing.duration_months == 6
        assert listing.duration_text == "6 Monate"
        assert listing.duration_is_open_ended is False

    def test_missing_duration_reads_as_unknown_not_open_ended(self):
        listing = self.adapter._normalize(_raw_by_id("2891235"))
        assert listing.duration_months is None
        assert listing.duration_is_open_ended is False

    def test_ambiguous_duration_text_survives_the_month_parse(self):
        """"3 MM" is plausibly Mannmonate, not three calendar months. The integer is
        taken at face value per the mapping, so `duration_text` is what makes the
        misread recoverable."""
        listing = self.adapter._normalize(_raw_by_id("2891236"))
        assert listing.duration_months == 3
        assert listing.duration_text == "3 MM"

    def test_freelancermap_embedding_is_not_mistaken_for_ours(self):
        """The source ships a 1024-dim vector; ours is 384-dim and asymmetric.
        It must reach no model field — only `raw_data`."""
        listing = self.adapter._normalize(_raw_by_id("2891234"))
        assert listing.raw_data["embedding"] == [0.014, -0.221, 0.098]

    def test_raw_payload_is_retained(self):
        listing = self.adapter._normalize(_raw_by_id("2891234"))
        assert listing.raw_data["pid"] == "P-2891234"


class TestRateIsNeverParsed:
    """`budget` is unit-ambiguous, so parsing it risks the silent cross-scale
    comparison the four-field rate shape exists to prevent. No live row has ever
    carried one — project 2891236 exists so the rule is pinned anyway."""

    def setup_method(self):
        self.adapter = FreelancermapAdapter(_make_config())

    def test_populated_budget_still_yields_no_rate(self):
        raw = _raw_by_id("2891236")
        assert raw["budget"], "fixture must carry a populated budget for this to mean anything"

        listing = self.adapter._normalize(raw)
        assert listing.rate_min is None
        assert listing.rate_max is None
        assert listing.rate_unit is None
        assert listing.rate_currency is None

    def test_empty_budget_yields_no_rate(self):
        listing = self.adapter._normalize(_raw_by_id("2891234"))
        assert (listing.rate_min, listing.rate_max) == (None, None)


class TestStartPrecedence:
    """immediate → exact day → month-granular, in that order."""

    def setup_method(self):
        self.adapter = FreelancermapAdapter(_make_config())

    def test_immediate_start_sets_the_flag_and_no_date(self):
        listing = self.adapter._normalize(_raw_by_id("2891234"))
        assert listing.start_is_immediate is True
        assert listing.start_date is None
        assert listing.start_text == "ab sofort"

    def test_exact_day_is_parsed(self):
        listing = self.adapter._normalize(_raw_by_id("2891235"))
        assert listing.start_date == date(2026, 9, 1)
        assert listing.start_is_immediate is False
        assert listing.start_text == "01.09.2026"

    def test_month_granular_start_never_fakes_a_day(self):
        """"Ab September 2026" gives a month, not a day. Synthesising the 1st would
        present an invented date as a known one."""
        listing = self.adapter._normalize(_raw_by_id("2891236"))
        assert listing.start_date is None
        assert listing.start_is_immediate is False
        assert listing.start_text == "Ab September 2026"

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
        listing = self.adapter._normalize(_raw_by_id("2891235"))
        assert listing.raw_data["endcustomer"] is True
        assert listing.client_type == "direct"

    def test_false_means_unknown(self):
        listing = self.adapter._normalize(_raw_by_id("2891234"))
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

    async def test_transient_http_failure_stays_recoverable(self):
        """A 503 is a bad day, not a broken source, so it degrades rather than alarms."""
        adapter = _adapter(lambda request: httpx.Response(503), queries=["LLM"])
        with pytest.raises(JobScoutAdapterError):
            await adapter.fetch()


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

        assert [j.id for j in survivors] == ["2891234"]

    def test_the_employee_leasing_row_is_rejected_by_the_contract_gate(self):
        adapter = FreelancermapAdapter(_make_config())
        listing = adapter._normalize(_raw_by_id("2891235"))
        assert listing.contract_type in _real_profile().dealbreakers.exclude_contract_types

    def test_the_eighty_percent_row_is_rejected_by_the_remote_floor(self):
        """At `minimum_remote_percentage: 100` the gate is deterministic, and it is
        the single largest reduction in the pipeline (~50% of the German pool)."""
        adapter = FreelancermapAdapter(_make_config())
        listing = adapter._normalize(_raw_by_id("2891236"))
        assert listing.remote_percentage == 80
        assert apply_hard_filter([listing], _real_profile()) == []


def _real_profile() -> UserProfile:
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
        freelancermap_queries=["Machine Learning"],
    )
