# Build Log

Chronological record of what was built each session.

---

## Day 1 — 2026-03-17

**Goal:** Project setup, data model, first adapter.

**Files created**
- `pyproject.toml` — package metadata, dependencies, pytest config (`asyncio_mode=auto`)
- `profile.yaml` — full search profile (Germany, ML/AI roles, €50K salary floor)
- `src/jobscout/models.py` — `JobListing` (frozen dataclass), `EvaluationResult` (Pydantic, score 1–10), `ScoredJob`, `UserProfile` and sub-models
- `src/jobscout/config.py` — `AppConfig` (Pydantic), lazy singleton `get_config()`, `reset_config()` for tests
- `src/jobscout/adapters/base.py` — `JobAdapter` ABC, `JobScoutAdapterError`
- `src/jobscout/adapters/adzuna.py` — `AdzunaAdapter` with Pydantic validation, pagination, `_infer_remote_policy()`, `_infer_seniority()`, `_parse_date()`
- `tests/fixtures/sample_adzuna_response.json` — 3-listing fixture
- `tests/test_adapters.py` — 28 passing tests

**Key decisions**
- `JobListing` is a frozen dataclass (immutable, hashable); Pydantic only for external data
- `Literal` types for `RemotePolicy`/`Seniority` (not Enum — serializes as plain string)
- Config uses lazy singleton to avoid breaking tests at import time
- Adzuna adapter does not apply salary/city filters at API level — German listings rarely disclose salary; city filtering would drop remote roles

---

## Day 2 — 2026-03-18

**Goal:** Hard filter, SQLite cache, pipeline orchestrator.

**Files created**
- `src/jobscout/filters/hard_filter.py` — `apply_hard_filter()` with 6 predicates: seniority → company → exclude keywords → require keywords (word-boundary regex) → salary → location
- `src/jobscout/storage/db.py` — `JobDatabase` context manager; `filter_unseen()` via batch SQL; `mark_seen_bulk()` with `INSERT OR IGNORE`
- `src/jobscout/run.py` — pipeline orchestrator; config-driven adapter registry; `--dry-run`, `--verbose`, `--max-results` CLI flags
- `tests/test_filter.py` — 36 passing tests
- `tests/test_db.py` — 14 passing tests (all use `:memory:` SQLite)

**Key decisions**
- Predicate order: seniority → company → exclude → require → salary → location (cheapest/most-aggressive first)
- `not_specified` seniority and `None` salary → benefit of the doubt (always pass)
- `require_any_keyword` uses `\b` word-boundary regex to prevent "ML" matching "XML"/"email"
- `filter_unseen` uses a single batch SQL query, not N individual lookups
- Dry-run skips all DB writes including `mark_seen_bulk`

---

## Day 3 (session 1) — 2026-03-19

**Goal:** Smoke test existing pipeline; fix bugs found during first real run.

**Bugs fixed**
- **SSL cert missing**: Conda sets `SSL_CERT_FILE=$CONDA_PREFIX/ssl/cacert.pem` on activation, but `ssl/` dir wasn't created. Fixed by copying from `Library/ssl/cacert.pem`.
- **Adzuna query returns 0 results**: `what = " ".join(target_roles)` sends a long phrase as an AND match → no results. Fixed by switching to `what_or` with ML-specific keywords (`"machine learning MLOps NLP AI engineer data scientist"`).
- **Location filter drops all jobs**: `target_countries = ["Germany"]` checked against Adzuna location strings like `"Berlin"` or `"Frankfurt am Main, Hessen"` — never matches. Fixed in two places:
  - `adzuna.py` `_normalize()`: appends `, Germany` to city-only location strings (all `/de/` results are Germany jobs)
  - `profile.yaml`: added `"Deutschland"` to `target_countries` for locations Adzuna returns in German

**Pipeline smoke test result**
```
50 jobs fetched → 32 passed hard filter (36% filtered)
```
End-to-end flow confirmed working through the hard filter stage.

**Next: Day 3 proper**
- `ranking/embedder.py` + `ranking/scorer.py` + `tests/test_ranking.py`

---

## Day 3 (session 2) — 2026-03-19

**Goal:** Embed + Rank stage.

**Files created**
- `src/jobscout/ranking/embedder.py` — `ProfileEmbedder` class; eager model load; profile text from `target_roles` + `skills.strong` + `skills.working_knowledge`; profile embedding cached (invalidates on text change); jobs encoded in a single batched call; `normalize_embeddings=True` hardcoded
- `src/jobscout/ranking/scorer.py` — `rank_jobs(jobs, profile, embedder)` function; cosine similarity via dot product on L2-normalised vectors; returns `list[ScoredJob]` sorted descending; returns early on empty input
- `tests/test_ranking.py` — 5 tests; module-scoped embedder fixture (loads once); ML job vs Software Engineer job; asserts ranking, sort order, score range, edge cases

**Files modified**
- `src/jobscout/run.py` — return type `list[JobListing]` → `list[ScoredJob]`; embedder constructed once; filter+rank unified into single code path after if/else dedup block; `JobListing` import restored
- `CLAUDE.md` — model updated from `all-MiniLM-L6-v2` to `multi-qa-MiniLM-L6-cos-v1`

**Key decisions**
- `multi-qa-MiniLM-L6-cos-v1` over `all-MiniLM-L6-v2`: same speed/size, trained for asymmetric semantic search (short query vs long document), 512-token limit vs 256
- Profile text: `target_roles` + `skills.strong` + `skills.working_knowledge` only — no location/salary/seniority (hard filter handles those; pollutes semantic signal)
- Job text: `"{title}. {description}"` only — company excluded (noise), no structural fields
- `rank_jobs` returns all ranked results — top-N cutoff is the LLM evaluator's responsibility
- `ProfileEmbedder` model_name is a constructor parameter (default = `multi-qa-MiniLM-L6-cos-v1`) — flexible for test injection

**Post-review fixes (simplify pass)**
- `ProfileEmbedder()` was being instantiated twice in `run.py` (once per branch) — unified to single construction before the if/else block
- Missing `JobListing` import in `run.py` — restored
- Duplicate filter+rank lines across dry-run and non-dry-run paths — deduplicated into single code path
- `test_empty_input_returns_empty` was creating a new `ProfileEmbedder()` — switched to module-scoped fixture

**Test count:** 83 passing
