# Build Log

Chronological record of what was built each session.

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

---

## Day 10 — 2026-03-24

**Goal:** Cross-source deduplication, false positive triage from digest review.

**Files created**
- `src/jobscout/filters/dedup.py` — `_fingerprint(title, company)` normaliser + `deduplicate_listings()`
- `tests/test_dedup.py` — 11 tests covering fingerprint normalisation, cross-source dedup, within-source dedup, longest-description selection, abbreviation expansion, punctuation stripping, location exclusion
- `docs/plan-cross-source-dedup.md` — design doc for dedup approach

**Files modified**
- `src/jobscout/run.py` — wired `deduplicate_listings` into pipeline after `mark_seen_bulk`; import added
- `profile.yaml` — added `"audio"` and `"QA"` to `dealbreakers.exclude_keywords` after triage of first real digests

**Key decisions**
- Fingerprint on `title + company` only — location excluded because remote jobs have inconsistent location data, and same role in two cities is likely one hire
- All unseen jobs marked seen *before* dedup — ensures neither variant of a duplicate resurfaces on the next run; best listing (longest description) is selected for the current run
- Abbreviation expansion (`sr→senior`, `ml→machine learning`, etc.) at fingerprint time prevents the same role with abbreviated vs full titles from being treated as distinct
- `"audio"` and `"QA"` added as hard excludes after reviewing real digest output and finding them as consistent false positives

**Test count:** 196 passing

---

## Day 11 — 2026-03-25

**Goal:** Fix dormant feedback centroid signal; add `--review` interactive labeling mode.

**Files created**
- *(none)*

**Files modified**
- `src/jobscout/models.py` — added `"skipped"` to `FeedbackStatus` Literal
- `src/jobscout/config.py` — added `feedback_path` property to `AppConfig` (eliminates 3 duplicated path expressions)
- `src/jobscout/storage/db.py` — extended `get_interested_descriptions()` to include `applied` status; added `company TEXT` column to `seen_jobs` with `ALTER TABLE` migration; added `first_seen` index; added `get_unreviewed_for_date(dt)` method; updated `mark_seen_bulk` to store `company`
- `src/jobscout/run.py` — implemented `_run_review(review_date)`; added `--review [YYYY-MM-DD]` CLI flag; replaced all inline `feedback_path` expressions with `config.feedback_path`; hoisted `status_map` outside loop
- `tests/test_db.py` — renamed `test_returns_text_for_interested_only` → `test_returns_text_for_interested_and_applied`; updated assertion to include `applied` entries; added `TestGetUnreviewedForDate` (5 tests)

**Key decisions**
- `applied` added to centroid signal — user's workflow is apply-or-reject (never `interested`), so `applied` is the only available positive signal; semantically stronger than `interested` anyway
- `skipped` tracked in DB only, not written to `feedback.yaml` — keeps yaml clean for human review; skip is an ephemeral cursor state, not meaningful feedback
- `--review` reads from `seen_jobs` (title + company), not the digest file — avoids fragile markdown parsing; user reads digest side-by-side
- DB connection held open during interactive loop — safe for single-user local SQLite; context manager guarantees cleanup
- `ALTER TABLE ADD COLUMN` migration re-raises on any `OperationalError` that isn't "duplicate column name" — avoids silently swallowing unrelated DB errors
- `feedback_path` moved to `AppConfig` property — was duplicated in 3 places in `run.py`

**Test count:** 201 passing

**Also this session — LLM scoring calibration**

Root cause: gpt-4o-mini was inflating scores (8–9 for mediocre fits) because the profile sent to the evaluator was too thin — just a skills list, no experience context, no ideal role description, no penalisation rules.

**Files modified (second pass)**
- `profile.yaml` — added `background`, `ideal_role`, `deprioritise` free-text fields; expanded `target_roles` (added `AI Application Engineer`, `GenAI Engineer`, `LLM Engineer`, `AI Software Engineer`); expanded `skills.strong` (NLP pipelines, agentic systems, OpenAI API); moved PyTorch/TensorFlow to `learning`; added `Kubernetes`, `Big Data`, `Recommendation Engine`, `Computer Vision` to `exclude_keywords`; expanded `require_any_keyword`; lowered `email_min_score` to 5
- `src/jobscout/models.py` — added `background: str`, `ideal_role: str`, `deprioritise: list[str]` optional fields to `UserProfile`
- `src/jobscout/evaluation/prompt.py` — full rewrite: explicit 3-step scoring process (base score → adjustments → cap); base score of 6 for reasonable overlap, 4 for weak overlap; degree penalty split into -2 (hard mandatory) vs -1 (comparable accepted); removed German language penalty (candidate targets Germany and speaks German); added -1 for MLOps/cloud as core, -1 for senior level, -1 for non-tech company without AI unit; boosts for LLM/RAG ownership (+1), specialist AI unit (+1), explicit LangChain/RAG/vector DB in stack (+1); `build_prompt()` now injects `background`, `ideal_role`, and `deprioritise` from profile; cap at 9

**Key decisions**
- `--review` surfaces all 18 `seen_jobs` entries but user only had context for 8 (the digest jobs) — known gap, fix deferred: will store evaluated job IDs at pipeline time so `--review` can filter to digest-only jobs
- German language penalty removed from prompt: candidate targets Germany and speaks German; penalising all German-requirement roles would incorrectly downrank valid fits like ML Reply
- Degree penalty split: "CS or comparable" is -1 not -2 — ML Reply uses this phrasing and should score ~8, which validated the calibration
- Stack boost (+1 for LangChain/RAG/vector DB explicitly named) added to create ceiling room — without it, most roles cap at 7 even with both other boosts
- Validated calibration by manually scoring ML Reply JD: expected ~8, confirmed the rules produce that result after fixes

---

## Day 12 — 2026-03-26

**Goal:** Fix `--review` to only surface jobs that appeared in the digest (scored >= `email_min_score`), not all `seen_jobs`.

**Files created**
- *(none)*

**Files modified**
- `src/jobscout/storage/db.py` — added `_CREATE_DIGEST_JOBS` DDL (`digest_jobs` table: `id, source, digest_date`, PK on all three); table created in `__enter__`; added `mark_in_digest(ids_sources, digest_date)` — bulk insert, idempotent; added `get_unreviewed_for_digest(dt)` — JOINs `seen_jobs` with `digest_jobs`, excludes rows with any feedback entry
- `src/jobscout/run.py` — `_run_review` now calls `get_unreviewed_for_digest` instead of `get_unreviewed_for_date`; empty result prints a clear message and exits (no fallback to seen_jobs); pipeline calls `mark_in_digest` after computing `email_jobs`, inside `if not dry_run` block, before `send_digest`
- `tests/test_db.py` — added `TestDigestTracking` (7 tests): insert, idempotent, empty noop, digest-only filtering, excludes reviewed, untracked date returns empty, title/company fields

**Key decisions**
- "In digest" = `email_jobs` (jobs scoring >= `email_min_score`), not all LLM-evaluated jobs — these are what get emailed and what the user has context to review
- `mark_in_digest` accepts `list[tuple[str, str]]` (id, source pairs), not `list[ScoredJob]` — keeps storage layer free of domain model imports; unwrapping done at call site in `run.py`
- `mark_in_digest` called before `send_digest` — digest jobs are recorded regardless of whether email delivery succeeds
- Empty result on `--review`: prints "No digest jobs recorded for {date}. Either no jobs met the score threshold, or this date predates digest tracking." and exits — no fallback to `get_unreviewed_for_date` (that would show jobs the user never saw, reintroducing the bug)
- Schema migration safe: `CREATE TABLE IF NOT EXISTS` — existing DBs get the new table on next open, old digest dates simply return empty from `get_unreviewed_for_digest`
- `digest_date.isoformat()` hoisted out of list comprehension in `mark_in_digest` — computed once per call

