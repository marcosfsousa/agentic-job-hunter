# Session State

**Last updated:** 2026-03-24

## Status
- Completed through: Day 9 — JSearch null description fix, email score threshold, job ID in digest, `--since` flag, skip email when no matches
- Last working command: `conda run -n jobscout python -m jobscout.run` (185 tests passing, pipeline ran end-to-end, email delivered)

## Known issues
- None outstanding.

## Next session (Day 10)
- [ ] Implement cross-source + within-source deduplication — full plan in `docs/plan-cross-source-dedup.md`
- [ ] Triage the Apple "Quality Engineer - Machine Learning" false positive — consider adding audio/QA keywords to `dealbreakers.exclude_keywords` or tightening `require_any_keyword`
- [ ] Review accumulated `feedback.yaml` entries and add first `interested` jobs to activate centroid boost more strongly
