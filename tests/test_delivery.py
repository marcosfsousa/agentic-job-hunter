"""Tests for delivery/formatter.py, delivery/writer.py, delivery/email_sender.py.

No network calls — smtplib.SMTP is patched at the import site.
File I/O uses pytest's tmp_path fixture.
"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import resend.exceptions

from jobscout.delivery.email_sender import _is_configured, send_digest
from jobscout.delivery.formatter import _format_salary, format_digest
from jobscout.delivery.writer import write_digest
from jobscout.models import EvaluationResult, JobListing, ScoredJob


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_RUN_DATE = date(2026, 3, 21)


def _make_scored_job(
    id: str = "job-1",
    *,
    with_evaluation: bool = True,
    salary_min: float | None = 55_000.0,
    salary_max: float | None = 75_000.0,
) -> ScoredJob:
    listing = JobListing(
        id=id,
        source="test",
        title="ML Engineer",
        company="Test GmbH",
        description="Build LLM pipelines using LangChain.",
        location="Berlin, Germany",
        remote_policy="hybrid",
        salary_min=salary_min,
        salary_max=salary_max,
        seniority="mid",
        url=f"https://example.com/job/{id}",
        posted_date=date(2026, 3, 20),
        fetched_at=datetime(2026, 3, 20, 12, 0, 0),
        raw_data={},
    )
    if with_evaluation:
        evaluation = EvaluationResult(
            match_score=8,
            matching_skills=["LangChain", "RAG systems"],
            gaps=["MLOps"],
            explanation="Strong match on core LLM skills.",
        )
        return ScoredJob(
            listing=listing,
            embedding_score=0.6,
            llm_score=0.8,
            final_score=0.72,
            evaluation=evaluation,
        )
    return ScoredJob(listing=listing, embedding_score=0.6)


def _make_config(**overrides) -> SimpleNamespace:
    defaults = dict(
        resend_api_key="re_test123",
        email_to="to@example.com",
        email_from="onboarding@resend.dev",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_resend(side_effect=None):
    """Patch resend.Emails.send (the sync call wrapped by asyncio.to_thread)."""
    mock = MagicMock(return_value={"id": "test-email-id"})
    if side_effect is not None:
        mock.side_effect = side_effect
    return patch("jobscout.delivery.email_sender.resend.Emails.send", mock)


# ---------------------------------------------------------------------------
# TestFormatDigest
# ---------------------------------------------------------------------------

class TestFormatDigest:
    def test_empty_evaluated_jobs_returns_no_matches_message(self):
        result = format_digest([], run_date=_RUN_DATE)
        assert "_No evaluated matches for today._" in result

    def test_filters_out_jobs_without_llm_score(self):
        jobs = [_make_scored_job("j1"), _make_scored_job("j2", with_evaluation=False)]
        result = format_digest(jobs, run_date=_RUN_DATE)
        assert "## 1." in result
        assert "## 2." not in result

    def test_count_line_singular(self):
        result = format_digest([_make_scored_job()], run_date=_RUN_DATE)
        assert "**1 match**" in result
        assert "matches" not in result

    def test_count_line_plural(self):
        jobs = [_make_scored_job("j1"), _make_scored_job("j2")]
        result = format_digest(jobs, run_date=_RUN_DATE)
        assert "**2 matches**" in result

    def test_job_section_contains_title_and_company(self):
        result = format_digest([_make_scored_job()], run_date=_RUN_DATE)
        assert "ML Engineer" in result
        assert "Test GmbH" in result

    def test_job_section_contains_score_skills_gaps_explanation(self):
        result = format_digest([_make_scored_job()], run_date=_RUN_DATE)
        assert "8/10" in result
        assert "LangChain" in result
        assert "MLOps" in result
        assert "Strong match on core LLM skills." in result

    def test_job_section_contains_apply_link(self):
        result = format_digest([_make_scored_job("j1")], run_date=_RUN_DATE)
        assert "[Apply](https://example.com/job/j1)" in result

    def test_rank_numbers_increment(self):
        jobs = [_make_scored_job("j1"), _make_scored_job("j2")]
        result = format_digest(jobs, run_date=_RUN_DATE)
        assert "## 1." in result
        assert "## 2." in result

    def test_run_date_in_header(self):
        result = format_digest([], run_date=date(2026, 1, 15))
        assert "2026-01-15" in result

    def test_no_salary_line_when_both_none(self):
        result = format_digest(
            [_make_scored_job(salary_min=None, salary_max=None)], run_date=_RUN_DATE
        )
        assert "**Salary:**" not in result


# ---------------------------------------------------------------------------
# TestFormatSalary
# ---------------------------------------------------------------------------

class TestFormatSalary:
    def test_both_min_and_max(self):
        assert _format_salary(50_000, 70_000) == "€50,000 – €70,000"

    def test_only_max(self):
        assert _format_salary(None, 70_000) == "up to €70,000"

    def test_only_min(self):
        assert _format_salary(50_000, None) == "from €50,000"

    def test_neither(self):
        assert _format_salary(None, None) == ""


# ---------------------------------------------------------------------------
# TestWriteDigest
# ---------------------------------------------------------------------------

class TestWriteDigest:
    def test_writes_file_with_correct_name(self, tmp_path):
        write_digest("content", tmp_path, run_date=_RUN_DATE)
        assert (tmp_path / "2026-03-21.md").exists()

    def test_file_content_matches_input(self, tmp_path):
        write_digest("hello digest", tmp_path, run_date=_RUN_DATE)
        assert (tmp_path / "2026-03-21.md").read_text(encoding="utf-8") == "hello digest"

    def test_creates_directory_if_missing(self, tmp_path):
        subdir = tmp_path / "nested" / "digests"
        write_digest("content", subdir, run_date=_RUN_DATE)
        assert subdir.exists()

    def test_overwrites_existing_file(self, tmp_path):
        write_digest("first", tmp_path, run_date=_RUN_DATE)
        write_digest("second", tmp_path, run_date=_RUN_DATE)
        assert (tmp_path / "2026-03-21.md").read_text(encoding="utf-8") == "second"

    def test_returns_correct_path(self, tmp_path):
        result = write_digest("content", tmp_path, run_date=_RUN_DATE)
        assert result == tmp_path / "2026-03-21.md"


# ---------------------------------------------------------------------------
# TestIsConfigured
# ---------------------------------------------------------------------------

class TestIsConfigured:
    def test_all_fields_set_returns_true(self):
        assert _is_configured(_make_config()) is True

    def test_missing_resend_api_key_returns_false(self):
        assert _is_configured(_make_config(resend_api_key=None)) is False

    def test_missing_email_to_returns_false(self):
        assert _is_configured(_make_config(email_to=None)) is False

    def test_missing_email_from_returns_false(self):
        assert _is_configured(_make_config(email_from=None)) is False


# ---------------------------------------------------------------------------
# TestSendDigest
# ---------------------------------------------------------------------------

class TestSendDigest:
    async def test_returns_false_when_not_configured(self):
        config = _make_config(resend_api_key=None)
        result = await send_digest("content", config, run_date=_RUN_DATE)
        assert result is False

    async def test_returns_true_on_success(self):
        config = _make_config()
        with _mock_resend():
            result = await send_digest("content", config, run_date=_RUN_DATE)
        assert result is True

    async def test_params_passed_correctly(self):
        config = _make_config()
        captured: list[dict] = []

        def capture(params):
            captured.append(params)
            return {"id": "test-id"}

        with _mock_resend() as mock_send:
            mock_send.side_effect = capture
            await send_digest("content", config, run_date=_RUN_DATE)

        assert captured
        assert "2026-03-21" in captured[0]["subject"]
        assert captured[0]["from"] == "onboarding@resend.dev"
        assert captured[0]["to"] == ["to@example.com"]

    async def test_returns_false_on_resend_exception(self):
        config = _make_config()
        exc = resend.exceptions.ResendError(500, "api_error", "Internal error", "Retry later")
        with _mock_resend(side_effect=exc):
            result = await send_digest("content", config, run_date=_RUN_DATE)
        assert result is False
