# Addendum — Publisher adoption of the new catalog schema

**Date:** 2026-07-07
**Parent spec:** `2026-07-07-catalog-storage-model-design.md`
**Siblings:** `2026-07-07-availability-lifecycle-addendum.md` (products), `2026-07-07-paint-adoption-addendum.md` (paints)
**Status:** Approved (user decisions, Plan 3 kickoff)

Plan 1 migrated the **product** data model and Plan 2 the **paint** data model. Plan 3 updates the
**publisher** (`WarHub.Catalog.Publish`) to read the new source schema and surface the new fields in
the published JSON. This is Plan 3 of 3; the full feature merges to `main` after all three.

## 1. Correctness — the paint reader is currently broken

`YamlSource.LoadBrands` deserializes `data/paints/brands/*.yaml` into the paint tool's **flat**
`BrandCatalog`/`Paint` model. Plan 2 rewrote those files into the **nested** `PaintRecord` shape
(`hex`/`set`/`r`/`g`/`b`/`type`/`finish` now live under a `details:` block). With
`IgnoreUnmatchedProperties`, the flat model reads those as empty/default — so published paints would
have blank `hex`/`range`/`type`/`finish`. **This must be fixed.** The publisher's own tests do not
catch it because their fixtures still use the pre-migration YAML shape; the fixtures must be updated
to mirror what the tools now emit.

**Approach:** the publisher gets **local read-DTOs** for the new brand-archive shape (mirroring the
existing `EquivFile`/`EquivRef` local read-models), decoupling the publisher's read contract from the
tool's internal model and avoiding a name clash with the publisher's own output `PaintRecord`. The
**product** reader already works — the product tool's `Product` model already matches the new schema
— so only the product *surfacing* (below) and its fixture change.

## 2. Surfacing — Rich (user decision)

No consumers exist yet, so there is **no back-compat constraint**; the published record schema may
grow directly. The published document envelope, partitioning, indexes, and manifest are unchanged.

**Published product record** gains: `category`, `status`, `availability`.
**Published paint record** gains: `category` (constant `paint`), `status`, `availability`,
`volumeMl`, `container`.

Existing fields are unchanged. New fields are added to the `product` / `paint` `$defs` in the JSON
schemas (`schema/product-catalog.json`, `schema/paint-catalog.json`). Field additions are optional
in the schema (not `required`) so a record missing one still validates; the builders always populate
them from the source. `schemaVersion` stays `1.0` (additive, no consumers).

Not surfaced this plan (trivial future adds if wanted): product `packaging`, `firstSeen`; paint
`firstSeen`, `ean`, `productCode`.

## 3. Filtering — include everything (user decision)

The published catalog **mirrors the archive**: every record is published regardless of `status`
(`current` / `suspected-discontinued` / `discontinued` / `delisted`). Consumers filter client-side
via the surfaced `status` field. No lifecycle filtering happens at publish time. This matches the
project's archival philosophy ("archive every release, ever").

## 4. Counts

Already satisfied — the publisher computes all `counts` at publish time; the source files carry no
derived counts (Plan 1/2 dropped them). No change needed.

## 5. Verification

Beyond unit tests on updated fixtures, Plan 3 runs the publisher against the **real** migrated
`data/` tree end-to-end (products + paints + equivalences): it must complete, every emitted document
must pass the publisher's own schema validation, and the published record counts must reflect the
full archive (no records dropped). This is the end-to-end proof that the three-plan stack composes.
Published output (`dist/`) is git-ignored and not committed.

## 6. Out of scope (Plan 3)

- Changes to the document envelope, partitioning scheme, index, or manifest structure.
- New published partitions (e.g. by-status).
- The `equivalences.yaml` shape (unchanged; still generated from the flat working model).
