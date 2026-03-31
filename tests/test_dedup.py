"""Tests for filters/dedup.py — fingerprint-based deduplication."""
from __future__ import annotations

from datetime import date, datetime

from jobscout.filters.dedup import job_fingerprint, deduplicate_listings
from jobscout.models import JobListing


def _make_job(**overrides) -> JobListing:
    defaults = dict(
        id="job-1",
        source="adzuna_de",
        title="ML Engineer",
        company="Acme GmbH",
        description="A short description.",
        location="Berlin, Germany",
        remote_policy="hybrid",
        salary_min=60_000.0,
        salary_max=80_000.0,
        seniority="mid",
        url="https://example.com/job/1",
        posted_date=date(2026, 3, 18),
        fetched_at=datetime(2026, 3, 18, 12, 0, 0),
        raw_data={},
    )
    defaults.update(overrides)
    return JobListing(**defaults)


# ---------------------------------------------------------------------------
# No-op paths
# ---------------------------------------------------------------------------

def test_single_job_returned_unchanged():
    job = _make_job()
    assert deduplicate_listings([job]) == [job]


def test_different_fingerprints_both_returned():
    a = _make_job(id="1", title="ML Engineer", company="Acme")
    b = _make_job(id="2", title="Data Scientist", company="Acme")
    result = deduplicate_listings([a, b])
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Deduplication cases
# ---------------------------------------------------------------------------

def test_cross_source_dedup():
    a = _make_job(id="1", source="adzuna_de", title="ML Engineer", company="DeepMind")
    b = _make_job(id="2", source="jsearch", title="ML Engineer", company="DeepMind")
    result = deduplicate_listings([a, b])
    assert len(result) == 1


def test_within_source_dedup():
    a = _make_job(id="1", source="adzuna_de", title="ML Engineer", company="DeepMind")
    b = _make_job(id="2", source="adzuna_de", title="ML Engineer", company="DeepMind")
    result = deduplicate_listings([a, b])
    assert len(result) == 1


def test_group_of_three_returns_one():
    jobs = [
        _make_job(id=str(i), source="adzuna_de", title="ML Engineer", company="SAP")
        for i in range(3)
    ]
    assert len(deduplicate_listings(jobs)) == 1


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------

def test_keeps_longest_description():
    short = _make_job(id="1", source="adzuna_de", description="Short.")
    long_ = _make_job(id="2", source="jsearch", description="A much longer description with more detail about the role.")
    result = deduplicate_listings([short, long_])
    assert result[0] is long_


def test_tiebreak_first_in_list_kept():
    a = _make_job(id="1", source="adzuna_de", description="Same length!!")
    b = _make_job(id="2", source="jsearch",  description="Same length!!")
    result = deduplicate_listings([a, b])
    assert result[0] is a


# ---------------------------------------------------------------------------
# Fingerprint normalisation
# ---------------------------------------------------------------------------

def test_abbreviation_sr_ml():
    assert job_fingerprint("Sr ML Engineer", "DeepMind") == job_fingerprint("Senior Machine Learning Engineer", "DeepMind")


def test_abbreviation_jr():
    assert job_fingerprint("Jr NLP Engineer", "Acme") == job_fingerprint("Junior Natural Language Processing Engineer", "Acme")


def test_punctuation_stripped():
    assert job_fingerprint("ML-Engineer", "Acme") == job_fingerprint("ML Engineer", "Acme")


def test_location_ignored():
    a = _make_job(id="1", location="Berlin", title="ML Engineer", company="SAP")
    b = _make_job(id="2", location="Munich", title="ML Engineer", company="SAP")
    result = deduplicate_listings([a, b])
    assert len(result) == 1
