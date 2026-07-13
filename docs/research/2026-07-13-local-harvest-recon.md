# Local deep-harvest recon: Tier-3 retailers + CMON re-verify (2026-07-13)

Live probe run locally with a real Chrome browser (claude-in-chrome extension driving the
user's actual Chrome — inherently headed, vanilla, no stealth plugins) plus `curl.exe` for
quick non-walled checks. Politeness: a handful of page loads per site, several seconds
apart. Targets: the Tier-3 "blocked" list and CMON section from
`2026-07-12-source-probe-retailers-barcodedb.md` / `2026-07-12-source-probe-manufacturers.md`.

## Summary verdict table

| Target | Reachable w/ real browser | Enumeration | EAN source | Est. harvestable | Effort |
|---|---|---|---|---|---|
| Wayland Games | **Yes**, but PerimeterX "Press & Hold" challenge fires after ~6-7 rapid navigations even in a headed browser | Sitemap open: 12 sub-sitemaps × ~7,123 URLs ≈ 85k URLs (mixed category+product) | JSON-LD `Product.sku`/`.mpn` present; **no `gtin13` field on GW or Mantic products checked**. One non-GW accessory brand (e-Raptor) had a valid EAN embedded as a literal substring of `sku`/URL slug (checksum-verified) — not generalizable | Low-moderate (mostly SKU/MPN, not EAN) | Medium-high: need real browser + slow pacing + likely occasional human captcha-solve for sustained crawls |
| Fantasywelt | **Yes** — Cloudflare "Just a moment" auto-clears in ~5s in a real browser, no interaction needed | Site claims "über 70.000 Artikel"; `/sitemap.xml` errored in-browser (blocked/absent); on-site keyword search (`?sSearch=`) is broken/returns near-whole-catalog regardless of query — would need category-tree crawling instead | **Confirmed**: `<span itemprop="gtin13">` inside `<li class="product-ean">` — clean microdata, present even for plain accessories (paint pot, third-party 3D-printed base) | High (broad EAN coverage across product types, if enumeration solved) | Medium: browser needed only to clear Cloudflare once per session; scraping itself is trivial microdata; biggest blocker is a working enumeration path (search is broken, sitemap unclear) |
| CMON | **Yes** — re-verified headed (`headless=False` equivalent; this IS a real, visible Chrome window). Loaded `cmon.com/products/bug-hunt/` cleanly, no Cloudflare interstitial, no captcha | `wp-sitemap-posts-products-1.xml` = 320 product URLs (curl-open, confirmed unchanged) | **None** — confirmed again: zero `<script type="application/ld+json">`, no ean/gtin/upc/barcode string anywhere in page text or HTML. Marketing-only page (rules PDFs, component list, no SKU) | 0 (not a source of EAN data regardless of reachability) | Low reachability effort now proven, but moot — CMON is not an EAN source at any access level |
| Element Games | **Yes**, plain curl even works for these URLs (200) | No sitemap; name search (`/search?q=`) works | EAN-as-URL **partially confirmed**: `elementgames.co.uk/5060200840474` resolves to a real (delisted/"Image Coming Soon") product page whose `SKU / Product Code` field = the EAN. But this is a **legacy artifact only** — tried the same pattern with a live, in-stock EAN (`5011921194285`, Combat Patrol: Necrons) and got a genuine 404. Live GW products use name/category slugs (e.g. `/games-workshop/warhammer-40k/necrons/mbat-patrol-necrons-2`), not EAN slugs. No JSON-LD/gtin/microdata on any product page, live or legacy | Reverse-lookup only useful for a subset of old/discontinued SKUs, not a live corroboration mechanism | Low value: don't build a live EAN→product lookup on this; only useful for opportunistic corroboration of already-known legacy EANs |
| Miniature Market | **Yes**, curl already worked (no walling) | 1 sitemap gz, 48,949 URLs (unchanged from prior probe) | Re-checked two product types (board game core set, Citadel paint pot) — **still `"productEAN":""` / `gtin:""` empty in both cases**. Field exists in the page JS schema but is unpopulated store-wide, not just for one product category | 0 today | Not worth polling repeatedly; field is structurally dead, not intermittently empty |

## Detail notes

### Wayland Games

- Real browser reaches product pages fine on the first several requests:
  `https://www.waylandgames.co.uk/e-raptor-insert-cry-havoc-expansion-e-rap-5902643192782`
  rendered a full `Product` JSON-LD block (`sku: "E-RAP-5902643192782"`, `mpn: "69744"`,
  `offers`). The 13-digit tail of that SKU (`5902643192782`) is a **valid EAN-13**
  (checksum verified) — this appears to be an e-Raptor-specific distributor SKU convention
  (`<PREFIX>-<EAN>`), not a general Wayland pattern.
- Checked two accessory products explicitly for the cross-cutting question:
  - `Necromunda 25mm Bases` (GW): slug `necromunda-25mm-bases-99070599001`, JSON-LD
    `sku: "99070599001"`, `mpn: "142729"` — **no gtin13**.
  - `Warpath Team Bases - 40mm` (Mantic): slug `warpath-team-bases-40mm-mgwpm108`, JSON-LD
    `sku: "MGWPM108"`, `mpn: "143731"` — **no gtin13**.
  - `Abaddon Black: Base 12ml` (GW Citadel paint): slug
    `citadel-base-abaddon-black-12ml-99189950025`, JSON-LD `sku: "99189950025"`,
    `mpn: "155322"` — **no gtin13**.
  - Conclusion: Wayland's Magento-derived platform structurally supports `gtin13` in its
    Product JSON-LD (the schema is there) but it is **not populated for GW or Mantic
    listings** in any of the three spot-checks. Not a source of accessory EANs today.
- **Wayland DOES sell GW product** (contrary to the assumption in the task brief) — the
  homepage prominently features GW 11th-edition starter sets, so it's not excluded by
  retail restriction; it's simply not exposing EAN in markup.
- Search endpoint: the documented Magento path (`/catalogsearch/result/?q=`) 404s even in
  a real browser — the live site uses `/search?query=<q>&q=<q>` instead (discovered via
  UI interaction). Useful correction for any future harvest tooling targeting this site.
- **Important operational finding**: after roughly 6-7 rapid navigations/searches within a
  couple of minutes (well under "hammering" by normal standards), PerimeterX served a
  "Press & Hold to confirm you are a human" challenge (`Access to this page has been
  denied`, with a `Reference ID`) on a plain product-search URL, in the same real,
  logged-in-as-a-human browser session that had been working fine seconds earlier. This
  is a "press & hold" interactive challenge, not a static block — it cannot be solved by
  a scripted click alone (needs a mouse-down hold gesture, similar to Cloudflare Turnstile
  behavioral captchas) and materially raises the effort/pacing requirement for any
  sustained Wayland crawl beyond "just use a real browser." Recommend: session-scoped
  pacing well under one request per few seconds, warm-up navigation before scraping, and
  a fallback plan for occasional manual captcha-solves if a long crawl is attempted.

### Fantasywelt

- `fantasywelt.de/` served a Cloudflare "Just a moment..." interstitial to the initial
  navigation; after a 5-second wait with no interaction, the real page loaded
  (title changed to "FantasyWelt.de | Tabletopshop..."). No click/challenge required —
  this is Cloudflare's JS-only auto-clearing challenge, not a managed/interactive one.
- **EAN confirmed via microdata**, not JSON-LD: product pages embed
  `<li class="product-ean"><strong>EAN:</strong><span itemprop="gtin13">5011921196791</span></li>`.
  Verified on `https://www.fantasywelt.de/Citadel-Base-Corax-White-21-52` (a genuine GW
  Citadel Base paint pot — an accessory, not a miniature kit). EAN `5011921196791` passes
  EAN-13 checksum.
- Second accessory spot-check: `https://www.fantasywelt.de/MK3D-Miniaturbase-40mm-10`
  (a third-party 3D-printed 40mm base, vendor "AEUS GmbH") also carried a populated,
  checksum-valid EAN (`4081541883051`) in the same `itemprop="gtin13"` field — confirms
  the EAN field isn't GW-specific or kit-specific on this platform.
- **Enumeration is the actual blocker, not access.** The on-site keyword search
  (`?sSearch=<term>`, submitted either via UI Enter-key or direct URL) returned
  essentially the same ~10,300-item "whole catalog" result set regardless of query
  ("warhammer combat patrol" and "Mantic Base" produced near-identical result lists) —
  the search index/relevance appears broken or the endpoint isn't actually filtering.
  `/sitemap.xml` also errored when navigated directly in-browser. A real harvest would
  need to walk the category tree (`Geländebau, Bases, Magnete & Bitz > Bases > ...` etc.,
  visible in the left-nav/breadcrumbs) rather than relying on search or sitemap.

### CMON (headed re-verify)

- Plan 4's finding (headless Chromium hits a managed challenge, 3/3) does **not**
  reproduce with a headed, real-user Chrome session: `https://www.cmon.com/products/rising-sun/`
  correctly 404'd (stale slug — "rising-sun" isn't a current product page; CMON returns a
  branded 404, not a bot page), and a valid current slug from the sitemap,
  `https://www.cmon.com/products/bug-hunt/`, rendered fully on first load with no
  Cloudflare interstitial, no CAPTCHA, and normal page content (rules PDFs, component
  list, SRP).
