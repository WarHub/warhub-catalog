# Source probe: web archives and misc databases (2026-07-12)

Probe of web.archive.org (Wayback CDX), BoardGameGeek, and Wikidata as sources for
out-of-print product recovery and EAN backfill. Run 2026-07-12 via curl.

## Wayback CDX API — enumeration works on all targets

Verified working query pattern:

```
http://web.archive.org/cdx/search/cdx?url=<domain>/<prefix>*&output=json&collapse=urlkey&fl=original,timestamp,statuscode&limit=N
```

| Target | Enumeration | Volume (`&showNumPages=true`) | Notes |
|---|---|---|---|
| `games-workshop.com/en-GB/*` | Yes | 30 pages | Old GW webstore product URLs are clean slugs (`/en-GB/10-man-kill-team`); captures 2014–2019 era plentiful, many 200s |
| `warhammer.com/shop/*` | Yes | 7 pages | Mostly 202/302/307/405 — queue-it + SPA; archived HTML likely client-rendered, low value |
| `waylandgames.co.uk/*` | Yes | 106 pages | Product slugs incl. old PrestaShop-era (`/-nam/51327-nam-rulebook`) and new-platform (2024+) URLs |
| `elementgames.co.uk/*` | Yes | 178 pages | Captures back to 2012. Bonus: archived `elementgames.co.uk/5060200840474` exists — Element supported EAN-as-URL barcode search pages |

Each "page" is a CDX index block chunk = thousands of rows.

### Pacing and query lessons

- `&filter=statuscode:200` works but is slow: a `page=1` query with the filter took 33.8 s.
- `&filter=original:<regex>` timed out at 60 s (curl exit 28) — avoid server-side regex
  filters on big domains; pull pages raw and filter locally.
- Pagination: `&page=N` with `&showNumPages=true`, or `&showResumeKey=true` for
  resume-key paging.
- Rate limits: at 1 req / 1–3 s pacing, zero 429s across ~15 requests. Stay ≤1 req/s.

## Archived page content — where the EANs actually are

**Old GW webstore** (`http://web.archive.org/web/20160826220543/https://www.games-workshop.com/en-GB/10-man-kill-team`, 58 KB):

- No EAN, no barcode, no JSON-LD, no microdata.
- Does contain GW's internal 11-digit product/SKU codes throughout: `skuId=99219999037`,
  `skuid="99020109001"`, image filenames like `99020109001_CorvusDropshipWingBundle01.jpg`,
  plus `productId=prod3070224`, display names, GBP prices.
- So old-GW archives recover **name + GW 11-digit product code + era pricing** for
  discontinued items — join EANs from elsewhere.

**Wayland Games archives:**

- 2019 capture (PrestaShop era): `"sku">FW910` (manufacturer code), OpenGraph
  `product:price:amount`, no EAN — PrestaShop has an ean13 field but it was not exposed
  in markup.
- 2024 capture (new platform, JSON-LD present): `"sku":"WLS-WTR3548"`, `"mpn":"165171"` —
  still no gtin13.

**Element Games archives** (2017 and 2024): microdata `itemprop="offerDetails"` only;
no gtin/EAN in markup.

**Archived Shopify retailers — the winning pattern.** Archived Goblin Gaming page
(`http://web.archive.org/web/20210624021531/https://www.goblingaming.co.uk/products/1-x-large-flying-stand`)
contains JSON-LD with:

```
"gtin13": 5060504044745
"sku": "BRFLY"
```

Shopify themes commonly emit `gtin13` when the merchant filled the barcode field, and
`/products/<handle>.json` (with per-variant `barcode`) is sometimes archived too.
**Enumerating archived Shopify-based miniature retailers via CDX (`<domain>/products/*`)
and parsing JSON-LD is the concrete EAN-recovery path for out-of-print products.**

## BoardGameGeek XML API2 — now locked

- `https://boardgamegeek.com/xmlapi2/search?query=star+wars+legion` → HTTP 401
  "Unauthorized. See https://boardgamegeek.com/using_the_xml_api", regardless of
  User-Agent/Accept. Same for `thing?id=233571&versions=1`. The policy page itself is
  behind Cloudflare (403 to non-browser fetch).
- BGG began requiring registered applications + bearer-token Authorization headers for
  the XML API, enforced late 2025, for all users. Whether `versions=1` output includes
  EAN/UPC could not be tested without a token (historically versions carry a
  `productcode` field — usually the publisher SKU, not a barcode; unverified).
- Refs: [XML API registration required](https://boardgamegeek.com/thread/3540336/xml-api-registration-required),
  [Registration now open](https://boardgamegeek.com/thread/3525319/registration-to-use-the-xml-api-and-obtain-soon-to),
  [BGG now requiring authorization tokens](https://boardgamegeek.com/thread/3600185/heads-up-bgg-now-requiring-authorization-tokens-fo),
  [Read this for uninterrupted access](https://boardgamegeek.com/thread/3539581/xml-api-read-this-for-uninterrupted-access).

## Wikidata — property verified, coverage negligible

- P3962 = "Global Trade Item Number" (external-id), confirmed via `wbgetentities`.
- Sitewide count of items with P3962: 2,794.
- Items with P3962 manufactured/published/developed by Games Workshop (Q587270):
  exactly 1 — Talisman, GTIN `9781589944626` (a bookland ISBN). **Dead end for
  miniature EANs.**

## Availability API vs CDX for bulk work

- `https://archive.org/wayback/available?url=<url>&timestamp=<ts>` works, fast (<1 s),
  returns only the single closest snapshot (verified: returned `20160826220543` for the
  GW kill-team page). One URL per request; no wildcards, no enumeration.
- **Verdict: CDX for bulk.** The availability API is only a last-mile "best snapshot of
  this exact URL" resolver; CDX does that too (`&limit=1&filter=statuscode:200`, or
  `from`/`to` bounds) while also enumerating unknown URLs — the core need for
  out-of-print recovery.

## Practical takeaways

1. Old GW webstore archives → authoritative name + GW 11-digit product code + era
   pricing for discontinued items; join EANs from elsewhere.
2. Archived Shopify miniature retailers (JSON-LD `gtin13`, plus `/products/*.json` where
   captured) are the primary archived-EAN source. Wayland/Element archived markup does
   not carry EANs.
3. Pace CDX at ≤1 req/s, page with `page=`/resume keys, avoid server-side regex filters;
   filter status codes locally or use only the cheap `statuscode:200` filter.
