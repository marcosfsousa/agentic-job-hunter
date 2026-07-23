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
from jobscout.delivery.formatter import format_digest
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
    remote_percentage: int | None = 50,
    match_score: int = 8,
    embedding_score: float = 0.6,
) -> ScoredJob:
    listing = JobListing(
        id=id,
        source="test",
        title="ML Engineer",
        company="Test GmbH",
        description="Build LLM pipelines using LangChain.",
        location="Berlin, Germany",
        remote_percentage=remote_percentage,
        url=f"https://example.com/job/{id}",
        posted_date=datetime(2026, 3, 20, 9, 0, 0),
        fetched_at=datetime(2026, 3, 20, 12, 0, 0),
        raw_data={},
    )
    if with_evaluation:
        evaluation = EvaluationResult(
            match_score=match_score,
            matching_skills=["LangChain", "RAG systems"],
            gaps=["MLOps"],
            explanation="Strong match on core LLM skills.",
        )
        return ScoredJob(
            listing=listing,
            embedding_score=embedding_score,
            llm_score=match_score / 10,
            final_score=match_score / 10,   # final_score == llm_score, no blend
            evaluation=evaluation,
        )
    return ScoredJob(listing=listing, embedding_score=embedding_score)


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

    def test_no_salary_line_is_ever_rendered(self):
        """Annual salary left the model with the contract pivot."""
        result = format_digest([_make_scored_job()], run_date=_RUN_DATE)
        assert "**Salary:**" not in result

    def test_remote_line_renders_from_percentage(self):
        result = format_digest([_make_scored_job(remote_percentage=100)], run_date=_RUN_DATE)
        assert "**Remote:** remote" in result

    def test_remote_line_renders_hybrid_from_partial_percentage(self):
        result = format_digest([_make_scored_job(remote_percentage=60)], run_date=_RUN_DATE)
        assert "**Remote:** hybrid" in result

    def test_remote_line_renders_when_percentage_is_unknown(self):
        result = format_digest([_make_scored_job(remote_percentage=None)], run_date=_RUN_DATE)
        assert "**Remote:** not_specified" in result

    def test_job_section_contains_id_and_source(self):
        result = format_digest([_make_scored_job("abc-123")], run_date=_RUN_DATE)
        assert "**ID:** abc-123" in result
        assert "**Source:** test" in result

    def test_digest_order_follows_final_score(self):
        """Rank 1 is the highest final_score. The formatter renders in the order it is
        handed — the evaluator now sorts before this point (F #9 decision 9), so a
        highest-first input must render highest-first, and rank order must track score
        descending. Before the sort landed the digest was ordered by embedding score."""
        jobs = [
            _make_scored_job("top", match_score=9),
            _make_scored_job("mid", match_score=6),
            _make_scored_job("low", match_score=4),
        ]
        result = format_digest(jobs, run_date=_RUN_DATE)

        top_pos = result.index("top")
        mid_pos = result.index("mid")
        low_pos = result.index("low")
        assert top_pos < mid_pos < low_pos
        assert result.index("## 1.") < result.index("## 2.") < result.index("## 3.")
        # rank 1 carries the 9/10 job
        rank1_block = result.split("## 2.")[0]
        assert "9/10" in rank1_block

    def test_embedding_line_still_rendered(self):
        """The **Embedding:** line stays — it no longer orders the digest but it is the
        retriever's confidence, worth seeing on the first live runs of a swapped model."""
        result = format_digest([_make_scored_job(embedding_score=0.512)], run_date=_RUN_DATE)
        assert "**Embedding:** 0.512" in result


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
