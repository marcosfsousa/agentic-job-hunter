# Session State

**Last updated:** 2026-03-31

## Status
- Completed through: Day 15 — Adzuna query tightening, email threshold tuning, embedding score floor
- Last working command: `conda run -n jobscout python -m pytest` (229 tests passing)

## Known issues
- Centroid signal still sparse — only a few `applied` entries seeding it. Will improve naturally as pipeline runs and reviews accumulate.
- Cron fires at 6am UTC (7am CET winter). Drifts to 8am local in summer (CEST) — acceptable for personal tool.
- `email_min_score` temporarily at 4 (down from 5) — review by 2026-04-07.

## Next session (Day 16)
- [ ] Review `email_min_score` calibration by 2026-04-07 — raise back to 5 if digest is too noisy, keep at 4 if quality holds
- [ ] Review embedding score floor (currently 0.30) after a week of digest runs — tune up if noise persists, down if good matches are being dropped
- [ ] Add JobSpy as a third adapter to increase job volume — follow `adapters/base.py` interface, register in `_ADAPTER_REGISTRY` in `run.py`
