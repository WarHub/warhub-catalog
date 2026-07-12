# Source probe: manufacturer sites (2026-07-12)

Live-endpoint probe of the nine catalog manufacturers, run 2026-07-12 via curl (plus
browser-session checks where curl was blocked). "products.json barcode" means the Shopify
`variants[].barcode` field in the public bulk JSON feed. "JSON-LD gtin" means schema.org
Product markup embedded in product detail page HTML.

## Cross-cutting finding: Shopify barcode placement

**Shopify's bulk `/products.json` feed no longer emits `barcode` at all** — the variant
objects carry sku/price/etc. only, even when the merchant filled the barcode field. This
held on every Shopify store probed (Steamforged, store.warlordgames.com, the Wyrd store,
store.asmodee.com, and retailers). The EAN is still retrievable per product:

- `/products/<handle>.js` — per-handle JSON endpoint, `variants[].barcode` populated;
- product detail page HTML — `gtin13` in JSON-LD (theme-dependent) or `"barcode":"…"`
  in the embedded Shopify product JSON.

Consequence: bulk feeds enumerate handles; EAN harvesting requires one request per product.

## Per-site findings

### Games Workshop — warhammer.com

- **Platform:** custom headless Next.js (v14.2.35), Algolia-backed catalog. Document
  requests protected by AWS WAF (`awswaf.com` challenge); curl gets an empty 202
  challenge. No Shopify/Woo endpoints (`/products.json` → 404).
- **Catalog API:** Algolia — appId `m5ziqznq2h`, index `prod-lazarus-product-en-gb`
  (per-locale indexes), endpoint `https://m5ziqznq2h-dsn.algolia.net/1/indexes/*/queries`.
  Internal proxy `https://www.warhammer.com/api/recommend/filters?indexname=…&facetname=…`
  returns 200. The Algolia search API key is not usably exposed in `__NEXT_DATA__` or the
  JS chunks (two 32-hex candidates in `_app.js` both returned 403) — key appears
  request-scoped/secured; Algolia calls succeed from a real browser session only.
- **Barcode/GTIN:** **none.** Algolia hit object fields: `id, sku, name, slug, price,
  ctPrice, images, formatVariants, colourVariants, GameSystemsRoot, objectID, …` —
  `sku` is a GW internal item code (e.g. `P-251417-60010199080`); no barcode/ean/gtin/upc
  field. Product pages contain zero `<script type="application/ld+json">` blocks.
  13-digit numbers in page data are GW image/item asset codes, not EANs.
- **Product count:** not enumerated (sitemap at `/sitemap.xml`; robots.txt allows
  `/app/resources/catalog/product/*`).
- **Protection:** AWS WAF.

### Atomic Mass Games — atomicmassgames.com / store.asmodee.com

