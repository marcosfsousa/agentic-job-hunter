# CLAUDE.md — JobScout

## Overview
Personal AI job matching pipeline. Ingests listings → hard filters → embeds + ranks
→ LLM evaluates → delivers digest (Telegram or markdown).
Goal: fewer, higher-quality matches. This tool finds and ranks. User decides what to apply to.

## Architecture
`Ingest → Hard Filter → Embed + Rank → LLM Evaluate → Deliver`

- Each stage is a separate module under `src/jobscout/`
- Adapters in `adapters/` are pluggable — new market = new adapter file + config entry, nothing else
- `profile.yaml` is the single source of truth for all user preferences. No hardcoded filters anywhere.
- SQLite at `data/jobscout.db` for deduplication and feedback. No external DBs.
- In-memory numpy cosine similarity for ranking — no vector store needed at this scale.

## Code conventions
- Python 3.11+, type hints everywhere, dataclasses for data structures
- Pydantic for external API validation; `httpx` (async) for all HTTP; `pathlib.Path` not `os.path`
- All config via `config.py` — never hardcode paths or keys
- `logging` stdlib only, no `print()`
- Tests in `tests/` with pytest; API fixtures in `tests/fixtures/`

## Constraints
- **NEVER auto-apply to jobs.**
- Use Claude Haiku for evaluation (not Sonnet); local `multi-qa-MiniLM-L6-cos-v1` for embeddings (asymmetric semantic search — profile query vs job document).
- LLM evaluation runs on top 20–30 jobs only, after hard filter and ranking reduce the pool.
- Hard filter is deterministic and cheap — no LLM calls, ever.
- Pipeline must be idempotent — same day = same digest.
- Adapter pattern must stay clean — pipeline stages never change when adding a source.

## When making changes
- Run `pytest` after any change to models, filters, or ranking
- If modifying the LLM prompt, test with at least 5 real job listings
- New adapter → follow `adapters/base.py` interface exactly
- At the end of each day's build, run `/simplify` on all files created or modified that session

## Session State
Before starting work, read `docs/session-state.md` for where we left off.
Full build history in `docs/build-log.md`.
Setup and run instructions → `docs/dev-notes.md`
Session state template → `docs/dev-notes.md#session-state-template`