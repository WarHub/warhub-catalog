# Addendum — Paint catalog adoption of the shared storage model

**Date:** 2026-07-07
**Parent spec:** `2026-07-07-catalog-storage-model-design.md`
**Sibling addendum:** `2026-07-07-availability-lifecycle-addendum.md` (products)
**Status:** Approved (user decisions, Plan 2 kickoff)

Plan 1 built the shared `WarHub.CatalogStore` library and adopted it in the **product** tool.
Plan 2 adopts the **same** library in the **paint** tool (`WarHub.PaintCatalog.Tool`), giving
paints the identical stability guarantees: append-only reconciliation, a liveness ledger, forced
quoting, deterministic order, and a one-time idempotent migration — with a paint-specific payload.

The parent spec left three paint specifics open. Grounded in an analysis of the current
`data/paints/brands/*.yaml` (19 brands, ~7,145 paints), they are decided as follows.

## 1. Paint identity key — `set | name | productCode | hex`

Within a brand file, paint **names collide heavily** (903 duplicate-name groups) and even
**product codes collide** in some brands (e.g. `ak-real-color` has 181 duplicate-code groups).
Measured collisions of candidate keys across the full dataset:

| Candidate key | Collisions |
| --- | --- |
| `name` | ~903 groups |
| `set \| name` | 50 (genuine distinct paints — e.g. Vallejo *Game Air / Alien Purple* exists twice with different codes+hex) |
| `set \| name \| productCode` | 4 |
| **`set \| name \| productCode \| hex`** | **0** |

**Decision:** identity key = `normalize(set) | normalize(name) | productCode | hex`.
- **0 collisions** on the current dataset → **every archival record is preserved** at migration
  (strict adherence to the never-drop directive; no silent merges).
- `normalize` = the shared `NameNormalizer` (NFKC → lowercase → trim → collapse whitespace →
  strip surrounding quotes); applied to `set` and `name`. `productCode` and `hex` are compared
  as-is (already canonical); a missing code contributes an empty segment.
- **Accepted risk:** `hex` is part of identity, so a future swatch/color backfix mints a new key
  and would appear as a duplicate until stitched by an `aliases:` override. Paint hex corrections
  are rare and this is the explicit, documented escape hatch.
- **Rename fallback (`adapter.Url`) returns `null` for paints.** The composite key is already
  strong; product-code and image URLs are non-unique/often-empty in paint data and would cause
  false-positive renames. Rare genuine renames are handled by `aliases:` overrides.

The **ledger key** (globally unique) is `{brandSlug}/{identityKey}`.

## 2. Packaging field clash — rename to `container`

Paints carry a `packaging` field meaning **bottle type** (`dropper` / `pot` / `spray`), which
collides with the product schema's `packaging` axis (`single | bundle | box | starter`). To keep
`packaging` meaning exactly one thing across both catalogs:

- Rename the paint field `packaging` → **`container`** (value-preserving; migration renames it).
- Paints do **not** carry the product `packaging` axis (every paint is an individually-sold unit;
  the axis would be uniform noise). Paint **sets** are already handled in the *product* catalog
  (`category: paint`, `packaging: bundle`).
- Paints gain the shared-core fields: `category` (constant `paint`), `status`, `availability`,
  `firstSeen`.

## 3. Record shape — paint specifics nested under `details:`

Shared core lives at the top level; paint-specific color/physical fields nest under `details:`
(realizing the parent spec's `details` extension point).

```yaml
- name: Retributor Armour
  category: paint             # constant for this catalog
  status: current             # current | suspected-discontinued | discontinued | delisted
  availability: unknown       # in_stock | out_of_stock | pre_order | limited | unknown
  firstSeen: 2026-07-07       # write-once, immutable
  productCode: '...'          # identity component; quoted if ambiguous
  ean: '...'                  # ALWAYS quoted
  imageUrl: '...'
  details:
    set: Base
    r: 138
    g: 110
    b: 62
    hex: '#8A6E3E'
    volumeMl: 12
    container: pot            # was `packaging`
    type: Base
    finish: Metallic
```

**Top-level field order:** `name, category, status, availability, firstSeen, productCode, ean,
imageUrl, details`. **`details` field order:** `set, r, g, b, hex, volumeMl, container, type,
finish`. Field order drives YAML order (stable C# property order).

### Working model vs archival record
Mirroring products (`RawProduct` → `Product`), the existing flat `Paint` record stays the
**working model** the markdown parser, enrichers, scrapers, and equivalence finder operate on
(unchanged). A new **archival `PaintRecord`** (core + `details`) is built from the enriched working
`Paint` immediately before reconciliation and is the only shape written to disk / reconciled /
ledgered. This isolates the nesting to one mapping point and leaves every enricher untouched.

## 4. Lifecycle / availability mapping (from `isDiscontinued`)

Paints have no scraped stock signal; the only lifecycle input is the legacy `isDiscontinued` bool
(and `(discontinued)` set-name markers already folded into it by the parser).

| `isDiscontinued` | `status` | `availability` |
| --- | --- | --- |
| `true` | `discontinued` | `out_of_stock` |
| `false` | `current` | `unknown` |

- **Merge rule (status):** `fresh.Status is "discontinued" or "delisted" ? fresh.Status :
  existing.Status` — identical to products; a source-confirmed discontinuation wins and is sticky,
  a later `current` never un-discontinues.
- **Merge rule (availability):** update-present / keep-on-empty, default `unknown`.
- The ledger's `suspected-discontinued` auto-flag + reactivation apply exactly as for products,
  gated on the per-brand source-success signal.

## 5. Churn removal & determinism (same as products)

- Drop the fully-exploded `generatedAt` DateTime block and the derived `paintCount` /
  `totalPaints` from brand files and manifest. Counts recompute at publish; a single ISO timestamp
  (if wanted) lives once in the ledger.
- Force-quote ambiguous scalars via the shared `QuotingEventEmitter` (fixes numeric-looking EANs /
  product codes / hex).
- Deterministic record order: by identity key (`Ordinal`).
- Sidecar `data/paints/_liveness.yaml` is the only file expected to change on an uneventful run.

## 6. Migration

One-time, idempotent `PaintMigrator` over `data/paints/brands/*.yaml`:
- Read legacy shape tolerantly (flat fields + `generatedAt` + `paintCount` + `packaging` +
  `isDiscontinued`).
- Build `PaintRecord`: `category: paint`; map `isDiscontinued` → `status`/`availability` (§4);
  rename `packaging` → `details.container`; nest color/physical fields under `details`;
  backfill `firstSeen` only-when-absent (migration date); quote EANs/codes; drop `generatedAt` /
  `paintCount`; re-sort by identity key; re-serialize.
- Seed `data/paints/_liveness.yaml` with every current key `{brandSlug}/{identityKey}` marked
  seen at the migration date, `missStreak: 0`, only-if-absent.
- **Idempotency is a hard requirement:** running it twice yields zero diff.

## 7. Out of scope (Plan 2)

- Publisher changes for the new paint schema (Plan 3).
- Merging paint and product trees (explicitly rejected in the parent spec).
- New paint sources or enrichment providers.
- The `equivalences.yaml` payload shape is unchanged (equivalence still computes from the flat
  working model in memory).
