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
