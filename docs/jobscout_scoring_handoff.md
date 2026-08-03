# JobScout — Scoring Pipeline Defects: Handoff & Issue Breakdown

**Date:** 2026-08-03
**Source of findings:** 46 postings read and hand-scored between 21 Jul and 3 Aug 2026, compared against JobScout's own digest output.
**Audience:** the coding agent working in the repo.

---

## 0. Division of knowledge — read this first

This document was written **without access to the repository.** The findings come from
comparing JobScout's outputs against the postings themselves and against hand-assigned
scores. That means:

- **What this side knows:** which outputs were wrong, in which direction, and why —
  grounded in the actual posting text.
- **What this side does NOT know:** the code. Every statement below about *where* a
  defect lives is an **inference from behaviour**, not an observation of implementation.

Two recommendations have already been made and withdrawn because the config already
contained them (role-shape penalties and the framing-paragraph rule both exist in
`profile.yaml`, unweighted). **Assume more of that.**

### Verify-first protocol — mandatory for every issue

Each issue below has a **VERIFY** block. Do not implement before answering it.
If verification refutes the claim, **stop and report back** rather than implementing
something adjacent. A refuted claim is a useful result, not a failure.

The behavioural evidence is reliable. The diagnosis is not.

---

## 1. Confirmed behavioural defects

Each is reproducible against a specific posting. These are observations, not theories.

| # | Observed behaviour | Posting | Tool | Human |
|---|---|---|---|---|
| D1 | Three of four stated `gaps` were false — skills present in the CV reported as absent | #3004625 | 6 | 6.5 |
| D2 | Platform-ownership language identified in prose, then not penalised | #3018325 | 7 | 4 |
| D3 | 1-week mandatory onsite identified in prose, called "a minor friction", no penalty | #3025628 | 6 | 3 |
| D4 | German inferred from location, then relabelled "declared" and penalised | #3028920 | 5 | 6 |
| D5 | `"Englisch (C1) oder Deutsch (C1)"` scored as a German requirement | #3018325 | 7 | 4 |
| D6 | Multiple hard blockers produced the same score as one soft mismatch | #3003311, #3027041 | 5, 5 | ~1.5, ~1 |

**Pattern across D2, D3, D4:** the model *comprehended* correctly and then failed to
*apply* the rule. These are adherence/bookkeeping failures, not comprehension failures.
That matters for the fix: a better-worded rule will not help.

---

## 2. Wave A — Instrumentation (blocks everything else)

Nothing in Wave B or C can be validated until Wave A lands. Do these first.

### A1 — Emit and verify the score arithmetic
**Size:** M (~3h) · **Depends on:** nothing · **Keystone issue**

Add a `score_trace` field to the evaluator's JSON output:

```json
"score_trace": {
  "start": 6,
  "adjustments": [
    {"rule_id": "boost_core_stack", "fired": true,  "delta": 1,  "evidence": "LangGraph named as core"},
    {"rule_id": "penalty_remote",   "fired": false, "delta": 0,  "evidence": null}
  ]
}
```

Then, **in Python, not in the prompt**:
- assert `start + Σdelta == match_score`
- assert every `fired: true` carries non-empty `evidence`
- on failure: log loudly, keep the row, flag it

**Why this is the keystone:** D2, D3 and D4 were invisible for twelve days and were
found by hand-reading. With a trace, D3 surfaces immediately as
`{"rule_id": "penalty_remote", "fired": true, "delta": 0}` → assertion error.
**Non-adherence becomes a test failure instead of silent drift.**

This also delivers most of what a larger model would buy, by forcing the arithmetic to
be explicit rather than implicit.

**VERIFY:** Does the evaluator already return structured output beyond the four
documented fields? Is there existing response validation to extend rather than
duplicate? Do `rule_id` values need to be enumerated in the prompt, or can the model
be given the list from a single source shared with the rubric?

**Done when:** a full daily run completes with the assertion active, and any arithmetic
mismatch is visible in the run log with the posting ID.

---

### A2 — Regression fixture set from hand-scored postings
**Size:** M (~3h) · **Depends on:** nothing (can run parallel to A1)

Build `tests/fixtures/scored_postings/` from the labelled cases in §6. Each fixture:
posting text, human score, **and the specific rule it exercises**.

Assert on **band, not exact score** (`hard_skip ≤4.5`, `marginal 5–6.5`, `apply ≥7`) —
exact-match assertions will be brittle and will get disabled.

**Why band-level:** the goal is catching a 1 scored as a 5, not arguing 6 vs 6.5.

**VERIFY:** Is there an existing eval or golden-file harness? Does the project already
depend on LangSmith anywhere, or would that be a new dependency? (A plain pytest
harness is acceptable and probably preferable for CI.)

**Done when:** `pytest` runs the fixture set offline, current failures are recorded as
a baseline rather than fixed, and the suite runs in CI.

---

### ~~A3 — Fix the stale experience string~~ — **REFUTED 2026-08-03. No issue filed.**

> **The defect does not exist.** The string was removed from **both** places on
> 2026-07-31, three days before this handoff was written: from `profile.yaml:background`
> by #88, and from `prompt.py`'s ramp-up clause by **#89, commit `16ddefb`**, whose
> message names it exactly — *"the ramp-up clause hardcoded '3 months hands-on AI
> engineering on top of 2.5 years', the exact claim #88 removed from
> profile.yaml:background. Prompt and profile were disagreeing inside a single request."*
>
> **What the code actually does.** The ramp-up clause (`prompt.py:66-83`) grades on
> shipped-deliverable evidence read from the profile text the request already carries,
> and explicitly demotes any stated years-of-experience requirement to *"a WEAK input to
> this judgement, never a mechanical trigger"*. The year-count is expressible in neither
> place — which is precisely the "no longer expressible in two places" outcome A3 asked
> for.
>
> **Why this was inferred.** The comment A3 cites has been inverted since it was read:
> `profile.yaml:21-29` now reads `CLOSED (2026-07-31, #89)`. The handoff was written
> against a pre-2026-07-31 snapshot. The only surviving copies of the string are in
> untracked scratch checkouts under `.claude/worktrees/` and in historical `digests/*.md`
> output, which is a record of past runs and not an input.
>
> **Residual, not actioned:** `profile.yaml:8-12` still opens with "2.5 years software
> engineering and tech lead experience". That is a different claim from the one A3 names,
> it is on the embedding side, and correcting it needs a number only the maintainer can
> supply. Listed as an open decision on #105.

~~**Size:** XS (~10 min) · **Depends on:** nothing · **Do this today**~~

~~The ramp-up clause hardcodes `the candidate has 3 months hands-on AI engineering on top
of 2.5 years professional software engineering`. This is no longer true (Ironhack
Dec 2025–Mar 2026; two systems shipped and running since Mar 2026 — roughly 8 months,
with production deployments). It sits inside the 0–3 point ramp-up penalty, the largest
single deduction in the rubric, so it costs points on every posting evaluated.
`profile.yaml` already carries a comment flagging this as open.~~

