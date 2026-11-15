# Acquisition health (combined)

_Run 2026-11-15 -- combined per-group reports, group order A1-G._

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
| mfr-wyrd-store | ok | False | 622 | 0 | barcodes_found=549, detail_fetch_errors=0, details_fetched=622, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=622, skipped_unknown_vendor=0, unmapped_hints=1244 |

## Unmapped hints

- mfr-wyrd-store: 1244

---

## Group B

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-corvus-belli | ok | True | 256 | 43 | fetched_pages=23, products_seen=256, reported_total=256, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2891 | 254 | cross_slice_duplicates=196, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2891, reported_nbhits=2891, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2475 |
| mfr-manticgames | ok | False | 2888 | 0 | detail_fetch_errors=265, details_fetched=2683, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2889, reported_total=2889, skipped_unknown_vendor=0, unmapped_hints=4488 |
| mfr-para-bellum | ok | True | 417 | 14 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=417, reported_total=417, skipped_unknown_vendor=0, unmapped_hints=85 |

## Unmapped hints

- mfr-gw-algolia: 2475
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
| ret-gamenerdz | ok | False | 783 | 0 | breadcrumbs_found=783, ean_source_bcdata=780, ean_source_jsonld=1, ean_source_microdata=0, eans_found=781, extraction_failed=5, fetch_errors=7, fetched_sitemaps=34, pages_fetched=1000, sitemap_urls_filtered=5105, sitemap_urls_total=268519, skipped_unknown_manufacturer=205 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