**Test count:** 217 passing

---

## Day 13 — 2026-03-27

**Goal:** GitHub Actions daily scheduler + blocked job board URL fix.

**Files created**
- `.github/workflows/daily_run.yml` — cron `0 6 * * *` (7am CET) + `workflow_dispatch`; pip + HuggingFace model caching; pytest on non-schedule runs; `git commit [skip ci]` + push to persist `data/jobscout.db` and `data/feedback.yaml`; Resend failure email on `if: failure()`; `concurrency` guard to prevent overlapping runs; Node.js 24 opt-in (`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`)

**Files modified**
- `.gitignore` — replaced `data/` with `data/*` + `!data/jobscout.db` + `!data/feedback.yaml` so DB and feedback file are tracked by git
- `src/jobscout/adapters/jsearch.py` — added `_BLOCKED_DOMAINS` (`stepstone.de`, `xing.com`, `monster.de`) and `_resolve_url()` which substitutes a Google search URL (`site:{domain}`) for apply links from boards that block direct access
- `tests/fixtures/sample_jsearch_response.json` — added jsearch_006 fixture with a StepStone apply URL
- `tests/test_adapters.py` — added `TestResolveUrl` (6 tests) and two new cases in `TestJSearchNormalize`

**Key decisions**
- DB persistence via git commit-back — simple, no extra infra, no secrets in data
- HuggingFace cache keyed on model name only (stable); kept warm by daily runs
- `pytest` skipped on `schedule` trigger (code unchanged between daily runs)
- `job_google_link` from JSearch is undocumented/unreliable — constructed Google search URL from title + company + `site:domain` instead
- Blocked domain list is small and unlikely to grow; LinkedIn/Indeed work fine as direct links

---

## Day 14 — 2026-03-31

**Goal:** Scoring calibration review, JSearch ID stability investigation, fingerprint-based DB dedup, multi-query JSearch.

**Files modified**
- `src/jobscout/evaluation/prompt.py` — Full scoring rubric rewrite:
  - German language promoted from soft `deprioritise` signal to hard `-2 pts` penalty
  - Experience penalty split: `-1 pt` for 2–4yr AI/ML-specific, `-2 pts` for 5+yr; both clarified as AI/ML-specific (general SWE experience does NOT trigger penalty — candidate has 2.5yr SWE)
  - Cloud platform penalty added: `-1 pt` for strong/extensive AWS/GCP/Azure as core competency
  - Step 2 restructured into `2a. Boosts (apply first)` and `2b. Hard penalties (apply to boosted score; boosts do not offset penalties)`
- `src/jobscout/filters/dedup.py` — `_fingerprint` renamed to `job_fingerprint` (now public); `company` param typed as `str | None`; `normalize()` handles `None` via `company or ''`
- `src/jobscout/storage/db.py` — Added `fingerprint TEXT` column to `seen_jobs` with index; backfill on `__enter__` for all NULL-fingerprint rows; `filter_unseen` upgraded to two-step check (ID lookup then fingerprint check); `mark_seen_bulk` now stores fingerprint column
- `src/jobscout/adapters/jsearch.py` — Multi-query support: `fetch()` iterates `profile.jsearch_queries` and calls `_fetch_query` per query; single shared `httpx.AsyncClient` across all queries (avoids repeated TLS handshakes); `_fetch_query` now accepts `client` as a parameter
- `src/jobscout/models.py` — Added `jsearch_queries: list[str]` to `UserProfile` with default `["machine learning engineer in Germany"]`
- `profile.yaml` — Added `jsearch_queries` section with 3 targeted queries replacing the old broad query
- `tests/test_db.py` — 4 new fingerprint tests: `test_fingerprint_blocks_same_job_with_new_id`, `test_fingerprint_does_not_block_different_job_same_source`, `test_fingerprint_stored_on_insert`, `test_backfill_sets_fingerprint_for_legacy_rows`; existing tests updated with distinct titles to avoid fingerprint collisions
- `tests/test_dedup.py` — Import updated from `_fingerprint` to `job_fingerprint`

**Key decisions**
- German as hard -2: previously only a soft `deprioritise` signal — NETCONOMY scored 7/10 despite German being a hard stated condition. Promoted to hard penalty so boosts (+2 max) cannot cancel it.
- Boosts-before-penalties ordering explicit in prompt: prevents "boosted score" from cancelling a hard penalty retroactively.
- JSearch ID instability confirmed empirically: 1/18 overlapping jobs (inovex GmbH) returned a different ID across two concurrent identical queries. In-memory `deduplicate_listings()` already protected the LLM budget within a run; DB `filter_unseen` was unprotected for cross-run re-entry.
- Discard on fingerprint hit (not update): if a job re-enters with a new ID, the existing DB record is left unchanged; the duplicate is silently discarded. Updating the ID would require cascading changes across `feedback` and `digest_jobs` tables for no real benefit.
- Sequential JSearch queries (not concurrent): intentional to avoid free-tier rate limits on JSearch API.
- `job_fingerprint` made public: needed by both `dedup.py` and `db.py`; single source of truth.
- `company: str | None` in `job_fingerprint`: 290/570 adzuna_de rows had NULL company — required to avoid `AttributeError` during backfill.

**Bugs fixed**
- `job_fingerprint(title, None)` raised `AttributeError` on `.lower()` — fixed by normalizing as `company or ''`
- Multiple test failures after fingerprint introduction: all `_make_job()` calls used same title/company → same fingerprint → batch tests broke. Fixed with distinct titles per test.
- `test_backfill_sets_fingerprint_for_legacy_rows` returned `None` with `:memory:` SQLite: in-memory DBs don't persist across `with` blocks. Fixed using `tmp_path` fixture with a file-based DB.
- `test_fingerprint_stored_on_insert` wrong expected value: `_ABBREV` expands `ML` → `machine learning`, giving `"machine learning engineer|acme gmbh"` not `"ml engineer|acme gmbh"`.

**Test count:** 229 passing

---

## Day 15 — 2026-03-31

**Goal:** Scoring calibration monitoring, Adzuna query tightening, email threshold tuning, embedding score floor.

**Files modified**
- `src/jobscout/adapters/adzuna.py` — Tightened `what_or` query: removed `MLOps` and `data scientist` (classical ML noise), replaced with `"LLM RAG generative AI engineer NLP LangChain agentic machine learning"` to better target Marcos's stack
- `profile.yaml` — Lowered `email_min_score` from 5 → 4 (temporary); scores are compressed low due to German language requirement dominating LLM penalties
- `src/jobscout/config.py` — Added `embedding_min_score: float = 0.30` field, overridable via `EMBEDDING_MIN_SCORE` env var
- `src/jobscout/run.py` — Added embedding score floor: jobs below `embedding_min_score` are dropped before LLM evaluation, with a log line showing how many were cut
- `src/jobscout/delivery/formatter.py` — Digest score line now shows both LLM and embedding scores (`Score: 4/10 | Embedding: 0.342`) for empirical calibration
- `src/jobscout/evaluation/evaluator.py` — Fixed Pylance error: added `None` guard on `response.choices[0].message.content` before passing to `json.loads`

