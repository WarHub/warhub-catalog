# Data Acquisition Rewrite — Evidence-Ledger Pipeline

- **Date:** 2026-07-12
- **Status:** Approved
- **Supersedes (acquisition layer):** the scraping/enrichment halves of
  `2026-07-07-catalog-storage-model-design.md` and its addenda. The storage-model
  *principles* (append-only archive, durable retract, deterministic serialization,
  loud guards) carry forward; their implementation is replaced.
- **Research basis:** `docs/research/2026-07-12-*.md` (live probes of every
  manufacturer, 13 retailers, Wayback CDX, and barcode DBs, plus the as-built
  pipeline analysis).

## 1. Mission

Not a refactor. The goal is a materially better catalog. Baseline: 12,799
products across 9 manufacturers with **46% EAN coverage**; 7,357 paints with
EANs for Vallejo only (1,268, computed). Priorities, in order:

1. **EAN/GTIN coverage and correctness** — the headline metric.
2. **Product completeness, including out-of-print** — mine web.archive.org;
   old retailer listings are also the richest barcode source for dead SKUs.
3. **Metadata correctness** — gameSystem, faction, quantity, product code are
   currently guessed by substring heuristics.
4. **An architecture where adding a source is cheap and a broken source is loud.**

Constraints decided with the user:

- LLM extraction allowed in scheduled CI (API key in secrets, capped budget).
- Crawl/evidence state is committed to the repo (claims, not raw HTML).
- Free rein on storage: the week-old CatalogStore/YAML model may be replaced.
- Polyglot allowed: acquisition/resolution in Python; publisher stays .NET.

## 2. Why the current pipeline caps at 46%

From the probe findings (see research docs for evidence):

- Shopify's bulk `products.json` **no longer emits `variants[].barcode`** on any
  store. The EAN is still present per product page — in `/products/<handle>.js`
  (`variants[].barcode`) and in JSON-LD `gtin13` / embedded theme JSON. The
  current pipeline only reads bulk feeds, so every Shopify manufacturer store
  yields zero native EANs. Warlord Games alone is ~5,843 products at 20%
  coverage — with per-page EANs sitting unread on its own store.
- GW (Algolia), Corvus Belli (AppSync), and CMON expose **no EAN anywhere**;
  coverage there must come from retailer cross-referencing. The current curated
  retailer list plus a 100-call/day UPCitemdb budget is the only mechanism.
- Every failure path is fail-soft: broken sources silently degrade coverage.

## 3. Architecture overview

Claims-first pipeline: sources emit **observations** (per-source claims with
provenance) into a committed **evidence store**; a deterministic **resolver**
folds all observations into the **canonical catalog** that the publisher reads.

```
descriptors (data/catalog/sources/*.yaml)
        │
   acquire (Python, budgeted, polite, contract-checked)
        │  observations
        ▼
data/evidence/{products,paints}/<source-id>/observations.jsonl   ← the ledger
        │
   resolve (deterministic: identity → join → corroborate → classify)
        │                          ├── review/conflicts.yaml   (loud queue)
        ▼                          └── catalog/matches.yaml    (adjudicated joins)
data/catalog/{products,paints}/*.yaml                            ← canonical
        │
   publish (.NET WarHub.Catalog.Publish, adapted readers)
        ▼
dist/ JSON → GitHub Release + Pages (contract additive)
```

## 4. Data model & repo layout

```
data/
  evidence/
    products/<source-id>/observations.jsonl   # one line per source-product, sorted by key
    products/<source-id>/cursor.yaml          # crawl state: sweep position, budgets, etags
    paints/<source-id>/...
  catalog/
    sources/*.yaml                            # source descriptors (see §6)
    products/<manufacturer>.yaml              # canonical resolved records (derived, committed)
    paints/<brand>.yaml
    taxonomy/*.yaml                           # game systems, factions, per-mfr code patterns,
                                              # GS1 prefixes, hint→taxonomy mappings
    classifications.yaml                      # committed LLM classification outputs + provenance
    matches.yaml                              # adjudicated cross-source joins (proposals reviewed via PR)
    overrides.yaml                            # human corrections + durable retracts (top precedence)
  review/
    conflicts.yaml                            # generated: EAN conflicts, ambiguous joins, contract breaches
```

