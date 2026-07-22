# Session State — CLOSED

> **This document is closed. Do not read it for current state, and do not update it.**
>
> **Closed:** 2026-07-22. **Last genuine update:** 2026-04-01 (Day 16) — it went stale through the
> whole FTE → freelance planning effort and never described the pivot.
>
> **Where state lives now:**
>
> | For | Go to |
> |---|---|
> | Where the pivot stands, and every decision behind it | [Wayfinder map, issue #3](https://github.com/marcosfsousa/agentic-job-hunter/issues/3) — "Decisions so far" is the running record |
> | What to build next | The four hand-off specs: [#26](https://github.com/marcosfsousa/agentic-job-hunter/issues/26) → [#27](https://github.com/marcosfsousa/agentic-job-hunter/issues/27) → [#28](https://github.com/marcosfsousa/agentic-job-hunter/issues/28) → [#29](https://github.com/marcosfsousa/agentic-job-hunter/issues/29), in that order (each blocks the next) |
> | Open work generally | GitHub issues via `gh` — see [`docs/agents/issue-tracker.md`](agents/issue-tracker.md) |
> | Build history | [`docs/build-log.md`](build-log.md) |
> | Domain model and terminology | [`CONTEXT.md`](../CONTEXT.md), [`docs/adr/`](adr/) |
>
> **Why it was closed rather than updated:** a single mutable "where we left off" file is the wrong
> shape for this phase. The pivot's state is a dependency graph across four specs and nineteen
> closed decision tickets, all of which live in the issue tracker with their reasoning attached.
> Mirroring a summary of that here would produce a second source of truth that drifts — which is
> exactly what happened between April and July.

---

## Historical record — Day 16, 2026-04-01

*Everything below is preserved as it stood on 2026-04-01 and is superseded. It describes the
FTE-era pipeline, which is tagged [`v1.0.0`](https://github.com/marcosfsousa/agentic-job-hunter/releases/tag/v1.0.0)
on `main`. Adjudication notes mark the items that later tickets settled, so they are not
re-actioned by mistake.*

### Status
- Completed through: Day 16 — JobSpy adapter (LinkedIn + Indeed), cron shift to 04:00 UTC, ops runbook, pre-commit hook
- Last working command: `conda run -n jobscout python -m pytest` (297 tests passing)

### Known issues
- Centroid signal still sparse — only a few `applied` entries seeding it. Will improve naturally as pipeline runs and reviews accumulate.
  - *Superseded:* the FTE-seeded centroid is explicitly out of scope on the map — it self-corrects as freelance reviews accumulate.
- Cron fires at 4am UTC. GH Actions queue adds ~1–2h delay consistently, targeting ~08:00–08:30 CEST delivery.
  - *Superseded:* spec 1 (#26) removes the `schedule:` trigger entirely; spec 3 (#28) re-arms it.
- `email_min_score` temporarily at 4 (down from 5) — review by 2026-04-07.
  - *Still open, and now owned:* the review date passed unactioned. It is a deliverable of spec 4 (#29), which also flags that the value has **two** consumers — the digest gate at `run.py:199` and `reeval_below` via `config.py:63` — so retuning one silently retunes the other.
- numpy 1.26.3 installed (jobspy constraint); scipy warns about version range but tests pass.
  - *Superseded:* spec 1 (#26) deletes the jobspy adapter, so the constraint that pinned numpy goes with it.

### Next session (Day 17)
*None of these were done, and none should be — Day 17 never happened; the FTE → freelance pivot
started instead.*
- [ ] Review `email_min_score` calibration by 2026-04-07 — raise back to 5 if digest is too noisy, keep at 4 if quality holds
  - → carried into spec 4 (#29), see above.
- [ ] Review embedding score floor (currently 0.30) after a week of digest runs — tune up if noise persists, down if good matches are being dropped
  - → moot. O (#21) deleted `embedding_min_score` outright with no replacement value: an absolute cosine threshold is scale-coupled and goes stale silently on a model swap. `top_n` in `config.py` becomes the sole constant carrying the top-20–30 constraint. Lands in spec 4 (#29).
- [ ] Monitor JobSpy yield in live digests — indeed returns 0 results for the ML query; may need query tuning
  - → moot. K (#15) measured jobspy at 73 raw → 2–3 filtered net-new freelance ML/week, an order of magnitude under the ≥5/week entry gate, and dropped it. The adapter is deleted in spec 1 (#26).
