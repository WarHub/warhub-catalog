# Acquisition health (combined)

_Run 2026-10-03 -- combined per-group reports, group order A1-G._

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
| mfr-corvus-belli | ok | True | 260 | 39 | fetched_pages=24, products_seen=260, reported_total=260, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2867 | 182 | cross_slice_duplicates=182, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2867, reported_nbhits=2867, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2450 |
| mfr-manticgames | ok | False | 2830 | 0 | detail_fetch_errors=264, details_fetched=267, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2831, reported_total=2831, skipped_unknown_vendor=0, unmapped_hints=4502 |
| mfr-para-bellum | ok | True | 411 | 10 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=411, reported_total=411, skipped_unknown_vendor=0, unmapped_hints=86 |

## Unmapped hints

- mfr-gw-algolia: 2450
- mfr-manticgames: 4502
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
| ret-gamenerdz | ok | False | 1826 | 0 | breadcrumbs_found=1826, ean_source_bcdata=1787, ean_source_jsonld=0, ean_source_microdata=0, eans_found=1787, extraction_failed=17, fetch_errors=6, fetched_sitemaps=33, pages_fetched=2500, sitemap_urls_filtered=5000, sitemap_urls_total=265530, skipped_unknown_manufacturer=651 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |

---

## Group E

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| arc-goblingaming | ok | False | 30 | 0 | cdx_pages_fetched=0, codes_found=0, eans_found=30, extraction_failed=468, fetch_errors=0, skipped_unknown_manufacturer=2, snapshots_fetched=500, urls_indexed=1435 |
| arc-gw-webstore | ERROR |  |  |  | FetchError: failed to fetch /cdx/search/cdx (status=503) |

---

## Group F

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| bdb-goupc | ok | False | 4 | 0 | corroborated=4, fetch_errors=20, mismatched_title=25, misses=1, queried=50, robots_crawl_delay_applied=10.0 |

---

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| bdb-upcitemdb | ok | False | 4 | 0 | corroborated=4, fetch_errors=50, mismatched_title=13, misses=13, queried=80 |

---


---

## Group G

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-gw-trade | CONTRACT VIOLATION |  |  |  | field=ean, rate=0.9981815426579784, required=1.0, source=mfr-gw-trade, type=field-fill-rate |
