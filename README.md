# warhub-catalog

A standalone, versioned **data catalog for tabletop miniatures** — a product catalog
(retail boxes with EAN barcodes, by game system) and a paint catalog (with cross-brand
CIEDE2000 **Delta-E** colour equivalences). The data is generated from public sources
and published as clean, versioned JSON for any client to consume.

This one repo holds everything: the generation **tools**, the source-of-truth **data**,
the automation **workflows**, and the **publisher** that bundles it all into the published
artifacts.

## Consuming the catalog

Every release is published two ways:

- **GitHub Pages** — stable "latest" URLs: `https://warhub.github.io/warhub-catalog/<path>`
- **GitHub Release assets** — immutable, versioned snapshots you can pin to.

**Fetch `manifest.json` first.** It is the discovery document: it names the version, the
release, and lists every published file with its byte size and `sha256`.

```
manifest.json                          # start here
products.json                          # every product, one document
products/index.json                    # list of game-system partitions
products/by-system/<system>.json       # just one game system (e.g. star-wars-legion)
paints.json                            # every paint, equivalents embedded
paints/index.json                      # list of brand partitions
paints/by-brand/<brand>.json           # just one brand (e.g. citadel-colour)
schema/*.json                          # JSON Schemas for every document kind
```

Take the **whole** catalog or just the **slice** you need — a Star Wars Legion app can
fetch one game-system file; a painter can fetch only the brands they own.

### Document shape

Every document carries a self-describing envelope plus its payload:

```jsonc
{
  "schemaVersion": "1.0",
  "kind": "paint-catalog",             // or *-partition, product-catalog, index, manifest
  "version": "2026.7.4",
  "generatedAt": "2026-07-04T05:00:00Z",
  "gitCommit": "abc1234",
  "partition": { "type": "brand", "key": "citadel-colour", "label": "Citadel" }, // partitions only
  "counts": { "paints": 462 },
  "source": {
    "repo": "WarHub/warhub-catalog",
    "release": { "tag": "v2026.7.4", "url": "https://github.com/WarHub/warhub-catalog/releases/tag/v2026.7.4" },
    "pageUrl": "https://warhub.github.io/warhub-catalog/paints/by-brand/citadel-colour.json"
  },
  "paints": [ /* … */ ]
}
```

- **Product**: `{ ean?, name, gameSystem?, faction?, quantity, productCode?, url?, imageUrl? }`
  — `ean` is optional (not every product has a barcode).
- **Paint**: `{ id, brand, range?, name, hex, type?, finish?, equivalents: [{ id, deltaE, tier? }] }`
  — `id` is the stable global key (`brand-slug/paint-slug`); `equivalents` reference other
  paints' ids and are stored **bidirectionally**. Colour equivalence is precomputed here, so
  clients need no colour math.

The authoritative contract is the JSON Schema set under `schema/` (also validated on every build).

### Versioning

Versions are per-day `yyyy.m.d` (e.g. `2026.7.4`); a second build the same day becomes
`2026.7.4.2`. The git tag is `v<version>`. Consume `.../latest` (Pages) for the newest, or pin
a release tag for a frozen snapshot.

## Repository layout

```
tools/
  WarHub.ProductCatalog.Tool/    # scrapes vendor sites -> data/products YAML
  WarHub.PaintCatalog.Tool/      # parses paint lists, computes Delta-E -> data/paints YAML
  WarHub.Catalog.Publish/        # bundles data/ YAML -> dist/ JSON (the published catalog)
  acquisition/                   # python: acquire/migrate/resolve/report
data/
  evidence/                      # source of truth: per-source observations (evidence ledger)
  catalog/                       # source of truth: resolved canonical catalog (products/, taxonomy/)
  products/                      # legacy, retired by the evidence-ledger pipeline; removal tracked for Plan 5
  paints/                        # source of truth: brands/*.yaml, equivalences.yaml, overrides.yaml
.github/workflows/
  catalog-acquire.yml            # nightly + weekly deep-sweep: harvest live sources -> evidence -> resolve -> sticky PR
  classify.yml                   # manual (workflow_dispatch only): LLM classify / join-adjudication -> sticky PR
  paint-catalog-update.yml       # weekly: regenerate paint data + equivalences (PR)
  catalog-publish.yml            # on catalog/paint data change: bundle -> Release + Pages
```

## Pipeline