- Confirms: **headed = reachable, headless = challenged**, for CMON specifically. This is
  useful operationally (a local deep-harvest campaign with a visible browser window can
  read CMON fine) but doesn't change the EAN finding — CMON is a marketing/distributor
  site with zero structured product data (`ldjson: []`, no ean/gtin/upc/barcode string
  anywhere on the page). Not a source of barcodes at any access level.

### Element Games

- `elementgames.co.uk/5060200840474` (the archived EAN-as-URL pattern) returned HTTP 200
  even via plain curl, and the browser confirmed it's a genuine (if sparse) product page:
  title "5060200840474 | Element Games", body shows `SKU / Product Code: 5060200840474`,
  `Image Coming Soon`, "currently unavailable - it is likely that distribution has
  ceased." This EAN did not resolve in Go-UPC either, consistent with a long-delisted SKU.
- Tested whether this is a *general* reverse-lookup mechanism using a known-good, currently
  in-stock EAN (`5011921194285`, Combat Patrol: Necrons, cross-verified in the prior probe
  doc against Radaddel/Goblin Gaming/Tistaminis/Go-UPC): `elementgames.co.uk/5011921194285`
  returned a genuine Element Games branded **404 Error: Page Not Found**. Confirmed via
  site search that the live product lives at
  `/games-workshop/warhammer-40k/necrons/mbat-patrol-necrons-2` — a name/category slug,
  not an EAN slug.