---

## 3. Wave B — Correctness fixes (independent, mergeable in any order)

Each is small, each is validated by A1/A2.

### B1 — Ground and cap the `gaps` field
**Size:** S (~1.5h) · **Fixes:** D1

`matching_skills` carries four constraints (distinctive over generic, strong over
working, no padding, max 5). `gaps` carries none. **All the discipline went to the
field that cannot mislead.**

- cap `gaps` at 5
- require each gap to reference the profile line it negates; a gap that cannot be
  grounded is not emitted
- reword output from `"gap"` framing to **"not represented in profile"** — the tool's
  statement is true about the *profile* and gets read as a claim about the *candidate*

**VERIFY:** Is the gap list consumed anywhere downstream (digest rendering, re-ranking,
feedback loop)? A cap may truncate something else's input.

---

### B2 — German clause: disjunction carve-out + de-duplication
**Size:** S (~1h) · **Fixes:** D5, probably D4

Two separate bugs:

1. **Disjunction.** The clause explicitly handles conjunction
   (`"Projektsprache: Deutsch und Englisch"` → 1 pt). It has nothing for **oder**.
   #3018325 offered German C1 *as an alternative to* English C1 — a language the
   candidate holds — and it fired at full band.
   → **Add: German at any level offered as an alternative to a language the candidate
   holds is not a requirement. 0 pts.**

