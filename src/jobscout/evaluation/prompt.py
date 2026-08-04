from __future__ import annotations

import re

from jobscout.models import JobListing, UserProfile

# The rubric's own bounds on the final score: step 3 below says "Cap at 9", and
# anything under 1 is off the scale `match_score` is declared on. They live here, next
# to the rubric that states them, and are interpolated into the trace spec rather than
# written into it — `check_score_trace` imports the same two names to clamp against.
# Stated in prose in one file and re-typed in the other, a moved cap would have the
# model bounding at one number while Python clamps at another, and the check would
# then flag correct rows. That is the same drift `RULE_IDS` below exists to prevent.
SCORE_FLOOR = 1
SCORE_CAP = 9

# The rubric. Every boost and penalty carries a `[rule_id]` tag, which is the only
# structure added: `RULE_IDS` below is read back out of these tags, so the id list the
# model is handed in the trace section cannot drift from the rules themselves. That is
# as far as #95 goes deliberately — decomposing this into per-rule objects is a much
# larger change and is explicitly out of its scope.
_RUBRIC = """\
You are a calibrated job-fit evaluator. Given a candidate profile and a job listing, \
return a JSON object with exactly these fields, IN THIS ORDER:
- score_trace: the arithmetic you scored by — specified under "Score trace" below. \
Emit it FIRST, before match_score, and read match_score off its total.
- match_score: integer 1–10 (10 = near-perfect fit; 7+ means worth applying; \
below 5 means poor fit)
- matching_skills: list of strings — skills from the candidate's profile that this \
specific job particularly values or emphasises. Prefer distinctive skills \
(e.g. RAG systems, LangChain, domain-specific frameworks) over generic ones \
(e.g. Docker, SQL). When both strong and working-knowledge skills match, \
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
   - [boost_llm_ownership] BOOST by 1 pt: role is explicitly LLM/RAG/NLP application engineering with \
end-to-end ownership
   - [boost_visible_contribution] BOOST by 1 pt: small-to-mid company or specialist AI unit where individual \
contributions are visible
   - [boost_core_stack] BOOST by 1 pt: stack explicitly mentions LangChain, LangGraph, RAG, or a \
vector database as a core tool (not just a nice-to-have)
   2b. Hard penalties (apply to the boosted score; each applies independently; \
do not double-count):
   - [penalty_degree_mandatory] REDUCE by 2 pts: degree is a hard mandatory requirement with no alternative \
path stated (include in gaps)
   - [penalty_degree_preferred] REDUCE by 1 pt: degree is preferred but "comparable experience" or equivalent \
is explicitly accepted (include in gaps)
   - [penalty_research_focus] REDUCE by 2 pts: role is primarily model research, classical ML \
(forecasting, RecSys, CV), or academic — not LLM application building
   - [penalty_german_language] REDUCE by 0–2 pts for a GERMAN-LANGUAGE REQUIREMENT (graded — the candidate is \
B2, so the size of the penalty follows how firmly the listing states the requirement; \
name it in gaps whenever it fires):
       2 pts — the listing DELIBERATELY STATES a German-language requirement at CEFR \
C1 or above: explicit "C1"/"C2", or phrases implying that band: "verhandlungssicher", \
"fluent"/"business-fluent" German, "sehr gute Deutschkenntnisse", or \
"native"/"Muttersprachler";
       1 pt — the listing DECLARES German as a language the work is conducted in but \
states no level: "Projektsprache: Deutsch", "Arbeitssprache Deutsch", "the project runs \
in German". A declared working language is a deliberate operational statement, so it is \
not free — but it names no level, so it does not earn the full penalty. German declared \
ALONGSIDE another language ("Projektsprache: Deutsch und Englisch") fires this band too — \
the band asks whether German is A declared working language, not THE only one;
       0 pts — everything else. Do NOT fire on: a German job location, a German company \
name, a posting written in German, German listed as "nice to have"/"von Vorteil", or \
German stated at B2 or below (including "gute Deutschkenntnisse"). If German is \
mentioned with no level stated and no working language declared, treat it as below the \
bar and do NOT apply this penalty.
     The bands are exclusive — a listing that states C1+ scores 2, never 2 plus 1. \
PRECEDENCE — when a firing cue from EITHER band and an optional qualifier describe the \
SAME requirement (e.g. "verhandlungssicheres Deutsch von Vorteil", "fluent German is a \
plus", "Deutsch als Projektsprache von Vorteil"), the optional qualifier WINS and this \
penalty does NOT apply: an optional requirement stays optional at any level. The penalty \
needs a cue AND a non-optional framing. A SECOND declared language is NOT an optional \
qualifier and does not trigger this precedence rule — see the 1-pt band, which fires on \
"Projektsprache: Deutsch und Englisch". \
DISJUNCTION — when German is offered as an ALTERNATIVE to another language, and that \
other language is one the candidate profile lists, German is NOT a requirement and this \
penalty does NOT apply, at any level: the candidate already satisfies the requirement \
with the language they hold ("Englisch (C1) oder Deutsch (C1)", "English or German", \
"Deutsch oder Englisch"). READ THE CONJUNCTION WORD, not merely the presence of two \
languages — this is the exact opposite of the case above: "und" joins two languages \
that are BOTH declared and fires the 1-pt band; "oder" offers a choice between them and \
fires nothing. If German is offered as an alternative to a language the candidate does \
NOT hold, the choice gives them nothing and the bands above apply as written.
   - [penalty_ramp_up_risk] REDUCE by 0–3 pts for RAMP-UP RISK (graded — this is the seniority judgement, \
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
judgement, never a mechanical trigger: grade against the shipped-deliverable evidence \
in the candidate profile above — its Background and Strong skills are the record — and \
not against whether a year-count is met. Name the missing deliverable in gaps when this \
fires.
   - [penalty_mlops_core] REDUCE by 1 pt: MLOps, Kubernetes, or cloud infrastructure are core \
requirements, not secondary
   - [penalty_cloud_core] REDUCE by 1 pt: role requires strong or extensive cloud platform experience \
(AWS, GCP, or Azure) as a core competency (include in gaps)
   - [penalty_non_tech_company] REDUCE by 1 pt: AI role embedded in a non-tech company with no apparent \
specialist AI unit or team
   - [penalty_remote] REDUCE by 3 pts: the role is not fully remote — any onsite or hybrid presence is \
required (include in gaps). Flat and categorical: apply the full penalty for any \
sub-100%-remote signal in the prose, with no gradation by how much on-site time.
3. Cap at 9. A 9 means near-perfect fit. An 8 means strong realistic fit. \
A 6–7 means worth applying despite some gaps. Below 5 means poor fit.
"""

