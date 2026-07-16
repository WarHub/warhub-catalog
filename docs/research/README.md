# Research notes

Reference docs from the 2026-07-12 exploration that preceded the data-acquisition
rewrite: live probes of every relevant source class, plus an as-built analysis of the
current pipeline. Probes were run against the real endpoints on 2026-07-12; endpoint
behavior (especially bot protection and Shopify feed fields) may drift.

| Doc | Takeaway |
|---|---|
| [Manufacturer site probe](2026-07-12-source-probe-manufacturers.md) | Shopify bulk feeds no longer carry barcodes, but per-product pages do (`gtin13` JSON-LD / embedded `barcode`); GW, Corvus Belli, and CMON expose no EANs on their own sites at all. |
| [Retailer + barcode-DB probe](2026-07-12-source-probe-retailers-barcodedb.md) | Tier-1 EAN retailers: Goblin Gaming, Tistaminis (Shopify per-handle `.js`), Miniaturicum, Radaddel (structured-data gtin13), Game Nerdz (BigCommerce `upc`). Go-UPC works as a lookup; other barcode DBs are dead ends or spotty. |
| [Web-archive probe](2026-07-12-source-probe-webarchive.md) | Wayback CDX enumeration is viable at scale; old GW webstore archives yield name + 11-digit code + price for dead SKUs; archived Shopify retailer pages carry `gtin13` — the EAN join for out-of-print products. BGG API now token-gated; Wikidata negligible. |
| [Current pipeline analysis](2026-07-12-current-pipeline-analysis.md) | As-built map of the acquisition layer: per-manufacturer source table, the three-step EAN chain and why it plateaus at 46%, metadata-heuristic inventory, storage-model mechanics, and the fail-soft error-surfacing inventory. |
| [Trade order sheets probe](2026-07-16-trade-order-sheets.md) | Manufacturer/distributor trade order sheets as a bulk EAN source: LOW viability. GW's public trade sheets carry the internal 11-digit code + name + price, never the GS1 EAN-13; the EAN-bearing forms are password-gated + Confidential (anti-ML/AI clause). Warlord's Excel/CSV export is behind the gated Trade Hub; Mantic publishes none. ~0 new EANs; keep the retailer-per-page and archived-Shopify veins instead. |

## Headline conclusions

1. **The biggest single EAN win is mechanical:** Warlord Games' own store (~5,843
   products, today's 20%-coverage anchor) exposes `gtin13` on every product page —
   as do Steamforged, Mantic, Wyrd, and Asmodee/AMG. Per-page harvesting closes the
   gap the barcode-less bulk feeds created.
2. **GW, Corvus Belli, and CMON need retailer cross-referencing** — their own sites
   expose no barcodes; Tier-1 retailers plus Go-UPC are the join path.
3. **Out-of-print recovery via web.archive.org is viable:** CDX enumeration works at
   scale, and archived Shopify retailer pages carry EANs for SKUs that no longer exist
   anywhere live.
