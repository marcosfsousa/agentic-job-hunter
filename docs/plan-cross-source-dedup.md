# Plan: Cross-Source (and Within-Source) Deduplication

## Problem

`filter_unseen` deduplicates by `(id, source)`. The same job posted on both Adzuna
and JSearch — or re-posted on the same source with a different ID — passes through
as two separate listings and can appear twice in the digest.

## Approach

Fingerprint-based deduplication on `title + company` after the DB seen-check.

### Insertion point in the pipeline

```
filter_unseen → mark_seen_bulk → [NEW: deduplicate_listings] → filter_feedback → hard_filter → rank → eval
```

Marking ALL unseen jobs (including duplicates) as seen **before** deduplication is
intentional: it ensures neither variant of a duplicate resurfaces on the next run.
Then we pick the best listing from each fingerprint group for the current run.

---

## Files to create

### `src/jobscout/filters/dedup.py`

**Private helper: `_fingerprint(title: str, company: str) -> str`**
- Lowercase both strings
- Strip punctuation (keep alphanumeric + spaces)
- Expand unambiguous title abbreviations:
  - `sr` → `senior`
  - `jr` → `junior`
  - `ml` → `machine learning`
  - `nlp` → `natural language processing`
- Collapse whitespace, strip
- Return `f"{normalized_title}|{normalized_company}"`

Location is **intentionally excluded** from the fingerprint — remote jobs have
inconsistent location data, and the same company posting the same role in two cities
is likely one hire anyway.

**Public function: `deduplicate_listings(jobs: list[JobListing]) -> list[JobListing]`**
- Group all jobs by fingerprint
- For each group with >1 member:
  - Keep the listing with the **longest `description`**
  - Tiebreak: first in list wins
- Log at INFO: total duplicate groups found + total listings dropped
- Log at DEBUG: one line per group — title, company, sources kept vs dropped
- Return flat list of winners (order preserved from input)

---

## Files to modify

### `src/jobscout/run.py`

One insertion in the non-dry-run deduplication block:

```python
unseen = db.filter_unseen(all_jobs)
db.mark_seen_bulk(unseen)
unseen = deduplicate_listings(unseen)   # ← new line
actionable = db.filter_feedback(unseen)
```

Import to add:
```python
from jobscout.filters.dedup import deduplicate_listings
```

---

## Files to create (tests)

### `tests/test_dedup.py`

| Test | What it covers |
|---|---|
| Single job → returned unchanged | no-op path |
| Two jobs, different fingerprints → both returned | no duplicate |
| Two jobs, same title+company, different sources → one returned | cross-source dedup |
| Two jobs, same title+company, same source → one returned | within-source dedup |
| Three jobs, same fingerprint → one returned | group > 2 |
| Keeps longest description when deduping | selection logic |
| Tiebreak: first in list kept when descriptions equal | tiebreak |
| `"Sr ML Engineer"` == `"Senior Machine Learning Engineer"` | abbreviation expansion |
| `"ML-Engineer"` == `"ML Engineer"` | punctuation stripping |
| Location difference does not split a group | location excluded |

---

## What is NOT changing

- `seen_jobs` schema — no migration needed
- `filter_unseen` — unchanged
- `mark_seen_bulk` — unchanged
- All adapter code — no changes
- `hard_filter.py` — unchanged

---

## Logging examples

```
INFO  Deduplication: 2 duplicate group(s) found — 3 listings dropped
DEBUG Duplicate group: "senior ml engineer|deepmind" — kept adzuna_de (480 chars), dropped jsearch (210 chars)
DEBUG Duplicate group: "machine learning engineer|sap" — kept jsearch (620 chars), dropped adzuna_de x2
```

---

## Definition of done

- [ ] `filters/dedup.py` implemented with `_fingerprint` + `deduplicate_listings`
- [ ] `run.py` updated (one line added)
- [ ] `tests/test_dedup.py` passing (all 10 cases above)
- [ ] `pytest` green (currently 185 passing — should increase by ~10)
- [ ] Run `/simplify` on modified files before closing
