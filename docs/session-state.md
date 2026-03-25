# Session State

**Last updated:** 2026-03-24

## Status
- Completed through: Day 10 — cross-source dedup, false positive triage, feedback seeding
- Last working command: `conda run -n jobscout python -m jobscout.run` (196 tests passing)

## Known issues
- Centroid boost is weakly activated — only one `interested` entry in `feedback.yaml`. More signal needed as pipeline runs accumulate.

## Next session (Day 11)
- [ ] Investigate why few `interested` listings are accumulating — check if pipeline is surfacing enough quality matches or if scoring thresholds are too aggressive
- [ ] Consider adding a `--feedback` flag or interactive review mode to make it easier to mark jobs after reading the digest
