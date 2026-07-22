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

# The remote cut points. Sole definition — the hard filter and any future
# ranking boost read `JobListing.remote_policy`, never these directly.
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
    # Read `remote_policy` (below), never these two directly.
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

class LocationConfig(BaseModel):
    target_countries: list[str]
    preferred_cities: list[str]
    remote_acceptable: bool
    eu_work_authorization: bool


class DealbreakersConfig(BaseModel):
    exclude_companies: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    require_any_keyword: list[str] = Field(default_factory=list)


class SkillsConfig(BaseModel):
    strong: list[str] = Field(default_factory=list)
    working_knowledge: list[str] = Field(default_factory=list)
    learning: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    name: str
    background: str = ""
    ideal_role: str = ""
    deprioritise: list[str] = Field(default_factory=list)
    target_roles: list[str]
    skills: SkillsConfig
    location: LocationConfig
    dealbreakers: DealbreakersConfig
    email_min_score: int = Field(default=7, ge=1, le=10)
