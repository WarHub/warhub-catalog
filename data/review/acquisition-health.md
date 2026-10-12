# Acquisition health (combined)

_Run 2026-10-12 -- combined per-group reports, group order A1-G._

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
| mfr-gw-algolia | ok | True | 2865 | 200 | cross_slice_duplicates=192, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2865, reported_nbhits=2865, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2447 |
| mfr-manticgames | ok | False | 2841 | 0 | detail_fetch_errors=266, details_fetched=2663, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=6, products_seen=2842, reported_total=2842, skipped_unknown_vendor=0, unmapped_hints=4522 |
| mfr-para-bellum | ok | True | 410 | 11 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=410, reported_total=410, skipped_unknown_vendor=0, unmapped_hints=85 |

## Unmapped hints

- mfr-gw-algolia: 2447
- mfr-manticgames: 4522
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
| ret-gamenerdz | ok | False | 768 | 0 | breadcrumbs_found=768, ean_source_bcdata=763, ean_source_jsonld=0, ean_source_microdata=0, eans_found=763, extraction_failed=9, fetch_errors=6, fetched_sitemaps=33, pages_fetched=1000, sitemap_urls_filtered=5011, sitemap_urls_total=265784, skipped_unknown_manufacturer=217 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
