# Acquisition health (combined)

_Run 2026-11-20 -- combined per-group reports, group order A1-G._

---

## Group A1

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-warlord-store | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |

---

## Group A2

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-steamforged | ok | False | 245 | 0 | barcodes_found=127, detail_fetch_errors=1, details_fetched=247, enumeration_capped=0, enumeration_capped_by_400=0, excluded_keys=2, excluded_retracted=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=586, skipped_unknown_vendor=339, unmapped_hints=488 |
| mfr-warmachine | ok | False | 664 | 0 | barcodes_found=501, detail_fetch_errors=110, details_fetched=664, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=683, skipped_unknown_vendor=19, unmapped_hints=1217 |
| mfr-wyrd-store | ok | False | 624 | 0 | barcodes_found=549, detail_fetch_errors=0, details_fetched=624, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=652, skipped_unknown_vendor=28, unmapped_hints=1248 |

## Unmapped hints

- mfr-steamforged: 488
- mfr-warmachine: 1217
- mfr-wyrd-store: 1248

---

## Group B

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-corvus-belli | ok | True | 256 | 43 | fetched_pages=23, products_seen=256, reported_total=256, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2896 | 255 | cross_slice_duplicates=196, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2896, reported_nbhits=2896, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2475 |
| mfr-manticgames | ok | False | 2888 | 0 | detail_fetch_errors=265, details_fetched=2675, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2889, reported_total=2889, skipped_unknown_vendor=0, unmapped_hints=4488 |
| mfr-para-bellum | ok | True | 425 | 15 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=425, reported_total=425, skipped_unknown_vendor=0, unmapped_hints=84 |

## Unmapped hints

- mfr-gw-algolia: 2475
- mfr-manticgames: 4488
- mfr-para-bellum: 84

---

## Group C

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| ret-goblingaming | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
| ret-tistaminis | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |

---

## Group D

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| ret-gamenerdz | ok | False | 947 | 0 | breadcrumbs_found=947, ean_source_bcdata=931, ean_source_jsonld=0, ean_source_microdata=0, eans_found=931, extraction_failed=2, fetch_errors=8, fetched_sitemaps=34, pages_fetched=1000, sitemap_urls_filtered=5111, sitemap_urls_total=268694, skipped_unknown_manufacturer=43 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
