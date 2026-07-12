# Source probe: retailers and barcode databases (2026-07-12)

Live probe of retailer sites and barcode databases for machine-readable EAN/GTIN,
run 2026-07-12 via curl with a browser UA and polite pacing.

## Verified GW EAN cross-checks

Three EANs confirmed by independent sources agreeing:

| EAN | Product | GW code(s) | Seen on |
|---|---|---|---|
| `5011921194285` | Combat Patrol: Necrons | SKU 99120110077 / code 49-04 | Radaddel, Goblin Gaming, Tistaminis, Go-UPC |
| `5011921142361` | Primaris Intercessors | GW-99120101309 | Miniaturicum |
| `5011921146000` | Stormraven Gunship | 41-10 / GWS41-10 | Game Nerdz, upcitemdb, Go-UPC |

## Tier 1 — machine-readable EAN, curl-friendly

### Goblin Gaming (goblingaming.co.uk) — Shopify — best UK source

- Product page JSON-LD: `gtin13: 5011921194285` on
  `https://www.goblingaming.co.uk/products/warhammer-40k-combat-patrol-necrons-2023`
  (also inside `offers`).
- `https://www.goblingaming.co.uk/products/<handle>.js` → `variants[].barcode` populated:
  Necrons Combat Patrol returned `{sku: '99120110077', barcode: '5011921194285'}`.
  Caveat: Shopify's bulk `/products.json` no longer emits `barcode` at all (applies to
  every Shopify store) — barcode must come from per-product `.js` or JSON-LD.
- Coverage: GW plastic kits yes; books/mats often empty or `'0'`.
- Enumeration: `/products.json?limit=250&page=N` works (handles); 6 product sitemaps,
  first = 2,501 URLs (~12–15k products total). Also exposes `sitemap_agentic_discovery.xml`.
- Search: `/search/suggest.json?q=<name>` works; search by EAN returns nothing.
- No bot protection.

### Miniaturicum (miniaturicum.de) — JTL-Shop, DE

- JSON-LD Product with `"gtin13": "5011921142361"`, `"sku": "GW-99120101309"` on
  `https://www.miniaturicum.de/Primaris-Intercessors`.
- **Search by EAN works** (only site found with working reverse lookup):
  `https://www.miniaturicum.de/Ergebnisse?qs=5011921142361` 302-redirects straight to the
  product page. Name search uses the same endpoint.
- Sitemap: `/sitemap_index.xml` → 3 gz files; sitemap_0 = 25,000 locs (includes `/en/`
  duplicates and category pages). Carries GW, Infinity, Army Painter, etc.
- No bot protection.

### Radaddel (radaddel.de) — Shopware 6, DE

- Microdata: `itemprop="gtin13" content="5011921194285"` on
  `https://www.radaddel.de/necrons-combat-patrol`.
- Sitemap: `/sitemap.xml` → `/web/sitemap/shop-1/sitemap-1.xml.gz` = 12,806 URLs.
- Search (`/search?search=<EAN>`) does not match EANs; name search works.
- No bot protection.

### Game Nerdz (gamenerdz.com) — BigCommerce, US

- `var BCData = {"product_attributes":{"sku":"GWS41-10","upc":"5011921146000","mpn":"41-10",…}}`
  plus visible `<dd data-product-upc>5011921146000</dd>` on
  `https://www.gamenerdz.com/warhammer-40k-stormraven-gunship`. JSON-LD carries sku/mpn
  only (gtin null there), but the BCData `upc` field is trivially scrapable.
- **Search by UPC/EAN works:** `/search.php?search_query=5011921146000` → "1 result"
  (grid is JS-rendered, but the heading confirms the match).
- Sitemap: `/xmlsitemap.php` → 27 product pages × ~5,370 URLs ≈ 145k URLs (includes
  variants and out-of-print).
- No bot protection.

### Tistaminis (tistaminis.com) — Shopify, CA — large GW range

- `/products/combat-patrol-necrons.js` → `barcode: '5011921194285'`. Same Shopify pattern
  as Goblin Gaming (bulk products.json without barcode; per-handle `.js` populated).
