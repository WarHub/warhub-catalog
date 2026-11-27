# Acquisition health (combined)

_Run 2026-11-27 -- combined per-group reports, group order A1-G._

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
| mfr-steamforged | ok | False | 245 | 0 | barcodes_found=10, detail_fetch_errors=228, details_fetched=247, enumeration_capped=0, enumeration_capped_by_400=0, excluded_keys=2, excluded_retracted=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=586, skipped_unknown_vendor=339, unmapped_hints=488 |
| mfr-warmachine | ok | False | 665 | 0 | barcodes_found=5, detail_fetch_errors=657, details_fetched=665, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=686, skipped_unknown_vendor=21, unmapped_hints=1219 |
| mfr-wyrd-store | ok | False | 769 | 0 | barcodes_found=11, detail_fetch_errors=742, details_fetched=769, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=5, out_of_scope_vendor=0, products_seen=797, skipped_unknown_vendor=28, unmapped_hints=1520 |

## Unmapped hints

- mfr-steamforged: 488
- mfr-warmachine: 1219
- mfr-wyrd-store: 1520

---

## Group B

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-corvus-belli | ok | True | 260 | 44 | fetched_pages=24, products_seen=260, reported_total=260, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2898 | 264 | cross_slice_duplicates=196, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2898, reported_nbhits=2898, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2475 |
| mfr-manticgames | ok | False | 2887 | 0 | detail_fetch_errors=266, details_fetched=2674, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2888, reported_total=2888, skipped_unknown_vendor=0, unmapped_hints=4464 |
| mfr-para-bellum | ok | True | 428 | 14 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=428, reported_total=428, skipped_unknown_vendor=0, unmapped_hints=84 |

## Unmapped hints

- mfr-gw-algolia: 2475
- mfr-manticgames: 4464
- mfr-para-bellum: 84

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
| ret-gamenerdz | ok | False | 707 | 0 | breadcrumbs_found=707, ean_source_bcdata=705, ean_source_jsonld=0, ean_source_microdata=0, eans_found=705, extraction_failed=7, fetch_errors=8, fetched_sitemaps=34, pages_fetched=1000, sitemap_urls_filtered=5148, sitemap_urls_total=268818, skipped_unknown_manufacturer=278 |
| ret-radaddel | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |
