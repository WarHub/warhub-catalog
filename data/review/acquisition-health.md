# Acquisition health (combined)

_Run 2026-09-30 -- combined per-group reports, group order A1-G._

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
| mfr-corvus-belli | ok | True | 261 | 38 | fetched_pages=24, products_seen=261, reported_total=261, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2868 | 172 | cross_slice_duplicates=182, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2868, reported_nbhits=2868, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2451 |
| mfr-manticgames | ok | False | 2830 | 0 | detail_fetch_errors=266, details_fetched=2653, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2831, reported_total=2831, skipped_unknown_vendor=0, unmapped_hints=4502 |
| mfr-para-bellum | ok | True | 410 | 10 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=410, reported_total=410, skipped_unknown_vendor=0, unmapped_hints=85 |

## Unmapped hints

- mfr-gw-algolia: 2451
- mfr-manticgames: 4502
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
| ret-gamenerdz | ok | False | 934 | 0 | breadcrumbs_found=934, ean_source_bcdata=908, ean_source_jsonld=0, ean_source_microdata=0, eans_found=908, extraction_failed=3, fetch_errors=6, fetched_sitemaps=33, pages_fetched=1000, sitemap_urls_filtered=4999, sitemap_urls_total=264387, skipped_unknown_manufacturer=57 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
