# Paint manufacturer harvest — design and site probes

Date: 2026-07-23. Goal: systematically fill paint ranges beyond the Arcturus5404 base set with
manufacturer-authoritative data, starting with the highest paint-count manufacturers
(tracking survey: issue #51). Field priority: **manufacturer/series/range/name** →
**color code/hex/image** → **sku** → **ean (when found)** → best-effort metadata (volume ml, price).

## Architecture

Follows the proven `mfr-gw-trade` → `gen_paint_barcodes.py` → `--barcodes` pattern: the Python
acquisition tool owns all fetching (PoliteClient: robots, rps, retries, `WARHUB_HTTP_CACHE_DIR`
cache, contract gates, liveness), a bridge script projects paint evidence into structured files
under `data/paints/`, and the C# `WarHub.PaintCatalog.Tool` stays the **single writer** of
`data/paints/brands/*.yaml` (reconciler, identity, liveness, equivalences untouched).

```
data/catalog/sources/mfr-<brand>.yaml        (descriptors, kind: manufacturer)
  └─ acquire strategies: shopify-paints | wp-rest-paints | woo-paints
       └─ data/evidence/products/mfr-<brand>/observations.jsonl   (hints.category=paint,
            hints.range/paintName/volumeMl/grams..., sku, ean, imageUrl, price)
            └─ tools/acquisition/scripts/gen_paint_harvest.py
                 └─ data/paints/harvest/<brand-slug>.yaml    (per-brand harvest projection,
                      entries pre-matched against the existing catalog identity)
                      └─ C# PaintCatalog.Tool --harvest data/paints/harvest
                           ├─ existing paints: fill BLANK non-identity fields only
                           │    (ean, imageUrl, volumeMl — same rule as BarcodeEnricher;
                           │    never touches set|name|productCode|hex identity fields)
                           └─ unmatched entries: appended as NEW paints (full identity at
                                birth; hex may be absent → identity hex empty until enriched
                                via overrides)
```

Fuzzy matching happens **once, in Python** (bridge), like `gen_paint_barcodes.py`; the C# side
does exact identity lookups only.

## Site probes (2026-07-23)

| Manufacturer | Platform | Endpoint | Fields confirmed | Notes |
|---|---|---|---|---|
| The Army Painter (704 base) | Shopify, open | `thearmypainter.com/products.json` (898 products) + `/products/{handle}.js` | title `Range: Name`, sku (`WP####P`/`AW####P`/`CP####S`), price, grams (26–31 g singles), images keyed by SKU; **barcode in `.js` detail** | types: Paint 487, Spray 33, `""` 274 (some ranges untyped) |
| Monument Hobbies | Shopify, open | `monumenthobbies.com/products.json` (333) + `.js` | type `Paint Singles` (179), sku `MPA-###`, **barcode confirmed** (`655368409059`), grams | multi-vendor store → filter `vendor: Monument Hobbies` |
| Turbo Dork | Shopify, open | `turbodork.com/products.json` (389) + `.js` | product_type IS the range (TurboShift 33 / Metallic 40 / ZeniShift 7), bare-name titles, sku `TDK######_#` | `Retail` type (275) = mixed/legacy, bridge filters |
| Vallejo (1,268 base — top priority) | WordPress, WAF | `acrylicosvallejo.com/en/wp-json/wp/v2/product` (1,991 items, X-WP-Total; ~20 pages @ per_page=100) + `product_cat` + `media` | title, slug ends in code (`dead-white-72001` → `72.001`), categories = ranges, featured image | **403 for non-browser UA** → politeness `uaProfile: browser`; robots.txt allows all paths but `Crawl-delay: 9000` (anti-bot posture) → API-only access, ≤ ~60 requests/run, `ignoreRobots: true` documented below |
| AK Interactive (892+432 base) | WooCommerce Store API, open | `ak-interactive.com/wp-json/wc/store/products?per_page=100&lang=en` | sku (`AK11###`/`ABT###`/`RC###`), EN names (ALL-CAPS), prices (minor units), images, categories | reuse woo pattern with paint-category scope |
| Reaper (438 base) | custom | `reapermini.com/paints` → range pages | swatches on range pages | follow-up source |
| Scale75 / Green Stuff World | PrestaShop | HTML | — | follow-up strategy |
| paintpad.app | static HTML | `/paints/<range>` | `data-paint-id`, `data-type`, name, **hex/gradient swatches** | candidate hex-enrichment source (aggregator; keep separate from mfr-authoritative fields) |
| brochure PDFs (Vallejo CC-series etc.) | PDF | see issue #51 | codes+names per range | reference/cross-check, not parsed initially |

## Operational model (owner steer, 2026-07-23)

- **One-off snapshots, not schedules.** Paint ranges are mostly one-off and rarely updated;
  new ranges appearing is the common event. Sources are run on demand (the existing
  `catalog-acquire.yml` `workflow_dispatch` `sources` input, or locally) when a range drops —
  none of the paint sources joins the nightly/weekly roster. The committed
  `observations.jsonl` + `data/paints/harvest/*.yaml` are the durable, referencable snapshots;
  `paint-catalog-update.yml` only re-merges those committed files (no network).
- **Source roles.** Shopify storefronts are never catalog-providers — at most extra-metadata
  sources. The bridge assigns each source a role:
  - `catalog` — may propose NEW paints and enrich (v1: `mfr-vallejo` only; its WP `product`
    CPT is a pure catalog, not a shop).
  - `metadata` — enrich existing catalog identities only (sku/ean/image/volume/price);
    unmatched store products are listed in the bridge report as candidates, never added
    (v1: `mfr-armypainter`, `mfr-monument`, `mfr-turbodork`, and `mfr-ak-interactive` until
    its harvest quality is reviewed — flipping a role is a one-line change in
    `gen_paint_harvest.py`).

## Policy notes

- **Vallejo robots**: `User-agent: * / Allow: /` but `Crawl-delay: 9000` (2.5 h/request) and the
  WAF 403s non-browser UAs. Page *crawling* is therefore off the table. The WP REST API
  enumeration is a bounded ~60-request/run footprint at rps ≤ 0.2, weekly — materially politer
  than any crawl the robots file contemplates. Descriptor sets `ignoreRobots: true` (existing
  precedent: `mfr-gw-algolia`) plus `uaProfile: browser`, with this rationale inline.
- **Hex**: manufacturers generally do not publish hex. Priority stays: keep Arcturus hex,
  harvest fills name/code/sku/ean/image/ml/price, new paints may land hex-less (identity has
  empty hex slot; `overrides.yaml` or a later swatch-extraction/paintpad enrichment fills them).
- Shopify variant `grams` ≈ gross weight; volumeMl derived per-brand in the bridge (e.g. TAP
  singles 26–31 g → 18 ml; Monument 30 g → 22 ml) — encoded as bridge rules, not guessed in C#.

## Rollout order (by base paint count)

1. `mfr-vallejo` (wp-rest-paints) — 1,268
2. `mfr-ak-interactive` (woo-paints) — 892 + 432
3. `mfr-armypainter` (shopify-paints) — 704
4. `mfr-monument` (shopify-paints) — 131
5. `mfr-turbodork` (shopify-paints) — 40
6. Follow-ups: Mr Hobby (static HTML, 668), Reaper (544), Scale75 (358, PrestaShop),
   Green Stuff World (220, PrestaShop), Kimera, TTCombat/Colour Forge/Two Thin Coats
   (Shopify — descriptor-only once shopify-paints exists), Wayback/CDX for dead catalogs
   (Testors) via existing `cdx-archive` strategy.

CI: no scheduled harvesting (one-off model above) — paint sources run on demand via
`catalog-acquire.yml`'s `workflow_dispatch` `sources` input. `gen_paint_harvest.py` runs in
`paint-catalog-update.yml` before the C# tool (alongside `gen_paint_barcodes.py`, committed
inputs only), and the tool gains `--harvest data/paints/harvest`.