- Conclusion: EAN-as-URL is a **historical artifact of an old catalog structure** that
  still resolves for some legacy/delisted SKUs, but current live inventory does not use
  it. It's useful only for opportunistic corroboration if you already suspect a specific
  EAN was once sold by Element Games — not a general-purpose reverse lookup, and not
  worth building tooling around.

### Miniature Market

- Re-checked the original board-game product
  (`star-wars-shatterpoint-core-set-amgswp01en.html`) and a different product category
  (a Citadel paint pot, `gw-21-25.html`, found via `/search?search=<q>`, which works
  cleanly on this Shopware 6 store and returned exactly 2 relevant hits for "citadel
  abaddon black").
- Both show the same result as the original probe: `"productEAN":""` and no `gtin` in the
  embedded product JS/JSON-LD (`ldGtin: undefined`, only `sku` populated —
  `AMGSWP01EN` and `GW-21-25` respectively). The field exists in the page's data schema
  but is empty across product types, not just for board games. Not a viable EAN source
  today; no need to re-poll unless Miniature Market visibly re-platforms.

## Cross-cutting: do reachable retailers carry EAN for system-less accessories?

Spot-checked 5 accessory products (not miniature kits) across four curl-friendly
retailers plus Fantasywelt, targeting the ~1,700 recently-published Mantic
bases/mats/paints and GW paints/tools/dice:

| Retailer | Product | EAN found | Source field |
|---|---|---|---|
| Goblin Gaming (Shopify) | Warhammer Base: Abaddon Black 12ml (GW Citadel paint) | **Yes** — `5011921196371` | `/products/base-abaddon-black.js` → `variants[].barcode` |
| Goblin Gaming | Halo: Flashpoint UNSC Base Terrain Set (Mantic Games) | **Yes** — `5060924984584` | same `.js` `barcode` field |
| Goblin Gaming | Muddy Streets Gaming Mat 3x3 (Battle Systems, not GW/Mantic but same accessory class) | **Yes** — `5060660091690` | same `.js` `barcode` field |
| Radaddel (Shopware 6) | Base: Abaddon Black 12ml (same GW paint as above) | **Yes** — `5011921196371` (**exact cross-source match** with Goblin Gaming, independently corroborating the barcode) | `<meta itemprop="gtin13" content="...">` |
| Radaddel | John Blanche: Gladeshard (Army Painter accessory shade) | **Yes** — `5713799412002` | same `itemprop="gtin13"` meta |
| Game Nerdz (BigCommerce) | Warhammer Colour Paint: Base - Abaddon Black 12ml (same GW paint, different regional SKU `GWS21-25-2026`) | **Yes** — `5011921234493` (differs from the Goblin/Radaddel EAN above — GW appears to have re-coded this paint for a newer release wave; both are checksum-valid, this is real-world GW SKU churn, not a scraping error) | `window.BCData.product_attributes.upc` + visible `[data-product-upc]` |
| Fantasywelt (Shopware 5-derived) | Citadel Base: Corax White 12ml (GW paint) | **Yes** — `5011921196791` | `itemprop="gtin13"` microdata |
| Fantasywelt | MK3D Miniaturbase 40mm (generic 3rd-party base, accessory-class) | **Yes** — `4081541883051` | same `itemprop="gtin13"` |
| Wayland Games | Necromunda 25mm Bases (GW) | **No** | JSON-LD `Product` present, `gtin13` absent |
| Wayland Games | Warpath Team Bases 40mm (Mantic) | **No** | same |
| Wayland Games | Abaddon Black 12ml (GW paint) | **No** | same |
| Miniature Market | Citadel Base Paint: Abaddon Black 12ml | **No** | `productEAN` field present but empty |

**Answer:** Goblin Gaming, Radaddel, Game Nerdz, and Fantasywelt all carry EAN/GTIN for
accessory-class products (paints, bases, terrain, mats) just as reliably as they do for
miniature kits — the barcode field is populated per-SKU at the retailer/distributor level
regardless of product category, so a retailer sweep of those four sources should lift EAN
coverage for the ~1,700 system-less accessories roughly as well as it does for kits. The
one clean GW paint example (Abaddon Black 12ml) was independently corroborated by two
retailers agreeing on the same EAN (`5011921196371`), with a third retailer showing a
different-but-valid EAN reflecting a newer GW SKU revision — a useful reminder to expect
occasional legitimate multi-EAN entries per product for repackaged GW lines. Wayland and
Miniature Market do **not** help close the accessories gap (EAN absent structurally on
both, independent of product category), so they shouldn't be prioritized for this
specific goal even though Wayland is technically reachable and Miniature Market is
technically curl-friendly.
