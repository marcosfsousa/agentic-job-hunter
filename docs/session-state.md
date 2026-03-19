# Session State

**Last updated:** 2026-03-19

## Status
- Completed through: Hard Filter + Deduplication (Days 1–2)
- Last working command: `python -m jobscout.run --dry-run --verbose --max-results 50`

## Known issues
- SSL cert: copied `cacert.pem` to `$CONDA_PREFIX/ssl/` manually — already fixed
- Adzuna: use `what_or` not `what`; append `, Germany` to city-only locations — already fixed

## Next session (Day 3)
- [ ] `ranking/embedder.py` — encode profile + jobs with `all-MiniLM-L6-v2`
- [ ] `ranking/scorer.py` — cosine similarity, return sorted `ScoredJob` list
- [ ] `tests/test_ranking.py` — verify ML job ranks above frontend job
- [ ] Wire ranking into `run.py` after hard filter