- `/search/suggest.json` name search works.
- No bot protection.

## Tier 2 — accessible but no EAN exposed

| Site | Platform | Finding |
|---|---|---|
| Firestorm Games (firestormgames.co.uk) | custom cart | Microdata `itemprop="mpn"` only (e.g. `73-462` on `/combat-patrol:-aeldari`); no gtin/EAN anywhere. Sitemap `/sitemap.xml` = 43,284 URLs. Name search `/products?q=` works; EAN search returns nothing. |
| Element Games (elementgames.co.uk) | custom | No JSON-LD, no gtin/ean/itemprop on product pages. No sitemap.xml (404). Name search `/search?q=` works; EAN search → "No results found." |
| Noble Knight (nobleknight.com) | custom | JSON-LD Product with name + `mpn` only (e.g. `GAW73-50` on `/P/2148137198/Combat-Patrol---Orks`). Massive archive: 31 product sitemaps × ~24k ≈ 700k+ products (`/sitemapproducts1.xml`…`31`). Search is JS-driven; `?Term=<EAN>` inconclusive. Great for out-of-print name/MPN data, useless for EAN. |
| Miniature Market (miniaturemarket.com) | Shopware 6 | Fields present but empty: `"productEAN":""` and `gtin: ""` in page JS on `/star-wars-shatterpoint-core-set-amgswp01en.html`. Sitemap: 1 gz file, 48,949 URLs. Not useful for EAN today. |

## Tier 3 — blocked or dead for curl

| Site | Blocker | Notes |
|---|---|---|
| Wayland Games (waylandgames.co.uk) | PerimeterX/HUMAN — product pages 403 "px-captcha" | Sitemap IS open: `/sitemap.xml` → 12 sub-sitemaps (`/media/sitemap-1-1.xml` = 7,123 URLs). Needs a real browser to check JSON-LD. |
| Fantasywelt (fantasywelt.de) | Cloudflare "Just a moment…" on everything (403 incl. sitemap) | Browser required. |
| Taschengelddieb (taschengelddieb.de) | JS-required shell ("Please enable JavaScript to continue") | No sitemap; `/products.json` not Shopify. Possibly minimal shop now. |

## Barcode databases (tested with real GW EANs)

- **Go-UPC (go-upc.com)** — works, best hit rate. `https://go-upc.com/search?q=5011921146000`
  → "Games Workshop Warhammer 40K: Space Marines Stormraven Gunship"; also resolved the
  newer `5011921194285` → "Games Workshop Combat Patrol Necrons Warhammer 40,000".
  Web lookup free/no auth via curl; official API is paid.
- **upcitemdb.com** — free trial API works unauthenticated:
  `https://api.upcitemdb.com/prod/trial/lookup?upc=5011921146000` → title, brand
  "Citadel Miniatures", model `99120101088`, price history, Walmart image. But spotty:
  `5011921194285` → 0 items; `5011921142361` → junk eBay-derived title ("BITS BITZ Multi
  Listing"). Rate limit ~100/day on trial.
- **opengtindb.org** — responds only at
  `http://opengtindb.org/?ean=…&cmd=query&queryid=400000000` and returns `error=5` even
  for Coca-Cola (test queryid apparently disabled; needs a free registered queryid).
  Unverified value.
- **barcode-list.com** — page loads; `5011921194285` returned an empty results table.
- **ean-search.org** — `?q=` renders the homepage without results via curl (form/JS
  needed); API is token-based, paid. Not usable anonymously.

## Practical takeaways

1. Highest-yield pipeline: enumerate Shopify stores' handles via `/products.json`
   pagination, then hit `/products/<handle>.js` for `variants[].barcode` (Goblin Gaming
   and Tistaminis confirmed populated for GW kits); supplement with Miniaturicum/Radaddel
   structured data and Game Nerdz BCData `upc` for US/AMG products.
2. Miniaturicum is the only site found with working EAN → product reverse lookup;
   Game Nerdz search also matches UPC.
3. Wayland/Fantasywelt need a real browser session (PerimeterX / Cloudflare); everything
   else above is plain-curl scrapable with polite pacing.
