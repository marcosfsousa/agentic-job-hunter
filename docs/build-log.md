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