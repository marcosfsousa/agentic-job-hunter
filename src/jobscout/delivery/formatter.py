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

    salary = _format_salary(listing.salary_min, listing.salary_max)
    skills = ", ".join(ev.matching_skills) if ev.matching_skills else "none"
    gaps = ", ".join(ev.gaps) if ev.gaps else "none"

    lines = [
        f"## {rank}. {listing.title} — {listing.company}",
        f"**Score:** {ev.match_score}/10",
        f"**Location:** {listing.location}",
        f"**Remote:** {listing.remote_policy}",
    ]

    if salary:
        lines.append(f"**Salary:** {salary}")

    lines += [
        f"**Matching skills:** {skills}",
        f"**Gaps:** {gaps}",
        f"**Summary:** {ev.explanation}",
        f"[Apply]({listing.url})",
        "\n---\n",
    ]

    return "\n".join(lines)


def _format_salary(salary_min: float | None, salary_max: float | None) -> str:
    if salary_min is not None and salary_max is not None:
        return f"€{salary_min:,.0f} – €{salary_max:,.0f}"
    if salary_max is not None:
        return f"up to €{salary_max:,.0f}"
    if salary_min is not None:
        return f"from €{salary_min:,.0f}"
    return ""
