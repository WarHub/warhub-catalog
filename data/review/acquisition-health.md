# Acquisition health (combined)

_Run 2026-10-22 -- combined per-group reports, group order A1-G._

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
| mfr-gw-algolia | ok | True | 2859 | 211 | cross_slice_duplicates=195, fetched_pages=33, malformed_object_id=0, missing_game_system_facets=0, products_seen=2859, reported_nbhits=2859, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2450 |
| mfr-manticgames | ok | False | 2845 | 0 | detail_fetch_errors=266, details_fetched=271, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2846, reported_total=2846, skipped_unknown_vendor=0, unmapped_hints=4432 |
| mfr-para-bellum | ok | True | 419 | 11 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=419, reported_total=419, skipped_unknown_vendor=0, unmapped_hints=87 |

## Unmapped hints

- mfr-gw-algolia: 2450
- mfr-manticgames: 4432
- mfr-para-bellum: 87

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
| ret-gamenerdz | ok | False | 622 | 0 | breadcrumbs_found=622, ean_source_bcdata=601, ean_source_jsonld=0, ean_source_microdata=0, eans_found=601, extraction_failed=5, fetch_errors=6, fetched_sitemaps=34, pages_fetched=1000, sitemap_urls_filtered=5023, sitemap_urls_total=267239, skipped_unknown_manufacturer=367 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
