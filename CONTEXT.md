# JobScout — Domain glossary

The ubiquitous language for the job-matching pipeline. Terms only — no implementation detail.
When a term here conflicts with how code or conversation uses a word, the conflict is the bug.

## Listing & sourcing

- **Listing** — one job/project as JobScout models it internally (`JobListing`), normalized from
  whatever a source returned. Post-pivot, a listing is a **contract/freelance project**, not an
  FTE vacancy.
- **Source** — a platform JobScout ingests from (e.g. freelancermap, Upwork). One adapter per
  source. The *source* — not the listing — often determines fields like `client_type`.
- **Poster vs. end-client** — the **poster** is whoever published the listing (`company`); on an
  intermediated listing that's an agency. The **end-client** is the company the work is actually
  for. On freelancermap the end-client (`endcustomer`) is named only ~4% of the time. JobScout
  stores the poster in `company` and does **not** store the end-client name.

## Money

- **Rate** — what a contract pays, along a **day / hourly / project-total** axis (`rate_unit`).
  This *replaced* annual **salary**; the two never coexist on a listing. Rate is usually **absent**
  on the DACH side (agencies treat it as a negotiation, not a published figure), so every rate
  field is nullable and nothing may require it.
- **Salary** — FTE-era annual-EUR figure. **Removed** from the model. If you see it, it's legacy.

## Contract shape

- **Contract type** — the legal engagement form: **contracting** (freelance project),
  **employee-leasing** (*Arbeitnehmerüberlassung* / AÜ — a temp-staffing placement, not freelance),
  or **permanent-position** (a Festanstellung leaking onto a project board). Only *contracting* is
  wanted; the other two are deterministically excludable.
- **Open-ended** — a contract with no stated end date (a distinct, positive signal), as opposed to
  one whose length simply wasn't stated (**unknown**). The model keeps these apart.
- **Client type** — whether a listing is **direct** (straight to the end-client) or via an
  **agency**. Mostly **unknown**. A ranking signal, never a hard filter — filtering on it leaves
  almost nothing.

## Remote

- **Remote percentage** — the share of work done remotely, as a number (`remote_percentage`), e.g.
  60. The **authoritative** remote signal when a source provides it.
- **Remote policy** — the coarse **remote / hybrid / onsite / not-specified** bucket. **Derived**
  from remote-percentage when present; only falls back to text inference when the percentage is
  unknown. The percentage always wins — the two cannot disagree.
- **Hybrid** — partial remote (any percentage strictly between fully-onsite and fully-remote).
  About half the DACH market; not expressible as a rung, only as a percentage.

## Timing

- **Start** — when the contractor begins. Three cases, kept distinct: **immediate** ("Sofort"),
  **month-granular** ("Ab Juli 2026", day unknown), or an **exact day**. Not the same as when the
  listing was posted.
- **Posted / created** — when the source published the listing. Carries a full timestamp (used for
  incremental sync), not just a date.
