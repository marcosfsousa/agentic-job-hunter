# Session State

**Last updated:** 2026-04-01

## Status
- Completed through: Day 16 — JobSpy adapter (LinkedIn + Indeed), cron shift to 04:00 UTC, ops runbook, pre-commit hook
- Last working command: `conda run -n jobscout python -m pytest` (297 tests passing)

## Known issues
- Centroid signal still sparse — only a few `applied` entries seeding it. Will improve naturally as pipeline runs and reviews accumulate.
- Cron fires at 4am UTC. GH Actions queue adds ~1–2h delay consistently, targeting ~08:00–08:30 CEST delivery.
- `email_min_score` temporarily at 4 (down from 5) — review by 2026-04-07.
- numpy 1.26.3 installed (jobspy constraint); scipy warns about version range but tests pass.

## Next session (Day 17)
- [ ] Review `email_min_score` calibration by 2026-04-07 — raise back to 5 if digest is too noisy, keep at 4 if quality holds
- [ ] Review embedding score floor (currently 0.30) after a week of digest runs — tune up if noise persists, down if good matches are being dropped
- [ ] Monitor JobSpy yield in live digests — indeed returns 0 results for the ML query; may need query tuning
