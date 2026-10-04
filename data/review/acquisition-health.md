# Acquisition health (combined)

_Run 2026-10-04 -- combined per-group reports, group order A1-G._

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
| mfr-gw-algolia | ok | True | 2880 | 182 | cross_slice_duplicates=194, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2880, reported_nbhits=2880, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2463 |
| mfr-manticgames | ok | False | 2830 | 0 | detail_fetch_errors=263, details_fetched=267, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2831, reported_total=2831, skipped_unknown_vendor=0, unmapped_hints=4502 |
| mfr-para-bellum | ok | True | 411 | 10 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=411, reported_total=411, skipped_unknown_vendor=0, unmapped_hints=86 |

## Unmapped hints

- mfr-gw-algolia: 2463
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
| ret-gamenerdz | ok | False | 592 | 0 | breadcrumbs_found=592, ean_source_bcdata=581, ean_source_jsonld=0, ean_source_microdata=0, eans_found=581, extraction_failed=6, fetch_errors=6, fetched_sitemaps=33, pages_fetched=1000, sitemap_urls_filtered=5000, sitemap_urls_total=265397, skipped_unknown_manufacturer=396 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
