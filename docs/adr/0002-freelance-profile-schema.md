# ADR 0002 — Freelance `profile.yaml` schema

- **Status:** Accepted
- **Date:** 2026-07-17
- **Wayfinder ticket:** [E — Freelance profile.yaml schema](https://github.com/marcosfsousa/agentic-job-hunter/issues/8)
- **Amended by:** [P — Reconcile ADR 0002 with F](https://github.com/marcosfsousa/agentic-job-hunter/issues/22) (2026-07-18) — `rate:` restated per-unit with no derivation and marked a knowingly-consumer-less exception; remote gate moved from F's hardcode into `dealbreakers.minimum_remote_percentage`; the `deprioritise` "5+ years" entry deleted; Risks 1 and 2 discharged. Amendments are marked inline.
- **Amended by:** [Spec 2 — Freelance profile schema + hard-filter gates](https://github.com/marcosfsousa/agentic-job-hunter/issues/27) (2026-07-22) — the `_passes_location` statement in Boundaries was ambiguous in a way that made `target_countries` dead config under a literal reading; replaced with the resolved predicate and its rationale. The `freelancermap_queries` English-only comment is flagged as disputed and deferred to spec 4. Amended in place, per P's precedent, so the ADR reads correct rather than merged-then-patched.
- **Amended by:** [Spec 3 — freelancermap adapter + fail-loud raw-ingest floor](https://github.com/marcosfsousa/agentic-job-hunter/issues/28) (2026-07-22) — the "DACH-widening of `target_countries`" tuning flag is struck: measurement shows `remoteInPercent` is populated on every freelancermap row, so `_passes_location` never reaches the country check and the flag is a no-op. The field stays (dormant, correct for a future text-only source); only its description as a live knob goes. `freelancermap_queries` is additionally noted as load-bearing for **coverage**, not just targeting.
- **Amended by:** [Spec 4 — e5 embedding swap + freelance ranking query and eval prompt](https://github.com/marcosfsousa/agentic-job-hunter/issues/29) (2026-07-23) — the disputed English-only `freelancermap_queries` comment is adjudicated and struck: N #19 §5 amends the *embedding query*, not the source's own HTTP search terms, so the German terms stay. `background` / `ideal_role` were rewritten positive-only and the "5+ years senior" `deprioritise` entry deleted as this ADR's decision table specified. Amended in place, per P's precedent.
- **Depends on:** [B — Contract data model](https://github.com/marcosfsousa/agentic-job-hunter/issues/5) ([ADR 0001](0001-contract-data-model.md); enums + removed job fields), [D — Hard filter semantics](https://github.com/marcosfsousa/agentic-job-hunter/issues/7) (which predicates read which config), [K — Repoint yield](https://github.com/marcosfsousa/agentic-job-hunter/issues/15) (adapter roster; "supply skews senior")
- **Part of:** [Wayfinder: JobScout FTE → freelance pivot](https://github.com/marcosfsousa/agentic-job-hunter/issues/3)

## Context

JobScout is being repointed from full-time-employment (FTE) listings to freelance/contract
projects — a full **replace**, not a second track. B ([ADR 0001](0001-contract-data-model.md))
decided the target `JobListing` shape (removed job-side `salary_min/max` + the `seniority` field,
added `rate_*` / `contract_type` / `client_type` / remote / duration / start). B and D both left
the **`profile.yaml`** schema — the single source of truth for user preferences — to this ticket.

This ADR decides the profile schema and the corresponding `models.py` (`UserProfile` and its
sub-configs) deltas. It does **not** write production code, migrate the profile file, or change
the hard filter (D) / ranking-eval (F). Those boundaries are recorded at the end.

Grounding principle (CLAUDE.md): *"`profile.yaml` is the single source of truth for all user
preferences. No hardcoded filters anywhere."* And a standing user preference: **prefer config over
hardcoded constants unless there is a very good reason.** Both point the same way on every call
below.

## Decision

### Resulting `profile.yaml` (freelance)

```yaml
# schema unchanged; values rewritten per F (#9) decision 3:
#   name, background, ideal_role, deprioritise, target_roles, skills,
#   dealbreakers.{exclude_companies,exclude_keywords,require_any_keyword},
#   email_min_score
# — `background` / `ideal_role` become positive-only prose, negatives consolidated
#   into `deprioritise`; the `deprioritise` "5+ years senior" entry is DELETED (P #22).
# — `freelancermap_queries` keeps its German terms (ADJUDICATED by spec 4 (#29), not
#   overlooked). N #19 §5's English-only amendment governs the *embedding query*
#   (embedder.py), not the HTTP `query=` terms sent to freelancermap's own search
#   endpoint — which an embedding-model swap has no bearing on. Spec 3 (#28) then made
#   those terms the adapter's sole coverage mechanism, so dropping the German ones would
#   shrink the corpus, not merely retarget it. See #29.

location:
  target_countries: ["Germany", "Deutschland"]   # only surviving location field

rate:                              # replaces the `salary:` block
  minimum_hourly: 50               # Stundensatz floor you'd accept (EUR/hour)
  target_hourly: 70                # hourly negotiation target
  minimum_daily: 450               # Tagessatz floor — STATED, never derived
  target_daily: 600                # daily negotiation target
  currency: "EUR"
  # No hours_per_day, no derived properties, no conversion in either direction.
  # NO PIPELINE CONSUMER — negotiating notes only (see acknowledged exception below).

dealbreakers:
  exclude_companies: []
  exclude_keywords: [...]          # value = tuning
  require_any_keyword: [...]       # value = tuning
  exclude_contract_types: ["employee_leasing", "permanent_position"]
  minimum_remote_percentage: 100   # job pct null → pass (fails open), < 100 → reject

freelancermap_queries:             # replaces jsearch_queries / jobspy_queries / jobspy_sites
  - "Machine Learning"
  - "LLM"
  - "Generative AI"
  - "Maschinelles Lernen"
  - "KI"

# REMOVED entirely: salary:, seniority:, jsearch_queries, jobspy_queries, jobspy_sites,
#                   location.{remote_acceptable, preferred_cities, eu_work_authorization}
```

### `models.py` deltas

| Change | Detail |
|---|---|
| `SalaryConfig` → **`RateConfig`** | Four independently-stated `float \| None` fields — `minimum_hourly`, `target_hourly`, `minimum_daily`, `target_daily` — plus `currency: str = "EUR"`. **No `hours_per_day`, no derived properties, no conversion.** `UserProfile.salary` → `rate`. Amended by P ([#22](https://github.com/marcosfsousa/agentic-job-hunter/issues/22)). |
| **Delete `SeniorityConfig`** | and `UserProfile.seniority`. No freelance analogue; the predicates that read it are gone (D). |
| **`LocationConfig`** trimmed | drop `preferred_cities`, `remote_acceptable`, `eu_work_authorization` (zero consumers in `src/`); keep only `target_countries`. |
| **`DealbreakersConfig`** | add `exclude_contract_types: list[ContractType] = Field(default_factory=list)` — imports B's `ContractType`. Also add `minimum_remote_percentage: int \| None = 100` — read by `_passes_location`, replacing F decision 7's hardcoded `100` (P [#22](https://github.com/marcosfsousa/agentic-job-hunter/issues/22)). |
| **`UserProfile`** | drop `jsearch_queries`, `jobspy_queries`, `jobspy_sites`; add `freelancermap_queries: list[str]`. |
| **All five profile models strict** | `UserProfile`, `RateConfig`, `LocationConfig`, `DealbreakersConfig`, `SkillsConfig` set `extra="forbid"` — an unrecognised key is a load error, not a silent default. Added by spec 2 ([#27](https://github.com/marcosfsousa/agentic-job-hunter/issues/27)). |

⚠️ **The strictness row is an addition by spec 2, not part of this ADR as originally accepted.**
Recorded here because it changes what `profile.yaml` may legally contain, which is this ADR's
subject. The reason is specific rather than stylistic: the two gates above are the first hard
filters wired to config, the tests build `UserProfile` in code, and so a key misspelled *in the
file* falls back to its Pydantic default, changes what gets filtered, and breaks nothing. With
`minimum_remote_percentage` defaulting to `100`, that means the strictest possible remote stance
applied silently.

It also makes the FTE profile cleanup a **hard prerequisite** rather than a tidiness item: a
leftover `salary:` / `seniority:` / `jsearch_queries` block becomes a load error, not an ignored
key.

**Scoped to the profile models only.** `EvaluationResult` and `FeedbackEntry` validate data from
outside the repo — Haiku's JSON and `feedback.yaml` — and stay permissive, so a provider adding a
response field cannot break the pipeline. This is a rule about *our* config file, not about
Pydantic usage in general.

### Answer to B's enum-wiring handoff

The profile references **`ContractType`** only (via `exclude_contract_types`). It deliberately
**does not** reference:
- **`RateUnit`** — the profile states a value *per unit* (hourly and daily both) rather than
  choosing between units, so it needs no unit **discriminator**. `RateUnit` stays a `JobListing`
  concern: the job carries the unit, and any future comparison pairs like against like.
  *(Amended by P [#22](https://github.com/marcosfsousa/agentic-job-hunter/issues/22) — the original
  wording said "rate is hourly-canonical, day rate derived"; the conclusion is unchanged.)*
- **`ClientType`** — the agency-vs-direct lean is deferred (see below).

**Naming note for execution:** ADR 0001 and this ADR both say "enum". `ContractType`, `RateUnit`,
and `ClientType` are `typing.Literal` **type aliases** (the shape already used at `models.py:13-15`
for `RemotePolicy` / `Seniority` / `FeedbackStatus`), not `enum.Enum` classes. Pydantic validates
them identically; do not go looking for an `Enum` class that was never specified.

## Rationale for the harder calls

- **Rate states hourly and daily independently; nothing is derived.** *(This bullet was rewritten
  by P [#22](https://github.com/marcosfsousa/agentic-job-hunter/issues/22); the original chose
  hourly-canonical with a `× hours_per_day` derivation.)*

  The original rationale rested on a premise the map's own later decisions inverted: *"Upwork — the
  one source with real rate data — quotes hourly, so hourly-canonical means zero conversion on the
  source that actually populates rate."* But L ([#16](https://github.com/marcosfsousa/agentic-job-hunter/issues/16))
  deferred Upwork behind a gate that may never fire, K ([#15](https://github.com/marcosfsousa/agentic-job-hunter/issues/15))
  dropped adzuna/jsearch/jobspy, and C ([#6](https://github.com/marcosfsousa/agentic-job-hunter/issues/6))
  adopted no second DACH source. **The only source that builds is freelancermap — DACH — which
  quotes *Tagessätze*.** The canonical unit was chosen to optimise the source that is now
  conditional, against the source that is now the entire corpus.

  Stating both units dissolves the question rather than re-answering it: with no canonical unit
  there is no conversion in either direction, so nothing can point the wrong way. It also retires
  this ADR's own lossy-×8 caveat honestly — a derived `hourly × 8` **fabricates** a Tagessatz
  (which carries bulk premiums the multiplication cannot know), whereas a stated one **records**
  the rate you would actually quote. Divergence between the two numbers is the signal, not a
  consistency bug, which is why no invariant ties them.

- **`rate:` has no consumer at all — an acknowledged exception to the rule below.** D removed
  `_passes_salary` outright, and F ([#9](https://github.com/marcosfsousa/agentic-job-hunter/issues/9))
  decision 5 then declined to build the eval judgement this ADR originally promised the field to
  (*"there is nothing to judge"* — `budget` is `0/22` per M, `0/128` per N). So `rate:` is read by
  no filter, no ranking, and no prompt.

  This is a **deliberate exception** to *"add the field with its consumer, never before it"*, and
  it is recorded as one rather than quietly tolerated. The basis: a rate floor is a negotiating
  position the user holds **independently of this tool**, and `profile.yaml` is defined as the
  single source of truth for user preferences — whereas the deferred leans below (client-type,
  duration, remote-% grading) exist *only* as tool behaviour and so have no meaning without their
  consumer. The two cases are not alike, which is why one earns an exception and the others do not.

  **Revisit trigger** (F's own recorded gap, not a new ticket): M measured only the structured
  `budget` field; nobody has checked whether rates appear in **description prose**, where German
  projects sometimes state them inline. If that measurement finds recoverable signal, a consumer
  becomes ticketable and F decision 5 should be revisited. Until then, building one would design
  against unmeasured data — the failure mode this map's Notes exist to prevent.
- **`SeniorityConfig` removed entirely, not switched off.** `target`/`exclude` were dead the moment
  B deleted `job.seniority`; `max_years_experience` fed the bilingual years-of-experience regex in
  `_passes_experience`, which D removed because DACH freelance ML **skews senior** (K) and a
  `max_years=4` ceiling deletes genuine matches invisibly. B's "capture the field now to avoid a
  second migration" logic (which justified the *widened* `JobListing`) **does not transfer to
  `profile.yaml`** — it is config, not a migrated DB, so re-adding a field later is a one-line edit
  with zero migration cost. Clean removal is the honest full-replace. The experience signal
  survives in `description` for F's LLM eval.
- **`exclude_contract_types` is user config, not a hardcoded predicate.** D explicitly offered the
  alternative of hardcoding "drop leasing + permanent" in the predicate, on the grounds that it is
  a fixed "this is a freelance tool" decision rather than a per-user preference. **Rejected** on
  two independent grounds: CLAUDE.md's "no hardcoded filters anywhere / `profile.yaml` is the
  single source of truth," and the standing no-hardcode preference. The cost of expressing it as
  config is one typed list; the benefit is that every filter input lives in one auditable place.
- **Blocklist, not allowlist.** `exclude_contract_types: [employee_leasing, permanent_position]`
  lets both `contracting` **and** `unknown` through. An allowlist of `[contracting]` would silently
  drop every `unknown` row the day a second source (Upwork, freelance.de) that emits `unknown` in
  bulk is added — the same fabricated-gate failure mode B/D called out for seniority. It fails
  *open* (an unwanted leasing row slips to eval) rather than *closed* (silently emptying the
  corpus), which is the safe direction. Matches D's `_passes_contract_type` exactly.
- **`freelancermap_queries` is per-source, not a generic `search_queries`.** Mirrors the
  established adapter-config pattern (`new source = new config entry`). DACH-German and Upwork-USD
  phrasing genuinely differ; if Upwork ever clears its deferred gate it adds `upwork_queries` with
  no migration. German terms (`Maschinelles Lernen`, `KI`) are included from the start because the
  source is DACH.
  ⚠️ **Spec 3 (#28) amendment — this list is now load-bearing in a way this ADR did not
  anticipate.** It was specified as per-source *targeting*. Pagination on freelancermap's anonymous
  view was then measured and **refuted**: 22 results per query and nothing reaches result 23, with
  four bare page parameters and the site's own canonical paginator URL all inert. The adapter
  therefore issues one request per entry here and unions the results, which makes this list the
  **sole coverage mechanism** — the only thing standing between the adapter and a 22-row corpus.
  Two consequences: adding a term is how coverage is widened (a value edit, not a code change),
  and the disputed English-only line above now bears on **coverage**, not merely on retargeting.
  Dropping the German terms would shrink the corpus. Spec 4 still owns that call, but should make
  it knowing this.
- **`target_roles` stays structurally unchanged.** It feeds the embedding query (`embedder.py`)
  and the eval prompt (`prompt.py`); its `list[str]` shape survives the pivot untouched. Refreshing
  its *values* toward contract/German phrasing is a `profile.yaml` value = tuning, owned by the
  user (same class as the annotation-shop exclusion list), not a schema decision.

## Deferred — add the field *with* the consumer, never before it

These are **boost-only / weighting** preferences with **no consumer today**. The map rules
preference-weighting logic out of scope (post-handoff tuning). Because `profile.yaml` is config
with zero migration tax, each field is added **together with** the weighting logic (F) that reads
it, so no field ever sits dead:

- **agency-vs-direct lean** (`client_type` boost). Note: freelancermap emits only `agency` /
  `unknown` (M: `endcustomer` → `agency` when present, never `direct`), so this lean is near-inert
  until a second source arrives — reinforcing the defer.
- **short-vs-long duration lean** (`duration_months` boost).
- **remote-% preference boost** (a *grading* field, e.g. `base_location`) on `remote_percentage`.
  F ([#9](https://github.com/marcosfsousa/agentic-job-hunter/issues/9)) decision 6 is the consumer
  this defers to, and **declined**: below 100% is a flat heavy penalty with no gradation, so there
  is nothing for a grading field to grade. The defer therefore becomes permanent-until-preferences-
  change, not pending.

  ⚠️ **The *gate* is a separate field and is no longer deferred — see the profile block above.**
  *(Amended by P [#22](https://github.com/marcosfsousa/agentic-job-hunter/issues/22).)* This bullet
  originally read *"remote is a soft preference, not a hard requirement... no profile knob needed"*
  and rejected a `min_remote_percentage` gate on the grounds that *"it would only add the power to
  reject low-remote German projects, a stronger stance than intended."* **F decision 7 then took
  exactly that stronger stance** (`remote_percentage` present and `< 100` → reject; null → pass),
  voiding the rejection's only stated reason. What remained was not *whether* to hold that power
  but *where it lives* — and F hardcoded `100` into `_passes_location` with no knob.

  P resolves that as **config**: `dealbreakers.minimum_remote_percentage`. Grounds — CLAUDE.md's
  "no hardcoded filters anywhere", the standing no-hardcode preference, and consistency with the
  `exclude_contract_types` call below, which rejected D's identical hardcode offer. H
  ([#12](https://github.com/marcosfsousa/agentic-job-hunter/issues/12)) set the bar for overriding
  those (*"a legal property of the source, not a user preference"*) and a remote-only stance does
  not clear it: it is a preference, and preferences move. Also note F decision 8 refused to
  hardcode a duration lean citing these same grounds — decision 7 was the outlier within F, not a
  competing principle.

## Risks — explicit hand-offs (not solved here)

1. ~~**`freelancermap_queries` is designed against an unverified search interface.**~~
   ✅ **CLOSED by N ([#19](https://github.com/marcosfsousa/agentic-job-hunter/issues/19)) §6.**
   The risk stated it was *"unconfirmed that free-text search exists at all; the real knob may be
   skill-IDs / category."* N pulled the search request against a live payload: **8 distinct
   free-text `query=` values returned 8 distinct result sets across 128 unique projects.** Free-text
   search exists, so `freelancermap_queries: list[str]` is sound **as designed** and the
   skill-ID/category contingency is moot — no adapter-side mapping layer is needed.

   N also measured the corpus at **81% German**, which strengthens rather than weakens the decision
   to seed German query terms from the start. *(Separately, N amends the query **values** to
   English-only once `multilingual-e5-small` lands — a value change, not a schema change.)*
   K's finding that `pagenr` does not paginate the anonymous view is **unaffected** and remains an
   open M/execution build item.
2. **Removing the seniority gate *relocated* the FTE bias into eval scoring; it did not remove it.
   → [F #9](https://github.com/marcosfsousa/agentic-job-hunter/issues/9).** `evaluation/prompt.py`
   still **hardcodes** `"REDUCE by 2 pts: role requires 5+ years of AI/ML-specific experience"`.
   That is code, not tuning, and K's finding is that freelance ML supply *skews senior*. So the
   pipeline stops hard-filtering senior roles (D) and then quietly down-scores the senior-skewed
   corpus in the LLM eval — the bias moves from a visible gate to an invisible penalty. F must
   reconcile the eval prompt's experience penalty with the senior-skewing freelance market. E's
   removal of `SeniorityConfig` is what exposes this; F owns the fix.

   ✅ **DISCHARGED — but only after P ([#22](https://github.com/marcosfsousa/agentic-job-hunter/issues/22))
   closed the second half.** F decision 4 deleted both hardcoded year-count penalties from
   `prompt.py` and replaced them with a graded ramp-up-risk judgement (evidence of having shipped
   *this* deliverable, not year-count). That handled the **code** path. It did not handle the
   **config** path: `profile.yaml`'s `deprioritise` list still carried *"Senior-level role requiring
   5+ years dedicated ML engineering experience"*, and `prompt.py` injects that list verbatim into
   the same Haiku turn under *"Deprioritise (reduce score)"* — so the exact penalty F deleted stayed
   live, on the senior-skewing corpus that was the reason for deleting it. This ADR had flagged the
   entry only as a user-owned tuning value (see below); P ruled that disposition inadequate and
   **deleted the entry**, applying F decision 4's own argument: a penalty that fires on nearly the
   whole pool does not rank it, it shifts the distribution down and compresses the top.

*(The former caveat about `hourly × 8` being lossy against real DACH day rates is **moot** — P
removed the derivation entirely; the daily figures are now stated directly. See the rate rationale.)*

## Tuning-value flags (user-owned, not locked by this ADR)

Handed down by D and surfaced here so they aren't lost; all are `profile.yaml` *values*, not schema:

- **German-adequacy of keyword lists** — `require_any_keyword` / `exclude_keywords` English phrases
  (e.g. "machine learning") will not fire on German text ("maschinelles Lernen"); add German terms
  and/or lean on the acronyms (ML/AI/NLP/LLM/RAG), which fire cross-language.
- ~~**DACH-widening of `target_countries`** — currently `["Germany", "Deutschland"]`; onsite projects
  in Austria/Switzerland are dropped though the user is EU-authorized and the sources are DACH.~~
  — ⚠️ **currently a no-op, and should stop being described as a live knob.** Spec 3
  ([#28](https://github.com/marcosfsousa/agentic-job-hunter/issues/28)) measured
  `remoteInPercent` populated on **22/22** search rows and, at pool level, **115/115** German
  projects bucketed by the payload's own aggregation. `_passes_location` reaches
  `target_countries` **only** on rows whose percentage is unknown, of which freelancermap has
  none — so every row takes the `pct >= floor` path and widening this list changes nothing.
  It is **dormant, not dead**: it is the correct behaviour for a future text-only source, which
  is why it is not being removed. Re-read this flag as live the day a second source lands.

  **There is a second, stronger reason**, and it survives even if the first stops holding: the
  adapter pins `countries[0]=1` (Germany) as a **server-side** filter on every request, to keep
  fetch volume down per G (#11)'s no-overload constraint. Non-DE rows are therefore never
  fetched at all, so widening `target_countries` to Austria or Switzerland could not work on
  freelancermap even if every row's `remoteInPercent` were null tomorrow. Actually widening to
  DACH is an **adapter** change (drop or extend that parameter) *and* a `profile.yaml` change —
  not the value edit this flag implied.
- **Annotation-shop exclusions** — add Mercor / Surge / Outlier / Scale to `exclude_companies`
  (they title labelling piecework as "AI Engineer" and will rank well while being wrong).
- **`target_roles` refresh** toward contract/German phrasing.
- ~~the `deprioritise` "5+ years senior" entry, which fights K's "supply skews senior" finding~~
  — **no longer a tuning flag.** P ([#22](https://github.com/marcosfsousa/agentic-job-hunter/issues/22))
  **decided its deletion**; it is a build item, not a value the user may leave as-is. Classing it as
  user-owned tuning is what let F decision 4's fix be applied to `prompt.py` and not to the config
  path feeding the same prompt. The rest of `deprioritise` is still refreshed per F decision 3
  (negatives consolidated in from `background` / `ideal_role`).
- ⚠️ **`email_min_score` is FTE-calibrated and its rubric moved underneath it** — flagged here,
  **deliberately not given a number**. F rewrote the rubric in *both* directions (deleted the 2–4yr,
  5+yr and €80k penalties; added a ramp-up-risk judgement and a flat hybrid penalty), so nobody
  knows which way the score distribution shifted on net, and any value chosen now would read as
  calibrated when it is a guess. **Revalidate it during F/N's "validate the rewritten prompt and
  profile prose together against ≥5 real listings" check.** Note it has **two** consumers: the
  digest gate (`run.py:199`) and, via `config.py:63`, the default re-evaluation floor
  (`reeval_below`) — so retuning the digest silently retunes re-evaluation volume. Raised by P
  ([#22](https://github.com/marcosfsousa/agentic-job-hunter/issues/22)).
  — ✅ **Settled 2026-07-31: `email_min_score: 5`.** Both halves of the flag above have since
  expired, in opposite ways. The **coupling is gone** — [#45](https://github.com/marcosfsousa/agentic-job-hunter/issues/45)
  gave `reeval_below` a standalone `DEFAULT_REEVAL_BELOW` in `config.py`, so the digest gate no
  longer has two consumers and retuning it no longer moves re-evaluation volume; the sentence above
  describing that coupling is history, not current behaviour. And the distribution is **no longer
  unknown**: the runs recorded in `docs/build-log.md` for #63 and #65 measure it directly, with the
  4-band carrying the bulk both times, so 5 is now a read off the data rather than the guess this
  entry refused to make. It is also the value the FTE era used before it was lowered as a temporary
  measure. Deciding it, not the number itself, is what was deferred here.

## Boundaries (recorded, not decided here)

- **Hard-filter predicates** → decided by D ([#7](https://github.com/marcosfsousa/agentic-job-hunter/issues/7)),
  since **amended twice on `_passes_location`**. E's schema is consistent with D's `_passes_all`
  (seniority/experience/salary removed, `_passes_contract_type` blocklist added). The current
  `_passes_location` is:

  ```python
  pct = job.remote_percentage
  floor = profile.dealbreakers.minimum_remote_percentage

  if pct is not None and floor is not None:
      # meets the floor -> country-blind pass; below it -> reject
      return pct >= floor

  # percentage unknown (or gate disabled): the REMOTE axis fails open,
  # but a text-only source that says "remote" is still exempt
  if job.remote_policy == "remote":
      return True

  # ...and the LOCATION axis still applies
  return any(c.lower() in job.location.lower()
             for c in profile.location.target_countries)
  ```

  *(D reshaped it; F decision 7 added the fail-open gate, which is why this ADR's earlier
  description of it "keeping German-located hybrid/onsite ones" was stale; P
  ([#22](https://github.com/marcosfsousa/agentic-job-hunter/issues/22)) moved the threshold out of
  the predicate into config.)* The `>= 100` / `<= 0` cut points were confirmed final by F decision 6
  and stay in `JobListing.remote_policy`; this predicate reads the property rather than re-deriving
  the boundary.

  ⚠️ **Amended by spec 2 ([#27](https://github.com/marcosfsousa/agentic-job-hunter/issues/27)) —
  the prose this replaces was ambiguous and had to be resolved to build it.** It read
  *"`remote_percentage` null → pass (fails open …); otherwise `location` must match a target
  country"*. Taken literally — null passes unconditionally — the `otherwise` branch is unreachable
  and `target_countries` becomes dead config, contradicting this same ADR keeping it as *"the only
  surviving location field"* and D handing down DACH-widening as a live tuning flag.

  **The correct reading is that "fails open" is scoped to the *remote axis*:** an unknown
  percentage means the row is not rejected *for being insufficiently remote*, and it still faces
  the country check. `target_countries` stays live and does its work on exactly the
  unknown-percentage rows. This is not a cosmetic distinction — freelancermap's `remoteInPercent`
  populated-rate is still unmeasured (F's build-time deferral, now spec 3's), so if most rows carry
  no percentage the literal reading would mean no location filtering at all. The predicate is
  correct either way that measurement lands.

  The pinning test is **null percentage + non-matching country → reject**
  (`TestPassesLocationWhenPercentageIsUnknown::test_non_matching_country_is_rejected`). Both
  readings are indistinguishable without it.
- **Ranking query + eval prompt** (including the rate-adequacy and experience-fit judgements this
  schema feeds, and Risk 2) → F ([#9](https://github.com/marcosfsousa/agentic-job-hunter/issues/9)).
- **Profile-file migration + `models.py` code edits** → execution. This ADR is the build list; no
  production code is written here.

## Consequences

- One money concept in the profile (`rate`), stated per unit with no conversion; **two**
  deterministic hard-filter gates wired to config (`exclude_contract_types`,
  `minimum_remote_percentage`); and a per-source query list — every mandated E preference is
  expressible.
- **One field is knowingly dead: `rate:` has no pipeline consumer.** *(Corrected by P
  ([#22](https://github.com/marcosfsousa/agentic-job-hunter/issues/22)) — this bullet previously
  claimed "no dead/speculative field is introduced", which F decision 5 falsified by declining to
  build the judgement the field was justified by.)* It is retained as an **acknowledged exception**
  on the reasoning given in the rate rationale, not by oversight. The deferred leans (client-type,
  duration, remote-% grading) remain genuinely absent, so the rule holds everywhere it was applied.
- `UserProfile` loses three sub-config concepts (`SalaryConfig`, `SeniorityConfig`, and the jobspy
  query/site config) and gains `RateConfig` + `freelancermap_queries` + two `DealbreakersConfig`
  fields — a net simplification.
- **Both original risks are now discharged**, not carried: the freelancermap search interface was
  confirmed by N ([#19](https://github.com/marcosfsousa/agentic-job-hunter/issues/19)), and the
  relocated experience bias was closed by F decision 4 plus P's deletion of the `deprioritise`
  entry that kept it alive through config.
- **Two items ride F/N's "≥5 real listings" validation** rather than being decided here:
  ~~`email_min_score` recalibration (with its `reeval_below` coupling)~~ — **settled 2026-07-31 at 5**,
  see the annotation on the flag above; the `reeval_below` half of it was dissolved separately by
  [#45](https://github.com/marcosfsousa/agentic-job-hunter/issues/45) — and the description-prose rate
  measurement that would reopen F decision 5 and give `rate:` a consumer, which **remains open**.
