# Acquisition health (combined)

_Run 2026-11-18 -- combined per-group reports, group order A1-G._

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
| mfr-warmachine | ok | False | 664 | 0 | barcodes_found=501, detail_fetch_errors=110, details_fetched=664, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=684, skipped_unknown_vendor=20, unmapped_hints=1217 |
| mfr-wyrd-store | ok | False | 622 | 0 | barcodes_found=549, detail_fetch_errors=0, details_fetched=622, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=645, skipped_unknown_vendor=23, unmapped_hints=1244 |

## Unmapped hints

- mfr-steamforged: 488
- mfr-warmachine: 1217
- mfr-wyrd-store: 1244

---

## Group B

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-corvus-belli | ok | True | 256 | 43 | fetched_pages=23, products_seen=256, reported_total=256, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2891 | 254 | cross_slice_duplicates=196, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2891, reported_nbhits=2891, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2473 |
| mfr-manticgames | ok | False | 2888 | 0 | detail_fetch_errors=265, details_fetched=278, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2889, reported_total=2889, skipped_unknown_vendor=0, unmapped_hints=4488 |
| mfr-para-bellum | ok | True | 426 | 14 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=426, reported_total=426, skipped_unknown_vendor=0, unmapped_hints=85 |

## Unmapped hints

- mfr-gw-algolia: 2473
- mfr-manticgames: 4488
- mfr-para-bellum: 85

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
| ret-gamenerdz | ok | False | 546 | 0 | breadcrumbs_found=546, ean_source_bcdata=541, ean_source_jsonld=0, ean_source_microdata=0, eans_found=541, extraction_failed=12, fetch_errors=8, fetched_sitemaps=34, pages_fetched=1000, sitemap_urls_filtered=5111, sitemap_urls_total=268571, skipped_unknown_manufacturer=434 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
