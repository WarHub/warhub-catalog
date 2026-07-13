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
  catalog-acquire.yml            # nightly: harvest live sources -> evidence -> resolve -> sticky PR
  paint-catalog-update.yml       # weekly: regenerate paint data + equivalences (PR)
  catalog-publish.yml            # on catalog/paint data change: bundle -> Release + Pages
```

## Pipeline

1. Product data flows through an **evidence ledger**: per-source observations under
   `data/evidence/` are resolved into the canonical catalog under `data/catalog/`
   (`tools/acquisition`). **`catalog-acquire.yml`** runs nightly (04:00 UTC): a job matrix
   harvests each live source group into `data/evidence/`, then an integrate job merges the
   evidence, runs `resolve`/`report`/`report --ean-guard`, and opens or updates a sticky PR
   (`catalog/acquisition`) with the combined health report, coverage table, and any
   confirmed-EAN guard findings. It supersedes the legacy `product-catalog-update.yml` /
   `product-catalog-enrich.yml` generation workflows. Deliberate deviation from the original
   plan: there is no separate weekly deep-sweep workflow — the nightly run already does full
   (cheap) enumeration plus budgeted detail fetches with persistent per-source cursors, which
   converges to full coverage across nights; the weekly cadence returns in Plan 4 as the
   archive-mining driver. Live-source strategies are covered by `pytest -m live` smoke tests
   under `tools/acquisition/tests/` (opt-in real-network checks, excluded from the default
   test run — see `test_live_smoke.py` / `test_live_smoke_woo.py`).
2. Merging a data PR triggers **`catalog-publish.yml`**, which runs the publisher — reading
   `data/catalog` for products and `data/paints` for paints — to build the `dist/` JSON tree,
   then publishes it as a versioned Release **and** to GitHub Pages. The publish trigger only
   watches `data/catalog/**` and `data/paints/**`, so evidence-only or legacy-tree churn never
   mints a release.

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