**Key decisions**
- Embedding floor set at 0.30 (conservative default): two false positives (Data Scientist — Telespazio, Full Stack PropTech) reached LLM evaluation despite zero skill overlap; root cause was no floor + small hard-filter pool (29 jobs → all 25 LLM slots filled including weak matches)
- Embedding scores logged to digest (not just internal): enables empirical tuning of the floor threshold after a week of runs
- `email_min_score` lowered temporarily: all 25 evaluated jobs scored ≤6/10 this run; German language requirement systematically penalises otherwise relevant roles
- Review `email_min_score` scheduled for 2026-04-07

**Test count:** 229 passing

---

## Day 16 — 2026-04-01

**Goal:** JobSpy adapter (LinkedIn + Indeed via python-jobspy), cron shift, ops runbook, pre-commit hook.

**Files created**
- `src/jobscout/adapters/jobspy.py` — `JobSpyAdapter`: sync-only jobspy library bridged to async pipeline via `run_in_executor`; sequential queries × sites loop with 2s pause between calls; `_safe()` NaN/NaT/namedtuple defence; `_sanitize_raw()` two-pass JSON-safe dict; `_since_to_hours_old()` with 6h buffer + 24h floor; German location post-filter; remote listing rescue via German job board domain check (`_is_german_domain`)
- `tests/test_adapter_jobspy.py` — 68 tests covering `_safe`, `_sanitize_raw`, `_is_german`, `_is_german_domain`, `_since_to_hours_old`, `_map_job_level`, `_normalize` (all field mappings), and fetch failure modes
- `.git/hooks/pre-commit` — warn-only hook: fetches origin and warns if local branch is behind (exits 0, never blocks)

**Files modified**
- `pyproject.toml` — added `python-jobspy>=1.1`; relaxed `numpy>=2.4` → `numpy>=1.26` (jobspy installs 1.26.3)
- `src/jobscout/models.py` — added `jobspy_queries: list[str]` and `jobspy_sites: dict` to `UserProfile`
- `profile.yaml` — added `jobspy_queries` (2 queries) and `jobspy_sites` (indeed + linkedin with per-site caps)
- `src/jobscout/run.py` — imported `JobSpyAdapter`; added `"jobspy"` entry to `_ADAPTER_REGISTRY`
- `.github/workflows/daily_run.yml` — shifted cron from `0 6 * * *` → `0 4 * * *` (GitHub Actions queue adds ~1–2h consistently; targeting ~08:00–08:30 CEST delivery)
- `CLAUDE.md` — added `## Git workflow` rule (always pull before editing); added ops-checks pointer to dev-notes
- `docs/dev-notes.md` — added `## Ops checks` section with sqlite/gh CLI commands for pipeline inspection

**Key decisions**
- Sequential loop (not `asyncio.gather`) for jobspy calls — LinkedIn and Indeed rate-limit aggressively; parallel scrapes trigger blocks
- Location fallback is `""` not `"Germany"` — honest about missing data; `_is_german("")` returns False, which triggers the remote rescue path for German-domain listings
- Remote rescue: listings with no location but `remote_policy == "remote"` and a German job board domain (linkedin.com, de.indeed.com, indeed.de) are kept and tagged `"Remote, Germany"` — these are high-value remote AI roles
- `_safe()` try/except guard: `pd.isna()` raises `ValueError` on namedtuples (Location objects) and `TypeError` on unhashable types — both caught, value returned as-is
- `_sanitize_raw()` two-pass: NaN→None first, then JSON round-trip with `default=str` to coerce numpy scalars and Timestamps

**Dry-run result**
```
Adzuna: 100 listings | JSearch: 60 listings | JobSpy: 11 listings (4 calls: 2 queries × 2 sites)
jobspy/indeed "AI engineer Germany" → 25 scraped, kept after German filter
jobspy/linkedin "AI engineer Germany" → 12 scraped
jobspy/indeed "machine learning engineer Berlin Munich Hamburg" → 0 results
jobspy/linkedin "machine learning engineer Berlin Munich Hamburg" → 12 scraped
Remote rescue fired for 9 linkedin.com listings with no location
```

**Test count:** 297 passing

---

## Spec 4 (#29) — 2026-07-23 — e5 embedding swap + freelance ranking query and eval prompt

