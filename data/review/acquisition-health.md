# Acquisition health (combined)

_Run 2026-09-26 -- combined per-group reports, group order A1-G._

---

## Group A1

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-warlord-store | ok | False | 5890 | 0 | barcodes_found=1026, detail_fetch_errors=0, details_fetched=2000, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=25, out_of_scope_vendor=0, products_seen=5907, skipped_unknown_vendor=17, unmapped_hints=8493 |

## Unmapped hints

- mfr-warlord-store: 8493

---

## Group A2

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-steamforged | ok | False | 246 | 0 | barcodes_found=127, detail_fetch_errors=1, details_fetched=248, enumeration_capped=0, enumeration_capped_by_400=0, excluded_keys=2, excluded_retracted=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=587, skipped_unknown_vendor=339, unmapped_hints=490 |
| mfr-warmachine | ok | False | 652 | 0 | barcodes_found=490, detail_fetch_errors=110, details_fetched=652, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=661, skipped_unknown_vendor=9, unmapped_hints=1194 |
| mfr-wyrd-store | ok | False | 616 | 0 | barcodes_found=546, detail_fetch_errors=0, details_fetched=616, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=4, out_of_scope_vendor=0, products_seen=616, skipped_unknown_vendor=0, unmapped_hints=1232 |

## Unmapped hints

- mfr-steamforged: 490
- mfr-warmachine: 1194
- mfr-wyrd-store: 1232

---

## Group B

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-corvus-belli | ok | True | 260 | 38 | fetched_pages=24, products_seen=260, reported_total=260, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2861 | 172 | cross_slice_duplicates=182, fetched_pages=34, malformed_object_id=0, missing_game_system_facets=0, products_seen=2861, reported_nbhits=2861, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2440 |
| mfr-manticgames | ok | False | 2830 | 0 | detail_fetch_errors=265, details_fetched=2653, excluded_keys=1, excluded_retracted=0, fetched_pages=30, gtins_found=0, products_seen=2831, reported_total=2831, skipped_unknown_vendor=0, unmapped_hints=4508 |
| mfr-para-bellum | ok | True | 411 | 9 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=411, reported_total=411, skipped_unknown_vendor=0, unmapped_hints=85 |

## Unmapped hints

- mfr-gw-algolia: 2440
- mfr-manticgames: 4508
- mfr-para-bellum: 85

---

## Group C

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| ret-goblingaming | ok | False | 7939 | 0 | barcodes_found=1432, detail_fetch_errors=1, details_fetched=1500, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=59, out_of_scope_vendor=0, products_seen=14340, skipped_unknown_vendor=6401, unmapped_hints=15877 |
| ret-tistaminis | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |

## Unmapped hints

- ret-goblingaming: 15877

---

## Group D

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-gw-trade | ok | False | 7652 | 0 | discontinued=2739, emitted=35285, lineage_links=1145, lineage_placeholder_barcodes=0, lineage_records=90, lineage_records_ambiguous=5, lineage_records_malformed=1, lineage_records_with_barcode=90, lineage_unmatched=0, lineage_with_barcode=540, parse_errors=0, rows=40554, skipped_bad_prefix=5200, skipped_no_ean=3, skipped_unreleased=66, snapshot_rows=40488, workbooks=14 |

---

## Group E

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| arc-goblingaming | ok | False | 18 | 0 | cdx_pages_fetched=9, codes_found=0, eans_found=18, extraction_failed=479, fetch_errors=2, skipped_unknown_manufacturer=1, snapshots_fetched=500, urls_indexed=1435 |
| arc-gw-webstore | ERROR |  |  |  | FetchError: failed to fetch /cdx/search/cdx (status=503) |

---

## Group F

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| bdb-goupc | ok | False | 17 | 0 | corroborated=17, fetch_errors=20, mismatched_title=13, misses=0, queried=50, robots_crawl_delay_applied=10.0 |

---

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| bdb-upcitemdb | ok | False | 2 | 0 | corroborated=2, fetch_errors=50, mismatched_title=11, misses=17, queried=80 |

---


---

## Group G

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-gw-trade | CONTRACT VIOLATION |  |  |  | field=ean, rate=0.998177953234133, required=1.0, source=mfr-gw-trade, type=field-fill-rate |
