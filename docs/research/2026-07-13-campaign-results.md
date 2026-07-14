# Local deep-harvest campaign — results (2026-07-13/14)

Plan: `docs/superpowers/plans/2026-07-13-local-deep-harvest.md`. All harvests run locally, politely paced, no CI constraints.

> **Correction notice.** The first version of this document claimed that ~3,600 of Warlord's EAN-less products were "out of print, unreachable by live sources," and recommended abandoning live-store work for Warlord and Mantic. **That claim was false and the recommendation was wrong.** The whole-branch review checked it against the evidence this very campaign committed: **1,861 of those products are `in_stock` on Warlord's own store today** (`missStreak: 0`, `lastSeen: 2026-07-13`). They are current products whose storefront does not publish barcodes. The corrected analysis is below; the numbers were always right, the story told about them was not.

## Headline

| | mission baseline | campaign start | campaign end |
|---|---|---|---|
| products | 12,799 | 15,348 | **18,392** |
| products with EAN | 5,853 | 7,801 | **10,152** |
| EAN coverage | **45.7%** | 50.8% | **55.2%** |

**+5,593 products and +4,299 EANs against the mission baseline. Absolute EAN count is up 73%.**

Every one of the 10,152 catalog EANs is a 13-digit, GS1-checksum-valid GTIN (independently verified). The resolver rejects malformed values before they reach the catalog, so coverage is not inflated by junk.

**The plan's ≥60% gate was NOT met.** It needs 883 more EANs. The reason is a *publication* gap, not an *existence* gap — see below.

## Per-source EAN attribution (this campaign)

| source | what changed | barcodes found |
|---|---|---|
| ret-goblingaming | dropped `scope.vendors` → all tracked brands | **4,766** |
| ret-gamenerdz | broadened `urlInclude` beyond GW terms | **4,182** |
| ret-radaddel | full 12,806-URL sweep (was 1,000 pages) | **3,614** |
| ret-tistaminis | dropped `scope.vendors` + vendor aliases | **2,542** |
| arc-tistaminis | new archived-Shopify source (+ `offers` fix) | **412** |
| arc-wargameportal | new archived-Shopify source | **292** |
| bdb-goupc | full provisional sweep | 44 (corroboration only) |
| arc-goblingaming | re-run under fixed extractor | 32 |
| mfr-cmon | headed browser (metadata only — no barcodes exist) | 0 |

Raw observations exceed net catalog gain because many corroborate EANs we already held.

## The finding that mattered: the gap was self-inflicted

Goblin Gaming enumerated 13,436 products and we harvested 2,923. Tistaminis enumerated 25,000 and we harvested 1,178. Both were scoped `vendors: [Games Workshop]` — while stocking Warlord, Mantic, Corvus Belli, AMG and Wyrd **at 85–100% barcode fill**:

| store | GW | Warlord | Mantic | Corvus | Wyrd | AMG |
|---|---|---|---|---|---|---|
| goblin fill | 100% | **92%** | 94% | 85% | 94% | 92% |
| tistaminis fill | 98% | **65%** | 97% | — | 95% | — |

The unlock was a taxonomy detail: **tistaminis tags vendors brand-plus-format** (`Warlord-BLISTER`, `Warlord-WEB`, `GW-Web`, `GW-OOP`). Without those four `vendorNames` aliases, un-scoping tistaminis would have returned **zero** Warlord products.

## Why 60% wasn't reached — and why it is still reachable

The 8,240 EAN-less products break down as:

| | count |
|---|---|
| **listed on a live source today** (a manufacturer store or a retailer we crawl) | **6,146** |
| seen only by legacy/seed/archives — genuinely gone from every live source | **2,094** |

Live-but-EAN-less, by manufacturer: warlord **2,334** · mantic **1,829** · GW 940 · cmon 279 · corvus 205 · AMG 181 · steamforged 157 · wyrd 147 · para-bellum 74.

**The barrier is that the sources we ask don't publish barcodes — not that the products don't exist.**

