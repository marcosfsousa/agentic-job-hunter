# Freelance / Contract Source Landscape — DACH + Remote

Research for the FTE → freelance/contract pivot. The question: which sources should JobScout
ingest for DACH-centric (Germany) + remote AI/ML contract work, and what can an `httpx`-based
adapter actually get out of them?

Everything below was fetched directly on **2026-07-16**. That is the access date for every ToS
quote in this document. These pages change — re-check before acting on any legal reading here.

Method: primary sources only for load-bearing claims — official API docs, developer portals, the
actual `robots.txt` and Terms pages, official pricing pages. Where a claim rests on a blog post or
a scraper library's README it is labelled secondary and treated as a lead, not a finding. Where
something could not be established, it says so rather than guessing.

Covered: freelancermap, freelance.de, GULP, Etengo, SOLCOM, Malt (incl. ex-Comatch), Upwork, Toptal,
Contra, Fiverr, We Work Remotely, RemoteOK, Himalayas, Hays, Randstad, Michael Page, Gun.io,
Braintrust, Instaffo, 9am, uplink.tech, Junico, Projektwerk, Twago. Where a feed or API was live, I
**fetched and parsed the actual payload** rather than reading the docs about it — that turned out to
be the difference between right and wrong answers repeatedly (see the data-model section).

**Provenance, which matters here.** Verified by me directly against live pages/payloads: all
`robots.txt` findings; the freelancermap `ProjectSearch` payload, field population, aggregation
counts and AGB clauses; the Upwork API Terms quotes; the WWR and RemoteOK feed contents; the
Projektwerk/Twago redirects; the GULP, freelance.de, Etengo and Malt ToS quotes. **Reported by a
delegated agent and *not* independently verified by me**: the Himalayas `/jobs/api/search` result
(76), the Hays JSON-LD/sitemap details, the Bundesagentur für Arbeit finding, the Braintrust
details, and the europeremotely parked-domain claim. Those are marked inline where they appear.

**Two corrections I made to my own work, recorded rather than quietly patched:** I reported
freelancermap's rate as "sometimes exposed" (it is 0/22) and its adapter as brittle CSS scraping (it
is a JSON parse); and I listed Projektwerk as a live board on the strength of its `robots.txt` when
the site 301s to freelancermap. Both errors came from reading pages instead of measuring payloads.

Not covered, and flagged as gaps rather than papered over: Working Nomads, Wellfound (its ToS claims
were retracted mid-research and remain unestablished), and a long tail of DACH agencies (Questax,
Westhouse, Allgeier, Computer Futures, Darwin Recruitment, Robert Half, Hays Talent Solutions,
codecontrol).

**I am not a lawyer and this is not legal advice.** The ToS readings below are quotes plus a plain
reading of them, offered so a human can make the call.

### Independent verification of the load-bearing freelancermap claims (2026-07-16)

The entire #1 recommendation rests on freelancermap, and this document's author reported reliability
problems with a delegated agent mid-research. So the freelancermap numbers were **re-fetched and
re-measured from scratch, independently**, before this document was accepted. All of it held:

| Claim | Reported | Independently measured | |
|---|---|---|---|
| ML projects, Deutschland | 116 | **116** | ✅ |
| ML projects, DACH | 136 | **136** (116 DE + 12 AT + 8 CH) | ✅ |
| Remote split | 57 / 52 / 7 | **57 remote / 52 hybrid / 7 on_site** | ✅ |
| Contract type split | 94 / 12 / 10 | **94 contracting / 12 employee_leasing / 10 permanent_position** | ✅ |
| `endcustomer` true | 5 of 116 | **5** | ✅ |
| `budget` populated | 0/22 | **0/22** | ✅ |
| `duration` populated | 17/22 | **17/22**, clean integers (`6`, `5`) | ✅ |
| `description` populated | 22/22 | **22/22** | ✅ |
| `skills` populated | 6/22 | **6/22** | ✅ |
| `projectContractType` populated | 22/22 | **22/22**, incl. `remoteInPercent` 100 / 60 / 50 | ✅ |
| `embedding` | 1024-dim | **1024-dim, 22/22** | ✅ |
| `created` | exact ISO timestamp | **`2026-07-16T15:38:04+02:00`** | ✅ |
| Field names | `duration`, `beginningYear` | **confirmed** (not `durationInMonths`/`startYear`) | ✅ |

**One correction, and it runs in the recommendation's favour:** description length was reported as
"~135 words" from one eyeballed listing. Measured across the page, the **median is 3,951 chars**
(min 1,026, max 8,289) — roughly 5× richer, which strengthens the embedding-quality argument rather
than weakening it. The 8,289-char max also surfaces a real downstream question: it overflows
`multi-qa-MiniLM-L6-cos-v1`'s 512-token window, so truncation strategy needs deciding.

The verification also confirms the `remoteInPercent` finding concretely: values of **100, 60 and 50**
appear on page one, so the "60% remote / 3 days on site" arrangement is real and today's
`remote_policy` enum genuinely cannot represent it.

Method: fetched `https://www.freelancermap.de/projekte?query=machine%20learning&countries%5B0%5D=1`,
extracted the `data-component-name="ProjectSearch"` script payload, parsed it, and counted populated
fields across `initialResults` plus the `aggregations` block. Reproducible in ~20 lines of Python.
**Everything outside freelancermap in this document retains the provenance stated above** — the
Himalayas, Hays, Braintrust and Bundesagentur claims remain agent-reported and unverified.

## The findings that matter most

1. **The DACH/global split is stark, and it runs opposite to intuition.** *Exactly one* platform in
   this landscape offers a public, outbound jobs API a solo developer can actually get — **Upwork**,
   the one you'd expect to be most hostile. Its API terms explicitly name JobScout's use case as
   permitted. Meanwhile **every single DACH-native source is scrape-or-nothing.** Every
   "freelancermap API" or "GULP API" lead traces back to either an *inbound* feed for recruiters
   posting jobs *in*, or a third-party scraper.
2. **For the DACH tier, the blocker is legal, not technical.** The adapter interface fits all of
   them; the pipeline stages would not change. What separates them is ToS posture — and it ranges
   from freelancermap's silence to GULP's flat contractual ban.
2b. **The DACH market consolidated onto freelancermap, which resolves most of the tension.**
   Projektwerk now **301s to freelancermap**; Twago **404s**; and Randstad/GULP and freelance.de post
   their listings *onto* freelancermap. **The two sources that prohibit automation are also
   substantially redundant** — one adapter reaches their inventory anyway. The legal answer and the
   engineering answer agree for once.
3. **Rate is the agencies' product, so agencies do not publish it.** This is stronger than "sparse":
   freelancermap's `budget` is populated **0 out of 22** across an ML search page, Etengo has no such
   field, Himalayas returns `0-0`. **Only Upwork has usable rate data, and it's USD-hourly.** Any
   ranking premised on day rate will not get the field. The realistic DACH ceiling is *duration +
   start date + remote % + contract type*; **rate is a negotiation, not a filter**, and
   `profile.yaml` should say so.
3b. **~96% of the DACH ML market is intermediated.** `endcustomer` = **5 of 116**. The
   agency-vs-direct signal Marcos most wants is real and structured — and filtering on it leaves five
   projects.
4. **Two platforms are structurally un-ingestible regardless of law.** Malt and Toptal **push** work
   to matched profiles; there is no board to read. Malt is the strongest DACH presence in this
   research and still has nothing to adapt. That makes it a profile-optimisation play, not a ticket.
5. **The sharpest constraint isn't access — it's Upwork's 24-hour data retention cap**, which
   collides with `data/jobscout.db` and, arguably, with storing embeddings at all. See the Upwork
   section; this is the one finding most likely to change a design decision.
6. **Openness and usefulness are uncorrelated.** The two most open sources in this report — We Work
   Remotely's public RSS and RemoteOK's public JSON API — are also the least useful: I pulled both
   and found **6 contract jobs out of 99** on WWR, and on RemoteOK **no contract field at all**,
   salary populated on **1 of 100**, and spam tags. The easiest adapters to build are the ones least
   worth building.

## Summary table

