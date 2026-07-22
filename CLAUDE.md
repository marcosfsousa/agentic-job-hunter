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
- When all todos for the current session are marked done, prompt the user: "All todos complete — run `/simplify` on files modified this session before closing?"

## Git workflow

Always run `git pull` before making any file changes in this repo.
The pipeline commits a DB file daily via GitHub Actions, so the local copy may be behind.
**Never push to `main` directly, force-push, or merge into `main` by hand.** All work reaches `main`
through a branch and a reviewed PR — a hotfix is a short-lived branch and a fast PR, not an edit on
`main`. (This replaces the previous stash → checkout main → edit → push hotfix flow.)

**During the FTE → freelance pivot (specs #26–#29):** `v2-freelance-pivot` is the long-lived
integration branch, cut from `main`. Each spec gets its own branch off it — `spec-1-contract-model`,
`spec-2-profile-filter`, `spec-3-freelancermap-adapter`, `spec-4-e5-ranking-eval` — and PRs *into*
the integration branch, never into `main`. Review therefore still happens in four normal-sized
chunks, and the eventual merge to `main` is already-reviewed work.

`main` stays on the last working pipeline until the pivot is whole. This is the reason for the
integration branch, not a style preference: spec 1 deletes all three FTE adapters and disarms the
cron, so the pipeline is **deliberately dark** from spec 1 until spec 3 re-arms it, and that state
must not sit on `main`.

**Tags are semver.** Tag `main` `v1.0.0` before any pivot code lands, so the FTE-era pipeline stays
recoverable by name — the repo has no tags today, so this establishes the scheme. Tag `v2.0.0` on
`main` once the integration branch has merged **and** spec 4's ≥5-listing validation has passed —
the pivot is complete when it is validated, not when it compiles.

## Agent skills

### Issue tracker

Issues live as GitHub issues in `marcosfsousa/agentic-job-hunter`, managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, used verbatim as label strings. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Session State

Before starting work, read the **[Wayfinder map (issue #3)](https://github.com/marcosfsousa/agentic-job-hunter/issues/3)**
for where we left off — its "Decisions so far" section is the running record, and the four hand-off
specs (#26 → #27 → #28 → #29, each blocking the next) are the work queue. Open work generally lives
in GitHub issues via `gh` → `docs/agents/issue-tracker.md`.

`docs/session-state.md` is **closed** (2026-07-22) and is not maintained. It is kept only as a
historical record of the FTE-era pipeline; do not read it for current state or update it.

Full build history in `docs/build-log.md`.
Setup and run instructions → `docs/dev-notes.md`
Ops checks (sync, pipeline inspection, queue delays) → `docs/dev-notes.md#ops-checks`
