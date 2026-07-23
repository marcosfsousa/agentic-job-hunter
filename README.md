# JobScout

JobScout is a personal AI job-matching pipeline for freelance/contract AI/ML work in the German market.

It pulls listings from freelancermap, removes obvious mismatches with deterministic filters, ranks the remaining projects with multilingual semantic search, asks an LLM to evaluate only the strongest candidates, and delivers a daily digest by email plus a markdown archive. The goal is simple: fewer, better projects to review by hand. It finds and ranks — you decide what to apply to.

This project is intentionally opinionated:
- it never auto-applies
- `profile.yaml` is the single source of truth for preferences
- the pipeline is idempotent, so rerunning on the same day does not spam duplicates
- adapters are pluggable, so new job sources can be added without changing the pipeline

## What It Does

Pipeline:

`Ingest -> Deduplicate -> Hard Filter -> Embed + Rank -> LLM Evaluate -> Deliver`

Source:
- freelancermap — the one viable DACH freelance source, and therefore the whole corpus. A new market is a new adapter file behind a shared interface; nothing else in the pipeline changes.

Core behaviors:
- normalizes raw listings into a single internal contract `JobListing` (day/hourly rate, contract type, remote percentage, duration)
- stores seen jobs and review feedback in SQLite
- deduplicates listings by content fingerprint, not fragile source IDs
- ranks with local multilingual embeddings — the corpus is ~80% German, so an English profile query and a German project land in the same vector space
- evaluates only the top slice with an LLM to control cost and latency
- writes daily digests to `digests/YYYY-MM-DD.md`
- emails only jobs above a configurable score threshold
- supports review labels like `applied`, `rejected`, and `interested` to shape future ranking
- fails loudly if the source's yield collapses, so an empty inbox is never mistaken for a quiet market

## Why It’s Interesting

This is not a demo wrapper around one API. It is a full decision pipeline with clear stage boundaries, local state, evaluation logic, and operational automation.

Highlights:
- async Python pipeline with source adapters behind a shared interface
- deterministic hard filters before any model call
- multilingual semantic ranking with `intfloat/multilingual-e5-small` (asymmetric profile-query vs. job-document search via e5’s `query:` / `passage:` prefixes)
- LLM scoring with Claude Haiku on the reduced candidate set only
- fingerprint-based deduplication for unstable third-party job IDs
- GitHub Actions daily scheduler with cache-persisted SQLite state (the database is never committed)
- ~290 pytest checks covering the adapter, filters, ranking, storage, delivery, and edge cases

## Tech Stack

- Python 3.11
- `httpx`, `pydantic`, `sqlite3`, `PyYAML`
- `sentence-transformers` + `numpy` for local embeddings
- Anthropic Claude Haiku for structured job evaluation
- Resend for email delivery
- GitHub Actions for scheduled runs

## Project Structure

```text
src/jobscout/
  adapters/     # Source integrations and normalization
  filters/      # Hard filters and cross-source dedup
  ranking/      # Embeddings and similarity scoring
  evaluation/   # Prompting and LLM evaluation
  delivery/     # Markdown digest + email sender
  storage/      # SQLite persistence and feedback tracking
  run.py        # Pipeline entry point
```

## Running It

```bash
conda activate jobscout
python -m jobscout.run
```

Useful commands:

```bash
python -m jobscout.run --dry-run
python -m jobscout.run --since 2026-07-01
python -m jobscout.run --review today
pytest
```

Environment variables — `ANTHROPIC_API_KEY` and the optional Resend keys — live in `.env`. See [.env.example](.env.example); full setup and ops notes are in [docs/dev-notes.md](docs/dev-notes.md).

## What This Shows

For recruiters and hiring teams, this project demonstrates:
- product thinking: optimize for signal, not raw volume
- applied AI judgment: models are used where they add value, not where simple rules are better
- backend engineering: typed Python, modular architecture, persistent state, automated scheduling
- cost awareness: LLM calls happen after filtering and ranking, not across the full corpus
- operational realism: idempotency, failure handling, digest history, and review workflows

Architecture and the decisions behind the freelance pivot live in [CLAUDE.md](CLAUDE.md) and the ADRs under [docs/adr/](docs/adr/); build history and implementation detail in [docs/build-log.md](docs/build-log.md).
