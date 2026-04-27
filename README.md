# JobScout

JobScout is a personal AI job-matching pipeline for AI/ML roles in Germany.

It pulls listings from multiple sources, removes obvious mismatches with deterministic filters, ranks the remaining jobs with semantic search, asks an LLM to evaluate only the strongest candidates, and delivers a daily digest by email plus a markdown archive. The goal is simple: fewer, better jobs to review by hand.

This project is intentionally opinionated:
- it never auto-applies
- `profile.yaml` is the single source of truth for preferences
- the pipeline is idempotent, so rerunning on the same day does not spam duplicates
- adapters are pluggable, so new job sources can be added without changing the pipeline

## What It Does

Pipeline:

`Ingest -> Deduplicate -> Hard Filter -> Embed + Rank -> LLM Evaluate -> Deliver`

Current sources:
- Adzuna
- JSearch
- JobSpy for LinkedIn and Indeed

Core behaviors:
- normalizes raw listings into a single internal `JobListing` model
- stores seen jobs and review feedback in SQLite
- deduplicates within and across sources
- uses local sentence-transformer embeddings for cheap first-pass ranking
- evaluates only the top slice with an LLM to control cost and latency
- writes daily digests to `digests/YYYY-MM-DD.md`
- emails only jobs above a configurable score threshold
- supports review labels like `applied`, `rejected`, and `interested` to improve future ranking

## Why It’s Interesting

This is not a demo wrapper around one API. It is a full decision pipeline with clear stage boundaries, local state, evaluation logic, and operational automation.

Highlights:
- async Python pipeline with source adapters behind a shared interface
- deterministic hard filters before any model call
- semantic ranking with `multi-qa-MiniLM-L6-cos-v1`
- LLM-based scoring on the reduced candidate set only
- fingerprint-based deduplication for unstable third-party job IDs
- GitHub Actions daily scheduler with persisted SQLite state
- nearly 300 pytest checks covering adapters, filters, ranking, storage, delivery, and edge cases

## Tech Stack

- Python 3.11
- `httpx`, `pydantic`, `sqlite3`, `PyYAML`
- `sentence-transformers` + `numpy`
- OpenAI API for structured job evaluation
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
python -m jobscout.run --since 2026-04-01
python -m jobscout.run --review today
pytest
```

Environment variables live in `.env`. See [.env.example](/C:/Users/Work/Documents/solo-projects/agentic-job-hunter/.env.example:1).

## What This Shows

For recruiters and hiring teams, this project demonstrates:
- product thinking: optimize for signal, not raw volume
- applied AI judgment: models are used where they add value, not where simple rules are better
- backend engineering: typed Python, modular architecture, persistent state, automated scheduling
- cost awareness: LLM calls happen after filtering and ranking, not across the full corpus
- operational realism: idempotency, failure handling, digest history, and review workflows

Build history and implementation detail live in [docs/build-log.md](/C:/Users/Work/Documents/solo-projects/agentic-job-hunter/docs/build-log.md:1).
