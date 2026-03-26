# Session State

**Last updated:** 2026-03-26

## Status
- Completed through: Day 12 — `--review` digest filtering, `digest_jobs` table
- Last working command: `conda run -n jobscout python -m jobscout.run` (217 tests passing)

## Known issues
- Centroid signal still sparse — only a few `applied` entries seeding it. Will improve naturally as pipeline runs and reviews accumulate.
- Old digest dates (before today) have no `digest_jobs` entries — `--review` will print the "predates digest tracking" message for them. Expected behaviour, not a bug.

## Next session (Day 13)
- [ ] **GitHub Actions daily scheduler** — `.github/workflows/daily_run.yml`, 7am CET cron, secrets for API keys, `workflow_dispatch` for manual trigger (Day 8 from spec — still missing)
- [ ] Monitor scoring calibration across a few real pipeline runs — adjust prompt if distribution drifts
- [ ] Consider lowering `email_min_score` further if too few jobs qualify after calibration settles
