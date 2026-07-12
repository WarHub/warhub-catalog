# Current pipeline analysis (2026-07-12)

State of the data acquisition and publishing pipeline as of commit `c0e1f68` (main,
2026-07-12), immediately after the four-plan storage-model rework merged. For the storage
model's design rationale see the specs under `docs/superpowers/specs/` (catalog storage
model design + availability, paint-adoption, publisher-schema, and hardening addenda);
this doc records the as-built acquisition behavior those specs do not cover.

## Headline numbers

- **Products:** 12,799 across 9 manufacturers / 47 game systems / ~250 faction files.
  5,853 (45.7%) have `ean:`; a further 115 carry `eanSource: not_found` (searched, none
  found). Top EAN providers: goblingaming.co.uk 3,446; flipsidegaming.com 656;
  steamforged.com 387. Coverage is uneven: GW 72%, Wyrd 88%, Para Bellum 89%, Corvus
  Belli 84% — vs **Warlord Games 20% of 5,854 products**, which drags the total down.
- **Paints:** 7,357 across 20 brand files. EANs: **1,268 — Vallejo only**, all *computed*
  (EAN-13 = `"8429551"` + 5-digit code + check digit, `Enrichment/EanComputer.cs`).
  Every other brand: zero.

## Product tool: end-to-end flow

`tools/WarHub.ProductCatalog.Tool`, entry `ProductCatalogApp.cs:22` (System.CommandLine;
root command + `migrate`). Phases: seed load → live scrape per manufacturer → enrich →
overrides → EAN enrichment → reconcile (append-only) → liveness ledger → YAML write.

```
seed YAML ─┐
           ├─► List<RawProduct> ─► ProductEnricher.Enrich ─► sample ─► OverrideApplier
scrapers ──┘   (Algolia/Shopify/WooCommerce/GraphQL/WP-REST/Playwright)
                                                              │
                                                        EAN enrichment
                                              (existing YAML → Shopify retailers
                                               → UPCitemdb)  sets Ean/EanSource
                                                              │
        existing faction.yaml ─► CatalogReconciler.Reconcile ◄┘
                                  (name-key match, URL/alias rename,
                                   append-only merge, firstSeen stamp)
                                                              │
                         LivenessUpdater.Apply (miss-streak, auto-flag) ─► _liveness.yaml
                                                              │
                                  YamlCatalogWriter ─► manufacturers/…/{faction}.yaml
                                                   └─► manifest.yaml
```

### Per-manufacturer sources

All JSON/API-based; no live HTML scraping in the active path. Each source is its own
class in `Scraping/` with no common contract.

| Manufacturer | Source class | Mechanism |
|---|---|---|
| Games Workshop | `AlgoliaProductSource.cs:53` | GW Algolia index `prod-lazarus-product-en-gb`, hard-coded app id + search key (`:18-20`), filter `productType:miniatureKit`. **No EAN in hits.** |
| Para Bellum | `WooCommerceProductSource.cs:52` | WooCommerce Store API at eshop.para-bellum.com |
| Warlord / Wyrd / Steamforged | `ShopifyProductSource.cs:62` | Shopify bulk `/products.json` (`:74`); game-system/faction via inline delegates in `ProductCatalogApp` (`:876`, `:963`, `:1151`) |
| Mantic | `WooCommerceProductSource` + `IsManticGameSystem` URL/name heuristic (`ProductCatalogApp.cs:1066`) | manticgames.com WooCommerce |
| Corvus Belli | `CorvusBelliProductSource.cs:78` | AWS AppSync GraphQL, hard-coded api-key (`:16-19`) |
| Atomic Mass Games | `AtomicMassGamesProductSource.cs:48` | WordPress REST `character?game_line={id}`, hard-coded taxonomy IDs (`:20-27`); SKU/image regex-extracted from rendered HTML (`:150-197`) |
| CMON | `CmonProductSource.cs:83` | WordPress REST via Playwright headless Chromium to pass Cloudflare (`:47-81`); SKUs backfilled from Athena Games Shopify (`:373`) |
| Privateer Press | stub (`ProductCatalogApp.cs:1140`) | returns empty (IP moved to Steamforged) |

`GamesWorkshopScraper.cs` is a retired HTML/JSON-LD scraper (could read `gtin13`,
`:157`) superseded by the barcode-less Algolia source.

### EAN acquisition chain (why coverage sits at 46%)

Priority order, writing `Product.Ean` + `Product.EanSource` (`Product.cs:26-29`):

