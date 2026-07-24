# Acquisition health (combined)

_Run 2026-07-24 -- combined per-group reports, group order A1-F._

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
| mfr-wyrd-store | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |

---

## Group B

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-corvus-belli | ok | True | 280 | 18 | fetched_pages=26, products_seen=280, reported_total=280, skipped_missing_identifier=0, skipped_missing_name=0, skipped_unknown_vendor=0, unmapped_hints=0 |
| mfr-gw-algolia | ok | True | 2843 | 31 | cross_slice_duplicates=191, fetched_pages=33, malformed_object_id=0, missing_game_system_facets=0, products_seen=2843, reported_nbhits=2843, skipped_missing_name=0, skipped_unknown_vendor=0, slices_over_pagination_cap=0, unmapped_hints=2429 |
| mfr-manticgames | ok | False | 2816 | 0 | detail_fetch_errors=255, details_fetched=2641, fetched_pages=30, gtins_found=0, products_seen=2816, reported_total=2816, skipped_unknown_vendor=0, unmapped_hints=4650 |
| mfr-para-bellum | ok | True | 406 | 1 | detail_fetch_errors=0, details_fetched=0, fetched_pages=6, gtins_found=0, products_seen=406, reported_total=406, skipped_unknown_vendor=0, unmapped_hints=90 |

## Unmapped hints

- mfr-gw-algolia: 2429
- mfr-manticgames: 4650
- mfr-para-bellum: 90

---

## Group C

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| ret-goblingaming | ERROR |  |  |  | RobotsDisallowedError: ret-goblingaming: robots.txt at https://www.goblingaming.co.uk disallows user-agent 'ClaudeBot' (Disallow: /) |
| ret-tistaminis | rate-limited |  |  |  | HTTP 429: failed to fetch /products.json (status=429) |

---

## Group D

## Acquisition health

| source | status | full sweep | observations | marked missed | stats |
|---|---|---|---|---|---|
| mfr-turbodork | ok | False | 357 | 0 | barcodes_found=329, detail_fetch_errors=0, details_fetched=357, enumeration_capped=0, enumeration_capped_by_400=0, fetched_pages=3, kept_paint_products=357, out_of_scope_vendor=12, products_seen=389, skipped_type=20, skipped_unknown_vendor=0 |
