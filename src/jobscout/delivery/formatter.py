from __future__ import annotations

from datetime import date

from jobscout.models import ScoredJob


def format_digest(jobs: list[ScoredJob], run_date: date | None = None) -> str:
    """Render evaluated jobs as a markdown digest.

    Only jobs with a completed LLM evaluation (llm_score not None) are included.
    Jobs are assumed to arrive sorted by final_score descending.

    Args:
        jobs: Evaluated ScoredJobs from the pipeline.
        run_date: Date to show in the header. Defaults to today.

    Returns:
        Markdown string ready for file write or Telegram send.
    """
    run_date = run_date or date.today()
    evaluated = [j for j in jobs if j.llm_score is not None]

    title = f"# JobScout Digest — {run_date.isoformat()}\n\n"

    if not evaluated:
        return title + "_No evaluated matches for today._\n"

    count = f"**{len(evaluated)} match{'es' if len(evaluated) != 1 else ''}** after evaluation.\n\n---\n\n"

    sections = [title + count]
    for rank, job in enumerate(evaluated, start=1):
        sections.append(_format_job(rank, job))

    return "\n".join(sections)


def _format_job(rank: int, job: ScoredJob) -> str:
    listing = job.listing
    ev = job.evaluation  # guaranteed non-None (caller filters)

    skills = ", ".join(ev.matching_skills) if ev.matching_skills else "none"
    gaps = ", ".join(ev.gaps) if ev.gaps else "none"

    lines = [
        f"## {rank}. {listing.title} — {listing.company}",
        f"**ID:** {listing.id} | **Source:** {listing.source}",
        f"**Score:** {ev.match_score}/10 | **Embedding:** {job.embedding_score:.3f}",
        f"**Location:** {listing.location}",
        f"**Remote:** {listing.remote_policy}",
        f"**Matching skills:** {skills}",
        f"**Gaps:** {gaps}",
        f"**Summary:** {ev.explanation}",
    ]

    # The flag half of #95's "keep the row, flag it". The row is rendered exactly as
    # any other - the point is that a score whose own trace does not add up is visible
    # where the score is read, not only to whoever greps the run log.
    if job.trace_warnings:
        lines.append(f"**UNVERIFIED SCORE:** {'; '.join(job.trace_warnings)}")

    lines += [
        f"[Apply]({listing.url})",
        "\n---\n",
    ]

    return "\n".join(lines)
