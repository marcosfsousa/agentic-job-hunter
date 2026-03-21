# Session State

**Last updated:** 2026-03-21

## Status
- Completed through: Day 6 — delivery tests, first real pipeline run, prompt tuning
- Last working command: `conda run -n jobscout python -m jobscout.run --verbose` (129 passed, full pipeline clean)

## Known issues
- None outstanding.

## Next session (Day 7)
- [ ] Add a second job source adapter (e.g. JSearch or LinkedIn) to widen the listing pool
- [ ] Add feedback loop to DB — allow marking jobs as "applied", "rejected", "interested" to inform future ranking
- [ ] Consider adding a `--since` flag to run the pipeline for a specific date range
