# Acquisition health (combined)

_Run 2026-11-14 -- combined per-group reports, group order A1-G._

---

## Group A1

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-warlord-store | ok | False | 5901 | 0 | barcodes_found=1178, detail_fetch_errors=0, details_fetched=2000, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=25, out_of_scope_vendor=0, products_seen=5918, skipped_unknown_vendor=17, unmapped_hints=8512 |

## Unmapped hints

- mfr-warlord-store: 8512

---

## Group A2

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-steamforged | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
| mfr-warmachine | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
| mfr-wyrd-store | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |

---

## Group B

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-corvus-belli | ok | True | 256 | 43 | fetched_pages=23, products_seen=256, reported_total=256, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2870 | 254 | cross_slice_duplicates=196, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2870, reported_nbhits=2870, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2456 |
| mfr-manticgames | ok | False | 2888 | 0 | detail_fetch_errors=266, details_fetched=2683, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2889, reported_total=2889, skipped_unknown_vendor=0, unmapped_hints=4488 |
| mfr-para-bellum | ok | True | 417 | 14 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=417, reported_total=417, skipped_unknown_vendor=0, unmapped_hints=85 |

## Unmapped hints

- mfr-gw-algolia: 2456
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
| ret-gamenerdz | ok | False | 1946 | 0 | breadcrumbs_found=1946, ean_source_bcdata=1934, ean_source_jsonld=1, ean_source_microdata=0, eans_found=1935, extraction_failed=15, fetch_errors=7, fetched_sitemaps=34, pages_fetched=2500, sitemap_urls_filtered=5105, sitemap_urls_total=268524, skipped_unknown_manufacturer=532 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |

---

## Group E

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| arc-goblingaming | ok | False | 9 | 0 | cdx_pages_fetched=0, codes_found=0, eans_found=9, extraction_failed=491, fetch_errors=0, skipped_unknown_manufacturer=0, snapshots_fetched=500, urls_indexed=1435 |
| arc-gw-webstore | ok | False | 262 | 0 | cdx_pages_fetched=30, codes_found=262, eans_found=0, extraction_failed=238, fetch_errors=0, skipped_unknown_manufacturer=0, snapshots_fetched=500, urls_indexed=7572 |

---

## Group F

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| bdb-goupc | ok | False | 3 | 0 | corroborated=3, fetch_errors=20, mismatched_title=27, misses=0, queried=50, robots_crawl_delay_applied=10.0 |

---

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| bdb-upcitemdb | ok | False | 0 | 0 | corroborated=0, fetch_errors=50, mismatched_title=12, misses=18, queried=80 |

---


---

## Group G

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-gw-trade | CONTRACT VIOLATION |  |  |  | field=ean, rate=0.9981927710843373, required=1.0, source=mfr-gw-trade, type=field-fill-rate |