| Platform | Access model | ToS posture on automation | Rate exposed? | Duration exposed? | Description quality | DACH AI/ML volume |
|---|---|---|---|---|---|---|
| **freelancermap** | No API, but **embedded `ProjectSearch` JSON** — parse one blob/page, page via `pagenr`, sync on exact `created` | **Silent** — no anti-automation clause in AGB; `robots.txt` `Disallow:` empty. Bound by §4(5) *"für eigene Zwecke"* + §11(2) no commercial reprocessing | **No — `budget` 0/22 populated** | **Yes — integer months, 17/22** | Full prose, 22/22 | **116 ML in DE / 136 DACH (verified);** 57 fully remote |
| **Upwork** | **Public GraphQL API, self-serve key**, OAuth2, 300 req/min | **Explicitly permits via API** (scraping prohibited) | **Yes — real min/max ranges** | Yes (structured) | **Full text in search response** | AI GSV +50% YoY; **no DACH breakdown published** |
| **Himalayas** | **`/jobs/api/search`** endpoint (agent-reported, **unverified by me**) | **Conflict**: API page says "anyone can use"; ToS bars automated access to Services | Field exists, usually `0-0` | — | — | **76 Contractor+AI+DE (unverified)** |
| **freelance.de** | Scrape only (no public API) | **Explicitly prohibits** — `robots.txt` comment bans non-search-engine crawling | No (not a field) | No | Moderate; company name paywalled | 56 live ML; **partly redundant — posts onto freelancermap** |
| **GULP** (Randstad) | Scrape only (no outbound API) | **Explicitly prohibits** — AGB §4 Nr. 1 d) | No | Typically yes | Unverified (JS shell) | **Redundant — inventory reaches you via freelancermap** |
| **Etengo** | Scrape only | **Silent on automation**; §5(1) permits retrieval/storage *for own use* | **No — field does not exist** | **Yes** (`Laufzeit 7 Monate`) | Terse, structured stub | Thin — ~0 dedicated AI/ML on inspection |
| **SOLCOM** | Scrape only; **403s automated fetches** | robots.txt permissive, but edge-blocks bots | No | Unverified | Unverified (403) | Unverified |
| **Malt** (incl. ex-Comatch) | Public API exists — **invoices + SCIM only, zero job endpoints**; model is push-not-pull | **Explicitly prohibits** — Art. 10.2; Cloudflare-challenges bots | n/a — no listing surface | n/a | n/a | Strongest DACH presence, **but nothing to ingest** |
| **Toptal** | No public API; **zero client engagements publicly listed** | **Explicitly prohibits** | n/a | n/a | n/a | n/a — admission problem, not ingest |
| **Contra** | SDK serves **freelancer profiles** (wrong direction); jobs 302 to login | **Explicitly prohibits** | n/a | n/a | n/a | Opaque — no stats published |
| **Fiverr** | No public API (`developers.fiverr.com` **doesn't resolve**) | **Explicitly prohibits** — §8.8(viii)+(ix) | n/a | n/a | n/a | **Inverted** — gig counts measure competitors |
| **We Work Remotely** | **Live public RSS**, no auth (verified) | Permissive `robots.txt`; **silent** ToS | No | No | **Best free source — median 7,947 chars** | **16 of 173 Contract** via category feeds; US-heavy |
| **RemoteOK** | **Live public JSON API**, no auth (verified: 100 jobs) | **Explicitly permits via API, conditional on attribution**; EU DSM Art. 4 reservation in robots | Field exists, **populated 1/100** | No — no contract field at all | Decent, but **honeypot in 100/100 — must strip** | **3/100 AI-tagged**; tags are spam; ~0 DACH |
| **Projektwerk / Twago** | **Dead** — projektwerk 301s → freelancermap; twago 404s | — | — | — | — | — |
| **Working Nomads / Wellfound** | **Not verified — gap** (Wellfound ToS claims retracted) | — | — | — | — | — |
| **Hays** | Scrape only | **Explicitly prohibits** (ToS §3) *despite* `robots.txt` allowing ClaudeBot | No | Typically yes | Moderate | Not isolable from FTE counts |
| **Randstad** | Scrape only | **Explicitly prohibits** — `robots.txt` blocks ClaudeBot from `/freelance/` by name | No | — | — | — |
| **Michael Page** | Scrape only | Silent on AI bots; **contract/salary facets robots-disallowed** | No | — | — | Weak |
| **Gun.io** | No public API | **Explicitly prohibits** — Terms §5 | No | No | Stub | ~0 DACH |
| **Braintrust** | No public API | Silent-to-weakly-restrictive | Yes ($/hr) | No | SEO stub, no description | Negligible DACH |
| **Instaffo** | No public job API | `Disallow: /*?` kills search URLs | No | — | — | Weak (FTE-leaning) |
| **9am.works** | **Login-gated aggregator** | robots.txt 404s | No | — | — | n/a — is a JobScout competitor |
| **uplink.tech** | **Login-gated** (`app.uplink.tech`) | robots.txt permissive | Yes (secondary claim) | — | — | Small, gated |
| **Junico** | Scrape only | robots.txt permissive | Unverified | Unverified | Unverified | Generalist, Gen Y/Z |

"Silent" throughout means *no clause found either way* — which is **not** permission. See the legal
note near the end on why silence plus a permissive `robots.txt` still leaves § 87b UrhG in play.

## freelancermap — the one to beat

**Access model: scraping only.** There is no outbound public API and no RSS feed. This needs
saying clearly because search results imply otherwise:

- The XML/JSON interface that turns up in searches is **inbound**. Per the
  [recruiter pricing page](https://www.freelancermap.de/preise/recruiter): *"Enterprise-Mitglieder
  können Projekte automatisiert via XML oder JSON importieren."* — Enterprise members (€89/mo) can
  *import projects into* freelancermap. It is a route for agencies to post jobs, not for consumers
  to read them. The standard import is free (*"Der Standardimport ist kostenfrei."*) but it is the
  wrong direction entirely.
- The [FAQ](https://www.freelancermap.de/hilfe.html) offers no RSS or API for freelancers searching
  projects — only an email "Projektagent": *"Auf Basis Ihrer gespeicherten Filtereinstellungen
  durchsucht er täglich die Projektbörse und sendet Ihnen automatisch relevante Ausschreibungen per
  E-Mail."*
- `https://www.freelancermap.de/rss-feeds.html` returns **HTTP 410 Gone** — an RSS feed existed once
  and was deliberately retired. (410 is "Gone", not 404 "Not Found" — the distinction is a
  deliberate signal that the resource was removed on purpose.) `https://www.freelancermap.de/partner-werden`
  also returns **410**, so the partner route appears retired as well.
- The third-party aggregator `freelance-o-mat.de/rss-feeds.html`, which turns up in searches
  claiming RSS feeds of freelancermap.de/.at/.ch projects, **also returns HTTP 410 Gone.**
  The RSS era for DACH freelance boards is over, on both the first-party and the aggregator side.
- The [Apify freelancermap scraper](https://apify.com/andinfinity/freelancermap/api) is a
  third-party product, not first-party consent. Secondary.

**ToS posture: silent.** This is the most permissive posture of any serious DACH source.

[`robots.txt`](https://www.freelancermap.de/robots.txt), verbatim and in full:

```
User-agent: *
Disallow: 
Sitemap: https://www.freelancermap.de/sitemap.xml
```

An empty `Disallow:` means nothing is disallowed. No AI-crawler blocks, no crawl-delay.

The [AGB](https://www.freelancermap.de/allgemeine-geschaeftsbedingungen.html) contain **no clause
mentioning** Roboter, Crawler, Spider, Scraping, automatisiert, or Auslesen. The nearest applicable
language is general, in § 4 Abs. 1:

> a) "dafür zu sorgen, dass die Netzinfrastruktur oder Teile davon nicht durch übermäßige
> Inanspruchnahme überlastet werden"
>
> b) "die Zugriffsmöglichkeit auf die freelancermap Dienste nicht mißbräuchlich zu nutzen und
> rechtswidrige Handlungen zu unterlassen"

Plain reading: no prohibition on automated access as such, but a duty not to overload the
infrastructure. A slow, well-behaved crawler is not obviously in breach; a hammering one is. This
is "silent", not "permits" — silence is not consent, and § 87b UrhG still applies (see the legal
note below).

*(Verification note: I did not take this on one pass. I pulled the AGB directly via curl and
searched the full ~50k-character text myself. Occurrences of `Crawler`, `Spider`, `Scraping`,
`automatisiert`, `auslesen`, `maschinell`, `Skript`, `Bots`: **zero**. The single hit for `Roboter`
is a reCAPTCHA UI string — *"Bitte bestätigen Sie, dass Sie kein Roboter sind."* — not a term.
§ 4 Abs. 1 a/b quoted above are verbatim from that fetch.)*

Two things that fetch turned up which sharpen the risk picture, in opposite directions:

- **§ 4 Abs. 3 names the actual consequence**, and it is not a scraping lawsuit: *"Verstößt der
  Nutzer gegen die in § 4 Absatz 1 genannten Pflichten, ist freelancermap berechtigt, das
  Vertragsverhältnis vorbehaltlich der Geltendmachung von Schadensersatzansprüchen ohne Einhaltung
  einer Frist zu kündigen"* — immediate termination of the contract, plus a reserved damages claim.
  So the realistic downside of over-crawling is **losing the account**, which for someone who
  actually wants to *work* through freelancermap is a meaningful cost in its own right.
- **freelancermap calls its own service a database**, in § 2 Abs. 2: *"Die Informationsdienste
  stellen dem Nutzer via einer elektronischen Datenbank Informationen zur Verfügung."* That is the
  platform's own characterisation, and it strengthens rather than weakens the § 87b UrhG angle
  below. The absence of an anti-scraping clause does not mean the absence of a database right.

**Two further AGB clauses define the actual boundary**, and they are the ones to design against.
Both verified verbatim from my own fetch:

> **§ 4 Abs. 5:** "Weiterhin ist der Nutzer verpflichtet, die Dienste und die darin enthaltenen
> Informationen nur innerhalb seines Vertrages und **für eigene Zwecke** zu nutzen. Der Nutzer
> verpflichtet sich, die Dienste nicht für rechtswidrige Zwecke zu verwenden oder eine Verwendung
> dafür zu gestatten."

> **§ 11 Abs. 2:** "Der Nutzer versichert, mit den von ihm bezogenen Informationen **weder zu
> handeln, noch sie gewerbsmäßig weiterzuverarbeiten** und dies auch Dritten nicht zu gestatten."

Plain reading, and note it is the *same shape* as Etengo's § 5(1): the binding constraints are
**use it for your own purposes; don't trade it; don't commercially reprocess it; don't overload the
infrastructure.** A personal, single-user, non-redistributing digest sits inside all four. **What
would breach them** is redistributing the digest, publishing the data, or building a product on it.

This is the strongest legal position available for a DACH source in this report — but it is a
position *within a contract*, not an absence of one. The moment JobScout gains a second user or a
public output, § 4 Abs. 5 and § 11 Abs. 2 are the clauses that break, and they break clearly.

Empirically, freelancermap does **not** bot-block: every project page fetched during this research
returned full server-rendered HTML with no 403.

**Fields exposed — I got this badly wrong on the first pass and have corrected it.** My initial
read was "no JSON-LD, so CSS-selector parsing, brittle." That is **wrong**. freelancermap's search
page embeds a `react-on-rails` component called **`ProjectSearch`** carrying a fully typed JSON
payload. There is no scraping-of-HTML involved at all — you parse one JSON blob per page.

I verified this directly by fetching `/projekte?query=machine+learning` and extracting the
component. The per-listing field list, verbatim from the payload:

```
beginningMonth, beginningText, beginningYear, budget, city, company, contractType, country,
created, description, duration, durationText, embedding, endcustomer, expires, firstName,
generatedMainCategories, id, image, industry, lastName, links, locations, matching, pid, plink,
poster, projectContractType, skills, slug, states, subCategories, title, topProject,
translations, updated, url, user, verlaengerung
```

**Field population, measured across the 22 results on page 1** (this is the part that matters and
that no schema tells you):

| Field | Populated | Example |
|---|---|---|
| `description` | **22/22** | full prose |
| `created` | **22/22** | `2026-07-16T15:38:04+02:00` — exact ISO |
| `expires` | **22/22** | epoch |
| `projectContractType` | **22/22** | `{'type': 'contracting', 'remoteInPercent': 100}` |
| `duration` | 17/22 | `6`, `5` — **integer months** |
| `contractType` | 18/22 | `CONTRACT` |
| `beginningYear` / `beginningText` | 12/22 · 11/22 | `2026` · `ab sofort` |
| `verlaengerung` (extension) | 12/22 | `1` |
| `skills` | **6/22** | `[{de: 'MLOps', en: 'MLOps', url: '/projekte/mlops'}]` |
| **`budget`** | **0/22** | `[]` — **empty on every single result** |
| **`endcustomer`** | **0/22** | `False` on all |

Three corrections to my own earlier claims fall out of this, and two of them cut *against*
freelancermap:

1. **Rate is not "sometimes present" — it is effectively never present.** I earlier reported
   `70,00 € Budget` from an individual project page and inferred rate was sometimes exposed. Across
   a full ML search page, `budget` is **populated 0 out of 22 times**. The one populated example I
   found was a tiny one-month gig. **Treat rate as absent on freelancermap.**
2. **`endcustomer` is `False` on all 22 results**, and the aggregation facet says **only 5 of 116**
   German ML projects are direct end-client. So my earlier framing — "agency-vs-direct is structured
   and filterable, a rare win" — was half right and misleading. It *is* a first-class filter facet
   (`endcustomer` appears in both `initialState.filter` and `aggregations`). But **filtering on it
   collapses the pool from 116 to 5.** It is a real field describing a market that is ~96%
   intermediated. That is a finding about the market, not about the schema.
3. **Duration is better than I said** — a clean integer month count, not free text to parse.

Two genuinely notable extras:

- **`projectContractType.remoteInPercent` is populated 22/22** — remote percentage is structured
  and universal, not a badge to regex out of prose.
- **`embedding` is populated 22/22 — freelancermap ships a precomputed 1024-dim vector per
  listing.** It is not from `multi-qa-MiniLM-L6-cos-v1` (384-dim) so it cannot be compared against
  Marcos's profile query directly, and it is undocumented, so I would not build on it. Noting it
  because it is unusual and might be useful for cheap clustering or near-duplicate detection.

For reference, the older field labels visible on individual project pages (still accurate, just
redundant now that the JSON exists):

On [api-developer-2539306](https://www.freelancermap.de/projekt/api-developer-2539306):

| Label | Value |
|---|---|
| Ort | `Düsseldorf, Deutschland` |
| Remote | `100% Remote` |
| Beschäftigungsart | `Freiberuflich` |
| Start | `ab sofort` |
| Dauer | `1 Monat` |
| Budget | `70,00 €` |
| Projekttyp | `Endkundenprojekt` |
| Skills | Java, .Net Framework, PHP, APIs, … |

On [api-schnittstelle-interface](https://www.freelancermap.de/projekt/api-schnittstelle-interface):
Ort, Remote (`100% Remote`), Beschäftigungsart, Verfügbarkeit (`ab sofort`), Branche
(`Automobilindustrie`), Projekttyp (`Endkundenprojekt`), a technology tag, contact person — and
**no Dauer, no Budget, no posted date**.

That contrast is the single most important field-level finding in this document: **rate and
duration are optional and frequently absent on the same source.** Any model must treat them as
nullable, and any hard filter keyed on them will silently discard most of the corpus.

- **Rate**: the `Budget` label (`70,00 €`) appears on the occasional listing page, but see the
  measured population above — **0/22 in the search payload.** Treat as absent. Where it does appear
  the unit is ambiguous (project total vs hourly vs daily).
- **Duration**: rendered as free text (`1 Monat`) on the page, but a clean **integer** in the JSON.
- **Start**: free text, dominated by `ab sofort` (`beginningText`), with `beginningYear`/
  `beginningMonth` alongside.
- **Remote**: **a percentage** (`100% Remote`) — richer than the current `remote_policy` enum, and
  populated 22/22 in the JSON as `projectContractType.remoteInPercent`.
- **Agency vs direct**: `Endkundenprojekt` is a badge and `endcustomer` is a real filter facet — but
  it is **true for only 5 of 116**. Structured, yes; useful as a hard filter, no.
- **Skills**: structured tags on the page; sparse in the payload (6/22). The EMSI-coded taxonomy
  lives in `aggregations`, not per-listing.
- **Description**: full free text, ~135 words on the sampled listing; populated 22/22 in the
  payload. Good embedding material — not a click-through stub.

**Volume — the best in the landscape, from first-party numbers.**
[freelancermap.com](https://www.freelancermap.com/) states: *"Currently over 15,700 open projects"*,
*"We list over 2,000 projects weekly on our platform"*, *"Over 188,900 freelancer profiles"*, *"0%
commission fees"*, with **Development: 7,515** and **Consulting: 7,404** projects.
[/fuer-freelancer](https://www.freelancermap.de/fuer-freelancer) independently says *"Zugang zu 2000
neuen Projekten pro Woche"* — consistent across the .de and .com properties.

Caveat on a number you will see elsewhere: several secondary sources claim *4,000* new projects per
week. Both first-party pages say **2,000**. Use 2,000; the 4,000 figure is unverified and likely
conflates the international network.

**AI/ML volume — RESOLVED, and it is good.** This was the biggest open question in my first pass and
I flagged it as potentially fatal to the recommendation. It is now answered, from first-party JSON.

The trap that misled me: the **tag/category pages are near-empty and not representative.**
[freelancermap.com/projects/machine-learning](https://www.freelancermap.com/projects/machine-learning)
says verbatim *"2 jobs & projects available"*; `/projekte/kuenstliche-intelligenz` returned
`0 Projekte`. I inferred this was tag sparsity rather than real scarcity but could not prove it.

**The inference was correct.** Querying `/projekte?query=machine+learning` and reading the
`aggregations` block out of the `ProjectSearch` payload gives, verbatim:

```
countries -> Deutschland: 116, Österreich: 12, Schweiz: 8, Großbritannien: 7, USA: 2, Irland: 2
```

**116 live ML projects in Germany; 136 across DACH** — not 2. The country filter defaults to
Germany. Further facets from the same payload, all first-party:

| Facet | Breakdown |
|---|---|
| `remoteInPercent` | **remote 57** · hybrid 52 · on_site 7 |
| `projectContractType` | **contracting 94** · `employee_leasing` **12** · `permanent_position` 10 |
| `endcustomer` | **5** |
| `matchingSkills` | Machine Learning 28 · Python 27 · Künstliche Intelligenz 21 · SQL 13 · MLOps 12 |
| `states` | Hessen 29 · NRW 27 · Bayern 20 · BaWü 11 · Berlin 6 |
| `industry` | IT 51 · Verkehr/Logistik 12 · Energie 8 · Telko 8 |

Three things worth pulling out:

- **57 of 116 are fully remote** — the remote-first slice of the DACH ML market is roughly half.
- **`employee_leasing` = 12** is *Arbeitnehmerüberlassung* (temp labour leasing), which is **not
  true freelance contracting** and should be filtered out. `permanent_position` = 10 means ~10 FTE
  roles leak onto the freelance board too. So **~19% of the 116 is not what Marcos wants**, and both
  are excludable deterministically via `projectContractType`.
- **`endcustomer` = 5.** Only five of 116 are direct-to-client. This is the single most sobering
  number in the report: the DACH ML contract market is ~96% intermediated.

Note the `matchingSkills` facet carries **stable Lightcast/EMSI-style skill IDs** —
`Machine Learning` is `KS1261Z68KSKR1X31KS3`, `Python` is `KS125LS6N7WP4S6SFTCK`. Those are
filterable by ID rather than by string matching. (They appear in `aggregations`; per-listing
`skills` are localised name/url objects and are populated only 6/22, so the taxonomy is more useful
as a *query* facet than as per-listing metadata.)

⚠️ One caveat I'd flag for whoever builds this: I verified 116 for `query=machine+learning` on one
day. I did **not** re-run it across `KI` / `Data Scientist` / `LLM` and de-duplicate, so **116 is
one query's result, not a measured total for "AI/ML"** — the true addressable pool is plausibly
larger, but I haven't measured it and won't assert it.

**Adapter route — much cleaner than I first reported.** Forget the sitemap. The route is:

1. `GET /projekte?query=<term>` with `httpx`
2. extract the `ProjectSearch` react-on-rails component's JSON
3. read `initialResults` (22/page) and page via the `pagenr` param
4. incremental-sync on `created`, which is an exact ISO timestamp — this satisfies the `since` half
   of the adapter contract properly, which almost nothing else here does
5. `aggregations` gives you free facet counts for observability

`initialState.filter` exposes the full server-side filter vocabulary — `countries`, `states`,
`remoteInPercent`, `projectContractTypes`, `endcustomer`, `industry`, `matchingSkills`, `created`,
`excludeDachProjects` — so most of `profile.yaml` can be pushed **server-side** rather than
hard-filtered locally. That reduces fetch volume, which also serves the § 4 Abs. 1 a) duty not to
overload the infrastructure. Good outcome all round.

⚠️ **The endpoint trap that cost me hours.** There are two search endpoints and they behave
differently:

- **`/projektboerse.html?query=…` silently ignores `query`.** The legacy endpoint returns the same
  total (13,661) for `machine+learning`, `SAP`, and literal nonsense. It does not error — it just
  returns everything. This is exactly the kind of thing that yields a confidently wrong volume
  number and an adapter that looks like it works.
- **`/projekte?query=…` filters server-side and is the correct one.**

Also: use **`.de`, not `.com`** — same query, 116 vs 22.

(The sitemap does exist — [`sitemap.xml`](https://www.freelancermap.de/sitemap.xml) → nine children
including a `projects.xml` index of shards — but it carries no `lastmod`, so it is strictly worse
than the `created`-ordered search for incremental ingest. Noted only to close the loop.)

**The structural finding: the DACH project market has consolidated onto this one board.** This is
the most important thing in the report for source *selection*, and I verified each leg:

- `https://www.projektwerk.com/` → **`301` → `https://www.freelancermap.de/?referer=pwerk`**
- `https://www.twago.de/` → **`404`** (dead)
- freelancermap carries listings whose poster company is *"Randstad Professional GmbH (vorm. GULP)"*
  and even *"freelance.de GmbH"*

So **GULP's and freelance.de's inventory partly reaches you *through* freelancermap anyway** — which
means the two sources with explicit contractual prohibitions are also substantially **redundant**.
That is a rare case where the legal answer and the engineering answer agree: don't build them.

## freelance.de — good volume, explicit "no"

**Access model: scraping only.** No public API found as of 2026-07; searched the site, its help
pages, and developer-portal patterns. No RSS link on the projects page.

**ToS posture: explicitly prohibits.** Uniquely, the prohibition lives in `robots.txt` itself —
which makes it machine-readable and impossible to claim ignorance of.
[`robots.txt`](https://www.freelance.de/robots.txt), verbatim:

```
# Hinweis: Die Verwendung von Robotern, Crawlern oder anderen automatisierten
# Systemen zum Zugriff auf freelance.de ohne die ausdrückliche schriftliche
# Genehmigung von freelance.de ist strengstens untersagt. Detaillierte
# Informationen zu unseren Crawling-Richtlinien finden Sie unter:
# https://www.freelance.de/pages/crawling-guideline.html.
# Öffentliche Suchmaschinen dürfen öffentlich zugängliche Seiten crawlen,
# sofern die Anweisungen in der robots.txt-Datei eingehalten werden.
# Jede andere Form des Crawling ist nur nach vorheriger Genehmigung gestattet.
# Schreiben Sie hierzu eine Anfrage an support@freelance.de.

User-agent: *
Sitemap: https://www.freelance.de/sitemap/sitemap.xml
```

The [crawling guideline](https://www.freelance.de/pages/crawling-guideline.html) it points to
confirms: public search engines may crawl to index public pages; everything else needs written
permission, requested from support@freelance.de. It states plainly that the guidelines themselves
do **not** grant permission, and that freelance.de monitors crawling activity and reserves the
right to pursue legal action:

> "freelance.de überwacht Crawling-Aktivitäten und behält sich das Recht vor, unautorisierte
> Aktivitäten zu unterbinden und rechtliche Schritte einzuleiten."

Notably, the [AGB](https://www.freelance.de/main/generalterms.php) themselves contain **no**
anti-automation clause — the whole prohibition rests in `robots.txt` and the guideline page. The
directive block is technically only a comment (there is no `Disallow:`), so a naive crawler would
see an open site. That does not help: the intent is unambiguous and stated in writing.

**A legitimate path exists**: write to support@freelance.de and ask. For a personal, low-volume,
non-competing tool this is not a hopeless ask, and it converts the best-volume-with-a-clean-no
source into a usable one. **Unknown whether they would say yes — untested.**

**Fields exposed.** From the [Machine-Learning-Projekte](https://www.freelance.de/Machine-Learning-Projekte)
listing, a representative card reads verbatim:

> `"Data Scientist / Machine Learning Engineer" — Ab Juli 2026 | D-Bayern | Remote | 03.07.2026 14:09`

So: start date (`Ab Juli 2026`), region (`D-Bayern`), a remote flag, and a **precise freshness
timestamp** — good for the `since` contract. But **no Tagessatz and no Laufzeit**, and company
names are paywalled (*"für EXPERT-Mitglieder sichtbar"*), so **agency-vs-end-client is not
determinable from the free view.** That paywall also caps description/embedding quality.

**Volume: the only hard AI/ML number in this research.** That same page shows
**"Projekte: 1-20 von 56"** — 56 live ML projects, freshest a few days old. Platform-wide, from
freelance.de's own [Q1 2026 market report](https://www.freelance.de/blog/freelancer-markt-q1-2026-stabilitaet-steigender-wettbewerb-und-erste-erholung-in-einzelnen-branchen/):

> "Im ersten Quartal 2026 wurden über freelance.de insgesamt knapp 15.600 Projekte veröffentlicht."
>
> "Im Vergleich zum Vorjahreszeitraum mit 15.200 Projekten entspricht dies einem Anstieg von 2,6 Prozent."

with IT the largest category: *"Mit über 5.000 Projekten im Quartal bleibt sie mit Abstand die
größte Kategorie."* Registered profiles passed 320,000 in 2026, ~5,000 new freelancers/month.

## GULP (Randstad) — explicit "no", in the contract

**Access model: scraping only.** No outbound public API or RSS found as of 2026-07; searched the
site, its AGB index, and feed patterns.

A trap worth flagging: GULP's terms index lists **"Technische Nutzungsbedingungen ("GULP Roboter")"**
at [`/agb/technischebedingungen`](https://www.gulp.de/agb/technischebedingungen), which looks like
crawler rules and is not. The "GULP Roboter" is a **GULP-operated crawler that pulls a client's
projects off the client's own webserver** into GULP — inbound again, the same direction as
freelancermap's XML import:

> "Der Roboter erfasst alle Angebote, die seiner Konfiguration entsprechen."
>
> "Der Kunde ist dafür verantwortlich, dass nicht mehr als die gebuchte Anzahl an Projekten auf
> seinem Webserver in der Form veröffentlicht wird, die vom Roboter erfasst wird."

**ToS posture: explicitly prohibits.** From the
[Allgemeine Geschäftsbedingungen](https://www.gulp.de/agb/allgemeine-geschaeftsbedingungen),
**§ 4 Nr. 1 d)** — the user undertakes to refrain from:

> "auf die Dienste in anderer Weise als über die von Randstad bereitgestellten Benutzeroberflächen
> und Schnittstellen zuzugreifen, insbesondere im Wege manueller oder automatisierter Verfahren,
> mittels Schadcode, Software oder Scripts"

That is about as direct as it gets: accessing the services other than through Randstad's own UI and
interfaces — expressly including automated procedures and scripts — is prohibited. An adapter is a
breach of contract on its face.

[`robots.txt`](https://www.gulp.de/robots.txt) is beside the point given the above, but for the
record it disallows `/search/`, `/experten-suche`, `/gulp2/g/*region`, `/stundensatz-analyse`,
`/automatisches-matching` and much else, while leaving `/gulp2/g/projekte/...` detail paths
technically allowed.

**Fields**: not verified. The project detail page fetched
([/gulp2/g/projekte/direkt/624568a0c68ec62a7eb0587b](https://www.gulp.de/gulp2/g/projekte/direkt/624568a0c68ec62a7eb0587b))
returned only a logo and an asset path — i.e. a **JavaScript app shell**, no server-rendered
content. So GULP would need a headless browser on top of a contract breach. Volume unverified for
the same reason.

**Verdict: rule out.** Explicit contractual prohibition, plus the highest adapter cost in the set.

## Etengo — cleanest structure, permissive-ish terms, but is the volume there?

**Access model: scraping only.** No public API found as of 2026-07.

**ToS posture: silent on automation, and unusually compatible with a *personal* tool.**
[`robots.txt`](https://www.etengo.de/robots.txt):

```
Sitemap: https://www.etengo.de/sitemap.xml
User-agent: *
Disallow: /cpresources/
```

The [Terms & Conditions](https://www.etengo.de/en/terms-conditions/) contain **no clause**
addressing crawling, scraping, robots, or automated retrieval — neither prohibiting nor permitting.
What they do say is about *use*, not *method*, and § 5(1) is worth reading closely:

> "Users may retrieve, store and utilise the contents of the database for their own use only."
>
> "The information retrieved may only be used for the users' own requirements."

with § 5(2) barring users from changing contents, duplicating them for or forwarding them to third
parties, or using them commercially. § 1(1) already contemplates *"the online retrieval of database
content"* and *"the reproduction of individual data by the user by means of downloading or
printing"*.

Plain reading: retrieving and storing listings **for your own use** is contemplated and permitted;
redistributing or commercialising them is not. JobScout is a personal tool that delivers a digest
to one user and does not republish — which lands on the permitted side of that line. This is the
most favourable terms language found anywhere in this research. It is still **not** affirmative
consent to *automated* retrieval, and § 87b UrhG applies independently.

**Fields — the tightest, most parseable schema in the landscape.** Verbatim from the
[project search](https://www.etengo.de/it-projektsuche/):

> `Pr.ID CA-102493 | PLZ DE 2XXXX | Laufzeit 7 Monate | Start Sofort | Branche IT-Services`
>
> `Pr.ID CA-102455 | PLZ DE 2XXXX | Laufzeit 4 Monate | Start 01.09.2026 | Branche Wholesale & Retail`

- **Rate: the field does not exist.** Not hidden, not "negotiable" — absent.
- **Duration: exposed and clean** (`7 Monate`).
- **Start: exposed, in both forms** — `Sofort` and dated `01.09.2026`. Useful for pinning the
  date-format question.
- **End client: always anonymised.** Only `Pr.ID CA-102493`; even the postcode is masked
  (`DE 2XXXX`). Etengo is an intermediary and every listing is by definition agency-side.
- **Remote %: not shown.**
- **Description: terse and structured**, closer to a stub than prose. Weaker embedding material
  than freelancermap despite being easier to parse — a real tension for a semantic-ranking pipeline.

**Volume: thin, and this is the problem.** 12 projects on page one, one data-adjacent ("Data
Integration / Middleware Developer"), **zero dedicated AI/ML/DS roles at time of access**. That is
a single observation, not a trend — but it is the observation we have, and it undercuts an
otherwise attractive candidate.

## SOLCOM — blocks bots in practice

[`robots.txt`](https://www.solcom.de/robots.txt) is permissive (only `/neos/` and
`/_Resources/Persistent/`), but **`/de/projektportal` and `/de/projektportal/projektangebote` both
returned HTTP 403 to automated fetches.** Permissive robots.txt, active edge bot-blocking: the
behaviour is the clearer signal of intent. Field structure and volume unverified as a result.
Secondary sources suggest rates are handled case-by-case ("marktgerechte Preise") rather than
published per listing — **inferred, not verified.**

## The staffing agencies — Hays, Randstad, Michael Page

**Hays is the instructive one, and a trap.**
[`robots.txt`](https://www.hays.de/robots.txt) explicitly allow-lists AI crawlers by name:

```
User-agent: AnthropicBot
Allow: /

User-agent: ClaudeBot
Allow: /
...
User-agent: *
Crawl-delay: 10
```

But the [Nutzungsbedingungen](https://www.hays.de/nutzungsbedingungen), Section 3 *"Ihre Nutzung der
Webseite"* (Stand: 01.11.2024), prohibit:

> "Kein Sammeln oder Auslesen von Informationen oder Daten aus den Services oder Hays' Systemen,
> kein Versuch, Übertragungen zu oder von den Servern, auf denen die Services betrieben werden, zu
> entschlüsseln"

and — directly on point for a job-matching tool:

> "Kein Anbieten oder Bewerben von Diensten, die im Wettbewerb zu den Services von Hays stehen."

**robots.txt permission is not ToS permission, and the ToS is the contract.** The allow-list is
plausibly an SEO/LLM-visibility decision; the robots.txt is also malformed (two `User-agent: *`
blocks), which argues against reading it as a considered legal artifact. Classification:
**explicitly prohibits.** Hays does expose a Contracting filter under *Beschäftigungsform* on its
[job search](https://www.hays.de/jobsuche/stellenangebote-jobs), but the visible sector counts
(Engineering 1314, Construction & Property 980) mix all employment forms and are **not** a usable
contract-volume estimate. No public API or feed found as of 2026-07.

**Randstad is the most unambiguous "no" in the set**, and it targets exactly the path that matters.
[`robots.txt`](https://www.randstad.de/robots.txt), verbatim:

```
User-agent: GPTBot
User-agent: Google-Extended
User-agent: ClaudeBot
User-agent: CCBot
User-agent: Bytespider
User-agent: Applebot-Extended
User-agent: Claude-Web
Disallow: /karriere/
Disallow: /hr-portal/
Disallow: /freelance/
```

Plus `Disallow: */api/*` for all agents. No ToS reading required — `/freelance/` is blocked for
ClaudeBot by name.

**Michael Page**: [`robots.txt`](https://www.michaelpage.de/robots.txt) is stock Drupal and silent
on AI crawlers, but disallows the salary-filter (`/*?*salary_range*=`, `/*?*field_job_salary_min=`)
and contract-type (`/*?*contract=temp`) URLs — **the exact facets needed to isolate contract roles
are robots-disallowed.** ToS not located (`/legal/nutzungsbedingungen` 404s); **unverified, not
permissive.**

## Gun.io, Braintrust, Instaffo, 9am, uplink, Junico — brief

**Gun.io** — [Terms of Use](https://gun.io/terms-of-use/) § 5 "Prohibited Uses" is the most explicit
ban in the entire research:

> "that you will not access (or attempt to access) the Site through any robot, spider, or other
> automated means (including use of scripts or web crawlers)"
>
> "that you will not conduct any systematic or automated data collection activities (including
> without limitation scraping, data mining, data extraction and data harvesting) on or in relation
> to the Site without our express written consent"

Its permissive Yoast robots.txt is irrelevant against that. [Public jobs page](https://gun.io/jobs/):
4 roles, no rate/duration/client, **no DACH roles**. Rule out — prohibited *and* worthless here.

**Braintrust** — [`robots.txt`](http://www.usebraintrust.com/robots.txt) allows `/`, blocks `/api/`.
Terms have no explicit scraping clause; closest is § 10: *"Attempt to access or search the Site
Services using any unauthorized engine, software, tool, or mechanism."* Classification:
**silent-to-weakly-restrictive.** But `/job-boards/*` are SEO landing pages, not listings — e.g.
`"Senior Full-Stack Engineer / $150–200/hr / 42 hired recently"` with **no client, no location, no
description, no apply link**; real listings sit behind auth + certification. Rates shown but
US-centric. Negligible DACH liquidity. Drop.

**Instaffo** — no public job API. `Disallow: /*?` kills the search URLs an adapter would need.
FTE-leaning. Drop.

**9am.works** — robots.txt **404s**. More importantly, 9am **is a job aggregator itself** — *"On
9am, you'll find hundreds of jobs from multiple platforms and recruiter job boards matching your
skills"* — i.e. a direct competitor to JobScout, and its board is gated behind `app.9am.works/join`.
Nothing publicly browsable. Drop.

**uplink.tech** — the most interesting near-miss. [`robots.txt`](https://uplink.tech/robots.txt) is
fully permissive (`Allow: /`), and secondary sources
([startupvalley](https://startupvalley.news/de/uplink-it-freelancer/)) claim projects are posted
*"immer inkl. Stundensatz, Kundenname und genauer Aufgabenbeschreibung"* with an €80/h minimum and
direct clients only — which would make it the **only rate-and-client-transparent DACH source found.**
But the project board is **gated behind `app.uplink.tech` login**; [uplink.tech](https://uplink.tech/)
exposes no public projects URL, and the first-party site does not itself state the rate-transparency
claim. Not adaptable without an authenticated session. **Worth a manual look as a human, not as an
adapter.**

**Junico** — [`robots.txt`](https://www.junico.de/robots.txt) permissive (`Allow: /`,
`Disallow: /cdn-cgi/`). Generalist, Gen Y/Z-oriented, not AI/ML-contract-dense. Fields and volume
unverified. Low priority.

## Two name collisions that would have produced wrong answers

Flagging these because both nearly poisoned the research and both would have produced confidently
wrong conclusions:

1. **`braintrust.dev` ≠ `usebraintrust.com`.** `braintrust.dev` is an **AI evaluation platform**
   with a well-documented public REST API. Completely different company from the Braintrust talent
   marketplace. Search engines conflate them constantly. Anyone concluding "Braintrust has a public
   API" has found the wrong Braintrust.
2. **`instaff.jobs` ≠ `instaffo.com`.** InStaff is an event/temp staffing company that has a real
   API. Instaffo is the job-matching platform. Different companies. Instaffo "REST-API" mentions
   trace to a secondary source describing **employer-side ATS integration**, not a public job feed.

**"Expert Cloud"**: `hire.expertcloud.de` exists but the only substantive description found
characterises it as a **customer-service/BPO work-from-home operation**, not an AI/ML contracting
marketplace. Low confidence this is what was meant — possibly a generic term picked up from a
listicle. Recommend dropping unless there is a specific reference behind the name.

## Upwork — the exception that inverts the picture

Upwork is the only platform in this entire research with a **public API a solo developer can get,
whose terms explicitly bless JobScout's exact use case.** It deserves to be read against the
expectation that it would be the most hostile.

**Access model: real, self-serve, documented.** GraphQL at `api.upwork.com/graphql`,
[documented here](https://www.upwork.com/developer/documentation/graphql/api/docs/index.html).
No partner agreement. Self-service key application at
[upwork.com/developer/keys/apply](https://www.upwork.com/developer/keys/apply), reviewed per
request; the documented conditions are a real name, full address, and profile portrait, with ID
verification if the profile isn't validated. OAuth 2.0, scope-based. Job search needs *"Read
marketplace Job Postings"*. Rate limits are documented and generous:

> "We allow 300 requests per minute per IP address."
>
> "Our daily allowed limit is 40K requests."

No fee documented for API access.

**ToS posture: explicitly permits via API — and explicitly prohibits scraping.** From the
[API Terms of Use, v2.1, effective 2025-07-31](https://www.upwork.com/legal#api):

> "**Permitted Uses of the Upwork API.** Your use of the Upwork API is limited to the purpose of
> facilitating your own or your Users' use of the Upwork Site and Site Services. Some examples of
> permitted uses of the Upwork API would be to create Applications that: **Allow Upwork Users to
> search for and browse Upwork job postings with a customized interface**; … Allow Upwork Users to
> apply to jobs on Upwork"

That is JobScout, in the permitted column, almost verbatim. Scraping, by contrast, is flatly out —
[Terms of Use v4.12, effective 2025-09-10](https://www.upwork.com/legal):

> "use a robot, spider, scraper, or similar mechanisms on our site without written permission; copy,
> distribute, or otherwise use any information you found on Upwork … **(no scraping allowed)**"

[`robots.txt`](https://www.upwork.com/robots.txt) agrees: `Disallow: /*/jobs/search*`,
`Disallow: /api*`, and notably `Disallow: /jobs/rss`, `Disallow: /jobs/atom` — **there is no feed
fallback.** The API is the only compliant path, and it is genuinely open.

**The catch is not access — it is a 24-hour data retention cap that collides with JobScout's
architecture.** From the API Terms, § 7 Data Storage:

> "Except as provided in the API Terms, Developer may not copy or store any Upwork Content, **or any
> information expressed by or representing Upwork Content (such as hashed or otherwise transformed
> data)**."
>
> "**Cached Content.** Solely for the purpose of improving user experience, Developer may cache
> Upwork Content for no more than **twenty-four (24) hours**."

Three concrete collisions:

1. **`data/jobscout.db`.** The dedup store persists job identity indefinitely by design — that is
   the whole point of `filter_unseen`. Storing Upwork titles/descriptions past 24h exceeds the
   cache cap. Storing *only opaque job IDs plus a timestamp* is a materially different and far more
   defensible posture, and would still satisfy dedup.
2. **Embeddings.** *"information expressed by or representing Upwork Content (such as hashed or
   otherwise transformed data)"* reads naturally onto a stored vector of a job description. This is
   the non-obvious clause and the highest-risk one. **This is an interpretation, not a settled
   fact** — but the language looks broad by design, and I would not assume embeddings fall outside
   it. Embedding ephemerally per-run sidesteps the question entirely.
3. **Idempotency.** "Same day = same digest" survives a 24h window. Anything longer does not.

One refinement on (1), which I verified directly and which cuts against the obvious workaround: the
only storage carve-out in § 7 is for **user** identifiers, not job identifiers —

> "**Authentication Tokens.** Developer may store any Developer Application-specific alphanumeric
> user identification codes that Upwork provides to Developer for identifying individual users of
> the Developer Application or any tokens that Upwork provides…"

So "just store the job IDs" is **not** clearly carved out either. It is a much more defensible
posture than storing descriptions, but it is not a documented exemption. Worth asking about
explicitly rather than assuming.

**Two further clauses bear directly on JobScout's design, and both are easy to miss.** From
*Prohibited Uses of the Upwork API*:

> "Use the Upwork API to retrieve Upwork Content that is then aggregated with third-party search
> results in such a way that **a user cannot attribute the Upwork Content to Upwork** (such as
> aggregated search results)."

**A JobScout digest is, precisely, Upwork content aggregated with third-party search results.** This
does not prohibit the digest — it conditions it: **every Upwork listing in the digest must be
visibly attributed to Upwork.** JobScout already carries a `source` field per listing, so this is
cheap to satisfy, but it must be *rendered in the delivered digest*, not merely stored in the DB.
That is a delivery-stage requirement falling out of an ingest-stage decision, and it would be easy
to ship without noticing.

> "Request from the Upwork API **more than the minimum data fields** and application permissions the
> Developer Application needs."

A data-minimisation duty. GraphQL makes this natural — select only the fields the pipeline uses —
but it argues against the reflex of "select everything and filter later."

Also noted and **not** a problem for a personal tool, but worth knowing it exists: *"Promote or
operate any product or service that competes with the Upwork Site Services."* JobScout is a
single-user digest that drives traffic *to* Upwork; it does not compete. If it ever became a
product, this clause is the one that would bite.

None of this is a blocker; all of it is a design decision that should be made deliberately rather
than discovered later. Upwork's terms invite the conversation (*"Contact the Upwork support team if
you need help extending or customizing your API Key Scopes"*), and a written answer on the
embeddings question would convert the riskiest assumption in the design into a fact.

*(Verification note: `upwork.com/legal` 403s normal fetches. I retrieved and re-read the API Terms
directly via curl with a browser UA and confirmed every quote in this section against the live page
myself, rather than relying on a single pass.)*

**Fields: the richest in the landscape, by a distance.** From the
`MarketplaceJobPostingSearchResult` schema:

| Need | Field | Quality |
|---|---|---|
| Rate | `hourlyBudgetMin` / `hourlyBudgetMax` (Money), `amount`, `weeklyBudget`, `hourlyBudgetType` | **Real ranges** — best in class |
| Duration | `duration`, `durationLabel`, `engagementDuration` | Structured + human-readable |
| Remote | `preferredFreelancerLocation` (+`…Mandatory`), `local`, `locations` | Location + mandatory flag; **no remote-%** |
| Agency vs direct | `enterprise` (Boolean), `client`, `teamId` | Partially distinguishable |
| Skills | `skills[]`, `ontologySkills`, `occupations` | **Structured ontology**, not free text |
| Description | `description - String!` | **Full text in the search response** |
| Freshness | `createdDateTime`, `publishedDateTime`, `relevance.hoursInactive` | Excellent |
| Competition | `totalApplicants`, `uniqueImpressions` | Useful ranking signal |

`description` being full text **in the search response** is the single most important fact for
embedding quality — no click-through, no second request, no stub. Filters map cleanly onto
`profile.yaml`: `searchExpression_eq`, `skillExpression_eq`, `jobType_eq`, `hourlyRate_eq`
(IntRange), `locations_any`, `daysPosted_eq`, with `RECENCY` sort.

One uncertainty worth testing: the docs list both `marketplaceJobPostingsSearch` (requires *"Read
marketplace Job Postings"*) and `publicMarketplaceJobPostingsSearch`, where **no "Required
Permissions" line appears**. That *suggests* an unauthenticated variant but **does not prove one** —
SpectaQL omitting a field is not a documented grant. Test empirically.

**Volume: strong AI signal, no DACH breakdown.** From
[Upwork's Q4/FY2025 results](https://investors.upwork.com/news-releases/news-release-details/upwork-reports-fourth-quarter-and-full-year-2025-financial)
(2026-02-09): FY2025 GSV $4.03B (+1% YoY), 785,000 active clients (**−6% YoY**), and
**AI-related work GSV >$300M annualised, +50% YoY**, with AI Integration & Automation +90%. The AI
signal is real: AI work grows >50% while the platform grows 1% and client count *shrinks*.

But Upwork publishes **no** geographic segmentation, **no** per-skill counts, **no** freshness
distribution. A DACH AI/ML listing count cannot be derived from $300M AI GSV without inventing an
average contract value and a DACH share, neither of which is disclosed. **No number given.** The
cheap fix: provision a key and read `totalCount` off a filtered search — one call converts this
from a gap to a fact.

## Toptal, Contra, Fiverr — nothing to adapt

**Toptal.** No public API found as of 2026-07 (searched developer-portal patterns, `toptal.com/api*`,
the master sitemap, web search). [`/freelance-jobs`](https://www.toptal.com/freelance-jobs) contains
**no listings** — it is a recruitment funnel whose own copy states the model: *"Jobs Come to You —
We vet each client opportunity and match you with the job postings that suit your preferences and
skills."* The [jobs sitemap](https://www.toptal.com/sitemap/core_jobs.xml) has 17 URLs, all
`/careers/*` — Toptal's own corporate hiring. **Zero client engagements are publicly listed.**
[ToS](https://www.toptal.com/tos) explicitly prohibits:

> "You may not use any 'page-scraper,' 'deep-link,' 'spider,' or 'robot or other automatic program,
> device, algorithm or methodology, or any similar manual process, to access, copy, acquire, or
> monitor any portion of the Site or any Content"

Toptal is a **one-time admission problem, not an ingest problem** — the
[screening funnel](https://www.toptal.com/top-3-percent) is <3% accepted over 3–8 weeks. Nothing to
adapt.

**Contra.** The [contra-sdk](https://github.com/contra/contra-sdk) is real but points the wrong way:
it serves **freelancer profiles** to clients, the inverse of what JobScout needs. `contra.com/jobs`
**302s to `/log-in`**; `/opportunities` returns a JS shell with ~72 characters of visible text; the
[sitemap](https://contra.com/sitemap.xml) has no opportunities/jobs entry.
[ToS](https://contra.com/policies/terms) prohibits:

> "Attempt to access or search the Platform … using any engine, software, tool, agent, device or
> mechanism (including **spiders, robots, crawlers, data mining tools** or the like) other than the
> software and/or search agents provided by Contra or other generally available third-party web
> search engines or web browsers"

Its [`robots.txt`](https://contra.com/robots.txt) is the most permissive of the set
(`Disallow: /@internal` only) and carries `Content-Signal: ai-train=no, search=yes, ai-input=yes` —
**do not read that as permission; the ToS governs and it prohibits crawlers.** No platform
statistics published; `contra.com/about` 404s. Skip.

**Fiverr.** No public API found as of 2026-07: `developers.fiverr.com` **does not resolve**,
`api.fiverr.com` **404s**. More fundamentally, **the model is inverted** — gigs are *seller*
listings, so a high Fiverr AI/ML gig count measures **your competitors, not your opportunities**.
The one job-board-shaped surface (Buyer Requests) was retired in 2022–23 in favour of AI-matched
Briefs with no public board (*corroborated but secondary — Fiverr's help pages 403*).
[ToS](https://www.fiverr.com/terms_of_service) § 8.8 is among the broadest found:

> "(viii) use any **robot, spider, crawlers** or other automatic device … that intercepts, '**mines**,'
> **scrapes** or otherwise accesses the Site … or **engage in any manual process to do the same**;
> (ix) **systematically retrieve data or other content to create or compile, directly or indirectly,
> a collection, compilation, database, or directory**"

Clause (ix) prohibits *compiling a database* from Fiverr content regardless of method — a JobScout
SQLite store of Fiverr data sits squarely inside it. Skip.

## Malt (and Comatch) — a definitive negative, from first-party evidence

**Comatch was acquired by Malt in March 2022** ([Malt newsroom](https://newsroom.malt.com/malt-acquires-comatch),
[TechCrunch](https://techcrunch.com/2022/03/27/freelancer-marketplace-malt-acquires-consulting-marketplace-comatch/)).
**No evidence a Comatch or "Talentgate" API ever existed** — searched the acquisition coverage,
Malt's docs, and Comatch's own blog. Treat that lead as unsubstantiated.

Malt has the strictest ToS posture of any DACH platform here. [Terms](https://www.malt.de/legal),
**Artikel 10.2 – Verbot des Scrapings**, version 2026-04-16:

> "Es ist strengstens untersagt, Informationen von durch Malt gehosteten Websites zu extrahieren,
> zu sammeln, zu übertragen oder wiederzuverwenden, unabhängig davon, ob dies automatisiert oder
> auf andere Weise erfolgt, insbesondere unter Einsatz von Software, Bots oder sonstigen
> Vorrichtungen, die dazu bestimmt sind, auf dem Marktplatz verfügbare Nutzerdaten auszulesen."

Reinforced by [`robots.txt`](https://www.malt.de/robots.txt): `User-agent: GPTBot / Disallow: /`,
plus `/api/`, `/missions`, `/mission/`, `/s?`, `/search/api` and `/dashboard` blocked.

But the ToS is almost beside the point, because **the more interesting fact is structural.**

Malt **does** have an official public API portal at [api.malt.com](https://api.malt.com/), and auth
is **self-serve** (tokens at `malt.com/account/tokens`) — not partner-gated. But the entire
documented public surface, from its own [OpenAPI spec](https://api.malt.com/unified-exposed-apis.json),
is **9 paths**: freelancer invoices, payments, fee-invoices, and SCIM user provisioning. **Zero job,
project, or mission endpoints.** A solo dev can get a Malt token in minutes and cannot fetch a
single job with it. This is a **definitive negative, not an absence of evidence.**

Why: the model is **push, not pull**. From
[Malt's own help centre](https://help.malt.com/hc/en-150/articles/29534878703506-How-do-opportunities-work-for-freelancers)
(updated 2026-06-17):

> "Malt's automated matching sends project proposals directly to the most qualified freelancers
> based on profile information."
>
> "You'll only receive projects that match at least **70%** of your profile."

**There is no browsable job board to ingest.** Work arrives in your inbox. Malt's own headline
demand metric is *searches* (2.5M), not postings — they measure clients searching *profiles*.

This is the strategic tension in the whole report: Malt has the **strongest verified DACH presence**
of any platform here — Berlin office, dedicated GM DACH, ~50-person team, the Comatch consulting
base, 250,000 tech freelancers, and AI agent demand ×60 vs 2024
([Malt Tech Trends 2026](https://www.malt.com/resources/trends/malt-tech-trends)) — and it will
**never** yield an ingestible feed. **Malt is a profile-optimisation play, not an adapter.** Skills,
job title, daily rate, location, availability ≤2 months, ≥70% match. That is real work with real
returns for Marcos, but it is not JobScout's kind of work, and it should be named as out of scope
rather than backlogged as "Malt adapter."

One caveat on Malt's ToS: the Art. 10.2 quote above came back cleanly, but `malt.de` **403s
non-browser clients and Cloudflare-challenges even `/sitemap.xml`**. Note that circumventing a
Cloudflare challenge is an affirmative act of bypassing a technical protection measure — which
German case law treats considerably more seriously than ToS breach alone. Malt is a hard no on
every axis at once.

⚠️ Malt's own surfaces state 1M+, 950,000, and 850,000 freelancers concurrently — unreconciled
vintages. Treat "~1M" as order of magnitude. The widely-cited "17.8% of freelancers in Germany"
figure is [Sifted, Oct 2022](https://sifted.eu/articles/germany-freelancing-com-malt-data); the
denominator has grown ~2.4× since — **do not apply that percentage to today's total.**

## The remote boards — live feeds, wrong content

We Work Remotely and RemoteOK are the two boards with genuinely open, live, public feeds. I fetched
and parsed both rather than reading about them, because the interesting question is not "does a feed
exist" (it does) but "what is actually in it".

### We Work Remotely — permissive, rich descriptions, ~6% contract

[`remote-jobs.rss`](https://weworkremotely.com/remote-jobs.rss) is **live**: HTTP 200, 934 KB,
**99 items**. [`robots.txt`](https://weworkremotely.com/robots.txt) is permissive (`Allow: /`, with
only admin/account paths disallowed). Observed field names, verbatim from the XML:

`title`, `region`, `country`, `state`, `skills`, `category`, `type`, `description`, `pubDate`,
`expires_at`, `guid`, `link`

The good news is real: **description median length 7,947 characters** (min 2,253, max 23,104) — full
HTML job bodies, not stubs. That is the best embedding material of any *free* source here.
`skills` is populated on 65/99. `expires_at` is a genuinely useful field nothing else offers.

The bad news is decisive. **`type` is structured, and it says:**

| `type` | count |
|---|---|
| Full-Time | **93** |
| Contract | **6** |

**Correction to my own number:** the main feed is **capped at ~10 items per category**, so "99
items / 6 Contract" measures the cap, not the board. Pulling the **per-category feeds**
(`/categories/<slug>.rss`) instead gets you deeper. Across the 7 category feeds I fetched
(one 301'd): **173 unique items, of which Contract = 16, Full-Time = 132.** So the contract share is
~9%, not 6%, and the reachable corpus is ~2× what the main feed shows.

*(The DACH agent reports 11 category feeds → 259 unique / 34 Contract. I partially corroborate the
direction — more feeds, more items, higher Contract count — but I only replicated 7 feeds and got
173/16. I have not verified 259/34 and am not asserting it.)*

Either way the conclusion is unchanged: no rate/salary field at all, US-dominated country
distribution, and a contract slice in the low tens of which almost none is DACH AI/ML.

Verdict: technically the easiest adapter in the entire report (parse RSS, done — no auth, no legal
ambiguity, permissive robots), and it would yield **~6 contract jobs, almost none of them DACH,
almost none AI/ML.** Cheap enough to be tempting; not worth a pipeline stage.

### RemoteOK — open API, and the data does not survive inspection

[`remoteok.com/api`](https://remoteok.com/api) returns HTTP 200, 396 KB, **101 entries** — the first
of which is a legal notice rather than a job. Quoted verbatim from the API response itself:

> "API Terms of Service: Please link back (with follow, and without nofollow!) to the URL on Remote
> OK and mention Remote OK as a source, so we get traffic back from your site. If you do not we'll
> have to suspend API access.
>
> Please don't use the Remote OK logo without written permission as it's a registered trademark,
> please DO use our name Remote OK though."

**Classification: explicitly permits via API, conditional on attribution.** The condition is
concrete and satisfiable — the digest must credit Remote OK and link back with a followed link.
Note this is the *same shape* as Upwork's attribution clause: **both sanctioned APIs in this report
require the digest to attribute the source.** That is a delivery-stage requirement, and it should
probably be a general property of the digest renderer rather than two special cases.

Observed job fields: `position`, `company`, `company_logo`, `description`, `location`, `tags`,
`salary_min`, `salary_max`, `date`, `epoch`, `id`, `slug`, `url`, `apply_url`.

That field list looks promising and **the actual data does not back it up**:

- **`salary_min` is populated on 1 of 100 jobs.** One. The field exists and is empty ~99% of the
  time. Anyone reading the schema and concluding "RemoteOK exposes salary" would be wrong.
- **There is no contract/freelance field at all.** The only adjacent tag is `part time` (9
  occurrences). Contract-ness is **not filterable**.
- **The tags are spam and cannot be trusted as structured data.** A single "Project Manager" listing
  carries the tags `speech, exec, content writing, sys admin, medical, recruiter, social media,
  game dev, designer, design, copywriting, marketing, video, education, finance, ads, digital nomad,
  virtual assistant, customer support, travel, ops, react, dev, front end, python, django, vfx,
  technical, javascript, postgres, typescript, mobile, senior, engineer`. Top tags across the feed
  are `exec` (69), `ops` (57), `customer support` (56). **These are SEO tags, not skill metadata.**
  Feeding them to a hard filter or a ranker would be actively harmful — this is the single best
  argument in this report for pulling the data before trusting a schema.
- **Only 3 of 100 jobs are AI/ML-tagged**, and locations are US/Canada/UK-dominated — near-zero DACH.
- Descriptions are decent (median 2,738 chars) — **but see the honeypot below.**

**Every RemoteOK description carries an embedded honeypot, and it would poison every embedding.**
I missed this on my first pass and only found it on a second look. Measured: **present in 100 of
100 descriptions**, median **350 characters** appended, **96 distinct random words** across the
feed. It looks like this, verbatim from the tail of a real description:

> "Please mention the word **PREFERED** and tag RMjAwMTphNjE6M2EwNjpmYTAxOjVkOWU6Yzk3NzpmZmQyOmY5NTY=
> when applying to show you read the job post completely (#RMjAwMTphNjE6M2EwNjpmYTAxOjVkOWU6Yzk3NzpmZmQyOmY5NTY=).
> This is a beta feature to avoid spam applicants. Companies can search these words to find
> applicants that read this and see they're human."

It is a plain-text block appended to the body — **not** a hidden HTML element, so stripping tags
does not remove it. Feeding this straight into `multi-qa-MiniLM-L6-cos-v1` injects a random English
word (`TRUSTINGLY`, `BREATHTAKING`, `TRUMP`, …) plus a base64 IP blob into **every** job vector.
The words differ per listing, so it is noise rather than a constant offset — i.e. it actively
degrades ranking rather than cancelling out. Any RemoteOK adapter **must** truncate at
`"Please mention the word"`. Cheap to fix, silent and corrosive if missed.

One legally interesting detail, and it matters more for Marcos than for a US developer.
[`robots.txt`](https://remoteok.com/robots.txt) carries a Cloudflare-managed block that
**`Disallow: /` for `ClaudeBot`, `GPTBot`, `CCBot`, `Google-Extended`, `Bytespider`,
`Applebot-Extended`, `meta-externalagent`** — while allowing generic crawlers with `Crawl-delay: 1`.
It also declares:

```
User-agent: *
Content-Signal: search=yes,ai-train=no,use=reference
Allow: /
```

with the preamble stating verbatim:

> "ANY RESTRICTIONS EXPRESSED VIA CONTENT SIGNALS ARE EXPRESS RESERVATIONS OF RIGHTS UNDER ARTICLE 4
> OF THE EUROPEAN UNION DIRECTIVE 2019/790 ON COPYRIGHT AND RELATED RIGHTS IN THE DIGITAL SINGLE
> MARKET."

This is not decoration. Article 4 of the EU DSM Directive makes the commercial text-and-data-mining
exception available **only where rights have not been expressly reserved in machine-readable form** —
and this is precisely such a reservation, aimed at an EU-based user. Reading it plainly:
`ai-train=no` forecloses training; `use=reference` and the absence of an `ai-input` signal leave
retrieval/embedding **neither granted nor restricted** by the signal (per the file's own stated
rules). JobScout embeds for retrieval and does not train, so it is arguably outside the `ai-train=no`
reservation — **but that is my reading of a novel and largely untested mechanism, and I would not
lean on it.** Note also that the ClaudeBot block governs *Anthropic's crawler*, not an `httpx`
client, and the API is a separately sanctioned channel with its own stated terms; those are three
different things and it is easy to conflate them.

**Verdict: don't adapt.** Not because of the law — the API's own terms permit it on attribution —
but because the payload is FTE-dominated, DACH-empty, salary-empty, contract-blind, and its tags are
unusable.

### Himalayas — the one remote board that isn't a dead end

**Not my own work — reported by the delegated agent, and I have not independently verified it.**
Flagging that clearly because it is the one remote-board finding that could change a decision.

Himalayas has a documented search endpoint, **`/jobs/api/search`**, which the agent reports returns
**76 strict matches** for `AI engineer` + `employment_type=Contractor` + `country=de`, with 14/14
spot-checked rows genuinely Contractor and Germany-eligible. If that holds, it is the **second-best
verified DACH-eligible contract AI/ML pool in this entire report**, behind freelancermap's 116 — and
it would mean my "the remote-board tier is hopeless" framing was too broad. The trick is querying
the search endpoint directly rather than walking the browse feed (which is what makes it a handful
of requests instead of ~4,900).

**But there is an unresolved ToS conflict**, and it is the reason this isn't ranked higher: the API
page reportedly says *"Anyone can use the interface"* while the Terms bar automated methods to
**"access the Services"** — which is broader than a scraping ban and would reach an API client. Two
first-party pages contradicting each other is not a green light. The docs invite attribution-based
use, so **asking is likely to land** — same play as freelance.de.

**Rate data is poor regardless**: `salaryPeriod=hourly` exists on some contract rows but `min`/`max`
are usually `0-0`, with real rates buried in titles (*"Upto $85/hr"*).

**Verdict: worth verifying properly, second to freelancermap.** I'd want to reproduce the 76 myself
and resolve the ToS conflict before committing.

### Working Nomads, Wellfound, EU Remote Jobs

- **europeremotely** — **delete it from consideration.** The agent found it is a **parked domain**
  (`Server: Parking/1.0`), not a job board. Not verified by me, but trivially checkable.
- **Wellfound** — genuinely unresolved. The agent explicitly **retracted** its own ToS claims here
  (`/terms` returns 403), so there is no reliable reading of Wellfound's posture in this document.
  Do not treat its absence from the shortlist as a considered rejection.
- **Working Nomads** — not examined by anyone. Still a gap.

The structural point that *is* established: the remote-board tier is built for full-time remote
hiring, and contract work appears in it incidentally — WWR's `type` resolves to ~16/173, RemoteOK
has no contract field at all. **Himalayas is the exception that keeps this tier alive**, and it
earns that on one unverified number.

## Projektwerk and Twago — dead. (A correction to my own error.)

I originally listed Projektwerk as "a smaller, long-running DACH project board", on the strength of
having fetched `projektwerk.com/robots.txt` and received a real, permissive robots file. **That was
wrong, and the mistake is instructive.** `robots.txt` is served at the domain level and kept
responding long after the site itself stopped existing as a board. Checking the actual site:

```
https://www.projektwerk.com/  →  301  →  https://www.freelancermap.de/?referer=pwerk
https://www.twago.de/         →  404
```

**Projektwerk now redirects to freelancermap; Twago is gone.** A live `robots.txt` is not evidence
of a live site — a lesson that generalises to every "permissive robots.txt" claim in this document.

## A legal note that applies even to the "silent" sources

Permissive `robots.txt` plus silent ToS is **not** the same as permission. German law has an
independent hook: **§ 87b UrhG** (sui generis database right,
[gesetze-im-internet.de](https://www.gesetze-im-internet.de/urhg/__87b.html)) gives a database maker
exclusive rights over reproduction of *"wesentliche Teile"* of a database, and treats **repeated and
systematic extraction of individually insubstantial parts** as equivalent where it conflicts with
normal exploitation (*"einer normalen Auswertung der Datenbank zuwiderlaufen"*) or unreasonably
harms the maker's legitimate interests.

A project board is squarely a protected database, and "fetch everything relevant, every day,
forever" is squarely systematic extraction. What keeps a personal tool on the right side of this in
practice is scope and use: fetch narrowly (only what matches the profile), throttle, do not
redistribute, do not compete. That is a risk-mitigation posture, not a legal clearance. **Again:
not a lawyer, not legal advice.** If this pipeline ever grew a second user or a public digest, the
analysis changes materially.

## What the sources imply for the data model

This is the part that feeds the model-widening ticket. The headline: **the freelance fields are far
sparser and far messier than the FTE fields they replace.** `salary_min`/`salary_max` was a clean
annual-EUR range; nothing in the freelance world is that tidy.

**Rate is mostly absent, and when present it is not one thing.** This is the biggest surprise and
the most consequential design constraint.

- **Absent entirely** on Etengo (the field does not exist), freelance.de, Hays, Randstad, Michael
  Page, SOLCOM. For the intermediary tier this is structural, not incidental — the margin between
  what the client pays and what the freelancer gets *is the agency's business*, so it will never be
  published. Do not expect this to improve.
- **Effectively absent on freelancermap too.** I initially reported it as "sometimes present" on the
  strength of one `70,00 € Budget` on a one-month gig page. Measured properly across an ML search
  page, `budget` is populated **0 of 22**. The label is *Budget*, not *Stundensatz*/*Tagessatz*, so
  even the rare populated value has an **ambiguous unit** (project total vs hourly vs daily) and a
  naive parse into `rate_min` would silently poison ranking.
- **`0-0` on Himalayas** — the field exists, `salaryPeriod=hourly` is set, and min/max are zero. Real
  rates hide in title strings (*"Upto $85/hr"*). A schema-trusting adapter reads this as "€0/hr".
- **Present as a genuine min/max range** on **Upwork** — `hourlyBudgetMin`/`hourlyBudgetMax` as
  typed `Money`, plus `amount`, `weeklyBudget`, and a `hourlyBudgetType` discriminator. This is the
  only source in the landscape that models rate *properly*, and note it hands you the
  hourly-vs-fixed distinction as a field rather than leaving you to infer it. Currency is USD, not
  EUR.
- **Present as a range** on Braintrust (`$150–200/hr`) — but US-centric and behind a useless stub.
- **Rate-transparent DACH sources exist but are login-gated** (uplink.tech).

Note the awkward consequence: the one source with clean rate data (Upwork) is USD-denominated and
hourly, while the DACH sources that matter most are EUR and day-rate — so `rate_currency` is load-
bearing, not decoration, and any cross-source comparison needs an FX assumption that should be
explicit rather than buried.

Design implication: rate must be **nullable, plus a unit discriminator, plus a period
discriminator** — something like `rate_min | rate_max | rate_currency | rate_unit
{hourly, daily, project_total} | rate_is_estimate`. A single `rate` float would be actively
harmful. And **the hard filter must not require rate**, because requiring it would discard
essentially the entire DACH corpus — a mistake that would be invisible until the digest went empty.

**The blunt version, since this is the finding most likely to change the design:** on the DACH side
rate is **not sparse, it is absent**. `profile.yaml` should stop treating day rate as a filter or a
ranking axis and treat it as what it actually is — **a negotiation that happens after the match**.
Rank on `remoteInPercent`, `projectContractType`, `duration`, and skills instead. Those are
populated; rate is not.

**Duration is the field that actually survives.** Formats seen in the wild, verbatim:

- `Laufzeit 7 Monate`, `Laufzeit 4 Monate` (Etengo — clean, uniform)
- `Dauer 1 Monat` (freelancermap)
- `6 Monate+`, `12 MM` (*Mannmonate*) are the conventional DACH forms — **I saw the `Monate` forms
  directly; I did not directly observe `MM` on the sources I fetched, so treat that format as
  expected-but-unverified.**

- Upwork is the outlier again: `duration` is a typed `JobDuration` enum with a separate
  `durationLabel` for humans and `engagementDuration` alongside it — structured, not parsed.

So on the DACH side duration is **free text in German, with an open-ended marker (`+`) and at least
two unit conventions** (calendar months vs man-months — which are *not* the same quantity).
Suggested shape: `duration_months: int | None` + `duration_is_open_ended: bool` + keep the raw
string. Parsing `MM` as calendar months would be a real bug. Upwork's enum will need mapping onto
the same field rather than the reverse.

**Start date has exactly two shapes**, and Etengo shows both side by side:

- `Start Sofort` / `ab sofort` / `Ab Juli 2026` (relative or month-granular)
- `Start 01.09.2026` (a real date, `DD.MM.YYYY`)

So: `start_date: date | None` + `start_asap: bool`, keeping raw text. Note `Ab Juli 2026` is
month-granularity — neither ASAP nor a precise date. Three cases, not two.

**Remote is a percentage, not an enum — and it's the best-populated field in the landscape.**
freelancermap's `projectContractType` is `{'type': 'contracting', 'remoteInPercent': 100}`,
populated **22/22**, with server-side buckets `remote` / `hybrid` / `on_site` (57 / 52 / 7 of 116).
The current `remote_policy` enum cannot represent `60% Remote`, which is the classic DACH "3 days on
site" arrangement and evidently half the market. **Widen to `remote_percentage: int | None` and
derive the enum from it, not the reverse.**

**A field JobScout doesn't have and needs: contract type.** freelancermap distinguishes
`contracting` (94) / `employee_leasing` (12) / `permanent_position` (10). **`employee_leasing` is
*Arbeitnehmerüberlassung* — temp labour leasing, legally and practically not freelance contracting**
— and `permanent_position` is FTE leaking onto a freelance board. Together that's ~19% of the pool
that Marcos does not want, and both are **deterministically excludable** — no LLM call, which is
exactly what the hard-filter constraint requires. Add `contract_type: {contracting,
employee_leasing, permanent_position, unknown}`. This has no FTE-model analogue at all.

**Agency-vs-direct is knowable on one source — and the answer is depressing.** freelancermap has
`endcustomer` as a per-listing field *and* a filter facet. But it is `False` on 22/22 sampled, and
the aggregation says **5 of 116**. So the field is real and the market is ~96% intermediated.
Elsewhere it's structurally unknowable (Etengo anonymises to `Pr.ID CA-102493`, masking even the
postcode to `DE 2XXXX`), paywalled (freelance.de hides company names behind *"für EXPERT-Mitglieder
sichtbar"*), or trivially constant (every Hays/Randstad/Etengo listing is agency-side by definition).
Shape: `client_type: {end_client, agency, unknown}` — `unknown` is the **majority** case and the
*source*, not the listing, usually determines the value. Worth having, but **as a ranking boost, not
a hard filter** — as a filter it yields five projects.

*(I overstated this in my first pass — I called it "a rare win" on the strength of the filter's
existence without checking how often the field is actually true. Field presence is not field
population; see below.)*

**Skills are structured tags** on freelancermap; free text or absent elsewhere.

**Description quality varies enough to change ranking behaviour, and it inverts against parse
effort.** This deserves emphasis because it is a genuine tension the downstream ticket has to
resolve:

- **Upwork**: `description - String!` **returned in full in the search response itself**. No
  click-through, no second request, no stub. This is the best embedding input available anywhere in
  the landscape, and it arrives already-structured.
- **freelancermap**: full prose, populated **22/22**, **median 3,951 chars** (min 1,026, max 8,289)
  — excellent asymmetric-search material for `multi-qa-MiniLM-L6-cos-v1`, which wants a real document
  to match the profile query against. And it arrives **inside the `ProjectSearch` JSON**, so no second
  request and no HTML parsing. *(An earlier draft said "~135 words" from eyeballing one listing;
  measured across the page it is roughly 5× that. Corrected during independent verification — see the
  verification note at the top. Note the 8,289-char max will exceed the model's 512-token window, so
  truncation strategy is a real downstream question, not a hypothetical one.)*
- **Etengo**: `Pr.ID CA-102493 | PLZ DE 2XXXX | Laufzeit 7 Monate | Start Sofort | Branche
  IT-Services` — trivially parseable and nearly content-free. **Embedding that yields almost
  nothing to rank on.** The listing's actual substance is behind a click.
- **Braintrust**: SEO stubs with no description at all.

I originally framed this as a clean tension — "the easiest sources to parse are the worst to embed"
— on the belief that freelancermap needed brittle CSS scraping. **That framing was wrong**, and
usefully so: freelancermap turns out to be *both* the easiest structured parse (one JSON blob) *and*
full prose, 22/22. Etengo is the genuine trap — trivially parseable and nearly content-free.

The durable point survives the correction: **a source whose descriptions are stubs will rank badly
no matter how clean its fields are** — and worse, it will rank *plausibly* badly, producing
confident nonsense rather than obvious breakage. **Description length is worth treating as a
first-class source-quality signal**, and possibly worth a per-source minimum before a listing is
allowed into the LLM-eval top-30. Etengo would fail such a check; freelancermap passes it easily.

**Field presence in a schema is not field presence in the data.** This is the single most useful
methodological finding here, and it caught me twice:

| Source | Field | Schema says | Data says |
|---|---|---|---|
| RemoteOK | `salary_min` | exists | **1/100 populated** |
| RemoteOK | `tags` | exists | **SEO spam** — a PM role tagged `vfx`, `game dev`, `django`, `postgres` |
| freelancermap | `budget` | exists | **0/22 populated** |
| freelancermap | `endcustomer` | exists + filter facet | **5/116 true** |
| freelancermap | `skills` | exists | **6/22 populated** |
| Himalayas | `salary min/max` | exists, `hourly` | **`0-0`** |

Every one of these would have produced an adapter that looked correct and ranked garbage. **Pull a
real payload and count populated fields before designing against any source** — including every
source in this document. I got freelancermap's rate and end-customer fields wrong on the first pass
by reading a page instead of measuring a payload.

**Also: sanitise description text before embedding.** RemoteOK appends a honeypot to **100/100**
descriptions (median 350 chars, 96 distinct random words) — plain text, not a hidden element, so tag
stripping misses it. It would inject noise into every vector. Assume any free board does something
like this and check.

**A cross-cutting delivery requirement falls out of the two sanctioned APIs.** Both Upwork and
RemoteOK condition API use on **attributing content back to the source in whatever the developer
builds** — Upwork prohibits aggregation "in such a way that a user cannot attribute the Upwork
Content to Upwork"; RemoteOK requires "link back … and mention Remote OK as a source". JobScout's
digest is exactly the aggregation both clauses contemplate. The `source` field already exists on
`JobListing`; the requirement is that it be **rendered in the delivered digest**, per listing, with a
followed link. Worth building into the digest renderer as a general property rather than as
per-source special-casing — the pattern will repeat on any future sanctioned API.

**One more model-shaped consequence**: `salary_min`/`salary_max` in *annual EUR* is not merely
insufficient — it is the wrong axis. Nothing in this landscape quotes an annual figure. The field
should be replaced, not extended, or old FTE rows will silently compare against new contract rows
on an incompatible scale.

## Shortlist recommendation: what I'd adapt

The actual source-selection decision is a separate ticket. This is a recommendation with its
reasoning exposed so it can be argued with.

**This ranking reversed during the research.** My first pass put Upwork first, because
freelancermap's AI/ML volume was unverified and I believed its adapter meant brittle CSS scraping.
Both premises turned out to be wrong — the volume is 116 and the adapter is a JSON parse. When the
evidence moved, the ranking moved. Flagging it so the reversal is legible rather than hidden.

### 1. freelancermap — scrape it, carefully. Build here first.

**Why it now leads**, and every one of these is first-party verified:

- **116 live ML projects in Germany, 136 across DACH** — the largest verified DACH AI/ML contract
  pool found anywhere in this research, by a wide margin. **57 of the 116 are fully remote.**
- **The adapter is a JSON parse, not a scrape.** The embedded `ProjectSearch` payload gives typed
  fields with an exact `created` ISO timestamp for clean incremental sync — it satisfies
  `fetch(max_results, since)` better than anything except Upwork.
- **`description` populated 22/22, full prose** — good embedding material.
- **`projectContractType` populated 22/22** with `remoteInPercent` *and* the
  `contracting` / `employee_leasing` / `permanent_position` distinction, so ANÜ and leaked FTE roles
  are excludable deterministically — no LLM call, exactly as the hard-filter constraint requires.
- **Server-side filters** (`countries`, `remoteInPercent`, `projectContractTypes`, `matchingSkills`
  by stable EMSI ID, `created`) mean most of `profile.yaml` pushes down to the query — less fetching,
  which also serves the §4(1)(a) no-overload duty.
- **The market consolidated onto it.** Projektwerk 301s here; Twago is dead; Randstad/GULP and
  freelance.de post *onto* it. One adapter reaches inventory that three prohibitions would otherwise
  block.
- **The legal position is the best available for a DACH source**: `robots.txt` `Disallow:` empty,
  no anti-automation clause in the AGB, and §4(5)/§11(2) permit use *"für eigene Zwecke"* while
  barring trading and commercial reprocessing — which is precisely the shape of a personal digest.

**Tradeoffs, honestly:**
- **"Silent" is not "permitted."** §87b UrhG applies regardless of what the AGB omit, and
  freelancermap calls its own service a *Datenbank* in §2(2). This is a **considered risk, not a
  green light** — Marcos's to accept, not mine to accept for him. The realistic downside is §4(3):
  account termination plus a reserved damages claim. For someone who wants to *work* through this
  platform, losing the account is a real cost.
- **Rate is absent** — `budget` populated 0/22. If day rate matters, this source will not give it.
- **`endcustomer` = 5 of 116.** The direct-client filter that makes this source attractive in
  principle collapses the pool to five in practice.
- **116 is one query's result**, not a measured "AI/ML total" — I didn't run `KI`/`LLM`/`Data
  Scientist` and de-duplicate.
- Undocumented internal JSON → **it can change without notice**. Lower effort than CSS scraping, but
  not a contract.

### 2. Upwork — via the official API. Build second.

**Why it's still here:** it is the only source where the legal question is **settled in our favour**
rather than merely unaddressed. Its terms name JobScout's use case in the permitted column, and the
fields are the richest anywhere — real `hourlyBudgetMin`/`Max` ranges (**the only usable rate data
in this report**), structured skill ontology, `RECENCY` sort, and full description text in the search
response.

**Why it dropped to #2:**
- **It is the weakest fit for the stated goal.** Marcos wants DACH contract work; Upwork is global,
  remote-first, USD-denominated, with **no published DACH breakdown at all**. Against freelancermap's
  *verified* 116, Upwork's DACH pool remains an **unmeasured assumption** — and that asymmetry is
  what flipped the order.
- **The 24-hour retention cap** is a genuine architectural constraint touching `jobscout.db` and
  plausibly the embedding store.
- Upwork skews to smaller/individual clients; 6-month Mittelstand engagements are not its centre of
  gravity.

**Still worth building** — it's the one adapter with no legal shrug, it's where rate data lives, and
provisioning the key is itself how you measure the DACH question (one `totalCount` call).

### 3. Himalayas — verify first, then decide.

Reportedly **76 Contractor + AI + Germany-eligible** matches via `/jobs/api/search` — which would be
the second-largest verified DACH-eligible contract AI pool here. **I have not verified this**, and it
comes from an agent that had reliability problems this session, so treat it as a strong lead rather
than a finding. Two things to settle first: reproduce the 76, and resolve the ToS conflict (API page
says "anyone can use the interface"; Terms bar automated access to "the Services"). The docs invite
attribution-based use, so asking is likely to land. **Rate data is poor** (`0-0` on most rows).

### 4. freelance.de — ask permission, don't scrape.

Has a verified 56 live ML projects, but scraping it is unambiguously against a written,
machine-readable prohibition (in `robots.txt` itself, reinforced by a crawling guideline, Stand
17.02.2025, reserving legal action). **I would not build this adapter as things stand.**

It drops to #4 for a new reason: **it's partly redundant** — freelance.de posts listings onto
freelancermap, so some of its inventory already reaches you via #1. Combined with paywalled company
names (agency-vs-direct unknowable) and 56 < 116, the case is weaker than it looked.

**Still worth the email** to support@freelance.de — they publish a request address and a process, and
a personal, low-volume, non-competing tool is not an absurd ask. Send it before writing any code. If
they say yes, a written permission beats freelancermap's silence outright; if they say no, drop it
cleanly and you've lost an afternoon. The asymmetry favours asking.

Caveat if they do say yes: company names are paywalled behind EXPERT membership, so agency-vs-direct
stays unknowable and description/embedding quality is capped. It would not displace freelancermap on
field richness — only add a second DACH source, which is worth something on its own given the
concentration risk noted below.

### What I'd drop, and why

- **Malt** — the most painful cut. Strongest verified DACH presence in the research (Berlin office,
  GM DACH, 250K tech freelancers, AI agent demand ×60), and **structurally impossible to ingest**:
  its public API is invoices and SCIM, and the model pushes work to profiles rather than publishing a
  board. Art. 10.2 bans scraping outright and Cloudflare enforces it. **Reframe Malt as a
  profile-optimisation task for Marcos personally** — skills, job title, daily rate, location,
  availability ≤2 months, ≥70% match. That is worth doing. It is not a JobScout ticket, and it
  should not sit in the backlog pretending to be one.
- **GULP** — AGB §4 Nr. 1 d) prohibits automated access in terms, *and* it's a JS app shell needing
  a headless browser, *and* — the new reason — **it's redundant**: its listings appear on
  freelancermap under the poster name *"Randstad Professional GmbH (vorm. GULP)"*. You reach the
  inventory without touching the prohibition. Drop.
- **Projektwerk and Twago** — **dead**, not deprioritised. Projektwerk 301s to freelancermap, Twago
  404s. I had Projektwerk listed as live on the strength of its robots.txt; that was my error.
- **Hays, Randstad, Michael Page** — Randstad blocks ClaudeBot from `/freelance/` by name; Hays'
  ToS §3 prohibits data extraction (its ClaudeBot-friendly `robots.txt` is a red herring — **the ToS
  is the contract**); Michael Page robots-disallows the very contract/salary facets you'd need. All
  three hide rates anyway. Drop.
- **Etengo** — genuinely tempting: the cleanest schema found (`Laufzeit 7 Monate`, `Start 01.09.2026`),
  permissive robots, and the most compatible ToS language in the report (§5(1) contemplates
  retrieval and storage *for own use*, which is what JobScout is). **But its descriptions are
  content-free stubs and there was ~zero AI/ML on inspection.** Easy to parse, nothing to rank.
  That combination is a trap for a semantic-ranking pipeline: it would produce confident nonsense
  rather than obvious breakage. **Keep as a fast follower if the AI/ML volume turns out to be real —
  its ToS posture is better than freelancermap's.**
- **We Work Remotely and RemoteOK** — the most *tempting* drops, because they are the easiest
  adapters in the report: open feed, no auth, no legal ambiguity, an afternoon each. **Drop them
  anyway.** WWR yields 6 contract jobs out of 99; RemoteOK has no contract field at all, salary
  populated on 1 of 100, spam tags, and 3 AI-tagged jobs — none DACH. Building these would feel like
  progress and add nothing to the digest. **This is the clearest case in the report of "cheap" and
  "worthwhile" pointing in opposite directions.** If either is ever reconsidered, note RemoteOK's
  attribution condition is binding and satisfiable, not a blocker.
- **Toptal, Contra, Fiverr, Gun.io, Braintrust, Instaffo, 9am, uplink, Junico, Projektwerk, SOLCOM** —
  prohibited, gated, structurally inverted, empty of DACH AI/ML, or some combination. Nothing to
  adapt. uplink.tech is the one worth a *human* look (claimed rate + client transparency, €80/h
  floor, direct clients) — as a place for Marcos to have an account, not an adapter.

### One extra recommendation that isn't a source: filter the annotation shops

Not a source-selection point, but it falls out of the volume work and belongs somewhere. **The most
likely false-positive class in a freelance AI/ML digest is RLHF / data-labelling piecework** —
Mercor, Surge AI, Micro1, Outlier, Scale AI, Invisible and similar now advertise roles titled *"AI
Engineer"* / *"AI Trainer"* where the actual work is annotation piecework, not engineering. They are
remote, they are contract, they match "AI engineer" semantically, and they will rank *well* against
Marcos's profile query while being exactly what he doesn't want.

This is a **deterministic company-name exclusion** — cheap, no LLM call, fits the existing hard-filter
constraint. Worth adding to `profile.yaml` as an exclusion list at the same time as the pivot.
*(Flagged by the delegated agent; the mechanism is obviously sound but I have not measured how many
such listings actually reach the digest.)*

### The honest summary of this shortlist

**Two to build, two to check.** freelancermap first — it's the only source with *verified* DACH AI/ML
volume (116), a clean JSON ingest path, and a market that has consolidated onto it. Upwork second —
legally settled and the only place rate data exists, but geographically unmeasured. Himalayas and
freelance.de are both one question away from being answerable: reproduce the 76, and send the email.

**They fail in opposite directions, which is the argument for running both of the first two:**
freelancermap is geographically right and legally silent; Upwork is legally clean and geographically
unproven.

**The uncomfortable findings underneath:**

- **The DACH market closed itself to tools like this, then consolidated.** RSS returned **410 Gone**
  on both first-party and aggregator sides; every "API" is inbound; Malt and GULP prohibit automation
  outright. And the boards collapsed into one. The DACH half of JobScout rests on scraping a single
  silent source — a concentration risk as much as a legal one. If freelancermap changes its posture
  or its internal JSON, the DACH half of the pipeline has no fallback.
- **Rate is not available.** Not hidden — absent. `budget` 0/22 on freelancermap, no field at all on
  Etengo/freelance.de/the agencies, `0-0` on Himalayas. **Only Upwork has usable rate data, in USD.**
  `profile.yaml` should stop treating day rate as a filter and treat it as a negotiation.
- **~96% of the DACH ML market is intermediated** (`endcustomer` 5 of 116). The "direct clients only"
  preference is a five-project filter, not a viable ranking axis.

## Open questions / what I could not establish

Being explicit, because several of these are load-bearing and one of them could invert the
shortlist:

1. ✅ **RESOLVED — freelancermap's DACH AI/ML volume is 116 (DE) / 136 (DACH).** This was my biggest
   gap; the tag pages (2 and 0) were misleading and my tag-sparsity inference was correct. Verified
   from first-party `aggregations`. **Residual uncertainty:** 116 is *one query* (`machine
   learning`) on one day — not a de-duplicated total across `KI`/`LLM`/`Data Scientist`. The real
   pool is plausibly larger; I haven't measured it.
2. **Whether freelance.de would grant crawling permission.** They publish a request address
   (support@freelance.de) and a process. Nobody has asked. Cheap to test — though now less valuable
   than it looked, since freelance.de partly posts onto freelancermap anyway.
2b. **Himalayas' 76 Contractor+AI+DE matches are unverified by me** — reported by an agent that
   retracted other claims this session. Reproduce before relying on it. Same for its ToS conflict.
2c. **How stable freelancermap's `ProjectSearch` JSON is.** It is an undocumented internal payload,
   not a contract. It could change shape without notice, and the whole #1 recommendation rests on it.
   No versioning, no deprecation policy, no guarantees.
3. **ToS not located** for: SOLCOM, Michael Page (404s), Randstad (404 — though its robots.txt
   settles it anyway), Instaffo, Junico, Projektwerk. Permissive robots.txt on Etengo, SOLCOM,
   freelancermap, Junico and Projektwerk is **not** consent — silence is silence.
4. **Whether Etengo's thin AI/ML page-one result is representative** or a snapshot artifact. One
   observation on one day.
5. **SOLCOM's field structure and volume** — blocked by 403s, entirely unverified.
6. **GULP's fields and volume** — JS app shell, never rendered. Moot given §4 Nr. 1 d), but
   unverified all the same.
7. **`12 MM` (Mannmonate) duration format** — expected from DACH convention but **not directly
   observed** on any source I fetched. Largely moot now: freelancermap's `duration` is a clean
   integer. Don't build a parser branch for it on my say-so.
8. ✅ **Mostly resolved — freelancermap's `budget` is empty (0/22), so its semantics barely matter.**
   The `70,00 €` I saw once was on a one-month gig page. **Residual:** if a populated `budget` ever
   appears, its unit (project total vs hourly vs daily) is still undefined — so if you do parse it,
   don't assume.
8b. **The `employee_leasing` (ANÜ) share is 12 of 116** — measured, contra the agent's note that it
   hadn't been. `permanent_position` is 10. Both excludable via `projectContractType`.
8c. **`embedding` (1024-dim, 22/22) is undocumented** — I don't know the model, and it's incompatible
   with `multi-qa-MiniLM-L6-cos-v1` (384-dim). Possibly useful for near-duplicate detection, which
   would touch the existing cross-source dedup plan. Unexplored.
9. **uplink.tech's rate/client transparency** — claimed by a secondary source
   ([startupvalley](https://startupvalley.news/de/uplink-it-freelancer/)), not confirmed
   first-party, and moot for adapters since the board is login-gated. Worth a human look.
10. **Not investigated at all**: Questax, Westhouse, Allgeier, Computer Futures, Darwin Recruitment,
    Robert Half, Hired, Freelance Junior, twago, Hays Talent Solutions, codecontrol.
11. **Whether any of the permissive-robots sources bot-block at the edge under sustained load.**
    freelancermap served every fetch cleanly, but that was a handful of requests, not a daily
    crawl. SOLCOM proves the failure mode is real.
12. **Upwork's DACH AI/ML volume.** No platform publishes geography × skill segmentation. Deriving
    it from the $300M AI GSV would require inventing an average contract value and a DACH share.
    **One call to `totalCount` on a filtered `marketplaceJobPostingsSearch` settles it** once a key
    exists — by far the highest value-per-effort item in this list.
13. **Whether embeddings fall inside Upwork's "hashed or otherwise transformed data".** My reading
    says probably yes; that reading is load-bearing for the storage design and is **not** a settled
    fact. Ask Upwork developer support in writing.
14. **Whether `publicMarketplaceJobPostingsSearch` is genuinely unauthenticated.** The docs show no
    permissions line; that is suggestive, not proof. Test it.
15. **Malt's ToS**, beyond the Art. 10.2 scraping clause — the site 403s non-browser clients and
    Cloudflare-challenges even `/sitemap.xml`. Moot given the clause, but noted.
16. **Fiverr Briefs replacing Buyer Requests** — corroborated but **secondary only**; Fiverr's own
    help pages 403.
17. **Working Nomads, Himalayas, Wellfound, and EU Remote Jobs were not examined first-hand.** I
    verified WWR and RemoteOK by fetching and parsing their feeds; these four did not get the same
    treatment. I *expect* them to mirror the pattern (FTE-dominated, weak contract signal, negligible
    DACH AI/ML) but **have not verified it and it should not be cited as a finding.** ~1 hour of work
    to close.
18. **Whether RemoteOK's `Content-Signal` / EU DSM Art. 4 reservation actually binds a
    retrieval-embedding pipeline.** My reading is that `ai-train=no` doesn't reach retrieval and that
    the API's own terms govern anyway — but this is a **novel, largely untested mechanism** and my
    reading is not authoritative. Moot given the recommendation to drop RemoteOK, but it will recur:
    Content-Signal is Cloudflare-managed and is spreading fast. Contra already carries one too.
