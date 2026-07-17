# ADR 0002 — Freelance `profile.yaml` schema

- **Status:** Accepted
- **Date:** 2026-07-17
- **Wayfinder ticket:** [E — Freelance profile.yaml schema](https://github.com/marcosfsousa/agentic-job-hunter/issues/8)
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
# unchanged: name, background, ideal_role, deprioritise, target_roles,
#            skills, dealbreakers.{exclude_companies,exclude_keywords,require_any_keyword},
#            email_min_score

location:
  target_countries: ["Germany", "Deutschland"]   # only surviving location field

rate:                              # replaces the `salary:` block
  minimum_hourly: 50               # floor you'd accept (EUR/hour)
  target_hourly: 70                # negotiation target
  currency: "EUR"
  hours_per_day: 8                 # derived day rate = hourly × hours_per_day

dealbreakers:
  exclude_companies: []
  exclude_keywords: [...]          # value = tuning
  require_any_keyword: [...]       # value = tuning
  exclude_contract_types: ["employee_leasing", "permanent_position"]

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
| `SalaryConfig` → **`RateConfig`** | `minimum_hourly: float \| None`, `target_hourly: float \| None`, `currency: str = "EUR"`, `hours_per_day: int = 8`; derived `@property minimum_daily` / `target_daily` = `hourly × hours_per_day` (None-guarded). `UserProfile.salary` → `rate`. |
| **Delete `SeniorityConfig`** | and `UserProfile.seniority`. No freelance analogue; the predicates that read it are gone (D). |
| **`LocationConfig`** trimmed | drop `preferred_cities`, `remote_acceptable`, `eu_work_authorization` (zero consumers in `src/`); keep only `target_countries`. |
| **`DealbreakersConfig`** | add `exclude_contract_types: list[ContractType] = Field(default_factory=list)` — imports B's `ContractType` enum. |
| **`UserProfile`** | drop `jsearch_queries`, `jobspy_queries`, `jobspy_sites`; add `freelancermap_queries: list[str]`. |

### Answer to B's enum-wiring handoff

The profile references **`ContractType`** only (via `exclude_contract_types`). It deliberately
**does not** reference:
- **`RateUnit`** — rate is *hourly-canonical* (day rate is derived, not selected), so the profile
  needs no unit discriminator. `RateUnit` stays a `JobListing`-only concern.
- **`ClientType`** — the agency-vs-direct lean is deferred (see below).

## Rationale for the harder calls

- **Rate is hourly min + target, day rate derived ×8.** Chosen over a daily-canonical or
  single-number shape. Upwork — the one source with real rate data — quotes **hourly**, so
  hourly-canonical means zero conversion on the source that actually populates rate; daily-quoting
  DACH sources are the ones needing the ×8 derivation, and they populate rate `0/22`, so the
  conversion almost never fires. `hours_per_day` is **config, not a hardcoded 8**, per the
  standing no-hardcode preference — it keeps the derived day rate transparent and tunable for one
  line. **Rate has no hard-filter consumer:** D removed `_passes_salary` outright (rate is
  `0/22`; a floor would only ever bite deferred/secondary Upwork in USD). `rate.minimum_hourly` is
  consumed **only** by F's eval/ranking judgement (not yet built) — it is a stated preference and
  a rate-adequacy input, never a gate.
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
- **remote-% preference boost** on `remote_percentage`. Remote is a *soft* preference, not a hard
  requirement: `_passes_location` already passes fully-remote jobs country-blind and keeps
  German-located hybrid/onsite ones (D), which is exactly "remote, or onsite/hybrid if it's in
  Germany" — no profile knob needed. A `min_remote_percentage` gate was considered and rejected: it
  would only add the power to *reject low-remote German projects*, a stronger stance than intended.

## Risks — explicit hand-offs (not solved here)

1. **`freelancermap_queries` is designed against an unverified search interface. → execution /
   [M #17](https://github.com/marcosfsousa/agentic-job-hunter/issues/17) build items.** Nobody has
   pulled the freelancermap *search request* — only its response payload (M mapped fields; K found
   `pagenr` does not paginate the anonymous view). It is **unconfirmed that free-text search exists
   at all**; the real knob may be **skill-IDs / category**. A free-text `list[str]` is the right
   *user-facing* abstraction regardless — if the param turns out to be skill-IDs, the
   free-text→skill-ID mapping belongs in the **adapter**, not a profile reshape, so this schema
   stays stable. But the adapter builder must verify the search param before assuming a query
   endpoint exists. This joins M's already-deferred request-param items (pagination), measure
   before designing.
2. **Removing the seniority gate *relocated* the FTE bias into eval scoring; it did not remove it.
   → [F #9](https://github.com/marcosfsousa/agentic-job-hunter/issues/9).** `evaluation/prompt.py`
   still **hardcodes** `"REDUCE by 2 pts: role requires 5+ years of AI/ML-specific experience"`.
   That is code, not tuning, and K's finding is that freelance ML supply *skews senior*. So the
   pipeline stops hard-filtering senior roles (D) and then quietly down-scores the senior-skewed
   corpus in the LLM eval — the bias moves from a visible gate to an invisible penalty. F must
   reconcile the eval prompt's experience penalty with the senior-skewing freelance market. E's
   removal of `SeniorityConfig` is what exposes this; F owns the fix.

A minor, non-blocking caveat (recorded for honesty, not a redesign): **hourly ×8 is lossy against
real DACH day rates** (a *Tagessatz* is not reliably `hourly × 8` — day rates carry bulk
premiums/discounts). Blast radius is negligible: rate is `0/22` on the corpus and never gates.

## Tuning-value flags (user-owned, not locked by this ADR)

Handed down by D and surfaced here so they aren't lost; all are `profile.yaml` *values*, not schema:

- **German-adequacy of keyword lists** — `require_any_keyword` / `exclude_keywords` English phrases
  (e.g. "machine learning") will not fire on German text ("maschinelles Lernen"); add German terms
  and/or lean on the acronyms (ML/AI/NLP/LLM/RAG), which fire cross-language.
- **DACH-widening of `target_countries`** — currently `["Germany", "Deutschland"]`; onsite projects
  in Austria/Switzerland are dropped though the user is EU-authorized and the sources are DACH.
- **Annotation-shop exclusions** — add Mercor / Surge / Outlier / Scale to `exclude_companies`
  (they title labelling piecework as "AI Engineer" and will rank well while being wrong).
- **`target_roles` / `deprioritise` refresh** — esp. the `deprioritise` "5+ years senior" entry,
  which fights K's "supply skews senior" finding.

## Boundaries (recorded, not decided here)

- **Hard-filter predicates** → already decided by D ([#7](https://github.com/marcosfsousa/agentic-job-hunter/issues/7));
  E's schema is consistent with D's `_passes_all` (seniority/experience/salary removed,
  `_passes_contract_type` blocklist added, `_passes_location` reshaped).
- **Ranking query + eval prompt** (including the rate-adequacy and experience-fit judgements this
  schema feeds, and Risk 2) → F ([#9](https://github.com/marcosfsousa/agentic-job-hunter/issues/9)).
- **Profile-file migration + `models.py` code edits** → execution. This ADR is the build list; no
  production code is written here.

## Consequences

- One clean money axis in the profile (`rate`, hourly-canonical), a single deterministic
  contract-type gate wired to B's enum, and a per-source query list — every mandated E preference
  is expressible, and no dead/speculative field is introduced (leans deferred to their consumers).
- `UserProfile` loses three sub-config concepts (`SalaryConfig`, `SeniorityConfig`, and the jobspy
  query/site config) and gains `RateConfig` + `freelancermap_queries` + one `DealbreakersConfig`
  field — a net simplification.
- Two live risks are carried forward as explicit hand-offs (freelancermap search interface →
  execution/M; relocated experience bias → F), rather than reading as solved.