1. **Native scrape barcodes** — only Shopify sources read `variants[].barcode` at scrape
   time (`ShopifyProductSource.cs:132`), and Shopify's bulk feed no longer carries
   barcodes, so this yields ~nothing (Warlord's own store: 0%, noted at
   `ShopifyEanSource.cs:24`). GW's live Algolia source has no EAN field.
2. **Retailer Shopify cross-reference** (`ShopifyEanSource.cs`) — the workhorse. Curated
   store list (`DefaultStores :21`, `CollectionStores :42` with hand-annotated expected
   counts); fetches per-product detail `/products/{handle}.json` (list endpoints omit
   barcodes, `:8-10`); matches by normalized SKU (`NormalizeSku :574` — GW numeric,
   `COR*`, `CMN*`, `-EN` stripping) or normalized title (`NormalizeTitle :646`, CMON).
   Valid barcode = 12–13 digits (`IsValidBarcode :516`).
3. **UPCitemdb trial API** (`EanEnricher.cs`, `UpcItemDbClient.cs`) — last resort. Search
   `"{manufacturer} {name}"`; GW filtered to GS1 prefix `5011921` (`:18`); ≥50% token
   match required (`:162`). 100 calls/day trial, 16 s spacing, budget-capped
   (`--ean-budget`, default 80 in CI). Misses stamped `EanSource = "not_found"` so they
   are never re-queried.

Structural ceiling: coverage stops where (a) the curated retailers don't stock the
product, (b) SKU/title normalization fails to match, or (c) the manufacturer exposes no
code to match on. Nothing harvests manufacturers' own per-product pages.

### Metadata heuristics (gameSystem / faction / codes / quantity)

Substring/keyword heuristics, scattered and fragile:

- **gameSystem** — inline switch on Shopify product_type/vendor/tags
  (`ProductCatalogApp.cs:876`, `:949`, `:1151`); Mantic URL/name substring (`:1066`);
  Corvus Belli name→API-id map (`:1103`); AMG hard-coded WordPress taxonomy IDs
  (`AtomicMassGamesProductSource.cs:20-27`).
- **faction** — hard-coded name arrays matched by `Contains`; GW parses Algolia
  hierarchy `lvl3/2/1` with a unit-type skip-list (`AlgoliaProductSource.cs:299-319`);
  Para Bellum / Corvus Belli by category/SEO substring (`WooCommerceProductSource.cs:177`,
  `CorvusBelliProductSource.cs:181`); CMON parses `"Faction: Name"` title prefix
  (`CmonProductSource.cs:239`). Faction lists duplicated between
  `ManufacturerRegistry.cs:12-247` and extractors — drift risk.
- **product code / SKU** — GW SKU parsed from Algolia objectID `P-{n}-{gwSku}` by last
  dash-segment (`AlgoliaProductSource.cs:284`); AMG regex on
  `<span class="product-code">` (`AtomicMassGamesProductSource.cs:187`); CMON from ACF
  fields or retailer name-match backfill (`:373`).
- **quantity/contents** — `ProductUnit` exists but **no scraper populates `Contents`**;
  only seed data/overrides supply it.
- **category/packaging** — keyword-on-name plus a price heuristic
  (`priceGbp >= 100 ⇒ box_set`, `ProductEnricher.cs:71-74`), collapsed by
  `CategoryClassifier`.

### Storage model (shared `WarHub.CatalogStore`)

Append-only/backfill-only archive; see specs for rationale. Key mechanics:

- **Identity** = `NameNormalizer.Normalize(Name)` within one faction file
  (`ProductRecordAdapter.cs:10`) — name-based; faction misclassification therefore
  changes identity (the known cross-faction-move gap, deferred in the hardening
  addendum). Rename fallbacks: URL, then alias overrides.
- **Reconcile** (`CatalogReconciler.cs:14`): skip retracted → key match/merge → URL
  rename → alias rename → insert with `firstSeen`. Merge is update-present/keep-on-empty;
  identity, `firstSeen`, `category` immutable; lifecycle sticky.
- **Liveness** (`LivenessUpdater.cs:21`, `_liveness.yaml`): miss-streak per record;
  auto-flag `suspected-discontinued` at streak 3. Guards: ledger only mutated on
  authoritative runs (no `--sample`/`--skip-scrape`); orphan GC only on full healthy
  runs; implausible-drop guard (scraped < 50% of last-good count ⇒ source degraded,
  `LedgerMaintenance.cs:12`).

### Error surfacing: fail-soft everywhere

