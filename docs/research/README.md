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
| [Retailer candidates: Warlord/Mantic](2026-07-16-retailer-candidates-warlord-mantic.md) | New-source hunt (2026-07-16) to close the Warlord/Mantic EAN gap toward 60%. Top pick **Athena Games** (Shopify, ClaudeBot-OK): 774 Warlord + 312 Mantic at ~90-100% barcode fill, incl. out-of-stock items. Backups: The Combat Company (AU Warlord), Board Game Bliss (CA Mantic). A Cloudflare managed robots.txt now blocks ClaudeBot on Firestorm/Caliver/Battlefield Berlin; Alphaspel is deep but publishes no EAN. |
| [GW trade barcode retrieval](2026-07-22-gw-trade-barcode-retrieval.md) | **Supersedes the trade-order-sheets probe.** GW's retailer site publishes retail EAN-13s in bulk, unauthenticated, via an open media REST API: 36 spreadsheets, **7,637 distinct valid barcodes**, covering current *and* discontinued products back to 2020-08. Also re-tested two sources the earlier probe called gated: **Warlord's `All_Products.csv` and Asmodee NA's catalogs are open.** |
| [GW EAN conflicts review](2026-07-23-gw-ean-conflicts.md) | Plain-English walkthrough of the 38 GW EAN conflicts the trade data surfaced. **8 fixed** via repackaging joins (old barcode → `additionalEans`); **~23 have a stale published primary** from a resolver ranking artifact (curated/legacy outranks live — one systemic fix clears them all); **3 are distinct products** that must not be merged (Zodgrod vs Beast Snagga army set; Combat Patrol vs Kill Team sharing a reused code; Tigurius metal→resin re-sculpt). |

## Headline conclusions

1. **The biggest single EAN win is mechanical:** Warlord Games' own store (~5,843
   products, today's 20%-coverage anchor) exposes `gtin13` on every product page —
   as do Steamforged, Mantic, Wyrd, and Asmodee/AMG. Per-page harvesting closes the
   gap the barcode-less bulk feeds created.
2. ~~**GW, Corvus Belli, and CMON need retailer cross-referencing** — their own sites
   expose no barcodes; Tier-1 retailers plus Go-UPC are the join path.~~
   **Superseded 2026-07-22 for GW.** GW's *consumer* properties still expose no barcodes, but its
   **retailer site does**, in bulk and unauthenticated — see
   [GW trade barcode retrieval](2026-07-22-gw-trade-barcode-retrieval.md). Corvus Belli and CMON
   are unchanged. The generalisation "manufacturer X publishes no EANs" was only ever tested
   against consumer storefronts; **trade/retailer portals are a separate surface and must be
   probed separately** — the same omission hid open EAN files at Warlord and Asmodee NA too.
3. **Out-of-print recovery via web.archive.org is viable:** CDX enumeration works at
   scale, and archived Shopify retailer pages carry EANs for SKUs that no longer exist
   anywhere live.
