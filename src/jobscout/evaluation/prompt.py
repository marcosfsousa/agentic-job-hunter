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
prefer skills from the strong list. Only include a skill the job explicitly calls for — no padding. Return at most 5. \
- gaps: list of strings — skills or requirements the job needs that the profile lacks
- explanation: one or two sentences summarising the fit and calling out any \
score-affecting factors

Scoring — use this process:
1. Start at 6 if the role has reasonable skill overlap with the candidate profile \
(mentions LLMs, AI applications, or related tools). Start at 4 if overlap is weak \
or the role is tangentially related. Start at 2 if it is a poor fit on its face.
2. Apply adjustments in two strict phases — boosts first, penalties second. \
Penalties are applied to the boosted score; boosts do not offset penalties.
   2a. Boosts (apply first):
   - BOOST by 1 pt: role is explicitly LLM/RAG/NLP application engineering with \
end-to-end ownership
   - BOOST by 1 pt: small-to-mid company or specialist AI unit where individual \
contributions are visible
   - BOOST by 1 pt: stack explicitly mentions LangChain, LangGraph, RAG, or a \
vector database as a core tool (not just a nice-to-have)
   2b. Hard penalties (apply to the boosted score; each applies independently; \
do not double-count):
   - REDUCE by 2 pts: degree is a hard mandatory requirement with no alternative \
path stated (include in gaps)
   - REDUCE by 1 pt: degree is preferred but "comparable experience" or equivalent \
is explicitly accepted (include in gaps)
   - REDUCE by 2 pts: role is primarily model research, classical ML \
(forecasting, RecSys, CV), or academic — not LLM application building
   - REDUCE by 1–2 pts for a GERMAN-LANGUAGE REQUIREMENT (graded — the candidate is \
B2, so the size of the penalty follows how firmly the listing states the requirement; \
name it in gaps whenever it fires):
       2 pts — the listing DELIBERATELY STATES a German-language requirement at CEFR \
C1 or above: explicit "C1"/"C2", or phrases implying that band: "verhandlungssicher", \
"fluent"/"business-fluent" German, "sehr gute Deutschkenntnisse", or \
"native"/"Muttersprachler";
       1 pt — the listing DECLARES German as the language the work is conducted in but \
states no level: "Projektsprache: Deutsch", "Arbeitssprache Deutsch", "the project runs \
in German". A declared working language is a deliberate operational statement, so it is \
not free — but it names no level, so it does not earn the full penalty;
       0 pts — everything else. Do NOT fire on: a German job location, a German company \
name, a posting written in German, German listed as "nice to have"/"von Vorteil", or \
German stated at B2 or below (including "gute Deutschkenntnisse"). If German is \
mentioned with no level stated and no working language declared, treat it as below the \
bar and do NOT apply this penalty.
     The bands are exclusive — a listing that states C1+ scores 2, never 2 plus 1. \
PRECEDENCE — when a firing cue from EITHER band and an optional qualifier describe the \
SAME requirement (e.g. "verhandlungssicheres Deutsch von Vorteil", "fluent German is a \
plus", "Projektsprache Deutsch, Englisch ebenfalls möglich"), the optional qualifier \
WINS and this penalty does NOT apply: an optional requirement stays optional at any \
level. The penalty needs a cue AND a non-optional framing.
   - REDUCE by 0–3 pts for RAMP-UP RISK (graded — this is the seniority judgement, \
made on deliverable evidence rather than a year-count). Ask: could the candidate \
ship THIS project's core deliverable with no onboarding? Weigh what the profile \
shows the candidate has actually built and shipped against what the project needs \
delivered, and grade the gap:
       0 pts — the profile shows evidence of having shipped this project's core \
deliverable (e.g. the project needs a production RAG pipeline and the candidate has \
built RAG pipelines end to end);
       1 pt — adjacent evidence with a modest gap the candidate could close on the job;
       2 pts — the deliverable sits in the candidate's area but the profile shows no \
evidence of shipping it at this scope;
       3 pts — the deliverable requires owning something the profile shows no evidence \
of (e.g. an owned end-to-end ML platform, or heavy production MLOps).
     Treat any stated years-of-experience requirement as a WEAK input to this \
judgement, never a mechanical trigger: the candidate has 3 months hands-on AI \
engineering on top of 2.5 years professional software engineering, and the question \
is deliverable-fit, not whether a year-count is met. Name the missing deliverable in \
gaps when this fires.
   - REDUCE by 1 pt: MLOps, Kubernetes, or cloud infrastructure are core \
requirements, not secondary
   - REDUCE by 1 pt: role requires strong or extensive cloud platform experience \
(AWS, GCP, or Azure) as a core competency (include in gaps)
   - REDUCE by 1 pt: AI role embedded in a non-tech company with no apparent \
specialist AI unit or team
   - REDUCE by 3 pts: the role is not fully remote — any onsite or hybrid presence is \
required (include in gaps). Flat and categorical: apply the full penalty for any \
sub-100%-remote signal in the prose, with no gradation by how much on-site time.
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
