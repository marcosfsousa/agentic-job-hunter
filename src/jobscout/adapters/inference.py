"""Shared inference helpers for all job adapters.

These utilities infer structured fields (remote policy, seniority, date)
from free-text job attributes. Kept here to avoid duplication across adapters.
"""
from __future__ import annotations

from datetime import date, datetime

from jobscout.models import RemotePolicy, Seniority


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


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO 8601 UTC timestamp to a date. Returns None on failure or None input."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return None