- **Manufacturer stores publish poorly.** Warlord's own Shopify emits barcodes on ~43% of its range; Mantic's emits 175 gtins across 2,789 products (**6%**).
- **The retailers we harvest publish well but stock shallow.** Goblin and Tistaminis carry Warlord at 92%/65% and Mantic at 94%/97% fill — but only a few hundred SKUs of each, not the deep back-catalogue.
- Only **1,726** Warlord products are plausibly archive-only (absent from every live crawl). That is the true out-of-print figure — not the ~3,600 originally claimed.

**Mantic is the clearest counter-example to the original conclusion**: its own store publishes 6% barcodes while retailers that stock it publish 94–97%. Mantic is not exhausted; it is *under-sourced*.

### The one verified vein we cannot use

Fantasywelt (~70k products) publishes `gtin13` in its markup **including accessories**, and stocks Warlord and Mantic deeply — barcodes verified live (`5060393709336` Warlord, `5060208869873` Mantic). Its `robots.txt` disallows `ClaudeBot` by name. **We declined it and did not switch user-agents.** That is an ethical constraint, honored deliberately — it is *not* evidence that the data doesn't exist. Conflating the two was the original document's core error.

## What would actually move the needle next

1. **Find retailers that stock Warlord/Mantic deeply AND publish barcodes.** This is the direct path to 60%+: 6,146 EAN-less products are live-listed right now, and 883 EANs close the gap. Goblin/Tistaminis prove such retailers exist and publish at 85–100%; we simply haven't found ones with deep Warlord/Mantic inventory. Candidate work: probe further UK/EU/US specialist retailers on the same platforms (Shopify `/products/<handle>.js`, Shopware `itemprop="gtin13"`, BigCommerce `BCData.upc`).
2. **Archived-retailer mining** for the genuine 2,094 archive-only products. The `offers` fix makes this viable (arc-tistaminis: 0 → 412 EANs). Each new archived store is one descriptor.
3. **Do not** invest further in free barcode databases (below).

## Dead ends, closed with evidence

- **Free barcode databases are finished.** They are barcode-in only (live-probed: name/SKU search → HTTP 400), so they can never *supply* a missing EAN — only corroborate one. Go-UPC now throttles hard at scale: the full 663-product sweep returned **603 fetch errors (91%)** even at the 10s `Crawl-delay` its own robots.txt requests. 44 corroborations. Do not re-run.
- **Wayland, Miniature Market, Element Games**: no usable barcodes (verified with a real browser, not assumed).
- **CMON**: reachable only with a headed browser (headless is genuinely Cloudflare-challenged), and carries **no barcodes at all, ever** — metadata-only. It cannot run in CI.

## Bugs this campaign surfaced

**JSON-LD `offers` extraction (`da338f9`) — worth ~700 barcodes.** `_extract_jsonld` read `gtin13` only from the Product node's top level; Shopify themes nest it inside `offers`. arc-tistaminis harvested **0.0 EAN fill** and tripped its contract — which is the only reason we looked. The barcode was sitting in the page (`5011921163106`). Fixed, with the real archived page committed as a regression fixture.

*Plan 4's archive adjudication survives*: arc-goblingaming's low yield is **not** this bug — 667 of its 700 captures contain no JSON-LD at all (pre-theme era). Both conclusions stand independently.

**robots.txt was never checked, across two plans of harvesting (`44b1504`, `06bb536`).** An audit found all 13 active sources permit us — luck, not enforcement. Now a preflight fetches and honors `robots.txt`, checks **every HTTP request** inside `PoliteClient`, treats a `ClaudeBot` disallow as binding, and honors `Crawl-delay` (Go-UPC's real `Crawl-delay: 10` is applied automatically).

**Retailer chrome in canonical names.** Radaddel's microdata omits `itemprop="name"`, so extraction fell back to `<title>` — which is shop-suffixed. This branch's full sweep amplified a latent bug into **1,047 polluted product names and 1,015 entity IDs** (e.g. `...-radaddel-radaddel-tabletop-shop`). Fixed at the extractor; evidence healed by re-harvest.

## Verification

Coverage figures recomputed from `data/catalog/products/*.yaml`. Warlord bucket analysis recomputed from `data/evidence/products/*/observations.jsonl` source-sets and `missStreak`/`availability` fields. EAN validity checked with GS1 checksums across all 10,152. Every number in this document is reproducible from committed data.