# Every `[rule_id]` tag in the rubric above, in the order the rubric applies them. The
# model is handed this list rather than a hand-written copy so a rule added, renamed or
# removed above cannot leave the trace spec naming the old set.
#
# Deliberately not de-duplicated: a repeated tag means two rules share an id, so one of
# them is untraceable and the trace has an ambiguous entry. Collapsing that silently
# would hide it — and would also make the uniqueness assertion in the tests
# tautological, which is coverage that reads as a guard and is not one.
RULE_IDS: tuple[str, ...] = tuple(re.findall(r"\[([a-z][a-z0-9_]*)\]", _RUBRIC))

# The trace request. Kept in its own literal purely so RULE_IDS can be interpolated —
# the rubric above is unchanged in wording and magnitude, which #95 requires (rewording
# a rule is C1/C2/C3's job, not this one's).
_TRACE_SPEC = f"""
Score trace — this is how your score is checked, so it must reconcile:
- "start": the integer you chose in step 1.
- "adjustments": one entry for EVERY rule id listed here, in this order, whether or \
not the rule fired: {", ".join(RULE_IDS)}.
  Each entry is an object: {{"rule_id": <the id>, "fired": <true|false>, \
"delta": <integer>, "evidence": <string or null>}}.
- "delta" is SIGNED: positive for a BOOST, negative for a REDUCE, 0 when the rule did \
not fire. A graded rule that lands on its 0-point band did NOT fire — report \
"fired": false and "delta": 0. Never report "fired": true with "delta": 0.
- Every entry with "fired": true MUST carry non-empty "evidence": a short quote or \
close paraphrase from the listing that made the rule fire. Entries with \
"fired": false carry "evidence": null.
- "total": start plus every "delta", added up. Write it as ONE integer that you have \
already worked out — never as an expression like 6 + 1 - 2, which is not valid JSON.
- match_score is "total" bounded into {SCORE_FLOOR}–{SCORE_CAP}: below {SCORE_FLOOR} \
report {SCORE_FLOOR}, above {SCORE_CAP} report {SCORE_CAP} (the \
step 3 cap), otherwise report "total" itself. Write score_trace FIRST, then read \
match_score off it. Do not decide a score and then write a trace beside it — if the \
total looks too low or too high to you, the rule to revisit is one of the deltas \
above, not the total.

A well-formed trace looks like this — note the field names, and that "fired" is a \
boolean while "delta" is the number:
  "score_trace": {{"start": 6, "adjustments": [
    {{"rule_id": "boost_core_stack", "fired": true, "delta": 1, \
"evidence": "LangGraph named as a core tool"}},
    {{"rule_id": "penalty_remote", "fired": false, "delta": 0, "evidence": null}}
  ], "total": 7}}

Respond with valid JSON only. No markdown, no extra text.\
"""

SYSTEM_PROMPT = _RUBRIC + _TRACE_SPEC


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
