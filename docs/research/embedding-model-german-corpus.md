# Embedding model choice for a German corpus

Research asset for wayfinder ticket **N (#19)**, graduated from **F (#9)**.
Map: [Wayfinder: JobScout FTE → freelance pivot (spec)](https://github.com/marcosfsousa/agentic-job-hunter/issues/3).

**Answer: replace `multi-qa-MiniLM-L6-cos-v1` with `intfloat/multilingual-e5-small`.**
The ticket's proposed candidate (`paraphrase-multilingual-MiniLM-L12-v2`) is **rejected — it measured
worse than changing nothing.**

---

## 1. Method

Everything below is measured against a live payload, per the map's standing rule
("measure the payload, don't reason from model cards").

- **Corpus:** 128 unique live freelancermap projects, pulled 2026-07-18 as an anonymous parse of the
  embedded `ProjectSearch` JSON, honest User-Agent, 8-request hard cap — the G (#11) constraints.
  Built from 8 search queries (`machine learning`, `data scientist`, `NLP`, `LLM`, `generative AI`,
  `python entwickler`, `deep learning`) deduplicated by project id.
- **Job document:** `title + skills + description`, HTML-stripped — the composition M (#17) decided.
- **Query text:** F (#9)'s composition (`target_roles` + skills + `ideal_role` + `background`,
  negation stripped), in two variants — **EN-only** and **bilingual** (F's decision 1).
- **Language label:** `langdetect` on the stripped description.
- **Relevance:** each candidate project scored 1–10 by **Claude Haiku** against `profile.yaml`,
  explicitly instructed to judge the work and ignore the posting's language. This is the pipeline's
  own evaluator, so it measures the thing actually at stake: the quality of the pool handed to
  evaluation. 71 documents scored (the union of all configurations' top-30s), each scored once.

Scripts were run locally and discarded, per the repo's no-one-off-scripts convention.

---

## 2. How German is the corpus?

**81% German.**

| language of `description` | count | share |
| --- | --- | --- |
| German | 104 | 81% |
| English | 24 | 19% |

This is the sub-question that reshapes the problem. F (#9) framed the risk as the embedding
"silently deleting the German half of the corpus". It is not half — **German is the corpus**, and
English is the minority dialect. Any English bias is not a partial loss of recall; it inverts which
four-fifths of the market the pipeline can see.

Two related payload facts, both measured across all 128:

- **`translations` is 0/128 populated.** freelancermap ships the field but never fills it, so there
  is no free English rendering of a German posting to fall back on.
- **`skills`, when present, is already bilingual** — each entry is `{de, en, url}`, and 61 of 148
  bilingual entries have a genuinely different English rendering (`Cloud-Engineering` /
  `Cloud Engineering`, `SQL` / `SQL Databases`). See §6 for why this matters less than it looks.

---

## 3. Is the bias real? (paired control)

Comparing German documents against English documents corpus-wide is **confounded** — German-language
postings may simply be less relevant work (more SAP/BI consulting, less GenAI product build). So the
load-bearing measurement is a **paired** one: take 25 German documents, translate each to English with
Haiku, and score *the same document* in both languages. Content is held constant, so any change is
language alone.

| model | query | DE original | EN translation | lift | translation scored higher |
| --- | --- | --- | --- | --- | --- |
| `multi-qa-MiniLM-L6-cos-v1` (current) | EN-only | 0.3078 | 0.4768 | **+0.1690** | **24/25** |
| `multi-qa-MiniLM-L6-cos-v1` (current) | bilingual | 0.4497 | 0.4627 | +0.0129 | 12/25 |
| `paraphrase-multilingual-MiniLM-L12-v2` | EN-only | 0.5303 | 0.5253 | −0.0050 | 10/25 |
| `intfloat/multilingual-e5-small` | EN-only | 0.8518* | — | **+0.0081** | 23/25 |

*The absolute cosine scale differs per model and is not comparable across rows; only the lift is.

The single clearest number is **cosine between a document and its own translation** — how well the
model recognises that they say the same thing:

| model | cos(document, its own translation) |
| --- | --- |
| `multi-qa-MiniLM-L6-cos-v1` (current) | **0.6517** |
| `paraphrase-multilingual-MiniLM-L12-v2` | 0.8862 |
| `intfloat/multilingual-e5-small` | **0.9631** |

**The concern F raised is confirmed, and it is large.** Under the current model, translating a
document into English — changing nothing about the work — raises its match score by +0.169 and does
so for 24 of 25 documents. At 0.65, the model does not recognise a document and its own translation
as the same document; that is not a degraded aligned space, it is an unaligned one.

**F's bilingual query works better than F expected.** F recorded it as a lexical-overlap hack that
"cannot be verified to fix the problem". It can be, and it substantially does: it cuts the paired
language penalty from +0.169 to +0.013 (24/25 → 12/25, i.e. coin-flip). It is a real mitigation, not
a placebo. Its weakness is not effect size but **fragility** — it works only for concepts whose
German equivalents someone hand-wrote into the query, so it degrades silently as `target_roles` and
`skills` change, and it cannot help the *document* side at all.

---

## 4. Does it reorder the top-N cut?

Yes — decisively. The pool handed to Haiku is almost entirely different depending on the model.

**Top-30 overlap between configurations** (30 = identical pool):

| | CURRENT | F's plan | para | e5 |
| --- | --- | --- | --- | --- |
| **CURRENT** (multi-qa + EN) | 30 | 22 | 4 | — |
| **F's plan** (multi-qa + bilingual) | 22 | 30 | 7 | — |
| **para** (multilingual-para + EN) | 4 | 7 | 30 | 12 |

The current model and the paraphrase model share **4 of 30** candidates. This is not a tie-break
being nudged; it is a different shortlist.

**Measured pool quality** — Haiku fit score of the top-30, plus how many of the 15 genuinely
highest-scoring projects in the corpus each configuration actually reaches:

| configuration | mean fit | ≥7 | ≥8 | DE in top-30 | captures best-15 |
| --- | --- | --- | --- | --- | --- |
| **CURRENT** multi-qa + EN query | 4.23 | 8 | 2 | 10/30 | 6/15 |
| **F's plan** multi-qa + bilingual | 4.70 | 10 | 4 | 18/30 | 9/15 |
| **para** multilingual-para + EN | **3.50** | 7 | 3 | 29/30 | 6/15 |
| **e5** multilingual-e5 + EN query | **5.07** | **13** | **5** | 23/30 | **12/15** |
| e5 + bilingual query | 4.40 | 9 | 5 | 27/30 | 8/15 |

*(corpus-wide mean over the 71 scored documents: 3.80. Corpus is 81% German, so a language-neutral
ranker should land near 24/30 German.)*

Three things fall out of this table.

**The status quo misses 60% of the best work.** The current configuration reaches 6 of the 15
best-fitting projects. F's bilingual mitigation lifts that to 9/15 — again, a real improvement.

**Fixing the language bias is not the same as improving recall.** `paraphrase-multilingual-MiniLM-L12-v2`
is the most language-neutral configuration by German share (29/30, above even the 81% base rate) and
simultaneously **the worst pool of all five — worse than changing nothing** (3.50 vs 4.23, and still
only 6/15). It maximises the metric the ticket proposed while degrading the outcome the metric was a
proxy for.

The cause is exactly the trade-off the ticket flagged as "a real trade-off, not a free upgrade":
it is a **symmetric paraphrase** model being asked to do **asymmetric** retrieval (short profile query
vs long project document). It ranks by "is this a German software project" rather than by topic. Its
top-10 contains a Delphi/Power Apps developer, an embedded software role, a CMMS Django/React
fullstack build and a Robot Framework test-automation role — German, and almost entirely off-topic.

**The resolution is a model that is both aligned and asymmetric.** `intfloat/multilingual-e5-small`
was not among the ticket's candidates and answers it on every axis: aligned multilingual space
(0.963), retrieval-tuned rather than paraphrase-tuned, and **still 384 dimensions**. Its top-10 is
on-topic in *both* languages — `Machine Learning Engineer für KI-gestützten Customer Support`,
`Senior GenAI Engineer — LLMs / RAG / Python`, `Architekten/Python-Entwickler für KI-Anwendungen |
Azure OpenAI`, `Forward Deployed AI Engineer - Freelance`. Its top-30 lands at 23/30 German against
an 81% base rate — the closest of any configuration to simply reflecting the market.

---

## 5. Blast radius

**None of the migration risk the ticket worried about materialises.**

| concern | finding |
| --- | --- |
| Stored feedback centroid assumes 384 dims | `multilingual-e5-small` is **384 dims** — no centroid migration, no storage change |
| Cached vectors | Job/centroid vectors are recomputed each run and discarded (per H #12); only the 384-dim assumption matters |
| Context window | 512 tokens, same as current — M (#17)'s head-truncation design carries over unchanged |

Two execution details that are easy to get wrong:

- **e5 requires prefixes.** Documents must be encoded as `passage: <text>` and the profile query as
  `query: <text>`. Without them the model silently underperforms — this is how e5 expresses the
  asymmetry that makes it the right choice.
- **`max_seq_length` is a live trap.** `paraphrase-multilingual-MiniLM-L12-v2` ships a
  sentence-transformers default of **128 tokens**, not 512. At that setting it truncates 99% of job
  documents *and the profile query itself* — the EN-only and bilingual queries produced byte-identical
  scores because both were cut before the German half was reached. Any model swap must assert
  `max_seq_length` explicitly rather than trust the default. (`multilingual-e5-small` defaults to 512.)

---

## 6. Truncation: a second, quieter German penalty

M (#17) measured description length in **characters** (median 3,951 / max 8,289) and concluded the
512-token window overflows. Measured in tokens, on HTML-stripped documents:

| model | doc tokens (median) | DE median | EN median | docs over 512 tokens |
| --- | --- | --- | --- | --- |
| `multi-qa-MiniLM-L6-cos-v1` (current) | 705 | **764** | 553 | **80%** |
| `intfloat/multilingual-e5-small` | 550 | **536** | 626 | 57% |

M's finding holds — most documents overflow — but there is a compounding effect M could not see from
character counts. The current model's English wordpiece vocabulary **shreds German into more
subwords**: a German document costs 764 tokens against an English one's 553, so at a fixed 512-token
cut, German documents lose proportionally more of their content. The language penalty in §3 and the
truncation penalty stack in the same direction.

The swap relieves this too. Under e5's multilingual vocabulary the relationship **inverts** (German
536 vs English 626) and overall overflow drops from 80% to 57%.

---

## 7. Recommendation

1. **Adopt `intfloat/multilingual-e5-small`** as the embedding model — 384 dims, 512-token window,
   `query:` / `passage:` prefixes required.
2. **Do not adopt `paraphrase-multilingual-MiniLM-L12-v2`.** Measured worse than the status quo.
3. **Revert F (#9)'s bilingual query to English-only once e5 lands.** The two mitigations are not
   additive — stacked, they overshoot: e5 + bilingual drops pool quality from 5.07 to 4.40 and
   best-15 capture from 12/15 to 8/15, because the query's German lexical mass pulls an
   already-aligned space toward German documents regardless of topic. Keep the bilingual query only
   as the fallback if the swap is deferred, where it remains a genuine improvement (4.70 vs 4.23).

## 8. Limits of this measurement

Recorded rather than omitted:

- **Relevance ground truth is Haiku's judgement, not Marcos's.** Haiku is also the downstream
  evaluator, so a shared blind spot would not show up here. It was instructed to ignore posting
  language, but that instruction is not verified to hold.
- **One snapshot, one day, 128 projects, one profile.** Seasonal or query-mix drift is unmeasured.
- **The symmetric-vs-asymmetric finding is measured on this task only.** It says the paraphrase model
  is wrong *here*; it is not a general claim about the model.
- **e5 was measured, but not tuned.** No comparison against `multilingual-e5-base` (768 dims, would
  force a centroid migration) — deliberately, since the same-dim option already clears the bar.
</content>
</invoke>