**Goal:** Repoint the last three pipeline stages (embed → rank → evaluate) at the freelance
corpus. Closes the FTE→freelance pivot map (#3): every decision A–S is now executed.
Branch: `v2-freelance-pivot` (integration branch; not `main`).

**Files modified**
- `src/jobscout/ranking/embedder.py` — model → `intfloat/multilingual-e5-small`; `query:` / `passage:` prefixes applied **per call site** (`encode_profile`=query, `encode_jobs`=passage, new `encode_feedback`=query); `max_seq_length` set explicitly to 512; profile query gains `ideal_role` + `background` (English-only, `skills.learning` excluded); `_Encoder` Protocol seam so tests can inject a recording encoder and assert the prefixes (their only failure mode is silent underperformance).
- `src/jobscout/ranking/scorer.py` — feedback centroid now goes through `encode_feedback` (`query:`-prefixed, so `feedback_weight=0.2` keeps its meaning).
- `src/jobscout/evaluation/prompt.py` — deleted the 2–4yr, 5+yr, and €80k penalties; added a graded (0–3) ramp-up-risk criterion judged on deliverable evidence, and a flat 3-pt below-100%-remote backstop; kept the German penalty.
- `src/jobscout/evaluation/evaluator.py` — `final_score = llm_score` (blend dropped); `evaluate_jobs` sorts descending by final score, tiebreak `embedding_score`, failed (None) evals sort last without crashing; `top_n` now required (no signature default). **`max_tokens` 256 → 512** (see validation).
- `src/jobscout/config.py` — `embedding_min_score` deleted (field + env read); `top_n` promoted to config (default 25).
- `src/jobscout/run.py` — embedding-floor block removed; `top_n=config.top_n` passed through.
- `src/jobscout/models.py` — `ScoredJob.final_score` comment corrected (no longer a blend).
- `profile.yaml` — `background` / `ideal_role` rewritten positive-only; negatives consolidated into `deprioritise` (mostly deletion — the four entries already covered them); FTE "5+ years senior" entry deleted.
- Stale-model edits: `CLAUDE.md` constraint, `README.md`, CI cache key (`daily_run.yml`), `dev-notes.md` env-var list.
- `docs/adr/0002-freelance-profile-schema.md` — disputed English-only `freelancermap_queries` comment adjudicated (German terms stay) and struck; spec-4 amendment line added.
- Tests: `test_ranking.py` (+recording-encoder prefix/count/max_seq_length seam, cross-language German-ML-beats-English-backend, query composition), `test_evaluation.py` (final==llm, sort/tiebreak/None, ramp-up + no-"5+ years" prompt assertions), `test_delivery.py` (digest order follows final score), `test_config.py` (top_n present, embedding_min_score gone).

**Key decisions**
- **Centroid takes `query:`, not `passage:`** — deliberate deviation from e5's symmetric-task guidance, commented in `encode_feedback`. The tiebreaker is the blend, not the taxonomy: both terms must share a scale for `feedback_weight` to mean 0.2 (O #21).
- **Jobs encoded once** even with feedback present (encode-twice design rejected, O #21) — pinned by a test that counts passage-encodes.
- **Ordering made real**: the sort lives in the evaluator (the stage that produces the score), making `formatter.py`'s long-standing "assumed sorted by final_score" docstring true. The digest was ordered by embedding score before this.
- Did **not** build the bilingual query (F decision 1 superseded by N #19 §5).

**Validation (F #9's ≥5-listing check — a required deliverable)**
- Ran `python -m jobscout.run --dry-run` against **live freelancermap**: 25 jobs fetched → hard-filtered → e5-ranked → Haiku-evaluated. Read all 25 evaluations end to end.
- **Score distribution: 5×8, 4×5, 3×10, 2×2** (range 2–5, four distinct values; nothing ≥6).
- **Ramp-up-risk produces a spread, not a uniform penalty** — the stated risk (Haiku noisy on a harder judgement) did not materialise. Explanations cite it explicitly and graded ("3-point RAMP-UP RISK", "ramp-up risk of 2–3 points", "significant ramp-up risk"), separating e.g. a RAG-adjacent Data Engineer (5) from an owned-ML-platform / SAP-integration role (2–3). **This check passes.**
- **Fluent-German penalty fires on 20/25 (80%) — most rows.** This is the largest driver of the ≤5 compression on an 81%-German DACH corpus, exactly as F's structural argument predicts. Recorded as a **measurement, not a decision**: F did not revisit the German penalty and this spec must not invent that decision — it warrants its own ticket, not a silent edit. (Note: Haiku fires it on *implied* German — location/company — not only "stated condition", which over-fires slightly beyond the rubric's wording.)
- **Remote backstop fires on 8/25 (32%)** from onsite/hybrid signals *in the prose* even though all 25 passed the `remoteInPercent=100` gate — i.e. freelancermap's structured 100% sometimes contradicts a "hybrid, München" description. Working exactly as designed.
- **No day-rate signal surfaced in the evaluated prose** — F decision 5 (rate-in-description) stays closed on this sample.
- **`max_tokens` bug found and fixed.** At 256, the more verbose rubric truncated the JSON mid-string on **19/25** evals (`stop_reason=max_tokens`) — only 6/25 parsed. Raised to **512** → 24/25 parse (one verbose outlier still overflows, fails loudly, and sorts last). Without this the validation was impossible to even read.
- **`email_min_score` review (user-owned value edit — flagged, not changed):** it sits at **4**, which would email 13/25 (all 4s and 5s). With the distribution compressed to ≤5, the natural quality break is at **5** (→ 8 matches). **Recommendation for the user:** consider raising the digest gate to 5. ⚠️ It has **two consumers** — the digest gate (`run.py`) and, via `config.py`, the default `reeval_below` — so raising it to 5 also lifts re-eval volume (jobs scoring <5) from 12 to 17. The compressed distribution is now the evidence P (#22) wanted for **splitting `reeval_below` from `email_min_score`**: the digest wants ~5, re-eval cost wants ~4. Left to the user.

**Test count:** 289 passing (+20 for spec 4)

**Still open before tagging `v2.0.0`:** the integration branch must merge to `main` (this spec closes the map, so that unblocks it), and the `email_min_score` / `reeval_below` split above is a user call. New-ticket candidate: the 80%-firing German penalty.

---

## Fix #44 — 2026-07-30 — re-aim German penalty at deliberately-stated C1+

**Goal:** Close #44. Spec 4's live validation found the fluent-German penalty firing on 20/25
(80%) of the corpus, on *implied* German (location, company, posting language) rather than a
stated requirement — the largest driver of the ≤5 score compression. PR #49 (branch
`fix/44-german-penalty-c1-threshold`) re-aims the trigger at CEFR C1+, with an explicit
carve-out for location/company/posting-language/B2-or-below/level-unstated German, magnitude
kept at −2, still visible-but-ranked-down rather than an exclusion.

**Validation (CLAUDE.md's ≥5-listing check — required before merge)**
- Ran `python -m jobscout.run --dry-run` against **live freelancermap**: 73 raw → 24 hard-filtered
  → sent to Haiku with the new prompt. The Anthropic account ran out of credits partway through
  (9 jobs failed on `credit balance is too low`, 1 more on an unrelated JSON parse error) —
  **14/24 completed**, short of spec 4's 25-listing scale but above the ≥5 floor. Read all 14
  evaluations end to end (`digests/2026-07-30.md`).
- **Fire-rate: 20/25 (80%) → 6/14 (~43%)**, and every firing case cited an explicit C1+ cue —
  `Projektsprache: Deutsch` (×2), `sehr gute Deutschkenntnisse` (×2), `verhandlungssicher`,
  one more C1-implying phrase. No firing traced to location or company alone.
- **Carve-out correctly held the line between language-proficiency and domain-skill German:**
  two rows flagged "German-language NLP/embeddings" as a *skill gap* (a technical requirement)
  without applying the penalty — the rubric's distinct-in-kind case survived contact with a live
  corpus.
- **Score ceiling moved**: before, nothing scored ≥6 (range 2–5). This run reached **8/10, 7/10,
  two 6/10s** alongside the usual spread — direct evidence the penalty, not the ramp-up-risk
  criterion, was the compression's driver, confirming spec 4's structural argument.
- Sample-size shortfall (14 vs. 25) is a real gap against spec 4's scale, accepted rather than
  re-run: the signal (fire-rate magnitude, carve-out precision, score ceiling) was unambiguous at
  14, and topping up credits for 10–11 more calls was judged not worth delaying the decision.

**Decision:** closes #44. The re-aimed rubric ships as validated; #49 is clear to merge.

**Still open:** the `email_min_score` digest-gate value (raise to 5?) needs its own fresh
≥5-listing read now that this retune has moved the distribution again — sequencing per #45's
writeup. Not decided here.

---

## Fix #51 — 2026-07-30 — close the three deferred German-carve-out findings

**Goal:** Close #51, the deferred-findings ledger from `/pr-cycle`'s review of #49. Branch
`fix/51-german-carveout-followups`. Three items, none blocking on their own, but they compound:
`profile.yaml`'s German entry had drifted to a strict subset of `prompt.py`'s SYSTEM_PROMPT clause
(it named location/company and B2-or-below, omitting posting-language and von Vorteil); the rubric
stated no precedence when a C1+ cue and an optional qualifier describe the same requirement; and
the test pinned only 2 of the 4 carve-outs — precisely the two `profile.yaml` still had, which is
why the drift went unnoticed. Both strings reach Haiku in one request, so the subset was a
self-contradiction in a single prompt, not a docs nit.

**Changes:** all four carve-outs + precedence in `profile.yaml`; a PRECEDENCE sentence in
SYSTEM_PROMPT (optional qualifier beats the level — the penalty needs the level AND a non-optional
framing); `test_evaluation.py` pins all four carve-outs plus the new rule; `test_config.py` gains a
lockstep check on the shipped profile so the two copies cannot silently diverge again. 307 passing.

**Validation (CLAUDE.md's ≥5-listing check — required before merge)**
- `python -m jobscout.run --dry-run` against **live freelancermap**: 74 raw → 24 hard-filtered →
  **24/24 evaluated, zero failures**. Full completion, unlike #44's credit-truncated 14/24.
- **Score distribution: 8×1, 7×2, 6×2, 5×6, 4×5, 3×5, 2×3** (range 2–8). The post-#44 ceiling holds;
  no regression from the added prompt text.
- **German penalty explicitly attributed in 7/24 (~29%)** — down from #44's 6/14 (~43%) and spec 4's
  20/25 (80%), though the corpora differ and the drop is not attributable to this change.
- **Carve-out held on the distinct-in-kind case again:** two rows flagged German-language NLP /
  embeddings as a *skill* gap without a proficiency penalty (nemensis, WorkGenius).
- ⚠️ **The precedence rule was NOT exercised.** No listing in this corpus paired a C1+ cue with an
  optional qualifier — "von Vorteil" appears nowhere in the 24 evaluations. The clause is therefore
  shipped as reasoned-but-unobserved; it is a narrowing (it can only suppress a penalty, never add
  one), so the risk of shipping it unvalidated is bounded, but it wants a corpus that contains the
  pattern before it can be called proven.
- ⚠️ **Pre-existing, not introduced here: "Projektsprache: Deutsch" fires the penalty with no CEFR
  level stated** (BLUECHILLED, SThree Intelligente Suche — 2 of the 7). The rubric's own closing
  sentence says level-unstated German is below the bar and must not fire, so these two contradict
  it. #44's validation counted the same pattern as legitimate C1+ cues, so this is inherited, not a
  regression. Arguably the rubric is wrong rather than Haiku: a stated project language is a
  deliberate operational requirement, not merely implied German. **New-ticket candidate.**
- Four further rows list German in `gaps` without the summary attributing a penalty (Tenth
  Revolution, AI Strategist, COMCAVE, Mobile KMP). Two of those are textbook carve-out cases —
  AI Strategist is location-implied and self-describes as "not explicitly stated"; COMCAVE says
  "no level stated". Whether −2 actually applied is **not determinable from the digest**, since
  `gaps` also carries ordinary skill gaps and `--dry-run` skips the DB writes that would let the
  arithmetic be reconstructed. Flagged as a measurement limit, not a verdict.

**Decision:** the three #51 findings are closed as implemented; the ≥5-listing gate passes on scale
(24) and on the unchanged-ceiling check. The precedence clause ships unobserved — stated plainly
rather than papered over.

**Still open:** (1) the `Projektsprache: Deutsch` fire-vs-carve-out contradiction above needs its own
ticket — decide whether the rubric or Haiku is wrong; (2) `email_min_score` (raise to 5?) still
carries over from #44, untouched here.

---

## Fix #56 — 2026-07-30 — pytest resolves `src/` from the tree it was started in

**Problem:** the editable install (`__editable__.jobscout-0.1.0.pth`) is a plain path entry pointing
at the main checkout. A `pytest` run started from `.claude/worktrees/<name>/` therefore collected the
worktree's `tests/` and imported the **main checkout's** `src/jobscout` — two trees in one run, with
nothing in pytest's output naming either. Hit twice during the #51 session: once as a false red that
cost a debugging detour (a correct new assertion failing against stale source), and latently as a
false green, which is the dangerous direction — every assertion still executes, just against code you
are not editing.

**Changes:** `pythonpath = ["src"]` under `[tool.pytest.ini_options]`. It is resolved relative to
rootdir and prepended to `sys.path`, so each run picks up the `src/` of whichever tree pytest was
invoked from; the `.pth` entry stays as a fallback. Added
`test_repo_invariants.py::test_suite_imports_src_from_this_tree`, asserting the imported
`jobscout.__file__` sits under the tests' own `src/`. That module already exists for invariants with
no code seam, and this is the same shape.

⚠️ **Corrected during review:** the first draft of this entry claimed "no other test in the suite can
notice". That is false. Re-running the full suite with `-o pythonpath=` fails **two** tests, the
second being `test_evaluation.py::test_system_prompt_ranks_optional_qualifier_over_c1_cue` — issue
#56's original reproduction, failing because the main checkout currently sits on a branch without
#53's PRECEDENCE clause. The accurate claim is narrower and is the one that actually motivates the
tripwire: it is the only test that fails *reliably*. Which other tests notice depends entirely on how
the two trees happen to differ that day — today two, after the next merge possibly zero. That
contingency is the whole danger, so a guard that does not depend on it is what was needed.

**Verification**
- Full suite from the worktree, `PYTHONPATH` unset: **308 passing** (307 + the new tripwire).
- Tripwire proven to fire, not merely pass: re-run with `-o pythonpath=` (simulating the setting's
  removal) fails with both paths named in the message.
- Duplicate `sys.path` entry is harmless where rootdir `src/` and the install target coincide —
  `importlib.metadata.version` and the `jobscout` console-script entry point both still resolve from
  dist-info, and nothing in `tests/` or `src/` reads installed metadata.
- CI: `tests.yml` and `daily_run.yml` both `pip install -e ".[dev]"` from the checkout root, so
  rootdir `src/` *is* the install target — the setting is a no-op there. This is also the same
  condition as the issue's "full suite from the main checkout" check, so CI covers both.

**Side benefit:** the suite no longer depends on an editable install existing, so a fresh clone can
run it without `pip install -e .`.

**Still open:** the fix covers pytest only. Any other entry point started from inside a worktree — a
bare `python -m jobscout.run`, a REPL, pyright — still resolves `jobscout` to the main checkout. So
"tests pass in the worktree" does not imply "running the pipeline in the worktree uses the worktree's
code". Out of scope for #56; noted in `docs/dev-notes.md` so it is not rediscovered the hard way.

---

## Fix #55 — 2026-07-30 — the deferred findings from #53's review

**Goal:** Close #55, the deferred-findings ledger from `/pr-cycle`'s review of #53 — the PR that
closed #51. Two of the four items are one piece of work, and they are the same defect #51 existed
to close, reintroduced one layer up.

**The defect, precisely:** #51 added `assert "von Vorteil" in SYSTEM_PROMPT` to pin the Do-NOT-fire
carve-out, and in the same commit added a PRECEDENCE example containing the words
`"verhandlungssicheres Deutsch von Vorteil"`. The assert was satisfied by the example, not by the
entry it named — so the carve-out could be deleted from the prompt with the suite still green
(verified by mutation, below). Meanwhile `test_config.py`'s "lockstep" test never read
SYSTEM_PROMPT at all; it asserted substrings on the profile side only. Neither direction of drift
was actually guarded.

**Changes:**
- `tests/test_config.py` gains `GERMAN_CARVE_OUTS`, a seven-row table pairing each carve-out's
  SYSTEM_PROMPT marker with its `profile.yaml` marker, asserted against **both** strings. The two
  are worded differently on purpose (the prompt instructs, the profile states a preference), so a
  literal comparison is impossible — the table is the seam. A fifth carve-out is one row here and
  nowhere else. A second test asserts each prompt marker matches *exactly once*, which is the
  self-satisfaction failure mode above, now unrepresentable.
- `test_evaluation.py` sheds its four carve-out asserts; keeping them would mean a fifth carve-out
  needs updating in two places, which is the drift being fixed.
- **`config.py:_load_config` read `profile.yaml` with a bare `open()`.** Filed as a nit; it is not.
  On Windows (cp1252) the German entry's em dash decoded to `â€"` and that mojibake shipped to
  Haiku on every local run. It never raised and Linux CI defaults to utf-8, so nothing caught it.
  `run.py:_sync_feedback` had the same bug against `feedback.yaml` — not in the ledger, found while
  fixing this one. It is a symmetry fix: the file is written utf-8 with `allow_unicode=True`, so it
  must be read utf-8 too. ⚠️ **Corrected during review:** this entry first called that instance
  *worse* than the `profile.yaml` one, because "umlauts in German job titles are undecodable under
  cp1252". False — `feedback.yaml` only ever holds `{id, source, status}` (`run.py:63`): IDs, source
  slugs and a fixed status enum, all ASCII. The title carrying the em dash goes to the console
  prompt, never to the file. The fix stands on symmetry and on making the schema safe to widen, not
  on a decoding failure that can currently occur. Same failure mode as #51's overclaim, one layer
  further out: a plausible severity story asserted without checking what the file actually holds.
- `build-log.md` separator at the old line 581 had no blank line before `---`, so GitHub rendered
  the preceding line as an H2 and swallowed the divider.

**Validation:** 322 passing, up from 307; 323 after `main` merged in, which adds #56's tripwire. No Haiku run — no prompt text changed,
so #51's ≥5-listing validation still holds. Three mutation checks instead, each reverted after:
delete the `von Vorteil` carve-out from SYSTEM_PROMPT → 2 failures; drop `posting language` from
`profile.yaml` → 1 failure; revert the `encoding="utf-8"` → the mojibake test fails. Guards that
have never been seen red are not evidence.

**On the worktree import trap:** this session hit it too — a bare `pytest` here reported a spurious
failure against the main checkout's `src/` before it was spotted, and the workaround (`PYTHONPATH=src`)
was briefly written into dev-notes by this PR. **#56 fixed it properly** in the meantime, via
`pythonpath = ["src"]` in `pyproject.toml` plus a tripwire test, so that dev-notes section was removed
when `main` merged in — it documented a defect that no longer exists. See the #56 entry above.

**Still open:** both carry-overs from #51 are untouched — the `Projektsprache: Deutsch`
fire-vs-carve-out contradiction, and `email_min_score`. The precedence clause remains
reasoned-but-unobserved; no new corpus was read here.

---

## Fix #54 — 2026-07-30 — grade the German penalty: −1 for a declared working language

**Goal:** Close #54. Branch `fix/54-projektsprache-middle-band`. `Projektsprache: Deutsch` states a
language but **no CEFR level**, so the clause's own closing sentence ("no level stated → do NOT
apply this penalty") said carve-out while Haiku applied the full −2 — 2 of the 7 fires on #51's
corpus. Inherited from #44, not a regression. Of the three options in the issue, **option 3** (a
middle band) was chosen: it is the only one that keeps #44's premise — an unstated level never buys
the full penalty — while conceding what Haiku got right, that a declared working language is a
deliberate operational statement rather than incidental German.

**Changes**
- `prompt.py`: the German clause is now graded `REDUCE by 1–2 pts`, in the shape RAMP-UP RISK
  already uses in the same rubric. **2 pts** — deliberately stated C1+ (cue list unchanged);
  **1 pt** — German declared as the language the work is conducted in with no level
  (`Projektsprache: Deutsch`, `Arbeitssprache Deutsch`); **0 pts** — everything else, all five
  carve-outs intact. The catch-all now reads "no level stated **and no working language declared**",
  which is the sentence that was contradicting observed behaviour.
- Two doors the grading opens, closed in the same clause: **the bands are exclusive** (a C1+ listing
  that also declares a project language scores 2, never 2+1 — otherwise this re-inflates the fire
  rate through a third door), and **PRECEDENCE now covers either band**, so
  `"Projektsprache Deutsch, Englisch ebenfalls möglich"` does not fire. That second one is not
  hypothetical: BLUECHILLED's own #51 rationale keyed on the phrase *"with no fallback"*.
  ⚠️ **Corrected by #65 (entry below):** the example in that last sentence is wrong and was wrong
  when written. A second declared language is not an optional qualifier on the same requirement, so
  it never was an instance of the PRECEDENCE rule — and `3030001` states `Projektsprache: Deutsch
  und Englisch` and **did** fire the 1-pt band in this very run, which is recorded four bullets
  down. The claim and its own counter-evidence sat in the same entry; the review round caught it,
  this session did not.
- `profile.yaml` rewritten in lockstep — both bands, all five carve-outs, the precedence rule.
- `test_config.py`: the band is a **fire** cue, not a carve-out, so it does not belong in
  `GERMAN_CARVE_OUTS`. It gets its own two-row `GERMAN_FIRE_BANDS` table, unioned into the same
  two parity tests — it drifts the same way and earns the same guard.
- 328 passing, up from 323.

**Guards seen red before being trusted** (the #58 entry's precedent — a guard never observed failing
is not evidence). Delete `"Projektsprache: Deutsch"` from SYSTEM_PROMPT → 3 failures; change
`profile.yaml`'s "declared working language" to "declared project language" → 1 failure. Both
reverted.

**Validation (CLAUDE.md's ≥5-listing check — required before merge)**

An accidental first run produced a **same-corpus baseline on the old prompt** (see the import trap
below), so this is a controlled before/after rather than a bare after: same 75-listing fetch, same
21 survivors, ~90 seconds apart, only the rubric differs.

- 75 raw → 21 hard-filtered → **21/21 evaluated, zero failures**, both runs.
- **Score distribution unchanged in shape:** old `2×8, 2×7, 1×6, 6×5, 4×4, 3×3, 3×2`; new
  `2×8, 2×7, 1×6, 6×5, 5×4, 3×3, 2×2`. Range 2–8 both; the post-#44 ceiling holds; no compression.
- **The bug reproduced on the baseline and is gone on the new run — same listing, same corpus.**
  `3027789` (KI-Services) old: *"the role explicitly states 'Projektsprache: Deutsch' as a
  non-optional frame, and the candidate profile does not confirm C1+ German ability, triggering a
  2-point penalty"*. New: *"German as project working language — candidate is B2, role declares"*,
  at the 1-pt band. `3025659` (SThree, Intelligente Suche — one of #54's two exhibits) old:
  *"'verhandlungssicheres Deutsch' implied by role setup"* — the fabricated level the issue called
  out; new: *"a declared working language (Projektsprache: deutsch) creates modest friction"*.
  **No row in the new run asserts a level the listing does not state.**
- **Both bands exercised:** −2 on 5 rows (`muttersprachlichem Niveau`, `Sehr gute Deutschkenntnisse`
  ×2, explicit C1, `verhandlungssicher`); −1 on 7 rows. So the *attribution* rate rose from #51's
  7/24 (~29%) to ~12/21 (~57%) while the **full**-penalty rate fell to 5/21 (~24%). That is the
  trade option 3 buys and it should be read as intended, not as regression: more rows touched, less
  damage each. Option 1's "re-inflating the fire rate" risk landed on the −1 band, which is where it
  was aimed.
- **Carve-outs held against the new band** — the risk being that a −1 for "declared working language"
  swallows the "posting written in German" carve-out. It did not: `3029863` (*"job posted in German
  with no stated level"*) and `3029652` (*"working language of project not specified at a level"*)
  both reasoned to no penalty. `3029231` again flagged German-language embeddings as a *skill* gap
  with no proficiency penalty.
- ⚠️ **Precedence still unobserved, now for both bands.** No listing paired a firing cue with an
  actual optional qualifier. `3030001` states `Projektsprache: Deutsch und Englisch` and Haiku fired
  the 1-pt band, reading a second declared language as not a fallback — defensible, but it is not
  the `von Vorteil` shape the rule is written for. Same status as #51: shipped reasoned-but-unobserved,
  bounded because it can only suppress a penalty, never add one.
- ⚠️ **Individual score moves are NOT attributable to this change.** `evaluator.py` sets no
  `temperature`, so sampling is at the API default of 1.0. 6 of 21 scores moved between the runs,
  ±1 in both directions, **including `3022972` which has no German signal at all** — so the
  run-to-run noise floor is at least ±1 and swamps a 1-point band on any single row. What is
  attributable is the *stated rationale*, which moved in the intended direction on every German row.
  Proving the arithmetic would need repeat runs at the same prompt, or the DB writes `--dry-run`
  skips.

**On the worktree import trap — a second live instance, and this one had teeth.** #56 fixed
`pytest`; a bare `python -m jobscout.run` inside a worktree still resolves through the editable
`.pth` to the **main checkout**, exactly as `dev-notes.md` warns. The first validation run therefore
evaluated the *old* prompt while appearing to validate the change — a false green of the dangerous
kind, caught only because the digest was written to the main checkout's path. It also **overwrote
`digests/2026-07-30.md` in the main checkout**, clobbering the artifact from that morning's #51 run
(gitignored and untracked, so nothing in git was touched; #51's findings survive in the entry
above). Correct invocation from a worktree is `PYTHONPATH=src python -m jobscout.run`. The salvage
is that the clobbering run *is* the old-prompt baseline this entry rests on.

**Still open:** `email_min_score` (raise to 5?) carries over untouched from #44 and #51. The
precedence clause wants a corpus containing a `von Vorteil`-shaped qualifier before it can be called
proven.

---

## Fix #65 — 2026-07-30 — the German clause's header range and its precedence example

**Goal:** Close the two non-blocking findings from `/pr-cycle`'s round-1 review of #63, folded into
one PR because they sit in the same clause and therefore share one validation run. Branch
`fix/65-german-clause-header-and-precedence-example`, cut from #63's head.

**Changes**
- **Header range.** The clause read `REDUCE by 1–2 pts` over a body whose lowest band is
  `0 pts — everything else`. The sibling RAMP-UP RISK clause writes `0–3` for exactly this reason:
  stating a floor of 1 invites reading *any* German signal as worth at least a point, which is the
  over-firing #44 and #54 both removed. Now `0–2`.
- **Precedence example.** `"Projektsprache Deutsch, Englisch ebenfalls möglich"` was offered as an
  instance of "an optional qualifier beats the level cue". It is not one — a second declared
  language is not a qualifier on the same requirement, it is a second requirement. The example is
  now `"Deutsch als Projektsprache von Vorteil"`, which is a real instance, and the two-language
  case is stated explicitly as **firing** the 1-pt band rather than left to be inferred.
- Tests pin both: the header string with its `0–2`, the presence of the `0 pts` band, the new
  example, and the two-languages sentence. 328 passing (unchanged — assertions were rewritten, not
  added).

**Validation (fresh ≥5-listing run, baseline = #63's run on the same day's corpus)**
- 75 raw → 21 filtered → **20 evaluated** (`3029231`/nemensis left the source between runs; 20 of
  #63's 21 survive, none new).
- Distribution: `1×8, 2×7, 3×6, 2×5, 6×4, 3×3, 2×2` vs #63's same-20 `1×8, 2×7, 1×6, 6×5, 5×4,
  3×3, 2×2`. Range 2–8 unchanged. 4 of 20 scores moved, ±1 — inside the noise floor established in
  the #63 entry, so not attributable either way.
- **The new two-languages sentence was exercised.** `3030001` (`Projektsprache: Deutsch und
  Englisch`) fired the 1-pt band and its rationale now reads *"project runs in German and English
  (declared working language); candidate is B2, role does not state a C1+ req"* — the behaviour the
  sentence codifies, previously only inferred.
- **A band was cited by number for the first time.** `3025659`: *"the declared working language
  (Projektsprache: Deutsch) applies a 1-pt penalty (no level stated, but a deliberate operational
  declaration)"*. That is the graded clause being read as written, not reconstructed by us from a
  score.
- **The 0 band held on an implicit working language.** `3029221` — *"no CEFR level stated but
  working language is implicit"* — took no German penalty this run, where #63's run had penalised
  it. Implicit ≠ declared is exactly the line the clause draws, but note this row moved *because*
  Haiku re-read it, not provably because of the header change.
- ⚠️ Same measurement limit as every run since #44: `--dry-run` skips the DB writes, so the
  arithmetic behind any single score cannot be reconstructed from the digest. Rationale text is the
  evidence; the numbers are not.

**Process note.** Both findings came from `/pr-cycle` round 1 on #63 — an independent subagent
reading the same clause this session had just written and validated. Neither was a bug in behaviour;
both were the prompt saying something other than what the run showed. The precedence overclaim had
its own counter-evidence sitting four bullets below it in the same build-log entry, which is the
kind of thing an author does not see.

**Still open:** #65 left **two** unticked items, not one — this line named only the second and is
corrected here (the omission was itself a deferred finding, #67's first). They are: (1) the
`tests/test_config.py` naming nit, where `GERMAN_FIRE_BANDS` is unioned into a class, test name and
failure message that all say "carve-out", so a dropped fire band reports as a dropped carve-out —
**still open**; and (2) `email_min_score`, then more load-bearing than before since a −1 band puts
more rows on the 4/3 boundary the digest gate sits on — **now settled at 5**, see the 2026-07-31
entry below.

---

## Fix — 2026-07-31 — raise the digest gate to `email_min_score: 5`

**Goal:** Settle the `email_min_score` value, carried unresolved through #44 → #51 → #65 and flagged
in ADR 0002 as "deliberately not given a number". User decision: raise 4 → 5.

**Changes**
- `profile.yaml`: `email_min_score: 4` → `5`, with the rationale and the measured numbers written at
  the value rather than left in a build-log entry nobody diffs against.
- `tests/test_config.py`: `test_defaults_to_standalone_constant_not_email_min_score` carried a
  comment asserting "shipped email_min_score is 4 today". This change makes that false, so it is
  rewritten. Worth noting *why* the test survives unchanged: while the gate sat at 4 it coincided
  with `DEFAULT_REEVAL_BELOW`, so a still-coupled config would have passed that assert. At 5 the two
  differ and the assert now discriminates on the shipped profile alone — the change strengthens the
  test it invalidated the comment on.
- `docs/adr/0002-freelance-profile-schema.md`: annotated in place, per the convention that entry
  already uses. Both halves of its ⚠️ flag had expired — the `reeval_below` coupling it warns about
  was dissolved by #45, and the distribution it called unknowable has since been measured twice.

**Evidence — from the recorded runs, not a fresh one**
- #65's run (2026-07-30, 20 evaluated): `1×8, 2×7, 3×6, 2×5, 6×4, 3×3, 2×2`. A gate at 4 emails 14
  rows; at 5 it emails 8.
- #63's run on the same corpus: `1×8, 2×7, 1×6, 6×5, 5×4, 3×3, 2×2`. Gate at 4 emails 15; at 5
  emails 10.
- So the raise cuts the emailed set by roughly a third to two-fifths, and in both runs it removes the
  single largest band. That is the intended direction — the tool exists to return fewer, better
  matches — and nothing is lost: everything under the gate is still written to the daily digest file.
- ⚠️ **The recorded #65 distribution sums to 19, not the 20 evaluated.** One row is unaccounted for
  in the transcription. It cannot change the conclusion (a single row moves either count by one) but
  the figures above are approximate for that reason, and the gap is noted rather than smoothed over.

**No fresh validation run.** CLAUDE.md's ≥5-listing gate is scoped to changes to the *LLM prompt*;
this is a delivery threshold read after evaluation, and it cannot move any score. The two runs above
already measure the distribution it cuts against. A fresh run was also not available here — the
pipeline needs an API key and the DB survives only in the Actions cache, not locally.

**Deliberately not touched:** `docs/session-state.md` lines 42/50 still record the gate at 4 with a
2026-04-07 review checkbox. That file is **closed** (2026-07-22) and kept as a historical record of
the FTE era; CLAUDE.md says not to update it, so it keeps saying what was true when it was written.

## Fix — 2026-07-31 — three deferred test nits, bundled

Three trivial deferred findings, test-file-only, closed in one PR because separately they were
three PRs' worth of ceremony for about thirty lines. None touches pipeline behaviour, and none
touches the LLM prompt — so the ≥5-listing validation gate does not apply, which is why they were
deferred rather than folded into the PRs that found them.

**#65 — the German parity guard was named for half of what it checks.** `GERMAN_FIRE_BANDS` is
unioned with `GERMAN_CARVE_OUTS` into `GERMAN_CLAUSE_ROWS`, but the class, the test and two failure
messages all said "carve-out", so a dropped *fire band* reported as a dropped *carve-out* and sent
the reader to the wrong half of the prompt. Renamed to `TestGermanClauseParity` /
`test_clause_row_is_present_on_both_sides`; parametrisation, markers and assertions untouched.

**#74 — `_the_one_bypass` indexed a list it had not proved was one.** It asserted non-empty, then
returned `actors[0]`. A truthy non-list passes the emptiness assertion and raises `KeyError` on the
index, so the reader gets a traceback instead of the message written directly above it. Shape is now
checked first, pointing at `test_bypass_actors_is_a_list_that_was_actually_read`, which already owned
that failure. Noise, not correctness — the shape was caught either way.

**#76 — nothing enforced the byte-identity `test_required_checks.py`'s header claims.** That file is
a copy of a `gh-repo-baseline` template and its header says fixes belong upstream "or they are lost
on the next copy". #75 recorded the upstream sha in the header, which was the precondition for
automating this. `TestTheCopiedGuardWasNotEdited` now pins a sha256 of the guard below its header
(newlines normalised), that the header still names the sha the hash is anchored to, and that the
split takes a body rather than the whole file.

**What that check deliberately does not do.** It attests that the local copy is *unmodified*; it does
**not** verify it against upstream. The hash is recorded by whoever does the copy, so it is a
self-attestation. Proving identity needs the template at that sha — a network fetch, which belongs in
a CI step rather than in pytest. Upstream's own `TestTheLiveGuardMatchesTheTemplate` gets away with a
plain file diff only because it holds both copies in one repo; downstream cannot. The class docstring
and the failure message both say this outright, so a green tick cannot be misread as "we match the
baseline". The weaker check was chosen on purpose: the realistic failure here is a session fixing a
bug *in* the copied guard instead of upstream, and #76 has three such upstream-owned bugs open
against that very file. Tamper-evidence catches exactly that, for one constant and no network.

Verified by mutation rather than by assertion-counting: a one-character body edit fails only the hash
test, a stale header sha fails only the sha test, a wholesale CRLF rewrite fails nothing, and a
deleted header trips the vacuity check. `tests/test_required_checks.py` is not edited by this work —
it is not this repo's to edit.

Suite: 379 → 382 passing.

## Fix — 2026-07-31 — re-copy the guard at upstream `ae78c6b3`

`gh-repo-baseline` PR #14 merged the same day, moving the template from `130a56a5` to
`ae78c6b3` and growing it 1099 → 1290 lines. This is the re-copy, plus the pin update that
has to travel with it.

**First live exercise of `TestTheCopiedGuardWasNotEdited`**, added in #79 about an hour
earlier. It went red on the re-copy exactly as designed — the hash it pins is a hash of the
old body — and its failure message is what specified the commit's contents: header sha,
`_GUARD_UPSTREAM_SHA`, `_GUARD_BODY_SHA256`, together, in one commit. The mechanism worked
on the first occasion it could have failed to.

**Procedure** (from #81 § C, which exists because this is easy to get subtly wrong):

1. Verified the pre-copy file differed from the template at `130a56a5` by exactly the two
   documented per-repo edits — so the header's claim was still true at the moment it was
   relied on, rather than assumed.
2. Re-copied from `ae78c6b3`, reapplying `_WORKFLOW` → `tests.yml` and the `"Tests"`
   assertion in `test_step_names_are_not_collected`.
3. Verified the result differs from `ae78c6b3` by exactly those two edits, same shape.

**A bug worth recording, because the second attempt only exists because of it.** The first
attempt lifted each per-repo edit by walking back over the contiguous comment lines above
its anchor in the live file. That over-captures: one of those comment lines was
*template-owned*, present in the new template too, so the copy ended up with it twice. The
fix is to compute the per-repo delta against the **old** template — our comments minus the
ones the template already carried above the same anchor — and to assert afterwards that
every line of the result is either in the new template or is per-repo, and that no per-repo
comment appears twice. Lifting the edits programmatically rather than retyping them is what
made the duplicate visible in a diff instead of shipping.

**What the re-copy actually resolved,** checked against the new file rather than inferred
from upstream PR titles (#81 § C step 4 asks for exactly this, and the answer differs from
what the titles suggest):

- `_COMMENTED_EVENT:trailing-note-and-indent` — **half.** The trailing-note half is fixed:
  the regex lost its `\s*$` so `# workflow_run:  # off for now` is now recognised. The
  indent half is not — `_COMMENTED_EVENT` and `_EVENT_KEY` still hardcode `^  ` (two
  spaces). That is upstream #13's job and it is still open.
- `_job_contexts:matrix-refusal-one-indent` — **not resolved.** Still
  `re.match(r"^      matrix\s*:", line)`: one hardcoded indent, no quoted keys, no inline
  flow mappings.
- `_trigger_branches:filter-name-any-depth` — **not resolved.** (Not *untouched*: `_trigger_branches`
  itself was substantially rewritten upstream between the two shas, 7253 → 12013 characters. What is
  unchanged is the `^\s{3,}` filter-key behaviour this item is about — an earlier revision said
  "not touched by this copy", which overreached.)
  A first draft of this entry claimed it was resolved "by the opposite mechanism", reading the
  docstring's any-indent rationale as evidence of a change. It is not one: `^\s{3,}` is
  byte-identical at `130a56a5`, at `ae78c6b3`, and in the pre-copy file, so that behaviour
  predates this re-copy entirely. The item asked for the filter name to be bound to the
  event's own indent level, and nothing here attempts that.

  Caught by the `/pr-cycle` round-1 review of #82, as a blocking finding: left in, it would
  have ticked an open tracker item that was never started. Worth recording because of where
  it sits — this very section exists to check resolutions against the file rather than infer
  them from upstream PR titles, and the inference still got in, one level down, from a
  docstring instead of a title. Diff the code, not the prose about the code.

Suite: 382 → 387. The five net-new tests are the template's own and pass unchanged. They do
**not** exercise this repo's `tests.yml`: all five are `tmp_path` unit tests of
`_trigger_branches` over synthetic workflows. An earlier revision of this line said they
"pass against this repo's `tests.yml`", which claimed a kind of coverage they do not provide.
