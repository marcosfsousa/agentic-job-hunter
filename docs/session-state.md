# Session State

**Last updated:** 2026-03-21

## Status
- Completed through: Day 8 — Feedback centroid ranking signal, email format fix, dry-run email guard
- Last working command: `conda run -n jobscout python -m jobscout.run --verbose` (166 tests passing, 156 jobs stored, email delivered)

## Known issues
- None outstanding.

## Next session (Day 9)
- [ ] `--since` flag — run pipeline for a specific date range
- [ ] Run full pipeline with both adapters active to confirm JSearch deduplication end-to-end
- [ ] Create `data/feedback.yaml` with first `interested` entries and verify centroid boost is active (`get_interested_descriptions` returns > 0)
