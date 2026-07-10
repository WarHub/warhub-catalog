# Addendum — Availability / Lifecycle split + durable retract

**Date:** 2026-07-07
**Parent spec:** `2026-07-07-catalog-storage-model-design.md`
**Status:** Approved (user decisions at Task 11 checkpoint)

Two user decisions during implementation expand the product schema and the retract semantics.

## 1. Durable retract (suppress-on-input)

Retract is no longer only an output filter. A retracted identity must never enter the catalog
while it stays listed in `overrides.yaml`. The reconciler must:

- **Drop fresh records** whose identity key is in the `retracted` set (never insert them), so a
  bad record that is *still live on the source* stays suppressed every run instead of reappearing
  as a new record with a reset `firstSeen`.
- **Not rename onto a retracted target:** the URL/alias fallback must skip a matched existing
  record whose key is in `retracted` (prevents a rename from resurrecting a retracted record under
  a new key).
- **Keep the output filter:** existing records whose key is in `retracted` are still dropped from
  output.

## 2. Availability / lifecycle split

`Product` gains a second status axis. The two are orthogonal:

### `status` — lifecycle (sticky, archival)
Values: `current | suspected-discontinued | discontinued | delisted`.
- Default `current`. A **scrape never sets lifecycle** — the enricher always emits `current` for
  scraped products.
- The **ledger** auto-sets `suspected-discontinued` (after N misses) and reactivates to `current`.
- **Humans / overrides** set `discontinued` / `delisted`.
- **Merge rule:** `Status = (fresh.Status is "discontinued" or "delisted") ? fresh.Status :
  existing.Status`. Rationale: since the enricher only ever emits `current`, a fresh
  `discontinued`/`delisted` can only have come from an override, so it wins; otherwise the archived
  lifecycle is sticky (a scrape's `current` never resets a managed state; ledger transitions and
  overrides are the only other mutators). This replaces the earlier `IsManagedStatus` preserve rule.

### `availability` — volatile (scrape-driven)
Values: `in_stock | out_of_stock | pre_order | limited | unknown`. `required` (always present).
- Reflects current purchasability. **Merge = update-present / keep-on-empty** from the fresh scrape.
- **Scraper mapping** (from the raw availability signal / `NormalizeStatus` input):
  - available / in stock / current → `in_stock`
  - out of stock → `out_of_stock`
  - pre-order → `pre_order`
  - limited → `limited`
  - "no longer available" / discontinued → `out_of_stock` (lifecycle stays `current`; genuine
    disappearance is what the ledger's `suspected-discontinued` is for)
  - unknown / blank → `unknown`

### Field order
`Product` field order becomes: `Name, Category, Packaging, Status, Availability, FirstSeen, Ean,
EanSource, Sku, ProductCode, PriceGbp, PriceUsd, PriceEur, Url, ImageUrl, ReleaseDate, Description,
Contents`.

## 3. Migration mapping (legacy `status` → new split)

| Legacy `status` | New `status` | New `availability` |
| --- | --- | --- |
| `current` | `current` | `in_stock` |
| `discontinued` | `discontinued` | `out_of_stock` |
| `pre_order` | `current` | `pre_order` |
| `out_of_stock` | `current` | `out_of_stock` |
| `limited` | `current` | `limited` |
| (anything else / blank) | `current` | `unknown` |

Legacy `discontinued` is preserved as a confirmed lifecycle state (user decision), even though it
was originally scrape-inferred. Idempotency: a record already carrying both `status` and
`availability` in the new vocabulary is left unchanged by re-migration.