**Observation** (JSONL line; update-in-place per key, never deleted):

```json
{"key": "ret-goblingaming:warhammer-40k-combat-patrol-necrons-2023",
 "url": "https://www.goblingaming.co.uk/products/warhammer-40k-combat-patrol-necrons-2023",
 "firstSeen": "2026-07-12", "lastSeen": "2026-07-12",
 "name": "Warhammer 40k: Combat Patrol Necrons (2023)",
 "sku": "99120110077", "ean": "5011921194285",
 "priceGbp": 76.5, "availability": "in_stock",
 "hints": {"vendor": "Games Workshop", "tags": ["40k", "Necrons"]},
 "extractor": "shopify-handle-js@2", "archived": false}
```

The evidence store **is** the liveness ledger: miss-streaks and staleness are
derived from `lastSeen` across live sources; no `_liveness.yaml` sidecar.
JSONL sorted by key for clean diffs. Size estimate: ~50k observations ≈ 20 MB.

**Canonical product** (YAML, deterministic order):

```yaml
- id: games-workshop/99120110077
  name: 'Combat Patrol: Necrons'
  manufacturer: games-workshop
  productCode: '99120110077'
  ean: '5011921194285'
  eanConfidence: confirmed        # confirmed | provisional | conflicted
  gameSystem: warhammer-40k       # attribute, not identity
  faction: necrons                # attribute, not identity
  category: miniatures
  packaging: box_set
  quantity: null                  # from seed/overrides/LLM extraction where known
  status: current                 # current | suspected-discontinued | discontinued | delisted
  availability: in_stock
  firstSeen: '2026-07-07'
  priceGbp: 76.5
  url: https://...
  imageUrl: https://...
  evidence: [mfr-gw-algolia:60010110004, ret-goblingaming:warhammer-40k-combat-patrol-necrons-2023]
```

The catalog is derived-but-committed: the resolver is deterministic (same
evidence → byte-identical catalog), so data PRs stay reviewable and the
publisher reads plain YAML. Identical input → identical output remains an
invariant (carried over from the storage-model design).

## 5. Identity & resolution

**Identity.** `manufacturer/productCode` when the code matches that
manufacturer's declared pattern in `taxonomy/` (GW `\d{11}`, Para Bellum
`PBW\w+`, Corvus Belli `\d{6}`, Wyrd `WYR\d+`, …); otherwise
`manufacturer/name-slug`. gameSystem/faction are resolved **attributes** —
reclassification never changes identity, resets `firstSeen`, or strands
duplicates (fixes the deferred cross-faction-move problem by construction).

**Joining** observations into entities, strongest first:

1. EAN exact match (validated EANs only).
2. Normalized manufacturer code (strip `-EN`, retailer prefixes `GWS`/`GW-`, etc.).
3. Per-source URL/key continuity (an observation key stays with its entity).
4. Normalized name — only auto-joined when unambiguous; ambiguous cases emit an
   LLM-adjudicated proposal (with reasoning) into `matches.yaml` via PR.
   Unreviewed proposals stay unjoined. Never silent.

**EAN rules** (priority 1):

- Validity gate: 12–13 digits, correct check digit. Per-manufacturer GS1 prefix
  (GW `5011921…`) is a scoring signal, not a hard filter.
- Confidence: `confirmed` = asserted by the manufacturer's own store **or** by
  ≥2 independent sources; `provisional` = a single retailer; a barcode DB alone
  never confirms.
- A previously confirmed EAN is never silently replaced; competing assertions
  (two EANs on one entity, one EAN on two entities) go to `review/conflicts.yaml`
  and the run's PR annotation.
- Published `ean` includes provisional values (coverage first) with
  `eanConfidence` exposed so consumers can filter.

**Metadata.** Per-source hint→taxonomy mappings (data, not code) replace the
in-code substring heuristics. Unmapped values go to LLM classification; outputs
are committed to `classifications.yaml` with model provenance — reviewable,
cached, re-run only when inputs change. `overrides.yaml` keeps top precedence;
retracts remain durable (suppressed at input; rename-onto-retracted blocked).