- Per-source fetch exceptions caught in the manufacturer loop
  (`ProductCatalogApp.cs:372-376`); source marked degraded, warning only under
  `--verbose`, run continues, exit code 0.
- Inside scrapers, HTTP errors `break` pagination and return partial results silently
  (`ShopifyProductSource.cs:107`, `WooCommerceProductSource.cs:97`,
  `AtomicMassGamesProductSource.cs:107`, `AlgoliaProductSource.cs:155`,
  `CorvusBelliProductSource.cs:142`, CMON `:149`).
- `ShopifyEanSource` swallows per-store/per-page exceptions (`:235, 365, 494`);
  overrides parse failures swallowed (`OverrideApplier.cs:36-39`); per-file deserialize
  errors skipped (`ExistingCatalogLoader.cs:60-64`).
- Net effect: a broken source degrades coverage instead of failing the run; the only
  visibility is `--verbose` output and the README coverage table drifting down. The
  full per-scraper health signal was explicitly deferred ("Plan 5") in
  `docs/superpowers/specs/2026-07-08-hardening-followups-addendum.md`.

## Paint tool

`tools/WarHub.PaintCatalog.Tool`, entry `PaintCatalogApp.cs`. Sources:

- Primary: `Arcturus5404/miniature-paints` (MIT) markdown, parsed by
  `Parsing/MarkdownPaintParser.cs`, brands mapped via `Configuration/BrandRegistry.cs`.
- `Scraping/ScalematesPaintSource.cs` — scalemates.com for brands not in Arcturus
  (currently Two Thin Coats); 1500 ms throttle.
- `Scraping/ShopifyPaintSource.cs` — Shopify enrichment (registry: Army Painter
  `thearmypainter.com`, collections warpaints-fanatic/speedpaint): swatch `imageUrl`,
  `barcode` (EAN), `sku`, matched by paint name.

Enrichment order: `VolumeEnricher` (brand/set lookup, `Configuration/VolumeTable.cs`) →
`PaintTypeClassifier`/`FinishClassifier` → `EanComputer.ComputeVallejoEan` (Vallejo only)
→ `OverrideApplier`. Reconciliation/liveness identical to products via CatalogStore
(paint identity key = `set|name|productCode|hex`).

Equivalences: `ColorScience/{CieLab,DeltaE}.cs` (full CIEDE2000, Sharma 2005),
`Equivalence/EquivalenceFinder.cs` — cross-brand matches ≤ ΔE 10, best-per-brand, top 5;
tiers close (≤5) / substitute (≤10) → `data/paints/equivalences.yaml`.

## Data layout and publisher

- **Products:** `data/products/manufacturers/{mfg}/{gameSystem}/{faction}.yaml` — header
  + `products:` list. Per-product fields: `name, category, packaging, status,
  availability, firstSeen, ean('quoted'), eanSource, sku, productCode,
  priceGbp|priceUsd|priceEur, url, imageUrl, description`.
- **Paints:** `data/paints/brands/{brand}.yaml` — `name, category, status, availability,
  firstSeen, productCode, ean, details:{set, r, g, b, hex, volumeMl, container, type,
  finish}`. (Note: `data/paints/README.md` still shows the older flat shape.)
- **Support:** `data/*/manifest.yaml`, `data/*/overrides.yaml` (both currently `{}`),
  `data/*/_liveness.yaml`, `data/paints/equivalences.yaml` (7,005 entries).
- **Seed/scripts:** `data/products/seed/` — 7 hand-authored files with `contents:` unit
  breakdowns (the only source of quantity data). `data/products/scripts/` — legacy
  PowerShell publishing path (`Build-Release.ps1`, `Build-AppArtifact.ps1` which emits
  EAN-only `warhub-products.json` for the WarHub app, `Generate-Summary.ps1` which
  computes the README coverage table — the origin of the "46%" figure).
- **Publisher:** `tools/WarHub.Catalog.Publish` — YAML → `dist/` JSON: `products.json` +
  `products/by-system/*.json`, `paints.json` + `paints/by-brand/*.json` (equivalents
  folded bidirectionally, stable `brand-slug/paint-slug` ids), `manifest.json` (files,
  sha256), `schema/*.json`; every document schema-validated before write; deterministic
  ordering for reproducible hashes.
- **CI:** `product-catalog-update.yml` (weekly scrape PR), `product-catalog-enrich.yml`
  (daily EAN matrix over 12 retailer Shopify stores + UPCitemdb budget 80), 
  `paint-catalog-update.yml` (weekly), `catalog-publish.yml` (on data merge → Release +
  Pages), `ci.yml` (tests).
