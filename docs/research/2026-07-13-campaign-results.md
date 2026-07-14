# Local deep-harvest campaign — results (2026-07-13/14)

Plan: `docs/superpowers/plans/2026-07-13-local-deep-harvest.md`. All harvests run locally, politely paced, no CI constraints.

## Headline

| | mission baseline | campaign start | campaign end |
|---|---|---|---|
| products | 12,799 | 15,348 | **18,392** |
| products with EAN | ~5,888 | 7,801 | **10,152** |
| EAN coverage | **46.0%** | 50.8% | **55.2%** |

**+5,593 products and +4,264 EANs against the mission baseline. Absolute EAN count is up 72%.**

**The plan's ≥60% gate was NOT met.** Section "Why 60% is out of reach with live sources" states exactly why, with evidence.

## Per-source EAN attribution (this campaign)

| source | what changed | barcodes found |
|---|---|---|
| ret-goblingaming | dropped `scope.vendors` → all tracked brands | **4,757** |
| ret-gamenerdz | broadened `urlInclude` beyond GW terms | **4,182** |
| ret-radaddel | full 12,806-URL sweep (was 1,000 pages) | **3,614** |
| ret-tistaminis | dropped `scope.vendors` + vendor aliases | **2,542** |
| arc-tistaminis | new archived-Shopify source (+ `offers` fix) | **412** |
| arc-wargameportal | new archived-Shopify source | **292** |
| bdb-goupc | full provisional sweep | 44 (corroboration only) |
| arc-goblingaming | re-run under fixed extractor | 30 |
| mfr-cmon | headed browser (metadata only, no EANs exist) | 0 |
| **total raw barcode observations** | | **~15,900** |

Raw observations exceed net catalog gain because many corroborate EANs we already held.

## The finding that mattered: the gap was self-inflicted

Goblin Gaming enumerated 13,436 products and we harvested 2,923. Tistaminis enumerated 25,000 and we harvested 1,178. Both were scoped `vendors: [Games Workshop]` — while stocking Warlord, Mantic, Corvus Belli, AMG and Wyrd **at 85–100% barcode fill**:

| store | GW | Warlord | Mantic | Corvus | Wyrd | AMG |
|---|---|---|---|---|---|---|
| goblin fill | 100% | **92%** | 94% | 85% | 94% | 92% |
| tistaminis fill | 98% | **65%** | 97% | — | 95% | — |

Warlord's "43% own-store ceiling" (accepted in Plan 3 as a fact about the brand) was never a ceiling on the product — only on the source we happened to ask.

The unlock was a taxonomy detail: **tistaminis tags vendors brand-plus-format** (`Warlord-BLISTER`, `Warlord-WEB`, `GW-Web`, `GW-OOP`). Without those four `vendorNames` aliases, un-scoping tistaminis would have returned **zero** Warlord products.

## Why 60% is out of reach with live sources

Warlord is the binding constraint: 6,031 products, 3,988 still without an EAN. Their evidence sources:

| # entities | seen by |
|---|---|
| 1,910 | legacy-catalog + Warlord's own store (store lists them, no barcode) |
| 1,726 | legacy-catalog only (out of print — not on any live store) |
| 247 | legacy + store + tistaminis (stocked, still no barcode) |

**~3,600 of Warlord's EAN-less products are old blisters and out-of-print items that no live retailer stocks.** The retailer barcodes we harvested landed overwhelmingly on products that *already* had EANs — Warlord netted only **+102**. No amount of live-store harvesting reaches the rest.

This is a structural ceiling, but a different one than Plan 3 claimed. The correct statement is: *live sources cannot barcode a product nobody sells anymore.*

**Only archives can.** That makes the JSON-LD `offers` fix (below) and further archived-retailer mining the real path to 60%+, not more live stores.

## Dead ends, closed with evidence

- **Free barcode databases are finished.** They are barcode-in only (live-probed: name/SKU search → HTTP 400), so they can never *supply* a missing EAN — only corroborate one. And Go-UPC now throttles hard at scale: the full 663-product sweep returned **603 fetch errors (91%)** even at the 10s `Crawl-delay` its own robots.txt requests. 44 corroborations. Do not re-run.
- **Fantasywelt: declined on principle.** ~70k products, `gtin13` confirmed in markup including accessories, Warlord (`5060393709336`) and Mantic (`5060208869873`) barcodes verified live — the largest untapped vein we found. Its `robots.txt` disallows `ClaudeBot` by name. We did not route around it with a different user-agent.
- **Wayland, Miniature Market, Element Games**: no usable barcodes (verified with a real browser, not assumed).
- **CMON**: reachable only with a headed browser (headless is genuinely Cloudflare-challenged), and carries **no barcodes at all, ever** — metadata-only. It cannot run in CI.

## Bugs this campaign surfaced

**JSON-LD `offers` extraction (`da338f9`) — worth ~700 barcodes.** `_extract_jsonld` read `gtin13` only from the Product node's top level; Shopify themes nest it inside `offers`. arc-tistaminis harvested **0.0 EAN fill** and tripped its contract — which is the only reason we looked. The barcode was sitting in the page (`5011921163106`). Fixed, with the real archived page committed as a regression fixture.

**Note on Plan 4's archive adjudication:** it survives. arc-goblingaming's low yield is *not* this bug — 667 of its 700 captures contain no JSON-LD at all (pre-theme era). Both conclusions stand independently.

**robots.txt was never checked, across two plans of harvesting (`44b1504`, `06bb536`).** An audit found all 13 active sources permit us — luck, not enforcement. Now a preflight fetches and honors `robots.txt` per source, checks **every request** inside `PoliteClient` (not just the base URL), treats a `ClaudeBot` disallow as binding, and honors `Crawl-delay` (Go-UPC's real `Crawl-delay: 10` is now applied automatically).

## What would actually move the needle next

1. **Archived-retailer mining at scale.** The `offers` fix makes archived Shopify stores viable (arc-tistaminis: 0 → 412). Warlord's out-of-print blisters were sold by retailers years ago; those captures are where their barcodes live.
2. **More archived stores.** Only 3 are wired. The CDX enumeration + shopify-jsonld extractor is now proven — each new store is a descriptor.
3. **Do not** invest further in barcode DBs or live-store breadth for Warlord/Mantic; both are exhausted.
