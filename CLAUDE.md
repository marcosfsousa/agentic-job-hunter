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
- Use Claude Haiku for evaluation (not Sonnet); local `intfloat/multilingual-e5-small` for embeddings (asymmetric semantic search — profile query vs job document, expressed through e5's `query:` / `passage:` prefixes).
- LLM evaluation runs on top 20–30 jobs only, after hard filter and ranking reduce the pool.
- Hard filter is deterministic and cheap — no LLM calls, ever.
- Pipeline must be idempotent — same day = same digest.
- Adapter pattern must stay clean — pipeline stages never change when adding a source.

## Working a tracked issue

When I say "work #<n>", fetch the issue and follow it. No further
briefing should be needed.

Before writing code:
- Read the issue, and the handoff section it links
  (`docs/jobscout_scoring_handoff.md`, incl. § 9 verification results)

While working:
- **If implementing reveals the diagnosis was wrong: STOP.** Comment
  on the issue with what the code actually does, and report back.
  Do not implement an adjacent fix you think is better.
- Stay inside the issue's `Scope: In`. If you see something wrong
  outside it, open a new issue labelled `discovered` and move on —
  do not fix it in passing.
- `Acceptance criteria` bound the work. Nothing beyond them ships.

Validation for scoring changes:
- If `tests/fixtures/scored_postings/` exists, run it and comment the
  band-accuracy result before and after on the issue. **A change that
  moves scores without moving band accuracy is not an improvement.**
- Until it exists, the ≥5-listing validation gate below applies.
  Once it exists, the fixture set supersedes that gate for any change
  to `SYSTEM_PROMPT`, `profile.yaml`, or the filter predicates.

**The private evaluation log stays out of the repo.** A finding from it becomes an issue
only when it can be stated as a reproducible behaviour with a posting ID attached;
everything else stays market intelligence. Quote a specific note inline in an issue if
its reasoning is unclear — never commit the file, and never paraphrase its contents at
length in a committed document.

## When making changes

- Run `pytest` after any change to models, filters, or ranking
- If modifying the LLM prompt, test with at least 5 real job listings
- New adapter → follow `adapters/base.py` interface exactly
- When all todos for the current session are marked done, prompt the user: "All todos complete — run `/simplify` on files modified this session before closing?"

## Git workflow

Always run `git pull` before making any file changes in this repo.
The daily GitHub Action commits `data/feedback.yaml`, so the local copy may be behind.
**`data/jobscout.db` is never committed** — it holds the full description of every ingested
listing, and republishing ingested source content is not ours to do. It is gitignored, lives
only on disk locally, and survives between CI runs via an Actions cache.
`tests/test_repo_invariants.py` fails if it becomes tracked again.
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

**Tags are semver.** ✅ **`v1.0.0` already exists** — annotated, pushed, at `af51f15` on `main`,
tagged 2026-07-20. It marks the FTE-era pipeline so it stays recoverable by name, and it
established the scheme. **Do not re-create or move it**; run `git tag -l` before concluding
otherwise. (This paragraph previously read "the repo has no tags today", which was true when
written and has since misled at least one session into reporting the tag as missing.)

✅ **`v2.0.0` already exists** — annotated, pushed, at `526c007` on `main` (the PR #42 merge that
landed the integration branch), tagged 2026-07-23. It marks the pivot complete: the integration
branch had merged and spec 4's ≥5-listing validation had passed at the point it was cut.
**Do not re-create or move it**; run `git tag -l` before concluding otherwise. Fixes landed on
`main` after this tag (e.g. #44, #45) are unreleased under any tag — that's expected, not a defect;
cut a new tag (`v2.0.1`/`v2.1.0`) only when there's a reason to mark a release point. (This
paragraph previously read "still to do: tag v2.0.0 ...", which was true when written and has since
gone stale — same failure mode the `v1.0.0` paragraph above already warns about.)

**Automatic PR review is disarmed** (2026-07-23) — the `review:` job in `.github/workflows/claude.yml`
is gated `if: false` after repeated unexplained failures. `@claude <request>` on a PR still reviews on
demand; re-arm by restoring that job's `if:` condition.

✅ **The daily run is live** (since 2026-07-31) — `daily_run.yml` fires at `15 3 * * *` and emails the
digest. **A workflow has two independent switches, and only one is in the repo.** The YAML's
`schedule:` block was armed by spec 3 in `391aab4`, but the workflow *object* stayed
`disabled_manually` at the GitHub level from spec 1's dark period until it was enabled by hand on
2026-07-31 — so for 19 days the file, `git log` and green CI all read healthy while nothing ran.
**Never conclude the schedule is live from the YAML alone**; `gh workflow list --all` is the only
place that state is visible. Verified end to end by dispatch run `30656471332`: 75 ingested → 22 past
the hard filter → 8 emailed. Note `Run tests` is gated `if: github.event_name != 'schedule'`, so
scheduled runs execute the pipeline with no test gate — use `gh workflow run daily_run.yml` when you
want `pytest` to run first.

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
