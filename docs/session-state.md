# Session State

**Last updated:** 2026-03-31

## Status
- Completed through: Day 14 — Scoring calibration, JSearch ID stability, fingerprint dedup, multi-query JSearch
- Last working command: `conda run -n jobscout python -m pytest` (229 tests passing)

## Known issues
- Centroid signal still sparse — only a few `applied` entries seeding it. Will improve naturally as pipeline runs and reviews accumulate.
- Cron fires at 6am UTC (7am CET winter). Drifts to 8am local in summer (CEST) — acceptable for personal tool.

## Next session (Day 15)
- [ ] Monitor scoring calibration across a few real pipeline runs with the new rubric — watch for over/under-penalisation
- [ ] Consider tightening Adzuna `what_or` query — remove `MLOps` and `data scientist` to reduce classical ML supply bleeding in
- [ ] Consider lowering `email_min_score` if too few jobs qualify after calibration settles
