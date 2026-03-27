# Session State

**Last updated:** 2026-03-27

## Status
- Completed through: Day 13 — GitHub Actions scheduler, blocked-domain URL fallback
- Last working command: `conda run -n jobscout python -m pytest` (225 tests passing)

## Known issues
- Centroid signal still sparse — only a few `applied` entries seeding it. Will improve naturally as pipeline runs and reviews accumulate.
- Cron fires at 6am UTC (7am CET winter). Drifts to 8am local in summer (CEST) — acceptable for personal tool.

## Next session (Day 14)
- [ ] Monitor scoring calibration across a few real pipeline runs — adjust prompt if distribution drifts
- [ ] Consider lowering `email_min_score` further if too few jobs qualify after calibration settles
