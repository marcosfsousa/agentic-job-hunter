# ADR 0001 — Contract-era `JobListing` data model

- **Status:** Accepted
- **Date:** 2026-07-17
- **Wayfinder ticket:** [B — Contract data model (widened for expressibility)](https://github.com/marcosfsousa/agentic-job-hunter/issues/5)
- **Depends on:** [A — Freelance source landscape](https://github.com/marcosfsousa/agentic-job-hunter/issues/4) (field realism), [G — Accept scraping risk](https://github.com/marcosfsousa/agentic-job-hunter/issues/11) (source is freelancermap)
- **Part of:** [Wayfinder: JobScout FTE → freelance pivot](https://github.com/marcosfsousa/agentic-job-hunter/issues/3)

## Context

JobScout is being repointed from full-time-employment (FTE) listings to freelance/contract
projects — a full **replace**, not a second track. The FTE-shaped `JobListing`
(`salary_min/max` in annual EUR, a junior/mid/senior/lead `seniority` rung) cannot express
contract work, and several of its fields are actively harmful if carried forward.

Ticket A measured real freelancermap payloads (the one viable DACH source, per G) rather than
trusting schemas, and handed this ticket a set of field-level constraints. The recurring lesson
from A: **field presence in a schema is not field presence in the data** — A got two findings
wrong by reading pages instead of counting populated fields. Every decision below is anchored to
a measured count where one exists.

This ticket decides the **target field set only**. It does not decide the DB migration of
existing rows (execution), the `profile.yaml` schema (ticket E), or hard-filter thresholds
(ticket D). Those boundaries are recorded at the end.

## Decision

The contract-era `JobListing` is the following field set. Fields are grouped as kept / changed /
removed / added relative to the FTE model.

### Kept unchanged

`id`, `source`, `title`, `company` (required `str`), `description`, `location`, `url`,
`fetched_at`, `raw_data`.

### Changed

- `posted_date`: `date | None` → **`datetime | None`**. freelancermap ships an exact `created`
  timestamp; truncating it to a calendar date would force incremental sync (fetch only projects
  newer than the last run) to reach into `raw_data`. FTE-era sources only had date granularity,
  so their values become midnight-stamped — honest, and consistent with `fetched_at`.

### Removed

- `salary_min`, `salary_max` (annual EUR) and `SalaryConfig`. Annual salary is the **wrong axis**,
  not merely insufficient — nothing in the contract corpus quotes an annual figure. Replaced by
  `rate_*` (below). Keeping both money axes on one model invites silent cross-scale comparison of
  an FTE row against a contract row.
- `seniority` (the field), the `Seniority` enum, and `_infer_seniority()`. Seniority is an
  employment-ladder concept with no freelance analogue; no source supplies it (freelancermap has
  no such field), so today's value is our own text inference dressed as data. The hard filter then
  drops any job whose *inferred* rung isn't in the profile target — DACH contract listings read
  "Senior / mehrjährige Erfahrung" as a market signal, so the pipeline would fabricate a rung and
  filter the corpus away on its own guess. The experience signal survives in `description` for LLM
  eval (F) and the existing years-of-experience regex.

### Added

| Field | Type | Source / rule |
|---|---|---|
| `remote_percentage` | `int \| None` | sourced from freelancermap `remoteInPercent` |
| `remote_policy_text` | `RemotePolicy` | adapter's text inference; **fallback only** |
| `remote_policy` | *`@property` → `RemotePolicy`* | derived; percentage always wins (see invariant) |
| `rate_min` | `float \| None` | |
| `rate_max` | `float \| None` | a single quoted value sets `rate_min == rate_max` |
| `rate_unit` | `RateUnit \| None` | `hourly` / `daily` / `project_total` |
| `rate_currency` | `str \| None` | e.g. `"EUR"`, `"USD"` |
| `contract_type` | `ContractType` | `contracting` / `employee_leasing` / `permanent_position` / `unknown` |
| `duration_months` | `int \| None` | freelancermap integer `duration` |
| `duration_is_open_ended` | `bool` | project with no end date — distinct from unknown length |
| `duration_text` | `str \| None` | raw `durationText`; preserves what parsing drops |
| `start_date` | `date \| None` | set **only** when an exact day is known |
| `start_is_immediate` | `bool` | the "Start Sofort" case — distinct from unknown |
| `start_text` | `str \| None` | raw `beginningText`; carries "Ab Juli 2026" losslessly |
| `client_type` | `ClientType` | `agency` / `direct` / `unknown` |

### Enums

```python
RemotePolicy = Literal["remote", "hybrid", "onsite", "not_specified"]   # kept
RateUnit     = Literal["hourly", "daily", "project_total"]              # new
ContractType = Literal["contracting", "employee_leasing", "permanent_position", "unknown"]  # new
ClientType   = Literal["agency", "direct", "unknown"]                   # new
# Seniority — removed
```

### The remote invariant

`remote_percentage` is the single source of truth. `remote_policy` is a computed property, so a
percentage and a policy can never contradict each other by construction:

```python
@property
def remote_policy(self) -> RemotePolicy:
    if self.remote_percentage is None:
        return self.remote_policy_text          # text-only sources (Upwork, jsearch, jobspy)
    if self.remote_percentage >= 100:
        return "remote"
    if self.remote_percentage <= 0:
        return "onsite"
    return "hybrid"
```

Read sites (`hard_filter.py`, `formatter.py`, the jobspy remote-rescue) are unchanged. Write
sites break: `remote_policy` is no longer a constructor argument, so the three adapters and the
test construction sites must set `remote_percentage` + `remote_policy_text` instead.

> **Note — threshold ownership.** The `>= 100 → remote`, `<= 0 → onsite`, else `hybrid` cut points
> are a *placeholder*, not a measured decision. freelancermap returned 100 / 60 / 50 on page one
> and hybrid is 52 of 116 DACH projects. Whether "60% remote" counts as good enough is a
> **ranking/filter** question owned by D (#7) and F (#9); if they pick different cut points, this
> property is where they change.

## Rationale for the harder calls

- **Rate is four nullable fields, not a bare float.** A single `rate` float would be actively
  harmful: freelancermap's one money label is *Budget*, unit-ambiguous, and populated **0/22**.
  Min/max mirrors the existing `salary_min/max` shape and preserves Upwork's ranges — the only
  source with real, useful rate data. Unit and currency are nullable together with the numbers;
  **all-None is the DACH norm**, and the hard filter must never require rate or it discards the
  entire DACH corpus invisibly until the digest goes empty.
- **`contract_type` is a 4-value enum, not a bool.** It maps 1:1 to freelancermap's measured
  `projectContractType` (94 contracting / 12 employee-leasing / 10 permanent). `employee_leasing`
  (*Arbeitnehmerüberlassung*) + `permanent_position` are ~19% of the pool Marcos does not want,
  **deterministically excludable with no LLM call** — exactly what the hard-filter constraint
  wants. A bool would fuse leasing and permanent, forcing a second migration the day the two need
  different treatment.
- **Duration and start date each carry a raw-text escape hatch.** A warned that parsing `MM`
  (*Mannmonate* / man-months) as calendar months is a plausible bug and the format is
  *expected-but-unobserved* — so `duration_text` / `start_text` keep the source string, and the
  parsed fields are best-effort. Start date has **three** cases (immediate / month-granular /
  exact day); a lone `date` field can't say "immediate" or "July, day unknown" without faking a
  day-of-month, hence `start_is_immediate` + text.
- **`client_type` is a ranking signal, never a hard filter.** `endcustomer` is populated 5/116, so
  `unknown` is the majority and the *source* usually determines the value. As a filter it yields
  ~5 projects; as a boost (direct-client is a positive signal) it's useful. Enum over bool so a
  future source that positively knows "agency" isn't blurred into "unknown".

## Deliberate non-additions

Weighed and rejected, recorded so they aren't re-litigated:

- **`end_customer` name field** — the real client is named only 5/116 (~4%). Too sparse to weight
  on, `client_type` already carries the agency/direct signal, and it's outside the widened-B
  mandate. Could return as a later ticket if F wants to boost on named clients.
- **Nullable `company`** — freelancermap (the confirmed source) always names the poster, so
  `company: str` stays required. freelance.de paywalls company names, but C (#6) has not chosen
  that source; defer nullability until a chosen source needs it.

## Boundaries (recorded, not decided here)

- **DB migration of existing FTE rows** → execution / C. Constraint B imposes: no FTE row may
  survive into a corpus read as `rate_*` (else silent cross-scale comparison). *How* — drop,
  rebuild, or null the salary columns — is execution's call.
- **`profile.yaml` schema**, including whether `SalaryConfig` / `SeniorityConfig` sections are
  removed or replaced, and how the profile references `RateUnit` / `ContractType` / `ClientType`
  → ticket E (#8). This ADR defines the enums as shared vocabulary; E wires the profile to them.
- **Hard-filter thresholds and gate-vs-boost decisions** → ticket D (#7). A's guidance for D:
  never hard-filter on rate or `client_type`; `contract_type` leasing/permanent are deterministically
  excludable; derive any remote gate from `remote_percentage`.

## Consequences

- One clean money axis (`rate_*`), one remote axis with an unbreakable invariant, and a
  deterministically-filterable `contract_type` — the model can express every widened-B preference
  (contract duration, agency-vs-direct, rate range, start date) without a second migration.
- The `remote_policy` → property change is the largest code ripple: three adapters + ~7 test
  construction sites move from `remote_policy=` to `remote_percentage=` + `remote_policy_text=`.
- Parsed `duration_months` / `start_date` are best-effort; the `*_text` fields are the source of
  truth when parsing is uncertain.
