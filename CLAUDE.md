# CLAUDE.md — JobScout Project Instructions

## Project overview

JobScout is a personal AI job matching pipeline. It ingests job listings from
external APIs, filters them against a user profile, ranks them using embeddings
and LLM evaluation, and delivers a daily digest via Telegram or markdown.

The goal is fewer, higher-quality matches — not maximum applications sent.
This tool finds and ranks jobs. The user decides what to apply to.

## Architecture

Pipeline stages: **Ingest → Hard Filter → Embed + Rank → LLM Evaluate → Deliver**

- Each stage is a separate module under `src/jobscout/`
- **Adapters** (`src/jobscout/adapters/`) are pluggable per-market job sources — adding a new market means adding a new adapter file and registering it in config, nothing else
- **Profile config** lives in `profile.yaml` at the project root — single source of truth for all user preferences
- **SQLite database** at `data/jobscout.db` for deduplication and feedback
- **No vector store** needed — in-memory numpy cosine similarity is sufficient at this scale (50–200 jobs/day)

## Directory structure

```
src/jobscout/
├── run.py               # Main pipeline entrypoint
├── config.py            # Loads profile.yaml + env vars
├── models.py            # JobListing dataclass + EvaluationResult
├── adapters/
│   ├── base.py          # Abstract adapter interface
│   ├── adzuna.py        # Adzuna API adapter (Germany)
│   └── jsearch.py       # JSearch/RapidAPI adapter (future)
├── filters/
│   └── hard_filter.py   # Deterministic rules-based filter
├── ranking/
│   ├── embedder.py      # Profile + job embedding logic
│   └── scorer.py        # Cosine similarity ranking
├── evaluation/
│   └── llm_judge.py     # Claude Haiku fit evaluation
├── delivery/
│   ├── markdown.py      # Local .md digest writer
│   └── telegram.py      # Telegram bot delivery
└── storage/
    └── db.py            # SQLite seen-jobs cache + feedback
```

## Code conventions

- Python 3.11+, type hints everywhere, dataclasses for data structures
- Pydantic for validation of external data (API responses)
- Use `httpx` (async) for all HTTP calls, not `requests`
- Use `pathlib.Path`, not `os.path`
- All config loaded via `src/jobscout/config.py` — never hardcode paths or keys
- Logging via Python stdlib `logging`, not `print()`
- Tests in `tests/` using pytest; API response fixtures in `tests/fixtures/`

## Key files

- `profile.yaml` — User profile (skills, preferences, dealbreakers)
- `src/jobscout/models.py` — Core data models (`JobListing`, `EvaluationResult`)
- `src/jobscout/adapters/base.py` — Abstract adapter interface all adapters must follow
- `src/jobscout/run.py` — Main pipeline orchestrator
- `src/jobscout/config.py` — Config loading and validation

## How to run

```bash
conda activate jobscout
python -m jobscout.run           # Full pipeline
python -m jobscout.run --dry-run # Fetch + filter + rank, skip delivery
python -m pytest tests/          # Run tests
```

## Environment

- API keys in `.env` (loaded via python-dotenv, gitignored)
- Conda environment: `jobscout` (Python 3.11)
- No Docker needed for development

Required keys:
- `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` — job data source
- `ANTHROPIC_API_KEY` — LLM evaluation (Claude Haiku)
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — delivery

## Important constraints

- **NEVER auto-apply to jobs.** This tool only finds and ranks listings.
- **Keep API costs minimal:** use Claude Haiku for evaluation (not Sonnet), local `all-MiniLM-L6-v2` embeddings for ranking.
- **LLM evaluation runs on top 20–30 jobs only**, after hard filter and embedding ranking have already reduced the candidate pool.
- **The adapter pattern must stay clean** — adding a new job source should only require a new file in `adapters/` and a config registration. No changes to pipeline stages.
- **`profile.yaml` is the single source of truth** for user preferences. No hardcoded filters anywhere in pipeline code.
- **SQLite only** for persistence. No external databases.
- **Pipeline must be idempotent** — running twice on the same day produces the same digest (deduplication via seen_jobs cache).

## Composite scoring

Final ranking uses: `final_score = 0.4 * embedding_similarity + 0.6 * llm_score`

LLM evaluation (Claude Haiku) returns structured JSON:
- `match_score` (1–10)
- `matching_skills` (list)
- `gaps` (list)
- `explanation` (one-line string)

## When making changes

- Run `pytest` after any change to models, filters, or ranking
- If modifying the LLM evaluation prompt, test with at least 5 real job listings
- If adding a new adapter, follow the interface in `adapters/base.py` exactly
- Hard filter is deterministic and cheap — keep it that way (no LLM calls here)
- The hard filter runs before any embedding or LLM work, eliminating ~80% of noise

## Build log

### Day 1 — 2026-03-17 (complete)

**Environment**
- Created `jobscout` conda environment (Python 3.11)
- Installed all dependencies via `pip install` and `pip install -e .[dev]`

**Files built**
- `pyproject.toml` — package metadata, dependencies, pytest config (`asyncio_mode=auto`)
- `profile.yaml` — Marcos's full search profile (Germany, ML/AI roles, €50K floor)
- `src/jobscout/models.py` — `JobListing` (frozen dataclass), `EvaluationResult` (Pydantic, score bounded 1–10), `ScoredJob` (frozen dataclass wrapping listing + scores), `UserProfile` and sub-models (Pydantic)
- `src/jobscout/config.py` — `AppConfig` (Pydantic), lazy singleton `get_config()`, `reset_config()` for tests; loads `profile.yaml` + env vars; required keys fail at load time, Telegram keys optional
- `src/jobscout/adapters/base.py` — `JobAdapter` ABC (`async fetch(max_results)`, abstract `source` property), `JobScoutAdapterError` for retriable failures
- `src/jobscout/adapters/adzuna.py` — `AdzunaAdapter`: `AdzunaJobRaw` Pydantic validation, `_infer_remote_policy()`, `_infer_seniority()`, `_parse_date()` as standalone testable helpers; paginates Adzuna Germany endpoint; discards predicted salaries (`salary_is_predicted=1`)
- `tests/fixtures/sample_adzuna_response.json` — 3-listing fixture (senior/remote, junior/hybrid, remote/no-salary)
- `tests/test_adapters.py` — 28 passing tests covering inference helpers, date parsing, Pydantic validation, normalization, and immutability

**Key design decisions made**
- `JobListing` is a frozen dataclass (immutable, hashable); Pydantic only for external data
- `Literal` types for `RemotePolicy` and `Seniority` (not Enum — serializes as plain string)
- `ScoredJob` is separate from `JobListing` to keep the listing model pure
- Config uses a lazy singleton (not eager import-time load) to avoid breaking tests
- Adzuna adapter does not apply salary or city filters at the API level — German listings rarely disclose salary; city filtering would drop remote roles
- `_normalize()` and inference helpers are private but module-level for independent testability without HTTP mocking

---

## Future extensions (not in scope for MVP)

Do not build these during the initial sprint:
- Feedback loop (thumbs-up/down data to adjust scoring weights)
- Additional markets (Portugal, Netherlands, remote-global)
- Company research agent
- Application tracker / CRM
- Skill gap dashboard
- LangGraph orchestration
