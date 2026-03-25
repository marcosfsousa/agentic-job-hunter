from __future__ import annotations

from jobscout.models import JobListing, UserProfile

SYSTEM_PROMPT = """\
You are a calibrated job-fit evaluator. Given a candidate profile and a job listing, \
return a JSON object with exactly these fields:
- match_score: integer 1–10 (10 = near-perfect fit; 7+ means worth applying; \
below 5 means poor fit)
- matching_skills: list of strings — skills from the candidate's profile that this \
specific job particularly values or emphasises. Prefer distinctive skills \
(e.g. RAG systems, LangChain, domain-specific frameworks) over generic ones \
(e.g. Python, Docker, SQL). When both strong and working-knowledge skills match, \
prefer skills from the strong list. Only include a skill the job explicitly calls for — no padding.Return at most 5. \
- gaps: list of strings — skills or requirements the job needs that the profile lacks
- explanation: one or two sentences summarising the fit and calling out any \
score-affecting factors

Scoring — use this process:
1. Start at 6 if the role has reasonable skill overlap with the candidate profile \
(mentions LLMs, AI applications, or related tools). Start at 4 if overlap is weak \
or the role is tangentially related. Start at 2 if it is a poor fit on its face.
2. Apply adjustments (each applies independently; do not double-count):
   - REDUCE by 2 pts: degree is a hard mandatory requirement with no alternative \
path stated (include in gaps)
   - REDUCE by 1 pt: degree is preferred but "comparable experience" or equivalent \
is explicitly accepted (include in gaps)
   - REDUCE by 2 pts: role is primarily model research, classical ML \
(forecasting, RecSys, CV), or academic — not LLM application building
   - REDUCE by 1 pt: role requires 5+ years dedicated ML experience, or salary \
band is clearly above €80k
   - REDUCE by 1 pt: MLOps, Kubernetes, or cloud infrastructure are core \
requirements, not secondary
   - REDUCE by 1 pt: AI role embedded in a non-tech company with no apparent \
specialist AI unit or team
   - BOOST by 1 pt: role is explicitly LLM/RAG/NLP application engineering with \
end-to-end ownership
   - BOOST by 1 pt: small-to-mid company or specialist AI unit where individual \
contributions are visible
   - BOOST by 1 pt: stack explicitly mentions LangChain, LangGraph, RAG, or a \
vector database as a core tool (not just a nice-to-have)
3. Cap at 9. A 9 means near-perfect fit. An 8 means strong realistic fit. \
A 6–7 means worth applying despite some gaps. Below 5 means poor fit.

Respond with valid JSON only. No markdown, no extra text.\
"""


def build_prompt(job: JobListing, profile: UserProfile) -> str:
    """Return the user-turn message for a single job evaluation."""
    strong = ", ".join(profile.skills.strong) or "none listed"
    working = ", ".join(profile.skills.working_knowledge) or "none listed"
    roles = ", ".join(profile.target_roles) or "none listed"

    parts = [
        "## Candidate profile",
        f"Target roles: {roles}",
    ]

    if profile.background:
        parts.append(f"Background: {profile.background.strip()}")

    if profile.ideal_role:
        parts.append(f"Ideal role: {profile.ideal_role.strip()}")

    parts += [
        f"Strong skills: {strong}",
        f"Working knowledge: {working}",
    ]

    if profile.deprioritise:
        penalties = "; ".join(profile.deprioritise)
        parts.append(f"Deprioritise (reduce score): {penalties}")

    parts += [
        "",
        "## Job listing",
        f"Title: {job.title}",
        f"Company: {job.company}",
        f"Location: {job.location}",
        f"Description:\n{job.description}",
    ]

    return "\n".join(parts)
