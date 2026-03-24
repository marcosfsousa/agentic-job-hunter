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

---

## Day 4 — 2026-03-20

**Goal:** LLM Evaluate stage.

**Files created**
- `src/jobscout/evaluation/prompt.py` — `SYSTEM_PROMPT` constant + `build_prompt(job, profile) -> str`; profile sections (roles, strong skills, working knowledge) + job fields (title, company, location, description)
- `src/jobscout/evaluation/evaluator.py` — `evaluate_jobs()`: sequential calls, top-25 slice, graceful per-job failure (`llm_score=None`), `final_score = 0.4 * embedding + 0.6 * (match_score / 10)`; private `_evaluate_one()` handles API call + JSON parse + Pydantic validation
- `tests/test_evaluation.py` — 9 tests: success path, API failure, bad JSON, top_n slicing, empty input, partial failure, prompt content

**Files modified**
- `src/jobscout/config.py` — added `llm_model: str = "claude-haiku-4-5-20251001"` (single field to swap models pipeline-wide)
- `src/jobscout/run.py` — wired `evaluate_jobs` after `rank_jobs`; `anthropic.AsyncAnthropic` client constructed once in pipeline

**Key decisions**
- Sequential Haiku calls — predictable rate limit behaviour; parallel rejected
- On evaluation failure: retain job with `llm_score=None`, never drop
- Return top 25 only — delivery stage only sees evaluated jobs
- `model` is a parameter, not hardcoded — `config.llm_model` is the single change point

**Post-review fixes (simplify pass)**
- `_SYSTEM` / `SYSTEM_PROMPT = _SYSTEM` alias removed — constant named `SYSTEM_PROMPT` directly
- `max_tokens` reduced 512 → 256 (typical response ~100–150 tokens; 256 gives adequate buffer with lower p99 latency)

**Test count:** 92 passing

---

## Day 5 — 2026-03-20

**Goal:** Deliver stage + end-to-end smoke test.

**Files created**
- `src/jobscout/delivery/formatter.py` — `format_digest(jobs, run_date)`: filters to evaluated jobs only, renders rank/title/company/location/salary/score/skills/gaps/explanation/URL as markdown; `_format_job()` + `_format_salary()` helpers
- `src/jobscout/delivery/writer.py` — `write_digest(content, digests_dir, run_date)`: writes `digests/YYYY-MM-DD.md`; creates dir if needed; silent overwrite on same-day re-run
- `src/jobscout/delivery/email_sender.py` — `send_digest(content, config, run_date)`: markdown → HTML via `markdown` lib; SMTP with STARTTLS; skips silently if credentials missing; `_is_configured()` guard