- **Platform:** atomicmassgames.com is a WordPress marketing site (curl → 403,
  Akamai-style block; browser OK) with **no store** — its "Store" link points to
  `store.asmodee.com/collections/atomic-mass` (Asmodee's Shopify).
- **Working endpoints:** `https://store.asmodee.com/products.json?limit=250` → 200
  (~947 KB/page). Sitemaps `sitemap_products_1.xml` + `sitemap_products_2.xml`.
- **Barcode/GTIN:** feed `variants[].barcode` = null across 250 sampled. Product detail
  page HTML exposes it — e.g. `store.asmodee.com/products/darwins-journey-1` contains
  `"barcode":"793567054998"` (theme product JSON + JSON-LD Product).
- **Product count:** ~2,748 on the whole Asmodee store (sitemap1 2,484 + sitemap2 264);
  the `atomic-mass` collection is a subset (`/collections/atomic-mass/products.json`
  returned 0 — handle differs or gated).
- **Protection:** AMG's own domain blocks curl; store.asmodee.com is open.

### CMON — cmon.com

- **Platform:** WordPress (Site Kit) behind Cloudflare (curl → 403 on product pages;
  browser renders). **Not an e-commerce site** — sells via distributors. No WooCommerce
  (`/wp-json/wc/store/products` → 404 `rest_no_route`).
- **Catalog API:** WordPress REST namespaces `oembed, jetpack, mailchimp, redirection,
  contact-form-7` — no store API. Sitemap index `/wp-sitemap.xml`.
- **Barcode/GTIN:** **none.** Product pages (`/products/<slug>/`) are marketing pages:
  no Product JSON-LD, no SKU/UPC/EAN, no add-to-cart — only game metadata (players,
  playing time, age, designer).
- **Product count:** `wp-sitemap-posts-products-1.xml` = 320 product URLs;
  `products-line-1` = 24 product lines.
- **Protection:** Cloudflare 403 to non-browser clients.

### Corvus Belli — store.corvusbelli.com

- **Platform:** custom Angular SPA on S3/CloudFront (`store-v3/browser/en/…`), backed by
  AWS AppSync GraphQL — endpoint
  `https://45k4ek2gqjazfd327btrd4drk4.appsync-api.eu-west-1.amazonaws.com/graphql`
  (an earlier session also showed `aiscbwsb6vb3xbysk57tnk3miy…`), auth via `x-api-key`
  (a `da2-…` key embedded in the JS bundle).
- **API shape:** introspection succeeds but the schema is a generic gateway — only
  `Query.ping` and `Mutation.send`; the catalog is fetched by posting a command payload
  to `send`. No introspectable Product type. Product-list GraphQL fires only on hard
  page load (SPA nav serves cached data).
- **Barcode/GTIN:** **not exposed.** Product pages show an internal reference only, e.g.
  `store.corvusbelli.com/en/infinity/wargame/miniatures/combined-army-overdron-batroids-tag-pack`
  shows `REF: 281649`. The string `ean` does not appear in the main JS bundle.
- **Product count:** not enumerated — no public products.json; store `/sitemap.xml` →
  404 (S3 NoSuchKey).
- **Protection:** none beyond the SPA; API key is public in the bundle.

### Mantic Games — manticgames.com

- **Platform:** WooCommerce on WordPress behind Cloudflare (LiteSpeed origin). Store API open.
- **Working endpoints:** `https://www.manticgames.com/wp-json/wc/store/products?per_page=…`
  → 200 with `X-WP-Total: 2789`. Product sitemaps: `product-sitemap.xml` (174) +
  `product-sitemap2.xml` (485) + `product-sitemap3.xml` (697).
- **Barcode/GTIN:** Store API returns `sku` (e.g. `KSEWG401`) but no barcode field.
  **Product pages emit JSON-LD Product with `gtin`** — on `/epic-warpath/gcps/maul-battleship/`:
  `"sku":"KSEWG401","gtin":"5060924988049"`.
- **Product count:** ~2,789 (Store API `X-WP-Total`).
- **Protection:** Cloudflare present; API and pages accessible to curl with a UA.

### Para Bellum — para-bellum.com / eshop.para-bellum.com

- **Platform:** marketing site is WordPress (Cloudflare, no store API); the store is
  `eshop.para-bellum.com` = WooCommerce (Apache origin), Store API open.
- **Working endpoints:** `https://eshop.para-bellum.com/wp-json/wc/store/products?per_page=…`
  → 200, `X-WP-Total: 384`. Prices in USD. `para-bellum.com/sitemap_index.xml` covers
  marketing content only; no product sitemap found on the eshop.
- **Barcode/GTIN:** Store API returns `sku` (e.g. `PBW8072`). Product page JSON-LD (Yoast)
  is a Product with `sku` but **no gtin/barcode** — e.g.
  `/product/sorcerer-kings-army-support-pack-w6/` → `"@type":"Product","sku":"PBW8072"`.
- **Product count:** 384.
- **Protection:** none on the eshop Store API.

### Steamforged Games — steamforged.com

- **Platform:** Shopify.
- **Working endpoints:** `https://steamforged.com/products.json?limit=250` → 200.
  Product sitemap `sitemap_products_1.xml` → 1,062 product `<loc>`s.
- **Barcode/GTIN:** feed `variants[].barcode` = null (0/354 variants across 250 products;
  `sku` populated, e.g. `SFIK-SKR399`). **Product pages carry JSON-LD `gtin13`** —
  `/products/warmachine-southern-kriels-kithguard-journeyman-ramhead`:
  `"gtin13": 5061060705453`.
- **Product count:** ~1,062.
- **Protection:** none.

### Warlord Games — warlordgames.com / store.warlordgames.com

- **Platform:** two systems. `www.warlordgames.com` is WooCommerce/WordPress but its Store
  API exposes essentially nothing (`X-WP-Total: 1`, a membership item) — it proxies to the
  shop. The actual catalog is `store.warlordgames.com` = Shopify.
- **Working endpoints:** `https://store.warlordgames.com/products.json?limit=250&page=N`
  → 200. Three product sitemaps `sitemap_products_1..3.xml`.
- **Barcode/GTIN:** feed `variants[].barcode` = null (0 across sampled pages 1 and 4; `sku`
  present). **Product detail JSON-LD has `gtin13`** — `/products/cruel-seas-starter-set`:
  `"gtin13": 5060393709671`.
- **Product count:** ~5,843 on the Shopify store (sitemaps 2,501 + 2,499 + 843).
- **Protection:** none. (Main WP site returns Yoast 404 for bad slugs, otherwise open.)

### Wyrd Games — wyrd-games.net / giveusyourmoneypleasethankyou-wyrd.com

- **Platform:** `www.wyrd-games.net` = Squarespace (marketing/community). The store is
  `giveusyourmoneypleasethankyou-wyrd.com` (their literal store domain) = Shopify.
- **Working endpoints:**
  `https://giveusyourmoneypleasethankyou-wyrd.com/products.json?limit=250` → 200.
  Product sitemap `sitemap_products_1.xml` ≈ 707 `<loc>`s.
- **Barcode/GTIN:** feed `variants[].barcode` = null (e.g. `miss-feasance`,
  sku `WYR21331 LE`, barcode None). **Product detail page HTML exposes barcode** —
  `/products/miss-feasance` contains `"barcode":"812152031524"` (embedded Shopify product
  JSON; no JSON-LD Product block on this theme).
- **Product count:** ~707.
- **Protection:** none.

## Summary table

| Manufacturer | Platform | Bulk feed | EAN on own site | Where | ~Count |
|---|---|---|---|---|---|
| Games Workshop | Next.js + Algolia (AWS WAF) | Algolia (browser-keyed) | **No** | — | n/e |
| Atomic Mass Games | Shopify (store.asmodee.com) | products.json | Yes | per-page embedded JSON (`barcode`) | 2,748 (whole Asmodee store) |
| CMON | WordPress (Cloudflare), no store | WP REST (no store API) | **No** | — | 320 |
| Corvus Belli | Angular SPA + AppSync GraphQL | non-introspectable gateway | **No** | — (REF codes only) | n/e |
| Mantic | WooCommerce | wc/store/products | Yes | per-page JSON-LD `gtin` | 2,789 |
| Para Bellum | WooCommerce (eshop.) | wc/store/products | **No** | — (sku only) | 384 |
| Steamforged | Shopify | products.json | Yes | per-page JSON-LD `gtin13` | 1,062 |
| Warlord Games | Shopify (store.) | products.json | Yes | per-page JSON-LD `gtin13` | 5,843 |
| Wyrd | Shopify | products.json | Yes | per-page embedded JSON (`barcode`) | 707 |
