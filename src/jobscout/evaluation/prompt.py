from __future__ import annotations

from jobscout.models import JobListing, UserProfile

SYSTEM_PROMPT = """\
You are a job-fit evaluator. Given a candidate profile and a job listing, return a \
JSON object with exactly these fields:
- match_score: integer 1–10 (10 = perfect fit)
- matching_skills: list of strings — skills from the profile that appear in the job
- gaps: list of strings — skills or requirements the job needs that the profile lacks
- explanation: one or two sentences summarising the fit

Scoring rule: if the job explicitly requires a formal CS or engineering degree as a \
mandatory qualification, reduce match_score by 2–3 points and include the degree \
requirement in gaps.

Respond with valid JSON only. No markdown, no extra text.\
"""


def build_prompt(job: JobListing, profile: UserProfile) -> str:
    """Return the user-turn message for a single job evaluation."""
    strong = ", ".join(profile.skills.strong) or "none listed"
    working = ", ".join(profile.skills.working_knowledge) or "none listed"
    roles = ", ".join(profile.target_roles) or "none listed"

    return (
        f"## Candidate profile\n"
        f"Target roles: {roles}\n"
        f"Strong skills: {strong}\n"
        f"Working knowledge: {working}\n\n"
        f"## Job listing\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location}\n"
        f"Description:\n{job.description}"
    )