**Files modified**
- `src/jobscout/config.py` — replaced Telegram fields with SMTP credentials (`smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `email_to`, `email_from`); all optional, all from env vars; switched `anthropic_api_key` → `openai_api_key`; `llm_model` default → `gpt-4o-mini`
- `src/jobscout/evaluation/evaluator.py` — swapped `anthropic.AsyncAnthropic` → `openai.AsyncOpenAI`; `messages.create` → `chat.completions.create`; `content[0].text` → `choices[0].message.content`
- `src/jobscout/run.py` — wired `format_digest → write_digest → send_digest` after evaluation; `run_date = date.today()` captured once and passed to all three to prevent midnight race condition
- `tests/test_evaluation.py` — all mocks updated to OpenAI response shape (`chat.completions.create`, `choices[0].message.content`)
- `pyproject.toml` — replaced `python-telegram-bot` with `markdown>=3.7` and `openai>=1.0`

**Key decisions**
- Email over Telegram — user preference; HTML body via `markdown` lib, plain text fallback attached (RFC 2046 multipart/alternative)
- `gpt-4o-mini` over Claude Haiku — Anthropic credits exhausted; gpt-4o-mini is the direct equivalent (fast, cheap, strong JSON output)
- `run_date` captured once in `run.py` and threaded to all three delivery functions — eliminates midnight date mismatch between filename, header, and email subject
- `server.ehlo()` removed — `starttls()` calls it internally; explicit call was a redundant round-trip

**Post-review fixes (simplify pass)**
- Redundant `server.ehlo()` removed from `email_sender.py`
- `header +=` mutation in `format_digest` replaced with two distinct variables (`title`, `count`)
- `run_date` passed explicitly to all delivery functions (race condition fix)

**Smoke test result (dry-run, 2026-03-20)**
```
100 fetched → 74 hard filter → 25 evaluated (gpt-4o-mini) → digest written
Score range: 5–9/10 | Best match: Kiwigrid ML Engineer (9/10)
```

**Test count:** 92 passing

---

## Day 6 — 2026-03-21

**Goal:** Delivery tests, first real pipeline run, deduplication verification, evaluation prompt tuning.

**Files created**
- `tests/test_delivery.py` — 29 tests covering `formatter.py`, `writer.py`, `email_sender.py`; `_mock_smtp()` context manager helper; `tmp_path` for file I/O; no network calls

**Files modified**
- `src/jobscout/evaluation/prompt.py` — tightened `matching_skills` instruction: prefer distinctive skills over generic ones (e.g. RAG systems over Python/Docker), prefer strong-list skills when both tiers match, only include skills the job specifically calls for

**Key decisions**
- `_mock_smtp(enter_side_effect=None)` context manager extracts the repeated 4-line SMTP patch setup shared across `TestSendDigest` tests
- `_make_scored_job` in `test_delivery.py` takes `salary_min`/`salary_max` kwargs — avoids manual `JobListing` reconstruction for the no-salary test case
- Prompt tuning: rewrote the `matching_skills` field description only; no changes to `build_prompt()`, profile format, or evaluator — the two-tier profile (`Strong skills` / `Working knowledge`) already gives the LLM the signal it needs
- Validated prompt change with a live 5-job eval: Merantix Momentum NLP went from `[Python, PyTorch, TensorFlow]` → `[RAG systems, LangChain, Vector DBs, LLM dev, Prompt eng]`

**First real pipeline run (2026-03-21)**
```
100 fetched → 25 passed hard filter → 25 evaluated (gpt-4o-mini) → digest written
Score range: 3–10/10 | Best match: Freenow ML Engineer (10/10), Dropbox ML Engineer (9/10)
Deduplication: second run returned 0 new jobs — idempotency confirmed
```

**Test count:** 129 passing

---

## Day 7 — 2026-03-21

**Goal:** Resend email delivery, JSearch second source adapter, feedback loop to DB.

**Files created**
- `src/jobscout/adapters/jsearch.py` — JSearch adapter via OpenWebNinja API; single call with `num_pages`; no salary fields; `job_is_remote=True` overrides inference
- `src/jobscout/adapters/inference.py` — shared `_infer_remote_policy`, `_infer_seniority`, `_parse_date` extracted from both adapters
- `tests/fixtures/sample_jsearch_response.json` — 3-listing fixture for JSearch tests
- `docs/handoff_day7.md` — session handoff

**Files modified**
- `src/jobscout/delivery/email_sender.py` — replaced smtplib with Resend SDK; `send_digest` made `async`; `asyncio.to_thread()` wraps sync Resend call
- `src/jobscout/adapters/adzuna.py` — removed duplicate inference helpers; imports from `inference.py`
- `src/jobscout/storage/db.py` — added `feedback` table; `upsert_feedback`, `filter_feedback`, `_id_source_params` helper
- `src/jobscout/models.py` — removed `MarketsConfig`; added `FeedbackStatus` and `FeedbackEntry`
- `src/jobscout/config.py` — removed SMTP fields; added `resend_api_key`, `open_web_ninja_api_key`, `email_to`, `email_from`
- `src/jobscout/run.py` — parallel ingest via `asyncio.gather()`; feedback sync + filter; `--apply-feedback` flag; fixed missing `await send_digest`
- `profile.yaml` — removed `markets` block
- `.env.example` — added Resend and JSearch entries
- `pyproject.toml` — added `resend>=2.0`
- `tests/test_adapters.py` — added JSearch tests (20 new)
- `tests/test_db.py` — added feedback tests (12 new)
- `tests/test_delivery.py` — updated SMTP mocks to Resend SDK mocks

**Key decisions**
- Key-presence gates sources: `_ADAPTER_REGISTRY` runs all adapters; each self-disables without a key. Removed `markets.active` from `profile.yaml` — it conflated source selection with user preferences and wasn't a real market selector.
- Shared `inference.py`: three identical helpers extracted from both adapters to eliminate duplication and give keyword lists a single source of truth.
- Feedback design: `data/feedback.yaml` → DB `feedback` table → filter step between dedup and hard filter. `applied`/`rejected` suppress future appearances; `interested` passes through. No ranking influence yet.
- `FeedbackEntry` moved to `models.py` — all domain models belong there, not in entry points.

**Bug fixed**
- `send_digest` was called without `await` in `run.py` after being made `async` — email was silently skipped on every pipeline run.

**Test count:** 159 passing

---

## Day 8 — 2026-03-21

**Goal:** Feedback centroid ranking signal — use `interested` history to boost similar new jobs.

**Files modified**
- `src/jobscout/config.py` — added `feedback_weight: float = 0.2` to `AppConfig`; loaded from `FEEDBACK_WEIGHT` env var; `@field_validator` enforces range `[0, 1]`
- `src/jobscout/storage/db.py` — added nullable `title TEXT` and `description TEXT` columns to `seen_jobs`; `mark_seen_bulk` now stores job text; new `get_interested_descriptions()` method (JOIN on feedback table, returns `"{title}. {description}"` strings)
- `src/jobscout/ranking/embedder.py` — added `encode_texts(list[str])` method; `encode_jobs` refactored to delegate to it
- `src/jobscout/ranking/scorer.py` — `rank_jobs` accepts `feedback_docs: list[str] | None` and `feedback_weight: float`; computes centroid of feedback embeddings, normalises, and blends: `(1 - w) * profile_score + w * centroid_score`
- `src/jobscout/run.py` — loads `feedback_docs` from DB inside context block; passes to `rank_jobs` with `config.feedback_weight`; `send_digest` now skipped on `--dry-run`; email format fixed (`nl2br` extension + Score/Location/Remote on separate lines)
- `src/jobscout/delivery/formatter.py` — Score/Location/Remote split into separate lines (were string-concatenated into one)
- `src/jobscout/delivery/email_sender.py` — added `nl2br` to markdown extensions so single newlines render as `<br>` in HTML
- `tests/test_db.py` — 4 new tests: text storage in `mark_seen_bulk`, `get_interested_descriptions` join correctness, NULL guard
- `tests/test_ranking.py` — 2 new tests: no-op with empty feedback docs, centroid widens score gap

**Key decisions**
- `interested` only in centroid — `applied` may reflect necessity not preference
- `feedback_weight` lives in `AppConfig` (pipeline config, not user preference) — overridable via env var
- No threshold: 0.2 weight limits noise from sparse data; activates from first `interested` job
- Job text stored in `seen_jobs` (nullable columns) — no migration needed for fresh DB; backward compatible schema
- `--dry-run` now skips email delivery (previously sent real emails)
- `encode_jobs` delegates to `encode_texts` — single encode call site in embedder

**Bug fixed**
- `--dry-run` was sending real emails — guarded `send_digest` with `if not dry_run`

**Schema change**
- `seen_jobs` table has new nullable columns — delete `data/jobscout.db` and rebuild when upgrading

**Smoke test result (2026-03-21)**
```
156 jobs stored — 0 NULL titles/descriptions — feedback table empty (no feedback.yaml yet)
Email delivered with corrected per-line formatting
```

**Test count:** 166 passing

---

## Day 9 — 2026-03-24

**Goal:** JSearch null description fix, email score threshold, job ID in digest, `--since` flag, misc pipeline fixes.

**Files modified**
- `src/jobscout/adapters/base.py` — added `filter_by_since(listings, since)` shared helper; updated `fetch()` abstract signature to accept `since: date | None = None`
- `src/jobscout/adapters/jsearch.py` — `job_description: str | None = None` (was `str = ""`); added `job_highlights: dict | None = None`; `_highlights_to_text()` fallback when description is null; `_since_to_date_posted()` maps a date to JSearch's fixed `date_posted` buckets; post-filter via `filter_by_since()`; `_DatePostedBucket` Literal type
- `src/jobscout/adapters/adzuna.py` — `since` param; passes `max_days_old` to API to reduce pages fetched; post-filter via `filter_by_since()`
- `src/jobscout/models.py` — added `email_min_score: int = Field(default=7, ge=1, le=10)` to `UserProfile`
- `src/jobscout/delivery/formatter.py` — added `**ID:** {id} | **Source:** {source}` line to each job card
- `src/jobscout/run.py` — email now filtered to `evaluation.match_score >= email_min_score`; file digest still contains all evaluated jobs; email skipped entirely (with INFO log) when no jobs qualify; `--since YYYY-MM-DD` CLI flag; `since` threaded to all adapter `fetch()` calls
- `profile.yaml` — added `email_min_score: 7`
- `tests/fixtures/sample_jsearch_response.json` — added jsearch_004 (null description + highlights) and jsearch_005 (both null)
- `tests/test_adapters.py` — tests for null description, highlights fallback, `_since_to_date_posted` mapping, `filter_by_since` post-filter behaviour
- `tests/test_delivery.py` — test for ID/source in digest output

**Key decisions**
- JSearch null description: allow `None`, fall back to `job_highlights` dict (flattened to text), then `""` — keeps listing in pipeline rather than dropping it; 35/53 JSearch listings were being dropped before this fix
- Email threshold in `profile.yaml` (`email_min_score`): user-tunable preference; file digest always contains full archive; only email is filtered
- Email skip guard: `send_digest` not called when `email_jobs` is empty — avoids sending "No evaluated matches" emails
- `filter_by_since` extracted to `base.py`: identical post-filter logic was duplicated across both adapters; shared helper eliminates duplication and is tested directly
- `--since` uses the tightest available JSearch `date_posted` bucket; Adzuna gets `max_days_old` to reduce pages fetched; both apply an exact post-filter on `posted_date` regardless
- Jobs with `posted_date = None` always pass the `--since` filter (conservative — don't discard potentially good jobs)

**Bugs fixed**
- JSearch dropped 35/53 listings due to `job_description: null` failing Pydantic `str` validation
- Pipeline could send up to 3 emails per day if run multiple times (investigated; caused by running verbose + non-verbose runs in same session — no code bug, operational issue)

**Test count:** 185 passing
