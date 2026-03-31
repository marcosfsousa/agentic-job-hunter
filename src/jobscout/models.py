from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constrained string types
# ---------------------------------------------------------------------------

RemotePolicy = Literal["remote", "hybrid", "onsite", "not_specified"]
Seniority = Literal["junior", "mid", "senior", "lead", "not_specified"]
FeedbackStatus = Literal["applied", "rejected", "interested", "skipped"]


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
    source: str                      # e.g. "adzuna_de", "jsearch"
    title: str
    company: str
    description: str
    location: str                    # Normalized: "Berlin", "Remote (Germany)"
    remote_policy: RemotePolicy
    salary_min: float | None         # Annual EUR
    salary_max: float | None         # Annual EUR
    seniority: Seniority | None
    url: str
    posted_date: date | None
    fetched_at: datetime
    raw_data: dict = field(repr=False)  # Original API response, hidden from repr


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

class SalaryConfig(BaseModel):
    minimum_annual_eur: float
    target_annual_eur: float
    currency: str = "EUR"


class SeniorityConfig(BaseModel):
    target: list[str]
    exclude: list[str]
    max_years_experience: int | None = None


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
    salary: SalaryConfig
    seniority: SeniorityConfig
    dealbreakers: DealbreakersConfig
    email_min_score: int = Field(default=7, ge=1, le=10)
    jsearch_queries: list[str] = Field(
        default_factory=lambda: ["machine learning engineer in Germany"]
    )