1. Product data flows through an **evidence ledger**: per-source observations under
   `data/evidence/` are resolved into the canonical catalog under `data/catalog/`
   (`tools/acquisition`). **`catalog-acquire.yml`** runs nightly (04:00 UTC) and does a
   **weekly deep sweep** (Saturdays, 02:00 UTC, or `workflow_dispatch` with `mode: weekly`): a
   job matrix harvests each live source group into `data/evidence/`, then an integrate job
   merges the evidence, runs `resolve`/`report`/`report --ean-guard`, and opens or updates a
   sticky PR (`catalog/acquisition`) with the combined health report, coverage table, and any
   confirmed-EAN guard findings. It supersedes the legacy `product-catalog-update.yml` /
   `product-catalog-enrich.yml` generation workflows. Every nightly run does full (cheap)
   enumeration plus budgeted detail fetches with persistent per-source cursors, converging to
   full coverage across nights; the weekly sweep additionally runs two source kinds that are too
   slow/quota-limited for nightly cadence: **archive mining** (`arc-*` sources, e.g. Wayback
   Machine snapshots of goblingaming/gw-webstore — one shared host, budgeted and paced
   accordingly) and **barcode-db corroboration** (`bdb-*` sources, e.g. upcitemdb/Go-UPC —
   always small, explicit per-source budgets, since upcitemdb's trial tier is quota-limited to
   ~100 requests/day). It also temporarily raises the slower retailer sources' budgets on the
   weekly run to converge their backlog faster. Live-source strategies are covered by
   `pytest -m live` smoke tests under `tools/acquisition/tests/` (opt-in real-network checks,
   excluded from the default test run — see `test_live_smoke.py` / `test_live_smoke_woo.py`).
2. Entities the resolver can't auto-classify (no confident `gameSystem`) or that need
   duplicate-entity adjudication go through **`classify.yml`**, a **`workflow_dispatch`-only**
   workflow (never scheduled — LLM spend stays human-triggered) with a `mode` input:
   `classify` builds the review queue, sends it to an Anthropic model for `gameSystem`/`faction`
   decisions, applies accepted decisions to `data/catalog/overrides.yaml`, then re-runs
   `resolve`/`report`; `propose-joins` finds suspected duplicate-entity pairs (shared EAN /
   normalized name / legacy-code match) and sends them to the model for a same-product verdict,
   writing `data/review/join-proposals.yaml` for human/controller review only — it never edits
   `data/catalog/matches.yaml` itself; promoting a proposed join stays a manual step. Both modes
   open or update their own sticky PR (`catalog/classification`, separate from
   `catalog/acquisition`). **Requires the `ANTHROPIC_API_KEY` repository secret** — the workflow
   fails fast with a clear error if it isn't configured, before spending any budget.
3. Merging a data PR triggers **`catalog-publish.yml`**, which runs the publisher — reading
   `data/catalog` for products and `data/paints` for paints — to build the `dist/` JSON tree,
   then publishes it as a versioned Release **and** to GitHub Pages. The publish trigger only
   watches `data/catalog/**` and `data/paints/**`, so evidence-only or legacy-tree churn never
   mints a release.

Both `catalog-acquire.yml` and `classify.yml` use **sticky PRs** (one persistent branch each,
updated in place rather than opened fresh every run): cursor/queue progress from a given run only
actually lands in `data/` — and so only becomes visible to the *next* run — once that sticky PR is
merged. An unmerged sticky PR means the next scheduled/dispatched run still starts from the
previously-merged state, not from what's sitting in the open PR.

## Build locally

Prerequisites: [.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0).

```bash
dotnet test WarHub.Catalog.slnx           # tools + publisher tests

# Bundle the committed data into ./dist
dotnet run --project tools/WarHub.Catalog.Publish -- \
  --catalog-version 0.0.0-local --page-base-url http://localhost:8080
# --catalog-dir defaults to data/catalog (products/*.yaml, taxonomy/*.yaml); pass it to point
# at another canonical catalog checkout

# Serve it like a client would
python -m http.server 8080 --directory dist
```

## Data sources & licensing

Product data is scraped from manufacturer and retailer sites. Paint data derives from
[Arcturus5404/miniature-paints](https://github.com/Arcturus5404/miniature-paints) (MIT) plus
public swatch sources. See `data/*/LICENSE` for the source-data terms; tooling is under this
repo's [LICENSE](LICENSE).