**Lifecycle.** Same status axis as today (`current` / `suspected-discontinued`
/ `discontinued` / `delisted`; only `suspected-discontinued` is auto-set),
derived from `lastSeen` across the entity's *live* (non-archived) sources, with
the healthy-source guard: a source failing its contract (or an implausible
count drop) cannot miss-flag anything. Archive-only entities enter as
`discontinued` directly. `availability` stays the volatile scrape-driven axis.

## 6. Source framework & roster

A source = **descriptor** + **extractor**. Descriptor (YAML, in
`data/catalog/sources/`):

```yaml
id: ret-goblingaming
kind: retailer            # manufacturer | retailer | archive | barcode-db
strategy: shopify
baseUrl: https://www.goblingaming.co.uk
scope: { vendors: [Games Workshop] }        # optional filter
politeness: { rps: 0.5, userAgent: warhub-catalog-bot }
budget: { pagesPerRun: 500 }
contract:
  minCount: 8000            # observed floor; violation = loud failure
  maxDropPct: 30
  requiredFieldRates: { name: 1.0, sku: 0.9, ean: 0.6 }
```

Fetch strategies implemented once, shared by all descriptors:

| Strategy | Mechanism | Used by (v1 roster) |
|---|---|---|
| `shopify` | bulk `products.json` for enumeration + change detection (`updated_at`); per-handle `/products/<h>.js` for `variants[].barcode` | Warlord store, Steamforged, Wyrd store, Asmodee (AMG), Goblin Gaming, Tistaminis, Army Painter (paints) |
| `woo-store-api` | `/wp-json/wc/store/products`; JSON-LD page fetch where gtin exists | Mantic (JSON-LD `gtin`), Para Bellum |
| `algolia` | GW `prod-lazarus-product-en-gb` index (current approach carried over) | Games Workshop |
| `appsync` | Corvus Belli GraphQL gateway (`send` command payloads) | Corvus Belli |
| `playwright` | headless Chromium for bot-walled sites | CMON (Cloudflare); optionally Wayland later |
| `sitemap+structured-data` | sitemap enumeration → JSON-LD / microdata / embedded-JS extraction | Miniaturicum (`gtin13` + EAN reverse lookup), Radaddel (microdata), Game Nerdz (BigCommerce `BCData.upc`) |
| `cdx-archive` | Wayback CDX enumeration (≤1 req/s, committed cursors) → archived-page extraction: deterministic for archived Shopify JSON-LD; LLM for old GW HTML | old GW webstore 2014–2019 (OOP names/codes/prices), archived Shopify retailers (OOP EANs) |
| `barcode-db` | UPCitemdb trial / Go-UPC lookup | corroboration-only, lowest priority |

**Contracts make breakage loud.** Violations fail the CI job and annotate the
PR. Evidence is append-only, so the worst a broken source can do is go stale —
visibly, never silently shrinking the catalog.

**Budgeted incremental crawling.** Per-run page budgets with committed cursors;
priority: products missing EANs → new handles → stalest observations. Change
detection via Shopify `updated_at` / sitemap `lastmod` keeps steady-state runs
cheap. Full sweeps complete over multiple scheduled runs.

**Paints.** Same framework and evidence model. Army Painter barcodes via
per-handle fetch (probe-confirmed); Vallejo computed EAN-13 kept as an
`extractor: computed-vallejo` source; other brand stores (AK Interactive,
Scale75, Two Thin Coats, Green Stuff World, …) probed as `shopify` /
`sitemap+structured-data` candidates during implementation. The Arcturus
dataset remains the swatch backbone; Scalemates stays for coverage. CIEDE2000
equivalence math ports to Python with golden-value tests against the current
`equivalences.yaml`.

**LLM usage** (scheduled CI, capped): archived/messy HTML extraction (old GW
pages), taxonomy classification for unmapped hints, join adjudication
proposals. Default model: Haiku-class; batch where possible; every output
lands in committed files with model + input-hash provenance so nothing is
re-queried unless inputs change.

## 7. Orchestration & CI

**Stack.** Python package `tools/acquisition/` (uv-managed): httpx,
selectolax + extruct (JSON-LD/microdata), playwright, pydantic models,
anthropic SDK. CLI verbs:

