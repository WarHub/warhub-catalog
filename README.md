# warhub-catalog

A standalone, versioned **data catalog for tabletop miniatures** — a product catalog
(retail boxes with EAN barcodes, by game system) and a paint catalog (with cross-brand
CIEDE2000 **Delta-E** colour equivalences). The data is generated from public sources
and published as clean, versioned JSON for any client to consume.

This one repo holds everything: the generation **tools**, the source-of-truth **data**,
the automation **workflows**, and the **publisher** that bundles it all into the published
artifacts.

The values this catalog is driven by — archive everything, never drop a published id, refuse
rather than guess — are in [docs/OBJECTIVES.md](docs/OBJECTIVES.md). Read it before changing what
the catalog *contains*.

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
  "schemaVersion": "1.1",
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

- **Product**: `{ id, manufacturer, ean?, additionalEans?, supersedes?, supersededBy?, name, gameSystem?, faction?, quantity, productCode?, url?, imageUrl? }`
  — `id` is the stable global key (`manufacturer-slug/product-code-or-slug`) and, with
  `manufacturer`, is present on every product; both are what a cross-product link points at. `ean`
  is optional (not every product has a barcode). `additionalEans` is present only on a product
  genuinely repackaged over time (same contents, new box/barcode): `ean` stays the single primary
  barcode, and the extra barcodes are listed here so existing single-barcode consumers are
  unaffected. `supersedes` / `supersededBy` link the same product across **two product codes** (a
  re-code, a repackaging): both records are published, each keeping its own `productCode` and
  `ean`, so a decade-old box still scans to a record and that record says what replaced it. The
  relation is deliberately not encoded in `status` — a retired record's status is still whatever
  the evidence says, so existing `status` filters keep working unchanged. `counts.products`
  includes those archival records; `counts.currentProducts` is the subset nothing supersedes.
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
  WarHub.PaintCatalog.Tool/      # parses paint lists, computes Delta-E -> data/paints YAML
  WarHub.Catalog.Publish/        # bundles data/ YAML -> dist/ JSON (the published catalog)
  acquisition/                   # python: acquire/migrate/resolve/categorize/report
data/
  evidence/                      # source of truth: per-source observations (evidence ledger)
  catalog/                       # source of truth: resolved canonical catalog (products/, taxonomy/)
  paints/                        # source of truth: brands/*.yaml, equivalences.yaml, overrides.yaml
.github/workflows/
  catalog-acquire.yml            # nightly + weekly deep-sweep: harvest live sources -> evidence -> resolve -> categorize -> sticky PR
  paint-catalog-update.yml       # weekly: regenerate paint data + equivalences (PR)
  catalog-publish.yml            # on catalog/paint data change: bundle -> Release + Pages
