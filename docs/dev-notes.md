# JobScout — Developer Reference

## Session State Template

# Session State

**Last updated:** YYYY-MM-DD

## Status
- Completed through: [stage name]
- Last working command: `[command]`

## Known issues
- [issue and fix, one line each]

## Next session
- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## Spec reference
[Link to relevant section of SPECS.md if applicable]

## How to run
```bash
conda activate jobscout
python -m jobscout.run           # Full pipeline
python -m jobscout.run --dry-run # Fetch + filter + rank, skip delivery
python -m pytest tests/          # Run tests
```

`pytest` sets `pythonpath = ["src"]` (pyproject.toml), resolved against the rootdir of
whichever tree it was started from. Two consequences: the suite runs on a fresh clone with
no `pip install -e .`, and a run started from a `.claude/worktrees/<name>/` checkout tests
*that* worktree's source instead of silently importing the main checkout's via the editable
`.pth`. `tests/test_repo_invariants.py::test_suite_imports_src_from_this_tree` fails loudly
if that ever stops holding. Note this covers pytest only — a bare `python -m jobscout.run`
or a REPL started inside a worktree still resolves to the main checkout.

## Environment
- API keys in `.env` (loaded via python-dotenv, gitignored)
- Conda environment: `jobscout` (Python 3.11)
- No Docker needed for development

Required keys:
- `ANTHROPIC_API_KEY` — LLM evaluation (Claude Haiku)

Optional: `RESEND_API_KEY` + `EMAIL_FROM` + `EMAIL_TO` — email delivery, skipped if unset.

The Adzuna and Open Web Ninja keys are gone with their adapters. **No source key is required
at all**: the one registered adapter, freelancermap, ingests anonymously — and must, since
never authenticating is one of the binding constraints under which ingesting it was accepted
(issue #11). Do not add a freelancermap credential.

Operational overrides, all optional and all with sane defaults in `config.py`:
- `FREELANCERMAP_MIN_RAW_INGEST` (default 30) — distinct-project floor below which the run
  fails loudly rather than delivering an empty digest. Must stay above 22; see `config.py`.
- `FEEDBACK_WEIGHT`, `REEVAL_BELOW` — ranking and evaluation tuning. (The old
  `EMBEDDING_MIN_SCORE` cosine floor was removed in spec 4: it was scale-coupled and went
  stale on the e5 swap. The LLM pool is bounded by the `top_n` rank cut instead.)

`freelancermap_max_requests` (default 10) is **not** in that list on purpose. It is the hard
request cap — one of issue #11's binding constraints — and a ceiling an operator can raise from
the environment is a convention, which is the thing a cap exists instead of. Changing it is a
code change and a review.

## Key files
- `profile.yaml` — User profile (skills, preferences, dealbreakers)
- `src/jobscout/models.py` — Core data models (`JobListing`, `EvaluationResult`)
- `src/jobscout/adapters/base.py` — Abstract adapter interface all adapters must follow
- `src/jobscout/run.py` — Main pipeline orchestrator
- `src/jobscout/config.py` — Config loading and validation

## Ops checks

### Sync local with remote before working
```bash
git fetch origin && git status
git pull  # data/jobscout.db is untracked — a pull never touches it
```

### Check what the daily pipeline did
```bash
# Job counts by day
sqlite3 data/jobscout.db "SELECT date(first_seen) as day, COUNT(*) FROM seen_jobs GROUP BY day ORDER BY day DESC LIMIT 7;"
sqlite3 data/jobscout.db "SELECT digest_date, COUNT(*) FROM digest_jobs GROUP BY digest_date ORDER BY digest_date DESC LIMIT 7;"

# Latest run status and logs
gh run list --limit 5 --workflow=daily_run.yml
gh run view <RUN_ID> --log | awk -F'\t' '$2=="Run pipeline" {print $3}' | grep "jobscout\."
```

### Re-score the hand-scored corpus (#96)

`pytest` alone runs the corpus **offline**, from the recorded tool scores in
`tests/fixtures/scored_postings.yaml` — no network, no API key. That is the mode CI runs,
and the mode that reports the six recorded baseline failures as `xfailed`.

Live re-scoring calls Haiku once per posting and is opt-in:

```bash
JOBSCOUT_LIVE_EVAL=1 pytest tests/test_scored_postings.py -q   # needs ANTHROPIC_API_KEY
```

Set `REEVAL_BELOW=0` on any baseline or comparison run of the **pipeline** too —
`REEVAL_BELOW=0 python -m jobscout.run` — not just in the harness, which pins it already.
Unpinned, the max-of-two draw issues a second evaluation for anything under 4 and keeps the
higher, which inflates the bottom of the distribution and confounds exactly the `hard_skip`
rows a before/after comparison is looking at.

It skips any case whose posting text is missing. That text is **gitignored** —
`tests/fixtures/scored_postings/<id>.md`, third-party posting content that does not go in
a public repo, guarded by `tests/test_repo_invariants.py`. On a fresh clone the directory
does not exist and every live case skips with that reason; the format for re-creating it
is in the manifest's header comment.

Run this before and after a `SYSTEM_PROMPT` change — the five `live_rescorable` cases are
real listings hand-scored against the real `profile.yaml`, which is exactly what CLAUDE.md's
"test with at least 5 real job listings" gate is asking for.

**Read a live result as evidence about the rule, not about the score.** Those five are
scored against *excerpts* — the clauses the rule reads — and the human scored the whole
posting, so the two are not the same conditions. Watch whether the clause fires and in
which direction; do not tune a rule until an excerpt reproduces a human number. Each case
records its `text_provenance` and the excerpt repeats it in front matter, so a full posting
behind a case declared `excerpt` fails rather than quietly upgrading the claim. The offline
baseline is unaffected — it never reads the text.

### Check GH Actions queue delay trend
```bash
gh run list --limit 10 --workflow=daily_run.yml --json startedAt,createdAt | python scripts/check_run_delays.py
```

## Future extensions (not in scope for MVP)
Do not build these during the initial sprint:
- Feedback loop (thumbs-up/down data to adjust scoring weights)
- Additional markets (Portugal, Netherlands, remote-global)
- Company research agent
- Application tracker / CRM
- Skill gap dashboard
- LangGraph orchestration