- `acquire [--source ID] [--budget N]` — run sources, update evidence + cursors.
- `resolve` — evidence → canonical catalog + conflicts (deterministic, offline).
- `report` — per-source health + coverage dashboard (also injected into PR bodies
  and the data README).
- `migrate` — one-time legacy import (§8).

**Workflows** (replacing `product-catalog-update.yml`,
`product-catalog-enrich.yml`, `paint-catalog-update.yml`):

- **Nightly acquisition:** matrix per source group (budgeted, politeness-paced)
  → `resolve` → sticky PR; PR body = health report (per-source fetched/new/
  changed, contract status, EAN coverage delta, open conflicts).
- **Weekly deep sweep:** full refresh cycles + `cdx-archive` mining + paint
  sources.
- `catalog-publish.yml` trigger unchanged (push to `main` touching `data/**`).
- `ci.yml` extends to run Python tests (pytest) alongside .NET tests.

## 8. Migration & retirement

One-time `migrate`:

1. Convert every existing faction/brand YAML record into a `legacy-catalog`
   evidence source — preserving name, EAN, `eanSource` (mapped to per-source
   provenance), SKU, prices, `firstSeen`, status, availability. Nothing is lost;
   existing EANs become corroborating evidence.
2. Seed `taxonomy/` from `ManufacturerRegistry` + the inline extractor tables
   (faction lists, game-system maps) so current classification knowledge is
   carried over as data.
3. Convert `data/products/seed/*.yaml` (curated contents/quantity data) into a
   `seed-curated` evidence source with high metadata precedence.
4. Resolve → initial canonical catalog; verify parity (product count ≥ legacy,
   EAN count ≥ legacy, zero lost identities) before the old outputs are removed.

Retirement: `WarHub.ProductCatalog.Tool`, `WarHub.PaintCatalog.Tool`, and
`WarHub.CatalogStore` (plus their tests) are deleted once parity is
demonstrated. `WarHub.Catalog.Publish` stays .NET: readers adapt to
`data/catalog/`, published schema changes are additive (`eanConfidence`,
provenance counts); `schemaVersion` stays 1.0 (no external consumers yet).
The PowerShell scripts under `data/products/scripts/` retire with the formats.
Open bot PRs #4/#5/#16 close superseded — their data re-derives through the
new pipeline.

## 9. Testing

- **Extractor fixtures:** committed captured pages (HTML/JSON) per strategy;
  extraction asserted against known-good observations.
- **Contract tests:** descriptor validation + violation behavior (loud failure).
- **Resolver golden tests:** evidence in → catalog out, byte-stable; identity,
  corroboration, conflict, lifecycle, and retract cases.
- **EAN validator:** check-digit + prefix unit tests.
- **Migration parity test:** legacy YAML → evidence → catalog with the
  invariants of §8.4.
- **Live smokes:** one per strategy, opt-in marker, non-blocking in CI.
- Publisher keeps JSON-Schema validation of every emitted document as the
  final gate.

## 10. Expected outcomes

- Warlord's own store (~5.8k products, per-page `gtin13`) alone should move
  overall EAN coverage from 46% to ~70%+.
- Five new EAN retailers (Goblin, Tistaminis, Miniaturicum, Radaddel, Game
  Nerdz) lift GW/Corvus/CMON coverage; Miniaturicum's EAN reverse lookup and
  Game Nerdz's UPC search enable targeted verification.
- Archive mining adds out-of-print products *with* barcodes (archived Shopify
  JSON-LD) instead of diluting the ratio; old GW webstore recovers dead SKUs'
  names/codes/prices.
- Paint EANs extend beyond Vallejo (Army Painter confirmed; more brands probed).
- Metadata driven by taxonomy data + committed classifications instead of
  in-code substring guesses.
- A new source is a descriptor + extractor + fixtures; a broken source is a
  failed CI job with a named contract violation.

## 11. Out of scope

- Paid data APIs (free tiers only, per mission).
- Changing the published `dist/` contract beyond additive fields.
- Wayland/Fantasywelt behind PerimeterX/Cloudflare (revisit via `playwright`
  strategy later).
- BGG (token-gated) and Wikidata (no coverage) — documented dead ends.
- Price-history tracking (observations keep latest price only).