```

## Pipeline

1. Product data flows through an **evidence ledger**: per-source observations under
   `data/evidence/` are resolved into the canonical catalog under `data/catalog/`
   (`tools/acquisition`). **`catalog-acquire.yml`** runs nightly (04:00 UTC, Sun-Fri -- Saturday
   is deliberately skipped so the nightly run never clobbers that day's weekly-sweep evidence)
   and does a **weekly deep sweep** (Saturdays, 02:00 UTC, or `workflow_dispatch` with
   `mode: weekly`): a
   job matrix harvests each live source group into `data/evidence/`, then an integrate job
   merges the evidence, runs `resolve`/`categorize`/`report`/`report --ean-guard`, and opens or updates a
   sticky PR (`catalog/acquisition`) with the combined health report, coverage table, and any
   confirmed-EAN guard findings. It supersedes the legacy `product-catalog-update.yml` /
   `product-catalog-enrich.yml` generation workflows. The health report carries a per-source
   `status` (`ok` / `rate-limited` / `ERROR` / `CONTRACT VIOLATION`), so a throttled source is
   distinguishable at a glance from a genuine failure: GitHub-runner IPs are routinely
   rate-limited (HTTP 429, or a Cloudflare 403) by Shopify/Cloudflare, so a source whose only
   failure is upstream rate-limiting is recorded as `rate-limited` and the run exits **degraded**
   (a distinct exit code the workflow treats as success-with-annotation) rather than failing —
   a throttled night keeps its cursor intact and converges next run, and no longer paints the
   job red or hides real failures (which still fail the run loudly). Every nightly run does full
   (cheap) enumeration plus budgeted detail fetches with persistent per-source cursors, converging
   to full coverage across nights; the weekly sweep additionally runs two source kinds that are too
   slow/quota-limited for nightly cadence: **archive mining** (`arc-*` sources, e.g. Wayback
   Machine snapshots of goblingaming/gw-webstore — one shared host, budgeted and paced
   accordingly) and **barcode-db corroboration** (`bdb-*` sources, e.g. upcitemdb/Go-UPC —
   always small, explicit per-source budgets, since upcitemdb's trial tier is quota-limited to
   ~100 requests/day). It also temporarily raises the slower retailer sources' budgets on the
   weekly run to converge their backlog faster. Live-source strategies are covered by
   `pytest -m live` smoke tests under `tools/acquisition/tests/` (opt-in real-network checks,
   excluded from the default test run — see `test_live_smoke.py` / `test_live_smoke_woo.py`).
   A source whose data is a **point-in-time document** rather than a live listing also commits a
   normalized extract under `data/snapshots/<source-id>/`, and `acquire --from-snapshot` re-parses
   that with no network at all. Today this is `mfr-gw-trade`: GW's workbooks rotate, get re-uploaded
   under new names, and its `Code Changes` register is cumulative only for as long as GW keeps
   restating old rows — so the product-code lineage the catalog's archival records depend on must
   not be re-derivable *only* by re-scraping someone else's site. The extract is column-filtered to
   exactly what the parser reads (never the raw workbook, so wholesale `Trade Price`/`Cost` columns
   stay out of git) and future-dated rows are dropped before it is written, since GW's Trade Terms
   make unreleased product information confidential.
2. **`categorize`** runs immediately after every `resolve`, in the same job, and decides what a
   product IS. `resolve` sets `category` from a source's own claim where one exists and falls back
   to `miniatures` otherwise, recording which happened in `categoryBasis`; `categorize` then
   replaces the fallbacks -- and only the fallbacks -- from three kinds of evidence the resolver
   does not read, in this order. First, each store's own taxonomy, stored verbatim at harvest time
   and mapped by a committed table per source under
   `data/catalog/taxonomy/category-rules/<source>.yaml`. Second, the paint catalog's barcodes,
   read live from `data/paints/` rather than through an index, so a paint that gained a barcode
   last night cannot keep yesterday's guess. Third, the product's own name, against a cross-source
   lexicon (`data/catalog/taxonomy/category-lexicon.yaml`) -- weakest, and the only signal
   available for a source that publishes no taxonomy at all. A store's filing about one product
   outranks the cross-catalog inference, which outranks the name; where the first two disagree the
   product keeps the store's answer and the disagreement is written to
   `data/review/categorize.yaml` for a human, alongside the ranked list of raw store values that
   would decide the most still-undecided products. Every rule carries the measurement that
   justified it, re-derivable with `scripts/measure_category_rules.py`. **Anywhere `resolve` runs,
   `categorize` must run after it** -- `resolve` rewrites every product file, so a run that skips
   it republishes decided products as guesses.
3. Entities the resolver can't auto-classify (no confident `gameSystem`) or that need
   duplicate-entity adjudication go through **`warhub-data classify`**, driven **locally, by
   hand**. There is no workflow: LLM spend stays human-triggered, and a classification wave is a
   campaign a person runs and reviews, not something a schedule starts.
   `scripts/classify_local.py` is the driver. It swaps the one SDK surface the committed pipeline
   calls (`client.messages.create`) for the locally-installed, account-billed `claude` CLI — same
   prompts, same batching, same cache, same thresholds, same provenance, and no
   `ANTHROPIC_API_KEY` anywhere. A full classify wave, from `tools/acquisition`:

   ```bash
   uv run warhub-data classify --data ../../data --emit-queue
   uv run --no-sync python scripts/classify_local.py \
       --data ../../data --run-date "$(date -u +%F)" --mode classify --budget 500
   uv run warhub-data classify --data ../../data --apply
   uv run warhub-data resolve   --data ../../data
   uv run warhub-data categorize --data ../../data
   ```

   `--emit-queue` writes `data/review/classification-queue.yaml`; the driver sends it in batches
   and writes accepted decisions to `data/catalog/classifications/products.yaml`; `--apply` merges
   those into `data/catalog/overrides.yaml`. **None of the classify verbs re-run `resolve`
   themselves** — a decision is invisible on the published catalog until `resolve` runs, and
   `categorize` must follow `resolve` for the reason step 2 gives.
   `--mode propose-joins` is the other wave: it finds suspected duplicate-entity pairs (shared
   EAN / normalized name / legacy-code match) and asks the model for a same-product verdict,
   writing `data/review/join-proposals.yaml` for human/controller review only — it never edits
   `data/catalog/matches.yaml`, and promoting a proposed join stays a manual step.
   The SDK path is still there (`warhub-data classify --llm` / `--propose-joins`, which want
   `ANTHROPIC_API_KEY`); nothing in this repository has ever run a classification wave that way.
   `warhub-data classify --propose-supersessions` is the lineage counterpart and needs **no** LLM
   and no key: the manufacturer's own re-coding register asserts that two product codes are the
   same product, so nothing needs adjudicating. It classifies each asserted edge by whether it is
   safe to declare and writes `data/review/supersession-proposals.yaml`, whose `readyToPromote`
   block pastes straight into `matches.yaml`'s `supersessions:`. Like the join proposer it never
   edits `matches.yaml` itself.
4. Merging a data PR triggers **`catalog-publish.yml`**, which runs the publisher — reading
   `data/catalog` for products and `data/paints` for paints — to build the `dist/` JSON tree,
   then publishes it as a versioned Release **and** to GitHub Pages. The publish trigger only
   watches `data/catalog/**` and `data/paints/**`, so evidence-only churn never mints a release.
   Two things sit outside it on purpose: `data/paints/README.md`, because prose for maintainers
   reaches no consumer, and the paint liveness ledger at `data/state/paint-liveness.yaml`,
   because per-run operational state would otherwise cut a Release every week on its own.

`catalog-acquire.yml` uses a **sticky PR** (one persistent branch, updated in place rather than
opened fresh every run): cursor progress from a given run only actually lands in `data/` — and so
only becomes visible to the *next* run — once that sticky PR is merged. An unmerged sticky PR
means the next scheduled run still starts from the previously-merged state, not from what's
sitting in the open PR. The same is true of a local classification wave for a different reason:
its output is an ordinary working-tree change, and the next `--emit-queue` reads the tree it is
run against.

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

Product data is scraped from manufacturer and retailer sites and resolved through the evidence
ledger (`data/evidence/` → `data/catalog/`). Paint data derives from
[Arcturus5404/miniature-paints](https://github.com/Arcturus5404/miniature-paints) (MIT) plus
public swatch sources. For source-data terms see `data/paints/LICENSE` (paints) and
`data/evidence/products/legacy-catalog/LICENSE` (the legacy product catalog that seeded the
evidence ledger) — both MIT, matching this repo's [LICENSE](LICENSE); tooling is under this
repo's [LICENSE](LICENSE).
