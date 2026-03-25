# Session State

**Last updated:** 2026-03-25

## Status
- Completed through: Day 11 — feedback centroid fix, `--review` mode, LLM scoring calibration
- Last working command: `conda run -n jobscout python -m jobscout.run` (201 tests passing)

## Known issues
- `--review` shows all `seen_jobs` for the date (18 today) but user only has context for digest jobs (8 today) — fix deferred: store evaluated job IDs at pipeline time so `--review` filters to digest-only
- Centroid signal still sparse — only a few `applied` entries seeding it. Will improve naturally as pipeline runs and reviews accumulate.

## Next session (Day 12)
- [ ] Fix `--review` to only surface jobs that appeared in the digest (not all `seen_jobs`)
- [ ] Monitor scoring calibration across a few real pipeline runs — adjust prompt if distribution drifts
- [ ] Consider lowering `email_min_score` further if too few jobs qualify after calibration settles
