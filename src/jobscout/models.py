from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constrained string types
# ---------------------------------------------------------------------------

RemotePolicy = Literal["remote", "hybrid", "onsite", "not_specified"]
RateUnit = Literal["hourly", "daily", "project_total"]
ContractType = Literal["contracting", "employee_leasing", "permanent_position", "unknown"]
ClientType = Literal["agency", "direct", "unknown"]
FeedbackStatus = Literal["applied", "rejected", "interested", "skipped"]

# The remote cut points. Sole definition — nothing outside `remote_policy` below
# re-derives the remote/onsite boundary. `_passes_location` compares the raw
# percentage against the user's configured floor, which is a different question,
# and still reads `remote_policy` for the bucket.
FULLY_REMOTE_PERCENTAGE = 100
FULLY_ONSITE_PERCENTAGE = 0


# ---------------------------------------------------------------------------
# Feedback entry — validated from feedback.yaml
# ---------------------------------------------------------------------------

class FeedbackEntry(BaseModel):
    id: str
    source: str
    status: FeedbackStatus


# ---------------------------------------------------------------------------
# Core job listing — normalized, immutable, pipeline-internal
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JobListing:
    id: str                          # Source-specific unique ID
    source: str                      # e.g. "freelancermap"
    title: str
    company: str
    description: str
    location: str                    # Normalized: "Berlin", "Remote (Germany)"
    url: str
    posted_date: datetime | None     # Full timestamp — incremental sync reads this
    fetched_at: datetime
    raw_data: dict = field(repr=False)  # Original API response, hidden from repr

    # Remote — `remote_percentage` is authoritative, `remote_policy_text` is the
    # adapter's text inference and is consulted only when the percentage is unknown.
    # For the coarse bucket read `remote_policy` (below), never `remote_policy_text`;
    # `remote_percentage` is read directly only where the number itself is the point
    # (the hard filter's configurable remote floor).
    remote_percentage: int | None = None
    remote_policy_text: RemotePolicy = "not_specified"

    # Rate. All four are nullable and required by nothing — all-None is the DACH
    # norm, not an anomaly. A single quoted value sets rate_min == rate_max.
    rate_min: float | None = None
    rate_max: float | None = None
    rate_unit: RateUnit | None = None
    rate_currency: str | None = None

    contract_type: ContractType = "unknown"
    client_type: ClientType = "unknown"

    # Duration — parsed months are best-effort; `duration_text` is the source of
    # truth when parsing is uncertain (e.g. "MM" as Mannmonate, not months).
    # Open-ended is a positive signal and stays distinct from unknown length.
    duration_months: int | None = None
    duration_is_open_ended: bool = False
    duration_text: str | None = None

    # Start — three distinct cases: immediate, month-granular (text only), or an
    # exact day. `start_date` is set only when the day itself is known.
    start_date: date | None = None
    start_is_immediate: bool = False
    start_text: str | None = None

    @property
    def remote_policy(self) -> RemotePolicy:
        """The remote policy, derived so it can never contradict the percentage.

        The percentage always wins; the adapter's text inference is a fallback for
        sources that publish no number.
        """
        if self.remote_percentage is None:
            return self.remote_policy_text
        if self.remote_percentage >= FULLY_REMOTE_PERCENTAGE:
            return "remote"
        if self.remote_percentage <= FULLY_ONSITE_PERCENTAGE:
            return "onsite"
        return "hybrid"


# ---------------------------------------------------------------------------
# LLM evaluation result — validated from Claude Haiku JSON output
# ---------------------------------------------------------------------------

class EvaluationResult(BaseModel):
    match_score: int = Field(ge=1, le=10)
    matching_skills: list[str]
    gaps: list[str]
    explanation: str


# ---------------------------------------------------------------------------
# Scored job — carries a JobListing through ranking and into delivery
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoredJob:
    listing: JobListing
    embedding_score: float
    llm_score: float | None = None        # None until LLM evaluation runs
    final_score: float | None = None      # 0.4 * embedding + 0.6 * llm
    evaluation: EvaluationResult | None = None


# ---------------------------------------------------------------------------
# User profile — validated from profile.yaml by config.py
# ---------------------------------------------------------------------------

class _StrictProfileModel(BaseModel):
    """Base for the profile models: an unrecognised key is an error, not a default.

    `profile.yaml` is the single source of truth, and two hard-filter gates now read
    it. Without this, a misspelled key falls back to its Pydantic default, the gates
    quietly change what gets filtered, and nothing fails — the tests build
    `UserProfile` in code, so only the file is wrong.

    Scoped to the profile models deliberately. `EvaluationResult` and `FeedbackEntry`
    validate data from outside the repo — Haiku's JSON and `feedback.yaml` — and stay
    permissive so a provider adding a response field cannot break the pipeline. This
    is a rule about our config file, not about Pydantic usage in general.
    """

    model_config = {"extra": "forbid"}


class LocationConfig(_StrictProfileModel):
    target_countries: list[str]


class RateConfig(_StrictProfileModel):
    """The user's negotiating position, stated per unit.

    Hourly and daily are independent statements, not two views of one number: a
    *Tagessatz* carries bulk-engagement premiums that no `hourly × hours_per_day`
    can know, so divergence between them is signal rather than a consistency bug.
    Nothing is derived in either direction, and there is deliberately no
    `hours_per_day`.

    **No pipeline consumer.** No filter, no ranking, no prompt reads this — see the
    note in `profile.yaml`. An acknowledged exception to "add the field with its
    consumer", on the basis that a rate floor is a position the user holds
    independently of this tool.
    """

    minimum_hourly: float | None = None
    target_hourly: float | None = None
    minimum_daily: float | None = None
    target_daily: float | None = None
    currency: str = "EUR"


class DealbreakersConfig(_StrictProfileModel):
    exclude_companies: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    require_any_keyword: list[str] = Field(default_factory=list)

    # Read by `_passes_contract_type` — a blocklist, and see that predicate for why
    # the direction matters. Empty rejects nothing.
    exclude_contract_types: list[ContractType] = Field(default_factory=list)

    # The floor `_passes_location` compares `remote_percentage` against; None
    # switches that gate off. Bounded because it is a percentage: a mistyped 1000
    # would otherwise reject every listing silently, which is the same class of
    # failure the strict key validation above exists to prevent.
    minimum_remote_percentage: int | None = Field(default=100, ge=0, le=100)


class SkillsConfig(_StrictProfileModel):
    strong: list[str] = Field(default_factory=list)
    working_knowledge: list[str] = Field(default_factory=list)
    learning: list[str] = Field(default_factory=list)


class UserProfile(_StrictProfileModel):
    name: str
    background: str = ""
    ideal_role: str = ""
    deprioritise: list[str] = Field(default_factory=list)
    target_roles: list[str]
    skills: SkillsConfig
    location: LocationConfig
    rate: RateConfig
    dealbreakers: DealbreakersConfig
    email_min_score: int = Field(default=7, ge=1, le=10)

    # Free-text search terms sent to freelancermap's `query=` parameter. Named
    # per-source so a second source adds its own list with no migration.
    #
    # Also the freelancermap adapter's sole coverage mechanism: its anonymous view
    # caps at 22 results per query and cannot paginate, so the adapter issues one
    # request per entry and unions them. The length of this list is the size of the
    # corpus, which is why the request cap in `config.py` bounds it.
    freelancermap_queries: list[str]
