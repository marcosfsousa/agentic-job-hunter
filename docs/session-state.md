# Session State

**Last updated:** 2026-03-19

## Status
- Completed through: Embed + Rank (Days 1–3)
- Last working command: `conda run -n jobscout python -m pytest -v` (83 passed, post-simplify fixes applied)

## Known issues
- SSL cert: copied `cacert.pem` to `$CONDA_PREFIX/ssl/` manually — already fixed
- Adzuna: use `what_or` not `what`; append `, Germany` to city-only locations — already fixed

## Next session (Day 4)
- [ ] `evaluation/evaluator.py` — Claude Haiku evaluates top 20–30 `ScoredJob`s, returns `EvaluationResult`
- [ ] `evaluation/prompt.py` — prompt template for Haiku evaluation
- [ ] `tests/test_evaluation.py` — mock Haiku response, verify `EvaluationResult` parsing
- [ ] Wire evaluation into `run.py` after ranking (slice top 25, evaluate, attach results)