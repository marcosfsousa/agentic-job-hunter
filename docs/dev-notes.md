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
- `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` — job data source
- `ANTHROPIC_API_KEY` — LLM evaluation (Claude Haiku)
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — delivery

## Key files
- `profile.yaml` — User profile (skills, preferences, dealbreakers)
- `src/jobscout/models.py` — Core data models (`JobListing`, `EvaluationResult`)
- `src/jobscout/adapters/base.py` — Abstract adapter interface all adapters must follow
- `src/jobscout/run.py` — Main pipeline orchestrator
- `src/jobscout/config.py` — Config loading and validation

## Future extensions (not in scope for MVP)
Do not build these during the initial sprint:
- Feedback loop (thumbs-up/down data to adjust scoring weights)
- Additional markets (Portugal, Netherlands, remote-global)
- Company research agent
- Application tracker / CRM
- Skill gap dashboard
- LangGraph orchestration
