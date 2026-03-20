# Session State

**Last updated:** 2026-03-20

## Status
- Completed through: Deliver (Days 1–5) — full pipeline working end-to-end
- Last working command: `conda run -n jobscout python -m jobscout.run --dry-run --verbose` (92 passed, smoke test clean)

## Known issues
- SSL cert: copied `cacert.pem` to `$CONDA_PREFIX/ssl/` manually — already fixed
- Adzuna: use `what_or` not `what`; append `, Germany` to city-only locations — already fixed
- `matching_skills` in LLM output often surfaces generic skills (Python, Docker) rather than distinctive ones (RAG systems, LangChain) — prompt tuning candidate for Day 6

## Next session (Day 6)
- [ ] Write tests for `delivery/formatter.py`, `delivery/writer.py`, `delivery/email_sender.py`
- [ ] Run full pipeline (non-dry-run) to populate DB and verify deduplication on second run
- [ ] Tune evaluation prompt — `matching_skills` should surface strong/distinctive skills, not just generic ones
- [ ] Consider adding `LangGraph` and `Prompt engineering` to `profile.yaml` `skills.strong`
