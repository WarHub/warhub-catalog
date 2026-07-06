# Catalog Storage Model Revamp — Design

**Date:** 2026-07-07
**Status:** Approved design, pending implementation plan
**Scope:** The source-of-truth data storage model under `data/` and the tools that read/write it
(`WarHub.ProductCatalog.Tool`, `WarHub.PaintCatalog.Tool`). The publisher
(`WarHub.Catalog.Publish`) is affected only where it consumes fields that change.

## Problem

The catalog's core objective is to **archive every release, ever** — discontinuations, limited
runs, site drops, and manufacturer closures must never remove data. We only ever backfix or add;
we drop only genuinely bad/invalid additions. The current storage model violates this and is
unstable in ways that produce enormous, meaningless diffs (see PR #4: +32k/−27k) and corrupt data
(see PR #5).

### Root causes

1. **The write model is "overwrite," not "archive."** Each run scrapes fresh products, groups them
   by manufacturer/system/faction, and writes each faction file from the fresh scrape. The only
   thing carried across runs is the **EAN field** (`MergeExistingEans` in
   `tools/WarHub.ProductCatalog.Tool/Program.cs`, keyed by SKU or name). Consequences:
   - **Data loss:** a product absent from a given scrape — rate limit, parse failure, site drop,
     discontinuation — is simply not written. The whole record vanishes. Only its EAN would have
     been reused, and only if it reappeared.
   - **Reordering:** within a faction, products are written in scrape order with no stable sort.
     Any change in source order or scrape timing reshuffles the file.
2. **EAN leading-zero corruption.** `Product.Ean` is a `string`, but YamlDotNet emits e.g.
   `889696012593` unquoted because it looks numeric. A schema-less parser reads it as a number and
   drops leading zeros. The enrichment tool's own read→write round-trip can corrupt it too.
3. **Churn magnets in the schema.** Every file carries denormalized `productCount`/`totalProducts`,
   and paint files serialize a fully-exploded `generatedAt` DateTime (`ticks`, `nanosecond`,
   `dayOfWeek`, …). Both change constantly for no informational gain.

## Objective

A **stable, append-only, backfill-only** data model with deterministic identity and ordering,
shared across products and paints. The guiding invariant:

> A data file changes only when a catalog **fact** changes — never merely because a scrape ran.

Corollary stability contract: **re-running the tool against identical input produces byte-identical
files.**

## Decisions (locked)

| Decision | Choice |
| --- | --- |
| Product identity | Composite name key: `manufacturerSlug / gameSystemSlug / factionSlug / normalizedName` |
| Rename resilience | Secondary URL match + manual `aliases:` override |
| Missing on scrape | Keep the record; auto-flag `suspected-discontinued` after N consecutive misses |
| Field updates | Update-present, keep-on-empty (a partial scrape can never blank a field) |
| Paints unification | Shared model + rules via a common library; separate file trees and payloads |
| Type model | Two orthogonal axes: `category` (what it is) + `packaging` (how it's sold) |
| Provenance | `firstSeen` + `status` in-record; all volatile liveness in a single sidecar ledger |
| Scrape health gate | Explicit per-source success signal reported by each scraper |
| Architecture | Shared `CatalogStore` reconciliation library used by both tools (Approach A) |

## Architecture — Approach A: shared `CatalogStore` library

Introduce an explicit reconcile stage as a standalone, testable library that **both** tools call.
The per-run flow for a catalog becomes:

```
1. LOAD    existing archive  → dict keyed by composite key (+ URL index, + alias map)
2. SCRAPE  fresh products    → list  (each source reports succeeded: true/false)
3. RECONCILE each fresh product against the archive:
     match (composite key → URL fallback → alias override)?
       YES → MERGE into existing record (update-present/keep-on-empty),
             preserve identity + firstSeen
       NO  → INSERT new record (firstSeen = today, status = current)
     mark the resolved key "seen this run" (for the ledger)
4. KEEP    every existing record NOT seen this run — untouched. Never dropped.
5. LEDGER  update liveness; apply auto-flag transitions (gated on source success)
6. ORDER   deterministically, SERIALIZE (shared serializer)
```

The library owns: the file envelope, the record *core*, identity/matching, reconciliation, the
ledger, and serialization. Each catalog supplies its own **payload record** (product vs paint) and
its own **scraper**. This directly realizes the "shared mechanism, separate schema" decision and
lifts the reconciliation logic out of today's 1088-line `Program.cs` into unit-testable units.

Rejected alternatives: **B — event-sourced append-only log** (large rework, fights git, overkill);
**C — minimal patch-in-place** (bolts onto the existing tangle, gives paints nothing reusable, and
the ledger + category/packaging expansion don't fit cleanly).

## Domain model & schema

**Faction file** loses derived noise (no `productCount`):

```yaml
manufacturer: CMON
manufacturerSlug: cmon
gameSystem: A Song of Ice and Fire
gameSystemSlug: asoiaf
faction: Baratheon
factionSlug: baratheon
products:
- ...
```

**Product record** — shared core + the two axes + a category-specific extension block:

```yaml
- name: 'Baratheon: Wardens'
  category: miniatures        # miniatures|terrain|accessory|paint|book|tool
  packaging: single           # single|bundle|box|starter   (replaces productType)
  status: current             # current|suspected-discontinued|discontinued|delisted
  firstSeen: 2026-07-07       # write-once, immutable
  ean: '889696010223'         # ALWAYS quoted string
  eanSource: shopify:entoyment.co.uk
  sku: ''
  productCode:
  priceUsd: 37.99
  url: https://www.cmon.com/products/baratheon-wardens/
  imageUrl:
  releaseDate:
  description: An Ideal Defensive Unit
  contents: [...]             # for bundles/boxes
  details:                    # OPTIONAL category-specific sub-block
    modelCount: 12            #   paints put hex/rgb/volumeMl/finish/range/equivalents here
```

Notes:
- `category` + `packaging` are orthogonal. `packaging` absorbs today's `productType`.
- `details` is the category-specific extension point — thin for minis/terrain today, rich for paints.
- `firstSeen` is the **only** per-record provenance in the data file (write-once → no churn).
- `status` changes only on real transitions.
- Removed from source files: `productCount`, `totalProducts`, and the exploded `generatedAt`.
  Counts are recomputed at publish; a single ISO timestamp (if wanted) lives once in the ledger.

### Status lifecycle

- `current` — seen recently / active.
- `suspected-discontinued` — **the only status the tool sets automatically**, when `missStreak`
  crosses N under a healthy source. Reverts to `current` on reappearance.
- `discontinued`, `delisted` — confirmed states, **human/override-only**.

## Identity & matching

**Primary key:** `manufacturerSlug / gameSystemSlug / factionSlug / normalizedName`.

**`normalizedName`** — conservative, deterministic, documented: Unicode NFKC → lowercase → trim →
collapse internal whitespace → strip surrounding quotes. Deliberately **not** aggressive (no
punctuation stripping) to avoid collapsing genuinely-distinct products.

**Matching precedence** when reconciling a fresh product to the archive:
1. **Composite key** exact match → same record.
2. **URL fallback** — no key match but URL equals an existing record's URL (same manufacturer) →
   a **rename**: keep the record's identity + `firstSeen`, update the name. Catches the composite
   key's main weakness before it duplicates.
3. **Alias override** — a manual `aliases:` map in `overrides.yaml` (`oldKey → canonicalKey`)
   stitches renames/faction-moves the URL can't, and merges accidental duplicates.
4. No match → **new record** (`firstSeen = today`, `status: current`).

**Deletion is never automatic.** The only removal path is an explicit `retract:` list in
`overrides.yaml` for genuinely bad/invalid additions.

## Reconciliation semantics

The archive is authoritative and the scrape *contributes* — the exact inversion of today's bug.

**Merge rule (update-present, keep-on-empty):**
- Immutable: identity `name`, `firstSeen`, and `category` once set (a source flip-flop won't churn
  it; overrides can correct).
- Mutable (`price*`, `url`, `imageUrl`, `description`, `packaging`, `releaseDate`, `contents`): a
  fresh **non-empty** value overwrites; a fresh **empty/missing** value keeps the archived value.
  A partial scrape can never blank a field.
- `ean` / `eanSource`: enrichment fills blanks; an existing EAN is never overwritten by an empty
  scrape.
- `status`: source-driven only for **reactivation** (a `suspected-discontinued` product reappearing
  → `current`); the auto-flag transition is the ledger's job; manual `discontinued`/`delisted` come
  from overrides.

## Liveness ledger & auto-flag

**One committed sidecar per catalog:** `data/products/_liveness.yaml`, `data/paints/_liveness.yaml`.
This is the **only** file expected to change on an uneventful run.

```yaml
schemaVersion: 1
sources:
  cmon:
    lastRun: 2026-07-07
    lastGoodRun: 2026-07-07
    lastRunSucceeded: true        # EXPLICIT signal from the scraper, not inferred
    productCount: 337
records:
  cmon/asoiaf/baratheon/baratheon-wardens:
    lastSeen: 2026-07-07
    missStreak: 0
```

**Auto-flag logic, gated on the explicit per-source success signal:**
- Each scraper reports `succeeded: true/false` for its run (HTTP health + expected-page markers).
- Source **succeeded**: for each of that source's known records — seen this run → `missStreak = 0`,
  `lastSeen = today`; not seen → `missStreak++`. When `missStreak` crosses **N (default 3,
  configurable)**, the record's `status` flips to `suspected-discontinued` — a real, git-worthy
  change written to the data file.
- Source **failed**: record `lastRunSucceeded: false`, touch no miss counters, flag nothing. A dead
  scrape can never mass-flag a catalog.
- **Reactivation:** a `suspected-discontinued` record reappearing in a healthy scrape → `current`,
  `missStreak = 0`.
- `discontinued` / `delisted` are human/override-only; the tool only ever sets the *suspected* state.

The ledger churns every run (isolated, one file); the data files move only on genuine facts.

## Serialization & determinism

The whole point: **identical input → byte-identical files.**

- **String quoting:** a shared emitter forces quoting on any string scalar that would round-trip as
  a non-string under the YAML core schema — all-digit (`ean`, `sku`, `productCode`), boolean-like,
  null-like, or date-like. Fixes leading-zero loss at the source and survives the enrichment tool's
  read→write round-trip. Unambiguous strings stay unquoted; multi-line descriptions keep the
  existing block-scalar (`|`) style.
- **Deterministic record order:** products sorted by `normalizedName`, tiebroken by `url` then
  `firstSeen`. Order never depends on scrape timing.
- **Fixed field order:** driven by record property order (stable in C#).
- **No derived data in source:** `productCount`/`totalProducts` dropped; exploded `generatedAt`
  gone. A single ISO timestamp, if wanted, lives once in the ledger.
- **`OmitNull`** retained so absent optionals emit no noise.

## Migration

A one-time, idempotent migration (a mode/command in the shared library) transforms the existing
tree into the new schema:
- Quote all EANs/SKUs/codes; map `productType → packaging`; infer `category` (default `miniatures`,
  heuristics for terrain/accessory/paint); backfill `firstSeen` (use existing
  `releaseDate`/`generatedAt` where present, else the migration date); drop
  `productCount`/`generatedAt`; re-sort and re-serialize every file.
- Seed the initial `_liveness.yaml` with every current key marked seen as of the migration date,
  `missStreak: 0`.
- Lands as **one large, expected, one-time reformatting PR**.
- **Idempotency is a hard requirement:** running it twice yields zero diff — the proof the new
  writer is stable.

## Testing strategy

- **Unit:** normalization/key generation; matching precedence (key → URL → alias); merge rules
  (never-drop, update-present, keep-on-empty, immutable `firstSeen`); ledger miss-streak + health
  gate + status transitions (flag at N, reactivation, failed-source flags nothing); serializer
  quoting (leading-zero EANs, null-like/date-like edge cases).
- **Headline guarantee test:** load archive → reconcile against an *identical* scrape → assert
  **byte-identical output** and an unchanged ledger except timestamps.
- **Partial-scrape test:** scrape missing half the records → assert nothing dropped, no field
  blanked, misses counted only under a healthy signal.
- **Migration idempotency test:** run migration twice → second run produces zero diff.

## Publisher impact

The publisher consumes fields that are changing (`productType` → `packaging`; new `category`,
`status`, `firstSeen`; EAN as string). It must be updated to read the new schema and may surface
`category`/`status` in the published JSON. The published document envelope and partitioning are
unchanged by this design; derived counts move to publish-time computation. Detailed publisher
changes are deferred to the implementation plan.

## Out of scope

- Fully merging paints and products into one schema/file tree (explicitly rejected).
- Changes to the published JSON contract beyond surfacing the new/renamed fields.
- New scraper sources or enrichment providers.
