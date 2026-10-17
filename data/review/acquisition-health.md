# Acquisition health (combined)

_Run 2026-10-17 -- combined per-group reports, group order A1-G._

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
| mfr-steamforged | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
| mfr-warmachine | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
| mfr-wyrd-store | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |

---

## Group B

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-corvus-belli | ok | True | 259 | 40 | fetched_pages=24, products_seen=259, reported_total=259, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2857 | 211 | cross_slice_duplicates=197, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2857, reported_nbhits=2857, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2441 |
| mfr-manticgames | ok | False | 2845 | 0 | detail_fetch_errors=265, details_fetched=271, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2846, reported_total=2846, skipped_unknown_vendor=0, unmapped_hints=4432 |
| mfr-para-bellum | ok | True | 418 | 11 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=418, reported_total=418, skipped_unknown_vendor=0, unmapped_hints=86 |

## Unmapped hints

- mfr-gw-algolia: 2441
- mfr-manticgames: 4432
- mfr-para-bellum: 86

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
| ret-gamenerdz | ok | False | 2051 | 0 | breadcrumbs_found=2051, ean_source_bcdata=2019, ean_source_jsonld=1, ean_source_microdata=0, eans_found=2020, extraction_failed=17, fetch_errors=6, fetched_sitemaps=33, pages_fetched=2500, sitemap_urls_filtered=5025, sitemap_urls_total=266351, skipped_unknown_manufacturer=426 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |

---

## Group E

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| arc-goblingaming | ok | False | 23 | 0 | cdx_pages_fetched=0, codes_found=0, eans_found=23, extraction_failed=476, fetch_errors=0, skipped_unknown_manufacturer=1, snapshots_fetched=500, urls_indexed=1435 |
| arc-gw-webstore | ERROR |  |  |  | FetchError: failed to fetch /cdx/search/cdx (status=503) |

---

## Group F

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| bdb-goupc | ok | False | 2 | 0 | corroborated=2, fetch_errors=20, mismatched_title=27, misses=1, queried=50, robots_crawl_delay_applied=10.0 |

---

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| bdb-upcitemdb | ok | False | 2 | 0 | corroborated=2, fetch_errors=50, mismatched_title=13, misses=15, queried=80 |

---


---

## Group G

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-gw-trade | CONTRACT VIOLATION |  |  |  | field=ean, rate=0.9981875849569551, required=1.0, source=mfr-gw-trade, type=field-fill-rate |
