# Acquisition health (combined)

_Run 2026-11-04 -- combined per-group reports, group order A1-G._

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
| mfr-corvus-belli | ok | True | 256 | 43 | fetched_pages=23, products_seen=256, reported_total=256, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2872 | 226 | cross_slice_duplicates=200, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2872, reported_nbhits=2872, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2457 |
| mfr-manticgames | ok | False | 2867 | 0 | detail_fetch_errors=265, details_fetched=295, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=16, products_seen=2868, reported_total=2868, skipped_unknown_vendor=0, unmapped_hints=4450 |
| mfr-para-bellum | ok | True | 419 | 12 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=419, reported_total=419, skipped_unknown_vendor=0, unmapped_hints=86 |

## Unmapped hints

- mfr-gw-algolia: 2457
- mfr-manticgames: 4450
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
| ret-gamenerdz | ok | False | 948 | 0 | breadcrumbs_found=948, ean_source_bcdata=924, ean_source_jsonld=0, ean_source_microdata=0, eans_found=924, extraction_failed=2, fetch_errors=7, fetched_sitemaps=34, pages_fetched=1000, sitemap_urls_filtered=5137, sitemap_urls_total=267917, skipped_unknown_manufacturer=43 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
