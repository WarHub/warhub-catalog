# Plan 5 recon: coverage arithmetic for local deep-harvest (2026-07-13)

Evidence-only recon for Plan 5 (LOCAL deep-harvest campaign). All numbers below are
computed from the real committed catalog (`data/catalog/products/*.yaml`, 15,348
products / 7,801 with EAN) and the real committed evidence cursors
(`data/evidence/products/ret-{radaddel,gamenerdz}/cursor.yaml`), plus live probes run
2026-07-13 (curl, browser UA, polite pacing) against go-upc.com, the Radaddel/Game
Nerdz sitemaps, and Wayback CDX for eight candidate archived Shopify retailers. No code
was written into the repo; this document and its throwaway scripts (session scratchpad
only) are the only artifacts.

Scripts used: `ean_analysis.py`, `ean_mfr_totals.py`, `ean_provisional_by_mfr.py`
(session scratchpad, PyYAML via `uv run` in `tools/acquisition`), plus ad-hoc `curl`
against live sitemaps / Wayback CDX / go-upc.com.

---

## A. Where are the missing EANs, exactly?

`15,348` total products, `7,801` with `ean` set, **`7,547` without** (matches the task's
starting figure exactly: `15348 - 7801 = 7547`).

### Per-manufacturer EAN coverage (context)

| Manufacturer | Total | Has EAN | No EAN | Coverage |
|---|---:|---:|---:|---:|
| warlord-games | 5,925 | 1,946 | 3,979 | 32.8% |
| games-workshop | 4,110 | 3,140 | 970 | 76.4% |
| mantic-games | 2,796 | 813 | 1,983 | 29.1% |
| wyrd-games | 709 | 577 | 132 | 81.4% |
| steamforged-games | 605 | 442 | 163 | 73.1% |
| para-bellum | 398 | 318 | 80 | 79.9% |
| atomic-mass-games | 333 | 215 | 118 | 64.6% |
| corvus-belli | 320 | 263 | 57 | 82.2% |
| cmon | 152 | 87 | 65 | 57.2% |

Warlord and Mantic are the two structurally-uncovered manufacturers (32.8% / 29.1%);
everyone else is 57–82%. Together Warlord + Mantic hold `3,979 + 1,983 = 5,962` of the
`7,547` missing EANs — **79.0% of the entire gap**.

### Top-5 (manufacturer × status × has-sku × gameSystem-null-or-not) buckets

| # | Manufacturer | Status | Has SKU | Has gameSystem | Count |
|---|---|---|---|---|---:|
| 1 | warlord-games | current | yes | yes | **3,978** |
| 2 | mantic-games | current | yes | **no** | **1,031** |
| 3 | mantic-games | current | yes | yes | 933 |
| 4 | games-workshop | current | yes | yes | 795 |
| 5 | steamforged-games | current | yes | yes | 160 |

Aggregate shape of the full 7,547: `(current, has_sku)=7,291`, `(discontinued,
has_sku)=156`, `(current, no_sku)=97`, `(discontinued, no_sku)=3`. Missing EANs are
overwhelmingly a **current-stock, has-SKU** problem (96.6% of the gap) — not a
discontinued/orphan-data problem. `gameSystem` is null for 1,101 of the 7,547 (14.6%);
present for the other 6,446 (85.4%).

### (1) Warlord's ~4,000 EAN-less bucket — exact shape

**3,979** Warlord products lack an EAN (task's "~4,000" estimate confirmed close).
Breakdown:
- **100% have a SKU** (3,979 / 3,979) — zero are SKU-less orphans.
- **100% are `status: current`** (3,979 / 3,979) — **zero discontinued Warlord products
  lack an EAN.** Warlord's historical/discontinued line is already EAN-covered from
  legacy migration; it's specifically the *current* catalog (live Shopify store) that
  hasn't been enriched.
- 3,978 of the 3,979 carry a `gameSystem`; only 1 does not.

This is a clean, homogeneous bucket: current, in-catalog, SKU-identified Warlord
products simply never got an EAN written. It is the single best target for a
retailer-cross-reference sweep (Radaddel/Game Nerdz/etc. all carry Warlord stock).

### (2) System-less newly-published accessories — real count is 1,101, not ~1,700

The task's ~1,700 prior estimate does not hold: the real number of (no-EAN AND
`gameSystem` null) products is **1,101**, all `category: miniatures`, and **100% have
`firstSeen: 2026-07`** (i.e., every single one was newly added by *today's* acquisition
run — this is a freshly-ingested bucket, not a long-standing backlog). Breakdown by
manufacturer:

| Manufacturer | Count |
|---|---:|
| mantic-games | 1,042 |
| games-workshop | 50 |
| wyrd-games | 5 |
| steamforged-games | 3 |
| warlord-games | 1 |

This bucket is 94.6% Mantic. It's effectively the same population as Mantic's
system-less sub-bucket below — Mantic dominates both framings.

### (3) Mantic's EAN-less bucket — real count is 1,983, not ~980 (2x the estimate)

The task's ~980 prior estimate is **off by roughly 2x**: Mantic actually has **1,983**
EAN-less products (29.1% coverage, the worst of the 9 manufacturers alongside Warlord).
Breakdown:
- Status: 1,981 current, 2 discontinued (99.9% current, same shape as Warlord).
- SKU: 1,964 have a SKU, 19 do not (99.0% SKU-complete).
- gameSystem: 941 have one, **1,042 do not** — Mantic alone supplies 94.6% of the
  system-less/newly-published bucket above (#2). This is Mantic's accessory/bits/parts
  catalog (bases, terrain add-ons, etc.) freshly ingested without game-system
  classification and without EANs.

### Synthesis

Warlord (3,979) + Mantic (1,983) = **5,962 of 7,547 (79.0%)** of all missing EANs, and
both buckets are near-100%-current, near-100%-SKU-complete — i.e., not
data-quality/orphan problems, just unenriched. A retailer-sweep campaign (Part D) that
carries Warlord/Mantic stock is the highest-value lever; Mantic's 1,042-strong
system-less accessory pile is a secondary, lower-priority tail (bases/terrain bits are
inherently low-signal for name-matching anyway).

---

## B. Barcode-DB ceiling

### Provisional-EAN pool (Go-UPC's actual input)

`eanConfidence: provisional` count, computed from the catalog:

```
provisional: 663   (confirmed: 7,094, conflicted: 44 — sums to has_ean=7,801)
```

By manufacturer: **games-workshop 658, warlord-games 5** — the provisional pool is
**99.2% Games Workshop**. Warlord and Mantic (the two manufacturers holding 79% of the
*missing*-EAN problem) have essentially nothing in the provisional pool to corroborate
— Go-UPC has almost no leverage on the buckets that matter most.

### Realistic yield of a full Go-UPC sweep

At the observed 32% corroboration rate (16/50 in the pilot sweep):

```
663 provisional × 0.32 ≈ 212 corroborated (provisional → confirmed)
```

That's the **entire realistic yield of a full Go-UPC sweep**: ~212 records flip
confidence tier. It changes **zero** entries in the 7,547-strong no-EAN pool, because
Go-UPC corroboration requires an existing EAN as the lookup key — it cannot originate
one. Net effect on overall EAN coverage (7,801/15,348 = 50.8%): **0.0 percentage
points** (has_ean count is unchanged; only confidence labels shift for ~212 already-EAN
GW records).

### Go-UPC reverse lookup (name/SKU → EAN): live-probe verdict — **NO**

Two polite live requests against go-upc.com, 2026-07-13:

1. `GET https://go-upc.com/search?q=Combat+Patrol+Necrons` → **HTTP 400**, page title
   "Invalid Value — Go-UPC", body: *"Please enter a valid UPC (12-digit number) or
   EAN/ISBN (13-digit number)!"* — the search box is barcode-typed only; a name string
   is rejected outright, not just unmatched.
2. `GET https://go-upc.com/docs` → the documented API surface is exactly two endpoints:
   `GET /v1/code/:code` and `GET /v1/image/:code`. Both are barcode-keyed. No
   name/SKU/keyword search endpoint exists anywhere in the product — free web UI or
   paid API.

**Verdict: Go-UPC (and by the same evidence, no free DB probed to date — see the
2026-07-12 barcode-DB doc: upcitemdb is also barcode→product only, opengtindb/
barcode-list/ean-search are dead or paid) supports only barcode→product lookup, never
product→barcode.** This hard-caps barcode-DB value at *corroboration* of EANs we
already have (~212 realistic upside from a full sweep). **The 7,547-product
missing-EAN problem cannot be solved by barcode databases at all — it must be solved by
retailers (Part D) or archives (Part C), which discover a *new* EAN from the seller's
own product-page markup rather than requiring one as input.**

---

## C. Archived-Shopify EAN mining — which stores are worth it?

Wayback CDX enumeration (`<domain>/products/*`, `showNumPages=true`) + one 2022–2024
archived product-page fetch per candidate, ≤1 req/s, 2026-07-13. Eight candidates
tested: the six named plus two newly-identified UK/US miniature Shopify stores
(Merlin's Miniatures, Wargame Portal — found via web search, confirmed live Shopify by
`/products.json` returning 200).

| Store | Platform confirmed | CDX volume (`/products/*`, `showNumPages`) | gtin13 in 2022–2024 archive? | Example |
|---|---|---:|---|---|
| **tistaminis.com** | Shopify | 10 pages | **YES** | `gtin13: 4573102621856`, capture `20221001055446` (1/35 Batmobile kit page) |
| **wargameportal.com** (new find) | Shopify | 2 pages | **YES** | `gtin13: 5011921171996` = GW Achilles Ridgerunner (SKU `51-61`), capture `20241208110155` |
| merlinsminiatures.co.uk (new find) | Shopify | 2 pages (~3,066 raw rows pre-collapse) | Inconclusive/no | JSON-LD `Product` present, no `gtin13` key at all on the sampled listing (a used/bits GW-parts item — Merlin's catalog skews secondhand/loose parts, which typically never had a manufacturer barcode to populate) |
| nobleknight.com | Custom (not Shopify) | 13 pages (largest archive of the set) | NO | No JSON-LD/gtin/barcode found in sampled 2023 capture — confirms live-probe finding (mpn-only) extends into the archive |
| elementgames.co.uk | Custom (not Shopify) | **0 captures** under `/products/*` | N/A | Site never used a `/products/<slug>` URL shape — confirms live-probe "custom platform" finding |
| firestormgames.co.uk | Custom (not Shopify) | 1 page, but all rows are `/products?q=...` search-result pages | NO usable pages | No individual `/products/<slug>` product pages archived at all — confirms live-probe "custom cart" finding |
| thewarstore.com | Unknown (defunct; live site now has a broken TLS cert, no cert match) | **0 captures** under `/products/*` | N/A | Never used a Shopify-style `/products/` URL structure |
| dicehaven.com | N/A — not a retailer | ruled out pre-probe | N/A | It's a hobbyist community/resource site (15mm/28mm miniature *guides*), not a shop — `/products.json` 404s, no cart |

**Verdict: 2 of 8 candidates carry `gtin13` in archived captures — tistaminis.com
(known-good, confirms Plan-4-style value) and wargameportal.com (new find, and its
example is a genuine current-catalog GW product with a clean EAN match).** Both are
worth adding as `cdx-archive` sources. Merlin's Miniatures is a maybe (theme supports
JSON-LD but the sampled used-parts listing had no gtin — worth one more product-page
sample before deciding, ideally a boxed/new item rather than loose bits). The other
four (Noble Knight, Element Games, Firestorm Games, The War Store) are dead ends for
this specific technique — either wrong platform, wrong URL shape, or no archived
product pages at all under `/products/*`.

---

## D. Retailer sitemap backlog

### Radaddel

- Sitemap total (live-verified 2026-07-13, `sitemap_index.xml` → single
  `sitemap-1.xml.gz`): **12,806 URLs** (`grep -c "<loc>"` on the decompressed sitemap —
  exact match to the source-probe doc's figure and the `ret-radaddel.yaml` descriptor
  comment).
- Fetched so far (`data/evidence/products/ret-radaddel/cursor.yaml`, `fetched:` map):
  **1,000** URLs.
- **Remaining: 11,806** URLs.
- Observed yield: `observations.jsonl` has 239 lines, 236 with a non-null `ean` — i.e.
  **236 EANs / 1,000 fetched pages = 23.6%** (matches the task's stated rate exactly).
- Full-sweep time at 0.5 rps (2 s/request, local, no CI timeout):
  `11,806 × 2 s = 23,612 s = 393.5 min ≈ 6.56 hours`.
- Projected additional yield at the observed rate: `11,806 × 0.236 ≈ 2,786` new EANs
  (full-sweep total across all 12,806 URLs ≈ `12,806 × 0.236 ≈ 3,022`, of which 236
  already banked).

### Game Nerdz

- Sitemap total (live-verified 2026-07-13, `/xmlsitemap.php` → 27 product-sitemap
  pages, summed `<loc>` count): **257,416 URLs** (task's "~260k" estimate confirmed
  close; source-probe doc's earlier "~145,000" estimate was a rough guess from sampling
  one page, not a full count — this is the real total).
- GW-filtered subset (`urlInclude: (?i)(warhammer|citadel|forge-world)` from
  `ret-gamenerdz.yaml`, applied live to all 27 pages' `<loc>` text): **3,164 URLs**
  (task's "~3,171" estimate confirmed close; small drift is normal site-content churn
  since the 2026-07-12 probe).
- Fetched so far (`data/evidence/products/ret-gamenerdz/cursor.yaml`, `fetched:` map):
  **800** URLs (all within the filtered scope — the source only ever fetches
  filter-matching URLs).
- **Remaining (within the configured filtered scope): 2,364** URLs.
- Observed yield: `observations.jsonl` has 342 lines, all 342 with a non-null `ean` —
  **342 EANs / 800 fetched pages = 42.75%** (matches the task's stated rate exactly).
- Full-sweep time at 0.5 rps for the *configured filtered scope*:
  `2,364 × 2 s = 4,728 s = 78.8 min ≈ 1.31 hours`.
- Projected additional yield at the observed rate: `2,364 × 0.4275 ≈ 1,011` new EANs
  (full filtered-sweep total across all 3,164 URLs ≈ `3,164 × 0.4275 ≈ 1,353`, of which
  342 already banked).
- Aside (not the configured scope, just for reference): sweeping the *entire unfiltered*
  257,416-URL sitemap at 0.5 rps would take `257,416 × 2 s ≈ 514,832 s ≈ 143.0 hours`
  (~6 days) — the `urlInclude` regex filter is what makes this source tractable at all.

### Combined picture

| Source | Indexed | Fetched | Remaining | Full-sweep-of-remainder time @ 0.5rps | Projected new EANs |
|---|---:|---:|---:|---:|---:|
| Radaddel | 12,806 | 1,000 | 11,806 | ~6.56 h | ~2,786 |
| Game Nerdz (GW-filtered) | 3,164 | 800 | 2,364 | ~1.31 h | ~1,011 |
| **Total** | | | **14,170** | **~7.87 h** | **~3,797** |

Both backlogs together finish in under 8 hours of local wall-clock time at 0.5 rps and,
*if the observed per-page yield rate holds linearly across the remainder* (unverified
assumption — the pilot fetches were priority-ordered "never-fetched first," so there's
no reason to expect systematic drift, but this hasn't been checked against
overlap/novelty), would add on the order of **3,797 EANs** — roughly half of the
current 7,547-strong no-EAN gap. Unlike Go-UPC (Part B), these retailer sweeps extract
the seller's *own* barcode markup keyed by product name/SKU match, so they can
originate genuinely new EANs rather than merely corroborate existing ones — this is
the structural reason retailer/archive sources, not barcode databases, are the correct
lever for closing the missing-EAN gap.

---

## Sources

- `data/catalog/products/*.yaml` (15,348 products, live committed state 2026-07-13).
- `data/evidence/products/ret-radaddel/{cursor.yaml,observations.jsonl}`,
  `data/evidence/products/ret-gamenerdz/{cursor.yaml,observations.jsonl}`.
- `data/catalog/sources/ret-radaddel.yaml`, `data/catalog/sources/ret-gamenerdz.yaml`.
- `docs/research/2026-07-12-source-probe-retailers-barcodedb.md`,
  `docs/research/2026-07-12-source-probe-webarchive.md`.
- Live probes 2026-07-13: `https://www.radaddel.de/sitemap_index.xml` +
  `/web/sitemap/shop-1/sitemap-1.xml.gz`; `https://www.gamenerdz.com/xmlsitemap.php` +
  27 `type=products&page=N` sub-sitemaps; `https://go-upc.com/search?q=...` and
  `https://go-upc.com/docs`; Wayback CDX
  (`http://web.archive.org/cdx/search/cdx?url=<domain>/products/*`) for tistaminis.com,
  elementgames.co.uk, firestormgames.co.uk, thewarstore.com, nobleknight.com,
  merlinsminiatures.co.uk, wargameportal.com, dicehaven.com, plus one archived-page
  fetch each (`web.archive.org/web/<ts>id_/<url>`) for the four candidates with
  non-empty CDX results.