## First snapshot results (2026-07-23 runs)

| Source | Observed | Enriched (exact identity) | EANs found | Additions | Candidates |
|---|---:|---:|---:|---:|---:|
| mfr-vallejo | 1,194 | 926 (images) | — (computed from codes) | 202 (TMM 75, Diorama FX 43, Pigment FX 25, Auxiliaries 50, gap-fills 9) | 51 (code-less legacy slugs) |
| mfr-ak-interactive | 1,142 | 473 (images, by AK code) | — | 0 (metadata role) | 669 (sets/books + Quick Gen + 3rd-gen gaps) |
| mfr-armypainter | 794 | 409 (EAN+image) | 725 harvested | 0 (metadata role) | 128 (new Fanatic waves, Air Triads, Masterclass) |
| mfr-monument | 197 | 126 of 131 (EAN+image) | 195 harvested | 0 (metadata role) | 27 (1-Step + AMP Colors ranges) |
| mfr-turbodork | (retry pending) | | | | |

Harvest-review notes: Speedpaint **Marker** SKUs (`SM____P`) share paint names with Speedpaint
droppers — excluded from singles matching (a marker EAN on a paint record would be a false
barcode); TAP name-matching requires a recognized range prefix, cross-set name matches are
never trusted. Monument's "Expert Acrylics" are vendored `Tri Art` on the store (rebrand) —
out of scope until that range exists in the catalog.

## Wave 2 (2026-07-24): AK promotion + next probes

- **AK promoted to catalog-role** (owner-approved): 139 additions via the name-suffix set
  mapping (`"NAME – SUBSERIES"`): Quick Gen 77 (18 ml), The-Inks 28 (`AK16xxx` — distinct
  from `AK112xx` 3rd-gen inks sharing the "– INK" suffix), Acrylic Wash 18, Color Punch 10,
  3rd-gen gap singles 6. Bridge additions are now RATCHETED (a prior addition never flips to
  enrich-only just because a merge landed it — that gating caused a decay loop where the next
  merge dropped harvest-born paints from the fresh set).
- **AK colours**: no usable vector chart found — the 236-colour briefcase chart is a raster
  JPG grid (`wp-content/uploads/2020/12/BRIEFCASE_235COLORS-CHART.jpg`, perfect 20-col grid,
  sequential codes; covers AK11001-236 which Arcturus already colours → cross-check value).
  A `grid-image` extractor (config: grid geometry + code sequence, same contact-sheet rails)
  is the vehicle; Quick Gen chart material not yet located (the AK17000GUIDE product is a PDF
  sold in-store). AK additions stay colour-less until then — the auto-alias healing makes
  that safe.
- **Mr Hobby probe**: mr-hobby.com rebuilt (Laravel; not Inertia). `/en/products/category/N`
  paginated listings (20/page) → `/en/products/detail/<id>` pages; codes/colours live on
  detail pages only → budgeted-detail-queue strategy (same shape as shopify-paints).
- **Reaper probe**: `/paints/msp2` is marketing-only (no data). The real per-paint listing
  (and the rumored embedded swatch hex) needs deeper mapping — next wave.