2. ~~**Duplication.** The German rule exists **twice** — banded in `SYSTEM_PROMPT`, and
   again as free text in the user turn via `profile.deprioritise`, in different wording.
   Two phrasings of one rule is a reconciliation task handed to the model.
   **Best hypothesis for D4.** → Delete the `deprioritise` copy. Single authority.~~
   — **REFUTED 2026-08-03. Not in #98's scope.**

   > **What the code actually does.** The duplication is real: the rule reaches the model
   > twice in one request — `SYSTEM_PROMPT` as the `system` parameter (`evaluator.py:105`)
   > and `profile.deprioritise` appended to the user turn (`prompt.py:122-124`). But the
   > two copies are **deliberately synchronised, and the code says so.**
   > `profile.yaml:33-34`: *"Kept lockstep with prompt.py's SYSTEM_PROMPT German clause —
   > both fire bands, all five carve-outs and the precedence rule, not a subset of them
   > (#51, #54)."* Read side by side they carry the same two bands, the same five
   > carve-outs and the same optional-qualifier precedence. This is one rule stated twice,
   > not two phrasings to reconcile.
   >
   > **And it cannot be D4's cause.** D4 (#3028920) is German inferred from location.
   > *Both* copies explicitly carve that out — `prompt.py:53-54` ("Do NOT fire on: a
   > German job location, a German company name, a posting written in German") and
   > `profile.yaml:35` ("German implied only by job location / company name / posting
   > language"). Deleting the duplicate removes text that says the right thing. D4 is an
   > adherence failure against a rule the model was given twice and followed neither
   > time — the § 1 pattern exactly, and it points at A1 (#95), not here.
   >
   > **Safe to know if it is ever deleted anyway:** `deprioritise` is read *only* by
   > `prompt.py:122`. It never reaches the embedder (`_build_profile_text`,
   > `embedder.py:45-63`, reads `target_roles`, `skills.*`, `ideal_role`, `background`),
   > so removing an entry cannot move the ranking vector. Whether to consolidate remains
   > an open maintainer decision on #105 — a maintenance question, not a correctness fix.

**VERIFY:** Confirm the duplication actually reaches the model in both places
(`build_prompt` appends `deprioritise` to the user turn; `SYSTEM_PROMPT` carries the
banded version). If they are already reconciled somewhere, report back.
→ **Answered:** it reaches both places, and they *are* already reconciled. See above.

---

### B3 — ANÜ three-state classifier (deterministic filter stage)
**Size:** M (~3h) · **New capability**

Arbeitnehmerüberlassung is a **hard exclusion until 2027-01-09** (legal: ANÜ requires an
employment relationship with the agency, which conflicts with the funding conditions of
the candidate's current business status). But the current handling is binary and the
real world has more states:

| State | Cues | Action |
|---|---|---|
| **exclusive** | `nur ANÜ` · `ausschließlich ANÜ` / `Arbeitnehmerüberlassung` · `Anstellung beim Personaldienstleister` · `keine Freiberufler` / `Selbstständigen` · `nicht auf Freelance-Basis` · `AÜ zwingend` | **drop**, log reason |
| **optional** | `ANÜ möglich` · `AÜ oder Werkvertrag` · `ANÜ oder Freiberuflich` · `auch ANÜ` · `wahlweise` | **keep**, set flag, surface in digest |
| **unknown** | untagged | keep, no flag (most of the corpus) |

**⚠️ Implementation trap: check `exclusive` first.** `"nur ANÜ möglich"` contains
`"ANÜ möglich"`; an optional-first pass classifies a hard exclude as a soft pass.
**This specific string must be a test case.**

**This belongs in the deterministic filter stage, NOT in `SYSTEM_PROMPT`** — the rubric
already carries ~15 branches the current model cannot execute reliably (see §5).

Mirror the existing two-layer remote design: structured metadata filter
(`exclude_contract_types`) + prose backstop.

**Log every drop with its matched cue** to the daily digest file. A silent drop is
invisible to review, and the screened ledger downstream depends on seeing them.

**VERIFY:** Where does `exclude_contract_types` get evaluated, and against what field?
Is there an existing prose-scanning stage to extend, or is the remote backstop
implemented purely in the prompt? (If the latter, that itself explains D3 — see B4.)

---

### B4 — Remote prose backstop
**Size:** S (~1.5h) · **Fixes:** D3

`minimum_remote_percentage: 100` filters on metadata. The `REDUCE by 3` rule is the
prose backstop for metadata/prose mismatches. **The backstop is the piece that failed.**

#3025628 renders `100% Remote` on the platform card while the body says
*"100% remote **after an initial 1-week onboarding onsite in Greater Frankfurt**"*.
The model read it, wrote "minor friction", and did not subtract.

The design is sound; only enforcement is missing. If A1 lands first, this may need no
prompt change at all — the assertion will catch it. **Check that before editing the rule.**

**VERIFY:** Is the −3 rule reachable at all, i.e. does the metadata filter already drop
these rows before evaluation? If #3025628 reached the evaluator, the metadata filter
passed a row whose prose disqualifies it — confirm which layer saw what.

---

### B5 — `profile.yaml` data corrections
**Size:** S (~1h) · **Data only, no logic**

- **Rate targets updated per maintainer** — `rate.target_hourly` and `rate.minimum_daily`;
  values in `profile.yaml`
  *(the file declares itself the single source of truth for preferences and has drifted
  because nothing consumes it)*
- Add to `skills.strong`: `MLflow`, `EU AI Act Art. 50 / AI compliance implementation`,
  `adversarial and prompt-exposure testing` — all present in the CV, all currently
  invisible to the evaluator, all implicated in D1
- Add `React`, `TypeScript` to `skills.working_knowledge` — **flagged, not decided:**
  they are genuinely held (one production SPA) but adding them raises recall on
  full-stack seats, which are mostly poor fits. **Improves gap accuracy, degrades
  targeting. Ask before doing.**
- **Conflict to resolve:** `exclude_keywords` contains `Empfehlungssystem` and
  `Recommendation Engine` as hard filters, but a recommender-system posting was applied
  to at 6.5 on 31 Jul. It arrived via a source JobScout does not read, so the filter
  never fired — but it would have deleted the row pre-scoring. **One of the two is wrong.
  Ask; do not resolve unilaterally.**

**VERIFY:** Does `skills.strong` feed the embedding query, the LLM prompt, or both?
The answer changes whether adding React is safe.

---

## 4. Wave C — Calibration (requires Wave A complete)

Do not attempt these without the fixture set. They change score distributions, and
without a baseline you cannot tell improvement from movement.

### C1 — Band the unweighted `deprioritise` entries
**Size:** S (~1h) · **Fixes:** D2

`profile.yaml`'s own comment states it: four entries (German, classical ML, MLOps/cloud,
research) have weighted bands in `SYSTEM_PROMPT`; **`ownership` and `framing` exist only
in the YAML, unweighted.**

Those two are exactly the rules that would have caught D2. The model receives the text
with no magnitude and does what models do with an unquantified negative — acknowledges
it and moves on. Its #3018325 summary *named* the platform-operation problem and still
returned 7.

Give both the same banded treatment as the German clause.

**VERIFY:** Confirm from the code which `deprioritise` entries have corresponding bands.
This claim comes from a YAML comment, not from reading `SYSTEM_PROMPT`.

---

### C2 — Anchor step 1 on task verbs, not on mentions
**Size:** M (~2h) · **Higher risk — shifts every score**

Step 1 sets the anchor at 6 if the role *"mentions LLMs, AI applications, or related
tools"*. In this corpus nearly every posting opens with a generic
*"Cloud-first KI-/LLM-Umfeld"* framing paragraph — **so the anchor is set by exactly the
text the framing rule says to discount.** A weightless correction downstream cannot
undo a structural anchor upstream.

Anchor on the responsibilities/task section instead.

**VERIFY:** Is the posting body pre-processed before reaching the evaluator (sections
split, boilerplate stripped)? If a task-section extractor already exists, this is a
much smaller change than it looks.

---

### C3 — Rebalance boosts against penalties
**Size:** M (~2h) · **Highest risk — do last**

Boosts: 3 rules, +1 each, **max +3.** Penalties: **max −15.** Boosts apply first and
explicitly cannot offset penalties. Anchor 6, cap 9.

A 3:15 ratio means three modest penalties floor any posting at 4 regardless of fit.
This is the likely mechanism behind D6 and behind the near-empty 6–8 band.

Two changes, testable independently:
1. narrow the ratio
2. **hard blockers should floor the score, not deduct from it** — with the deliberate
   trade-off that an imperfectly-detected blocker then kills a row instead of docking it.
   Mitigate by flooring only on the narrow, well-specified list (contract form,
   non-Python primary stack, numeric year gates, declared C1) and leaving softer
   conditions as deductions.

**Note:** conservatism already exists in `email_min_score`. Applying it in the
arithmetic *as well* applies it twice and destroys resolution in the band where
decisions are actually made.

**VERIFY:** Re-derive the max-penalty sum from the actual `SYSTEM_PROMPT`; −15 is a
hand count.

---

### C4 — Model selection, decided on evidence
**Size:** M (~2h) · **Depends on:** A1 + A2

The current model is a small fast model. D2/D3/D4 are adherence failures over ~15
conditional branches with a two-phase ordering constraint — the known weak spot of that
class. **But a larger model would also mask C1–C3 rather than fix them, which is why
this issue sits after them.**

Volume is ~20–40 evaluations/day. Across the entire plausible model range the cost
difference is on the order of €10–15/month. **Cost is not a real constraint here and
should not drive the choice.**

Run a bake-off against the A2 fixtures: current model · a mid-tier open model ·
one reasoning-enabled configuration. Pick on measured band accuracy.

**VERIFY:** Where is the model configured, and is it swappable without touching the
evaluation code? Is there existing retry/JSON-repair logic whose behaviour would change?

---

## 5. Wave D — Architectural (optional, propose before building)

**D1 — Split mechanical extraction from judgement.** Extract in code: remote %,
Auslastung, declared language + level, contract form, stated year requirements, start
date, duration. Apply those penalties arithmetically outside the model. Leave the LLM
to judge only role shape, deliverable fit and ramp-up.

This is the project's own stated principle — *deterministic preprocessing so the LLM
stage receives clean input rather than compensating for upstream noise* — applied to the
scoring stage, where it currently is not.

**D2 — `Auslastung` as a scored dimension.** It appears nowhere in the profile or the
rubric, and it was the single factor that decided the most consequential call of the
period (a 20% engagement is additive to the pipeline; the same posting at 100% is a
strategic error). Needs D1's extraction first.

**Do not start Wave D without discussing scope.**

---

## 6. Labelled cases for the A2 fixture set

Band targets, with the rule each case exercises. Cases 1–8 are current failures.

| Posting | Tool | Human | Band | Exercises |
|---|---|---|---|---|
| #3018325 | 7 | 4 | hard_skip | ownership band (C1) + disjunctive language (B2) |
| #3025628 | 6 | 3 | hard_skip | remote prose backstop (B4) |
| #3008147 | 7 | ~3 | hard_skip | two must-have zeros in core deliverable |
| #3003311 | 5 | ~1.5 | hard_skip | multiple stacked blockers → floor (C3) |
| #3027041 | 5 | ~1 | hard_skip | tail behaviour |
| #3004625 | 6 | 6.5 | marginal | false gaps (B1) |
| #3028920 | 5 | 6 | marginal | inferred vs. declared language (B2) |
| #2999393 | 7 | 6.5 | marginal | non-engineering deliverable (Wave D2) |
| `case09` | — | 8 | apply | zero-blocker positive control |
| `case10` | — | 7.5 | apply | direct client, Werkvertrag shape |
| `case11` | — | 7 | apply | thin posting, no language gate |
| #3028352 | — | 6.5 | marginal | strong content vs. structural gate |
| `case13` | — | 6.5 | marginal | sibling-posting comparison |
| #3027789 | — | 6 | marginal | strong AI content, weak profile match |

**Every row has a stable identifier.** Ten cases key on their platform posting ID. Four
carry no such ID and key on a case number instead. That is a different split from the
one the scores show: **six** rows have no tool score, because the tool never saw them,
and two of those six do carry a posting ID. The company each row refers to, and the full
posting text, are in the private evaluation log — extract per fixture rather than in
bulk.

**No key is derived from a posting's identity**, and that is the rule rather than "no
company names" — it holds without a judgement call each time a row is added. It is why
`case13` is a case number despite naming only a city: a location next to a score is
mildly identifying on its own. #96's manifest adopts these same fourteen keys in #111,
which supersedes #115.

The three `apply` rows are the positive controls #96's C3 sufficiency gate depends on.
**Write that gate against `band: apply`, not against the labels** — the band is already
in the manifest and is the queryable form, whereas a label grep matches one row of the
three and passes when it should not.

---

## 7. Sequencing summary

Updated 2026-08-03 with issue numbers. A3 is gone — refuted, see § 2. B3 became two
issues, split on produce vs. surface — see § 10.

```
#106  #107 ─────────────────────────────► filter stage, no blocker, start any time

A1 #95 ──┬──► B1 #97   B2 #98   B4 #99   B5 #100     (independent of each other)
         │
A2 #96 ──┴──► C1 #101 ──► C2 #102 ──► C3 #103 ──► C4 #104
                                                    │
                                                    └──► Wave D (discuss first)
```

**#106 and #107 are not blocked by #95.** Both are filter-stage and deterministic, so
nothing they touch reaches the evaluator and `score_trace` has nothing to assert about
them. This corrects the handoff's own diagram, which put all of Wave B behind A1.

**Merge order matters only within Wave C.** Wave B issues are independent and can be
split across sessions or people.

**#98 and #101 are both `SYSTEM_PROMPT` edits**, and each re-opens CLAUDE.md's ≥5-listing
validation gate. Bundle their validation run, as commit `16ddefb` did for three prompt
edits.

---

## 8. On the private evaluation log

The original section argued against feeding the log to the agent, and made that argument
by describing what the file holds. That description was removed before this document was
committed, this repo being public. What it concluded survives, and is what #96 and its
manifest cite this section for:

- **The log is the source; this handoff is the interface.** It stays out of the repo
  entirely — the same rule `data/jobscout.db` lives under.
- **One narrow exception: fixture extraction (A2 / #96).** Pull posting text and human
  scores per case, as *data*, never in bulk. If an issue's reasoning is unclear, quote
  the one relevant note inline in that issue.
- **The standing rule.** A finding from the log becomes an issue only when it can be
  stated as a reproducible behaviour with a posting ID attached. Everything else stays
  market intelligence. Also carried in CLAUDE.md § "Working a tracked issue".

Section numbering is preserved deliberately — §§ 9 and 10 are cited by number from
issue #105 and from individual issue bodies.

---

## 9. Verification pass — answers from the repository

**Date:** 2026-08-03 · **Ref:** `main` @ `5a95868` · **Scope:** verification only, no
implementation.

> ⚠️ **A snapshot, not a live record — and it is already behind.** A1 (#95) landed after
> this pass, via PR #109, merged to `main` at `2a021aa`. The evaluator and the prompt are
> exactly what it changed, so `file:line` references below — into `evaluator.py` and
> `prompt.py` above all — have moved, and some no longer resolve. **Re-read the file
> before acting on any coordinate here.** The findings stand; the coordinates do not,
> and CLAUDE.md's "read § 9 before writing code" means an agent will meet them cold.

Every VERIFY block below is answered against the code. Line references are to `main` at
the commit above. Nothing in Wave A/B/C was implemented, including A3 — see A3.

The behavioural evidence in §1 was not re-tested and is taken as given. What follows
only checks the *diagnoses*.

### Summary table

| # | Verdict | One line |
|---|---|---|
| A1 | **CONFIRMED**, with two code-grounded constraints the issue must absorb | four fields only, no validation to extend, and a 512-token ceiling the trace will collide with |
| A2 | **CONFIRMED** | no eval harness, no LangSmith; plain pytest is the only option |
| A3 | **REFUTED** | already fixed on 2026-07-31 by #89 (`16ddefb`); nothing to correct |
| B1 | **CONFIRMED** | `gaps` has exactly one consumer (digest rendering); a cap is safe |
| B2.1 | **CONFIRMED** | neither copy of the German rule handles `oder` |
| B2.2 | **PARTLY REFUTED** | it does reach the model twice, but the two copies are deliberately synchronised, not divergent — and both already carve out D4's cause |
| B3 | **CONFIRMED**, one sub-requirement unbuildable as written | no prose-scanning stage exists; the digest cannot carry a drop ledger today |
| B4 | **CONFIRMED** | the metadata filter passed the row correctly; the −3 rule is reachable and is the *only* defence |
| B5 | **CONFIRMED** | `skills.strong` feeds **both** the embedding query and the prompt; `rate` feeds nothing |
| C1 | **CONFIRMED**, and worse than stated | the two unweighted entries are correct — and `ownership` collides with a **+1 boost** |
| C2 | **CONFIRMED** | no section extractor exists; this is the full-size change, not the small one |
| C3 | **CONFIRMED** | −15 re-derived exactly; two further conservatism layers found |
| C4 | **CONFIRMED with a correction** | the model is swappable *within Anthropic only*; the bake-off as described needs a client abstraction |

---

### A1 — Emit and verify the score arithmetic — **CONFIRMED**

*Does the evaluator already return structured output beyond the four documented fields?*
**No.** `EvaluationResult` (`src/jobscout/models.py:105-110`) is exactly
`match_score`, `matching_skills`, `gaps`, `explanation`. It deliberately does **not**
inherit `_StrictProfileModel` (`models.py:129-143` explains why), so Pydantic's default
`extra="ignore"` applies: **a `score_trace` the model returns today is silently
discarded.** The field must be added to the model.

*Is there existing response validation to extend rather than duplicate?* One line —
`EvaluationResult.model_validate(json.loads(raw))` at `evaluator.py:115`. That is all.

**Constraint 1 — where the assertion goes is load-bearing.** That `model_validate` sits
inside a bare `except Exception` (`evaluator.py:96-123`) whose handler returns the job
**unevaluated** (`llm_score=None`), and `format_digest` then filters it out entirely
(`formatter.py:22`). An assertion raised inside that block therefore does the opposite
of A1's "keep the row, flag it" — it **deletes the row from the digest**. The check must
run *after* `_evaluate_one` returns, or in its own try.

**Constraint 2 — the token budget.** `max_tokens=512` (`evaluator.py:104`) carries a
measured history: at 256 the JSON truncated mid-string on ~76% of a live pool (6/25
parseable vs 24/25 at 512). A trace of ~9 adjustments each carrying an `evidence` string
is plausibly another 300–500 tokens. **A1 will re-open that failure mode unless
`max_tokens` rises with it.** This is the single largest unlisted risk in the document.

*Can `rule_id` come from a source shared with the rubric?* **No such source exists.**
`SYSTEM_PROMPT` is one 92-line string literal (`prompt.py:5-97`) with no structure —
no ids, no per-rule objects. Sharing a list means first decomposing the prompt, which is
a real piece of work and is not in A1's 3h estimate.

**Re-size: M → L.** The trace is the easy half; the token headroom and the prompt
decomposition are not.

---

### A2 — Regression fixture set — **CONFIRMED**

*Existing eval or golden-file harness?* **None.** `tests/fixtures/` holds exactly one
file, `freelancermap_search.html`, used by the adapter tests. `tests/test_evaluation.py`
mocks Haiku with `unittest.mock` and asserts plumbing (score propagation, fence
stripping, sort order) — not scoring quality.

*LangSmith?* **Not a dependency.** `pyproject.toml:10-27` lists ten runtime deps and two
dev deps; LangSmith appears nowhere in the repo except as a string inside
`profile.yaml`'s `skills.strong`. Plain pytest is not merely "acceptable" — it is the
only option that does not add a dependency.

**Unlisted design constraint.** `reeval_below=4` (`config.py:23,82`) re-evaluates any job
scoring below 4 and **keeps the higher of the two samples** (`evaluator.py:51-66`). Six
of the eight §6 failure cases target the `hard_skip` band, which sits squarely in that
range — so those fixtures are scored by *max of two draws*, not one. Fixtures must pin
`reeval_below=0` or assert against the documented max-of-two behaviour, or the suite will
flake.

---

### A3 — Fix the stale experience string — **REFUTED. Do not implement.**

The string does not exist in the repository. It was removed from **both** places on
2026-07-31:

- `profile.yaml:background` — by #88.
- `prompt.py`'s ramp-up clause — by **#89, commit `16ddefb`**, whose message names it
  exactly: *"the ramp-up clause hardcoded '3 months hands-on AI engineering on top of
  2.5 years', the exact claim #88 removed from profile.yaml:background. Prompt and
  profile were disagreeing inside a single request."*

The current clause (`prompt.py:66-83`) grades ramp-up on **shipped-deliverable evidence
read from the profile text the request already carries**, and explicitly demotes any
stated year requirement to "a WEAK input to this judgement, never a mechanical trigger"
(`prompt.py:79-83`). The year-count now lives in neither place — which is exactly the
"no longer expressible in two places" outcome A3 asks for.

*Is this string duplicated anywhere else?* Only in stale git worktrees under
`.claude/worktrees/` (untracked scratch checkouts) and in historical `digests/*.md`
output, which is a record of past runs and not an input.

**The comment A3 cites has been inverted since it was read.** `profile.yaml:21-29` now
reads `CLOSED (2026-07-31, #89)`. The handoff was written against a pre-2026-07-31
snapshot.

**Residual, and deliberately not actioned:** `profile.yaml:8-12` still opens with
"2.5 years software engineering and tech lead experience". That is a *different* claim
from the one A3 names, it is on the embedding side, and updating it needs a number only
you can supply. Flagged for B5, not corrected here.

---

### B1 — Ground and cap the `gaps` field — **CONFIRMED**

*Is the gap list consumed anywhere downstream?* **One place only.**
`formatter.py:43,52` joins it into the digest markdown. Nothing else reads it: not
ranking (`scorer.py` / `embedder.py` never see `EvaluationResult`), not the feedback loop
(`db.get_interested_descriptions()` composes from listing text, and `run.py:224` gates
the email on `match_score` alone), not re-ranking.

**A cap truncates nothing but display text.** B1 is safe as specified.

The asymmetry it describes is real and visible in one screen: `matching_skills` carries
four constraints at `prompt.py:10-14`; `gaps` is described in eleven words at
`prompt.py:15`. Both the digest file and the email render the same `format_digest`
output, so the "not represented in profile" rewording lands in both.

---

### B2 — German clause — **B2.1 CONFIRMED · B2.2 PARTLY REFUTED**

**B2.1 (disjunction) — CONFIRMED.** The banded clause (`prompt.py:40-65`) enumerates
five carve-outs, a precedence rule, and one conjunction case
(`"Projektsprache: Deutsch und Englisch"`, `prompt.py:50-52`). **The word "oder" /
"alternative" appears nowhere in either copy.** `"Englisch (C1) oder Deutsch (C1)"` hits
the 2-pt band's literal `"C1"` cue with nothing to stop it. The gap is exactly as
described.

**B2.2 (duplication) — reaches the model twice: CONFIRMED. "Different wording,
reconciliation handed to the model": REFUTED.**

It does reach twice, in one request: `SYSTEM_PROMPT` carries the banded version as the
`system` parameter (`evaluator.py:105`), and `build_prompt` appends
`"Deprioritise (reduce score): ..."` to the user turn (`prompt.py:122-124`), joining all
six `profile.deprioritise` entries — the first of which
(`profile.yaml:35`) is the German rule.

But the two are **deliberately synchronised, and the code says so.** `profile.yaml:33-34`:
*"Kept lockstep with prompt.py's SYSTEM_PROMPT German clause — both fire bands, all five
carve-outs and the precedence rule, not a subset of them (#51, #54)."* Reading them side
by side confirms it: same two bands, same five carve-outs, same optional-qualifier
precedence. This is one rule stated twice, not two rules to reconcile.

**And it is not a plausible cause of D4.** D4 is German inferred from location. *Both*
copies explicitly carve that out — `prompt.py:53-54` ("Do NOT fire on: a German job
location, a German company name, a posting written in German") and `profile.yaml:35`
("German implied only by job location / company name / posting language"). Deleting the
duplicate removes text that says the right thing. D4 is an adherence failure against a
rule the model was given twice and followed neither time — which is precisely §1's own
"comprehended then failed to apply" pattern, and points at A1, not at B2.

*One safety fact for whoever does delete it:* `deprioritise` is read **only** by
`prompt.py:122`. It never reaches the embedder (`_build_profile_text`,
`embedder.py:45-63`, reads `target_roles`, `skills.*`, `ideal_role`, `background`), so
removing an entry cannot move the ranking vector.

---

### B3 — ANÜ three-state classifier — **CONFIRMED, with one sub-requirement unbuildable
as written**

*Where does `exclude_contract_types` get evaluated, and against what field?*
`hard_filter.py:70-78`, against `JobListing.contract_type`, as a blocklist
(`job.contract_type not in profile.dealbreakers.exclude_contract_types`). That field is
set at `freelancermap.py:590` from `projectContractType.type`, mapped 1:1 against the
`ContractType` literals via `_contract_type` (`freelancermap.py:780-793`); anything
unrecognised becomes `unknown`, which **passes** — a documented fail-open.

So the structured half already exists: `profile.yaml:149` excludes `employee_leasing`,
and freelancermap's own tag drops those rows. The binary-handling diagnosis is right.

*Is there an existing prose-scanning stage to extend?* **No.** The hard filter's only
text predicates are `_passes_exclude_keywords` (naive `in` substring,
`hard_filter.py:53-57`) and `_passes_require_keywords` (word-boundary regex,
`hard_filter.py:60-67`), both over `f"{title} {description}"`. There is no cue
extraction, no classification, no per-row reason capture anywhere in the pipeline.
**The remote backstop is implemented purely in the prompt** — which is the parenthetical
the issue anticipated, and it is confirmed. See B4.

**The unbuildable part.** *"Log every drop with its matched cue to the daily digest
file."* The digest is produced by `format_digest(evaluated, run_date)`
(`run.py:220`), which takes `list[ScoredJob]` and renders only rows with a completed
evaluation (`formatter.py:22`). Hard-filter drops happen ~30 lines earlier
(`run.py:193`) and are reported as a single aggregate count
(`hard_filter.py:15`). Carrying per-row drop reasons into the digest means a new
channel through the pipeline — a rejection list threaded from `apply_hard_filter` to
`format_digest`, changing both signatures. That is its own issue, not a bullet in this one.

**Re-size: M (3h) → M for the classifier + a separate S/M for the drop ledger.**

---

### B4 — Remote prose backstop — **CONFIRMED. The −3 rule is reachable, and it is the
only defence.**

*Does the metadata filter already drop these rows before evaluation?* **No — and it was
right not to.** `_passes_location` (`hard_filter.py:81-112`) returns `pct >= floor` when
both are present (`hard_filter.py:94`). With `minimum_remote_percentage: 100`
(`profile.yaml:156`), only `remote_percentage == 100` passes.

`remote_percentage` comes from `projectContractType.remoteInPercent`
(`freelancermap.py:576`) — the same structured field that renders the platform card's
`100% Remote`. #3025628's card said 100, so the field said 100, so the filter passed it.
**The metadata filter saw metadata that was true; the disqualifying fact existed only in
the prose.**

That makes the layering sharper than the issue states: because *only* 100%-metadata rows
survive to evaluation, the `REDUCE by 3` rule (`prompt.py:90-92`) can fire **only** on a
metadata/prose contradiction. It is not a redundant second check — it is the sole
detector for this entire class, and its wording is already maximally blunt ("Flat and
categorical... with no gradation by how much on-site time"). D3 is pure non-adherence
against an unambiguous rule.

**The issue's own hedge is correct.** There is no prompt change available that would help
— the rule cannot be worded more categorically than it is. **Re-size: S (1.5h) → drop as
a standalone issue.** It becomes one A2 fixture plus one A1 trace assertion.

---

### B5 — `profile.yaml` data corrections — **CONFIRMED**

*Does `skills.strong` feed the embedding query, the LLM prompt, or both?* **Both.**
`_build_profile_text` (`embedder.py:45-63`) puts `"Strong skills: ..."` into the query
vector at line 56; `build_prompt` (`prompt.py:118`) puts the same list in the user turn.

**So the React/TypeScript question is a real trade, not a theoretical one.** They would
go to `working_knowledge`, which `embedder.py:57` also embeds — moving the ranking query
toward full-stack seats *and* changing which 25 rows reach the LLM at all. The doc's
framing ("improves gap accuracy, degrades targeting") is exactly right, and the targeting
half acts upstream of the accuracy half. **Correctly flagged for you to decide.**

**The rate corrections are free.** `RateConfig` has **no pipeline consumer** — verified
by grep across `src/`: the only occurrences are the field declarations at
`models.py:166-167`. Both `models.py:158-163` and `profile.yaml:106-111` document this as
deliberate. Changing either rate field cannot affect a single score.

**The `Empfehlungssystem` conflict is real and fires as described.**
`_passes_exclude_keywords` (`hard_filter.py:53-57`) lowercases `title + description` and
rejects on any **substring** match. `"Recommendation Engine"` and `"Empfehlungssystem"`
(`profile.yaml:126-127`) would therefore delete a matching row before scoring — including
one mentioning recommenders only in passing, since it is substring, not word-boundary.
**Correctly escalated; do not resolve unilaterally.**

---

### C1 — Band the unweighted `deprioritise` entries — **CONFIRMED, and the situation is
worse than the YAML comment says**

Read from `SYSTEM_PROMPT` rather than from the comment, as asked. Six entries at
`profile.yaml:32-50`:

| `deprioritise` entry | Band in `SYSTEM_PROMPT`? |
|---|---|
| German C1+ (`:35`) | **Yes** — `prompt.py:40-65`, 0–2 graded |
| recommendation/forecasting/classical ML (`:36`) | **Yes** — `prompt.py:38-39`, −2 |
| MLOps / Kubernetes / cloud infra (`:37`) | **Yes** — `prompt.py:84-85`, −1 |
| model research / academic (`:38`) | **Yes** — same rule as `:36` (`prompt.py:38-39`) |
| **ownership of a platform (`:39-45`)** | **No — nothing** |
| **framing-paragraph-only AI (`:46-50`)** | **No — nothing** |

The comment is accurate. Note the four banded entries map to **three** prompt rules —
`:36` and `:38` share one.

**The additional finding.** `ownership` is not merely unweighted. The word appears in
`SYSTEM_PROMPT` exactly once, and it is a **boost**: *"BOOST by 1 pt: role is explicitly
LLM/RAG/NLP application engineering with end-to-end ownership"* (`prompt.py:26-27`).
The profile's entry deprioritises *"architecture or design authority over a data platform
or AI platform... setting engineering standards for other teams"*, and takes an entire
sentence to distinguish it from the good kind (`profile.yaml:43-45`). A model reading
both in one request sees "ownership" rewarded with a number and "platform ownership"
discouraged with none.

That is a better explanation of D2 than "unquantified negative" alone: #3018325 scoring 7
against an anchor of 6 is consistent with the boost **firing**. C1 must therefore
disambiguate the boost's wording, not only add a penalty band — otherwise the two rules
fight and the one carrying a number wins.

**Re-size: S (1h) → M.** It is now a two-sided edit, and every `SYSTEM_PROMPT` change
re-opens CLAUDE.md's ≥5-listing validation gate (see `16ddefb`'s commit message, which
bundled three prompt edits for exactly that reason — bundle C1 and B2.1 the same way).

**Noted for completeness, not raised as an issue:** the asymmetry runs the other way too.
Five prompt penalties have no `deprioritise` counterpart — degree (×2, `prompt.py:34-37`),
cloud-platform competency (`:86-87`), non-tech-company embedding (`:88-89`), sub-100%
remote (`:90-92`), and ramp-up (`:66-83`). The two files are not intended to mirror each
other, so this is context for whoever edits them, not a defect.

---

### C2 — Anchor step 1 on task verbs — **CONFIRMED**

*Is the posting body pre-processed before reaching the evaluator?* **No. There is no
task-section extractor, and this is the larger change, not the smaller one.**

The only transformation between source and prompt is `_plain_text`
(`freelancermap.py:708-717`), which flattens editor HTML to text and collapses blank-line
runs. Its docstring is explicit that the markup is the target. The result is assigned to
`JobListing.description` (`freelancermap.py:563`) and reaches the model whole at
`prompt.py:132` (`f"Description:\n{job.description}"`). No section split, no
Aufgaben/Anforderungen segmentation, no boilerplate stripping.

The rest of C2's diagnosis holds against the text: the anchor at `prompt.py:20-22` reads
*"Start at 6 if the role has reasonable skill overlap... (mentions LLMs, AI applications,
or related tools)"* — literally a mention test — while the only rule discounting framing
paragraphs is the unweighted `profile.yaml:46-50` entry from C1. **The anchor is set by
the text the framing rule says to discount, and the framing rule carries no number.** C1
and C2 are the same defect at two altitudes; C1's fix is a prerequisite for C2 being
testable.

**Size M (2h) stands only for the prompt-side rewrite.** A real section extractor is a
new deterministic stage (Wave D1 territory) and should not be smuggled in here.

---

### C3 — Rebalance boosts against penalties — **CONFIRMED. −15 is exact.**

Re-derived from `prompt.py:32-92`, penalty by penalty:

| Rule | Line | Max |
|---|---|---|
| degree hard-mandatory | `:34-35` | −2 |
| degree preferred, equivalent accepted | `:36-37` | (−1, mutually exclusive with the above) |
| model research / classical ML / academic | `:38-39` | −2 |
| German-language requirement (graded 0–2) | `:40-65` | −2 |
| ramp-up risk (graded 0–3) | `:66-83` | −3 |
| MLOps / Kubernetes / cloud infra core | `:84-85` | −1 |
| cloud platform competency core | `:86-87` | −1 |
| AI role in non-tech company | `:88-89` | −1 |
| not fully remote | `:90-92` | −3 |
| | **total** | **−15** |

**The hand count is right.** The two degree bands are mutually exclusive by construction
("no alternative path stated" vs "equivalent is explicitly accepted"), so they contribute
2, not 3. Read as stackable the ceiling would be −16; nothing in the prompt forbids it
beyond "do not double-count" (`prompt.py:32-33`), so −15 assumes the intended reading.

Boosts confirmed at **+3** (three ×+1, `prompt.py:25-31`), phase ordering confirmed
(`prompt.py:23-24`, "boosts first, penalties second... boosts do not offset penalties"),
anchor 6 (`:22`), cap 9 (`:93`). **The 3:15 ratio is exactly as stated.**

**Two conservatism layers the issue does not list.** Its note names `email_min_score` as
the existing conservatism; there are three.

1. **No floor exists in the arithmetic, but one is enforced at the boundary.**
   `EvaluationResult.match_score` is `Field(ge=1, le=10)` (`models.py:106`). Anchor 6 +3
   −15 = −6 is not expressible, so the model must silently saturate at 1 — or return the
   real number, fail validation, and have the row **dropped from the digest** by the
   `except` at `evaluator.py:116`. Either way resolution is destroyed at the bottom of
   the range before any human sees it.
2. **Re-evaluation is max-of-two, upward only.** Anything scoring below `reeval_below=4`
   is re-run and the **higher** score kept (`evaluator.py:51-66`). This actively fights
   C3's proposal 2: a hard blocker that correctly floors a row to 1 gets a second draw,
   and one non-adherent sample restores it. **If blockers become a floor, `reeval_below`
   must be reconsidered in the same change** — otherwise the floor is a suggestion.

Everything else in C3 stands. **Keep it last, and keep the note about not applying
conservatism twice — it is now a note about applying it four times.**

---

### C4 — Model selection — **CONFIRMED, with one correction to the bake-off design**

*Where is the model configured?* `AppConfig.llm_model = "claude-haiku-4-5-20251001"`
(`config.py:34`), passed through `run.py:211` into `evaluate_jobs(..., model=...)` and
reaching only `client.messages.create(model=model, ...)` (`evaluator.py:104`).
**No evaluation code reads the model name.** Swapping is a one-line edit.

**Correction: swappable within Anthropic only.** The client is
`anthropic.AsyncAnthropic`, constructed at `run.py:206` and typed in `evaluate_jobs`'s
signature (`evaluator.py:19`). "A mid-tier open model" is therefore **not** a config
change — it needs a second client and a provider seam. Only the Anthropic tiers and a
reasoning-enabled Anthropic configuration are reachable by editing `config.py:34`.
Size the bake-off accordingly, or narrow it to Anthropic tiers.

Also note `llm_model` is **not** environment-overridable, unlike `reeval_below`,
`feedback_weight` and the ingest floor (`config.py:161-170`). A per-run model override for
the bake-off needs adding.

*Existing retry / JSON-repair logic whose behaviour would change?* Three pieces:
1. **Code-fence stripping** (`evaluator.py:112-114`) — added because Haiku fences JSON
   despite instructions. A different model may fence differently, or not at all.
2. **Score-triggered re-evaluation** (`evaluator.py:51-66`) — a second full API call for
   any score below 4, keeping the higher. This **doubles the per-row cost** on the low
   band and is a confound in any bake-off: set `REEVAL_BELOW=0` for the comparison runs.
3. **No error retry at all.** A failed call is logged and the row returned unevaluated
   (`evaluator.py:116-123`).

The `max_tokens=512` finding from A1 applies here too: it was tuned to Haiku's output
length under the current rubric (`evaluator.py:98-103`). A more verbose model may need
more, and a truncation failure looks like a parse failure, not like a model being worse.

---

### What should change in the issue list

Recommendations, for your decision — nothing acted on.

**Drop outright**
- **A3.** Done on 2026-07-31 by #89. Zero work remaining.
- **B4 as a standalone issue.** Verified sound; the rule is reachable, correctly scoped,
  and already worded as categorically as English allows. It survives as one A2 fixture
  (#3025628) and one A1 assertion. Deleting it removes 1.5h that would produce no diff.

**Demote to a question, do not implement**
- **B2.2 (delete the `deprioritise` German copy).** The duplication is real but
  deliberate and synchronised (#51, #54), and both copies already carve out D4's stated
  cause. Deleting it is a maintenance-burden argument, not a correctness fix, and it
  should not be sold as "probably fixes D4". Decide it on its own merits after A1 shows
  whether the rule fires correctly.

**Merge**
- **B2.1 + C1 into one `SYSTEM_PROMPT` edit.** Both are prompt-text changes, and every
  such change re-opens CLAUDE.md's ≥5-listing validation gate. `16ddefb` already
  established the pattern of bundling prompt edits so one before/after run answers all
  of them. Two issues, one branch, one validation run.
- **C1 and C2 are one defect at two altitudes.** The framing entry is unweighted (C1) and
  the anchor is a mention test (C2). Keep them as separate issues — C2 is riskier — but
  sequence them as a pair and validate together.

**Re-size**
- **A1: M (3h) → L.** Three additions the estimate does not cover: the `max_tokens`
  headroom (a 512 ceiling with a measured 76% truncation rate below it), the assertion's
  placement outside the swallowing `except`, and the fact that no shared rule-id source
  exists to draw from.
- **C1: S (1h) → M.** Not "add a band" but "resolve a boost and a penalty that name the
  same concept in opposite directions".
- **B3: M (3h) → M + a separate S/M.** The classifier is correctly sized; the drop
  ledger needs a new channel from `apply_hard_filter` through to `format_digest` and is
  its own change.
- **C4: M (2h) → M, scope narrowed.** Either drop the open-model arm or budget for a
  provider seam; `AsyncAnthropic` is in the function signature.

**Add**
- **`reeval_below`'s max-of-two behaviour is a scoring rule that no issue accounts for.**
  It inflates the bottom of the distribution, confounds A2's band assertions, silently
  undermines C3's proposed blocker-floor, and doubles cost per low-scoring row in a C4
  bake-off. It deserves its own issue, or an explicit paragraph in C3.

**Unchanged and correctly diagnosed:** A2, B1, B5, C2, C3. The behavioural findings in
§1 and the §6 case list need no revision.

---

## 10. Issue register

Filed 2026-08-03 from the verification pass above. Tracking issue: **#105 — JobScout
scoring pipeline defects**, which carries the full task list, the sequencing graph and
the open decisions.

| ID | Issue | Labels | Blocked by |
|---|---|---|---|
| A1 | [#95](https://github.com/marcosfsousa/agentic-job-hunter/issues/95) — Emit and verify score arithmetic | `wave-a` `size-m` | — |
| A2 | [#96](https://github.com/marcosfsousa/agentic-job-hunter/issues/96) — Regression fixture set from hand-scored postings | `wave-a` `size-m` | — |
| A3 | **not filed — REFUTED**, see § 2 | | |
| B1 | [#97](https://github.com/marcosfsousa/agentic-job-hunter/issues/97) — Ground and cap the gaps field | `wave-b` `size-s` | — (#95 landed) |
| B2 | [#98](https://github.com/marcosfsousa/agentic-job-hunter/issues/98) — German clause: disjunction carve-out | `wave-b` `size-s` | — (#95 landed) |
| B3 | [#106](https://github.com/marcosfsousa/agentic-job-hunter/issues/106) — ANÜ exclusive-drop classifier | `wave-b` `size-s` | — |
| B6 | [#107](https://github.com/marcosfsousa/agentic-job-hunter/issues/107) — Drop observability: surface hard-filter drops | `wave-b` `size-m` | — |
| B4 | [#99](https://github.com/marcosfsousa/agentic-job-hunter/issues/99) — Remote prose backstop: fixture and trace assertion | `wave-b` `size-xs` `blocked` | #96 |
| B5 | [#100](https://github.com/marcosfsousa/agentic-job-hunter/issues/100) — `profile.yaml` data corrections | `wave-b` `size-s` | — (#95 landed) |
| C1 | [#101](https://github.com/marcosfsousa/agentic-job-hunter/issues/101) — Band the unweighted `deprioritise` entries | `wave-c` `size-m` `blocked` | #96 |
| C2 | [#102](https://github.com/marcosfsousa/agentic-job-hunter/issues/102) — Anchor step 1 on task verbs, not on mentions | `wave-c` `size-m` `blocked` | #101 |
| C3 | [#103](https://github.com/marcosfsousa/agentic-job-hunter/issues/103) — Rebalance boosts against penalties | `wave-c` `size-m` `blocked` | #102 |
| C4 | [#104](https://github.com/marcosfsousa/agentic-job-hunter/issues/104) — Model selection, decided on evidence | `wave-c` `size-m` `blocked` | #103 |

`size-m` is the largest label in the agreed vocabulary. A1 and C1 were both re-sized
upward during verification (M → L and S → M); their issue bodies say so.

### B3 became two issues — split on produce vs. surface

The diagnosis verified as **CONFIRMED** (§ 9, B3), but the item carried a classifier plus
two changes the classifier does not need. Split by the maintainer on **produce vs.
surface**, deliberately not on classifier vs. plumbing. B6 is a new ID, not in the
original handoff.

**#106 — ANÜ exclusive-drop classifier** (`size-s`). Produces the three-state
classification and acts on `exclusive`. Funding-critical — ANÜ is a hard exclusion until
2027-01-09 — with no digest dependency. Ships first, small and clean. It also builds the
pipeline's **first deterministic prose-scanning stage**: B4 verified that the "two-layer
remote design" B3 was told to mirror is in fact a metadata filter plus a `SYSTEM_PROMPT`
rule, with nothing deterministic in between. Keep it minimal for that reason.

**#107 — Drop observability** (`size-m`). Surfaces drops — *all* of them, not just ANÜ's.
`apply_hard_filter` (`hard_filter.py:11-16`) logs one aggregate count, `_passes_all`
(`:23-35`) short-circuits, and none of the five predicates returns a reason, so a row
dropped for remoteness, contract type or an excluded keyword leaves no trace at all. ANÜ
merely exposed it. Filed as a child of #106 it would read as ANÜ tail-work and get
deferred; it is the more reusable of the two, and it is what makes the
`Empfehlungssystem` conflict below answerable from a real run — that conflict went
unnoticed for weeks precisely because drops leave no trace.

**Audit surface for #107's frozen-dataclass field**, checked before filing: `ScoredJob`
has one production construction site (`ranking/scorer.py:48`), one mutation
(`evaluator.py:132`), and three test sites, all inside helper factories. `JobListing` has
one production site (`freelancermap.py:554`) and exactly one per test file across eight
files, also all factories. A defaulted field costs one production edit and one factory
edit per touched test file — **the audit surface does not size the issue**; the
reason-capture refactor across the five predicates and the `format_digest` signature
change do.

Neither is blocked by #95: both are filter-stage and deterministic, so nothing they touch
reaches the evaluator and `score_trace` has nothing to assert about them.

### Open decisions carried to #105

1. B2's duplication — consolidate, or keep the deliberate lockstep?
2. B5 — `React` / `TypeScript` in `working_knowledge`: improves gap accuracy, degrades
   targeting, and acts upstream via the ranking query.
3. B5 — the `Empfehlungssystem` / `Recommendation Engine` filter conflict. #107 makes it
   decidable from a real run; consider deciding it after #107 lands.
4. `reeval_below`'s max-of-two behaviour — no document ID, so folded into #96, #103 and
   #104 as a constraint rather than filed. Say if it should be its own issue.
5. `profile.yaml:8-12`'s "2.5 years" — needs a number only the maintainer can supply.
6. Wave D — not filed; the handoff says discuss scope first.
