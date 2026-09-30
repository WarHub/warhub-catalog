# Correcting a data fact

Start from the symptom. Each mechanism's authority is the header or docstring named in its **File**
cell. This table points at those, and where it disagrees with one, the header is right and this
page is stale.

Not everything needs correcting. Sources that disagree while no evidence settles which is right
stay in `data/review/conflicts.yaml` as `ean-mismatch`. That row is the catalog saying so honestly,
and none of the mechanisms below exists to silence it.

Before applying an entry, predict what it changes (conflict rows, ids, barcodes). Afterwards,
check that exactly that happened.

**Run afterwards** uses three sequences:

- **R**, from `tools/acquisition`: `uv run warhub-data resolve --data ../../data`, then
  `uv run warhub-data categorize --data ../../data`, then
  `uv run warhub-data report --data ../../data --ean-guard`. The order comes from `matches.yaml`'s
  header, and README pipeline step 2 says why `categorize` must follow `resolve`. Guard exit 5
  means a barcode HEAD attests (a confirmed primary, any `additionalEans` entry, any paint
  barcode) is now held by no record. A dropped provisional barcode is reported but passes.
- **S**, from the repo root: `uv run --with pyyaml python tools/acquisition/scripts/gen_set_contents.py`.
- **T**: `uv run pytest -q` from `tools/acquisition`. `tests/test_repo_data.py` holds the
  tripwires that fail on an entry that names nothing or no longer takes effect.

## `data/catalog/matches.yaml`

Keys on the left are an observation key (`source_id:key`) or an entity id (`manufacturer/code`),
as each **File** cell says.

| Symptom | Evidence bar | Effect | File | Run afterwards |
|---|---|---|---|---|
| One product is published as two records: an archive capture, a listing with no code of its own, or a second store page for the same SKU. Or an `ambiguous-join` row, where a code-less listing's name matches two records. | The two are one product, and merging them destroys no product code and no barcode; that is the header's line between a join and a supersession. A name match alone does not qualify. For an `ambiguous-join`, find the listing's own barcode. | That observation joins the named entity. Anchor priority decides which id survives, so an entry may point at the other side's id. | `joins`: `{source_id:key: entity id}`. Authority: the header's "JOIN or SUPERSESSION?" | R, T |
| One product exists under two codes and two barcodes (a re-code, a repackaging, a new edition of the same box) and nothing links them. Or a `readyToPromote` edge in `data/review/supersession-proposals.yaml`. | Both sides have the same contents. A material, roster or edition-content change makes them distinct products with no lineage. | Both records are published: the retired one gains `supersededBy`, the current one gains `supersedes`, and no shared barcode can re-merge them. Keyed by the retired id, so a second entry replaces the first. | `supersessions`: `{retired id: current id}`. Authority: the header, and `Matches.supersessions` in `resolve/join.py` | R, T |
| One box carries two of the maker's own codes and one barcode (re-coded, not re-barcoded), and the old code appears nowhere. | The same box, with one barcode. If the old code has a barcode of its own, it is a supersession. | Rows carrying the alias code are read as the canonical code. The record publishes the alias in `additionalCodes`. | `codeAliases`: `{alias id: canonical id}`. Authority: `Matches.codeAliases` | R, T |
| A maker's web-only bundle (a book sold with a special figure) carries its component's barcode under its own code. The two fuse, or the bundle takes the barcode. | The maker sells both under separate codes, and the barcode is printed on the component. Nothing was retired, so it is not a supersession. | The barcode stays with the component and is dropped from the bundle's rows. The two stay two records, and the bundle publishes `bundleOf`. | `bundles`: `{bundle id: component id}`. Authority: `Matches.bundles` | R, T |
| A listing's SKU names the wrong product code, fusing two different products into one record. | That one row is demonstrably mis-coded, and its barcode is right. If the barcode is the wrong part, use `rejectEans`: rejecting a barcode here would discard a correct one. | Before grouping, the row takes the corrected code, and the other product splits back out. | `reassignCodes`: `{source_id:key: code}`. Authority: `Matches.reassignCodes` | R, T |
| A row is filed under the wrong maker, because its source took the maker from a shelf, a path or a store's `vendor` field. It shows as `cross-manufacturer-ean`, `ean-shared`, or one code under two manufacturers. | The item's own manufacturer, or its GS1 company prefix, says otherwise, and the entry says which. A whole source that files by shelf is fixed by `manufacturerIsShelf` on its descriptor (see that field's comment); this list is for single rows. | Applied before anything else: the row groups, is named and publishes as that maker's. | `reassignManufacturer`: `{source_id:key: slug}`. Authority: `Matches.reassignManufacturer` | R, T |
| One listing asserts a barcode that belongs to a different product. It merges two records through the barcode union, or publishes someone else's barcode in `additionalEans`. | The item's own manufacturer asserts a different barcode, or the GS1 prefix belongs to someone else. "Two sources disagree" does not qualify. | That observation's barcode is disbelieved, and everything else it says stands. If it was a confirmed or additional barcode and no other record holds it, the guard reports it `lost` until `withdrawn-eans.yaml` names it. | `rejectEans`: `{source_id:key: [ean]}`. Authority: `Matches.rejectEans` | R, T |
| An `ean-mismatch` row whose sources disagree about one product's barcode. The loser cannot be shown to be something else, but the automatic primary is the wrong one. | Evidence about the value, not about who asserts it. The value must be one the entity's own evidence asserts. | Sets the primary. Every rival stays in `additionalEans`, the record stays `conflicted`, and only the `conflicts.yaml` row goes. | `preferEans`: `{entity id: ean}`. Authority: `Matches.preferEans` | R, T |
| A record's id changed (its maker was corrected, its code respelled), and a pointer in this repo still names the old id: a join target, a supersession side or a `withdrawn-eans.yaml` key. | The rename happened. | Moves no observation. Anything that still names the old id resolves to the new one: a group the resolver would name that way, a join target, a supersession, bundle or `codeAliases` side, or a `withdrawn-eans.yaml` key. It is not published. | `aliases`: `{old id: current id}`. Authority: the section's own comment, and `docs/OBJECTIVES.md` 3 | R, T |

## The other hand-authored files

| Symptom | Evidence bar | Effect | File | Run afterwards |
|---|---|---|---|---|
| A published field is wrong, and fixing it is a maintainer's decision rather than a correction to evidence. | A person decided it. Nothing machine-written belongs here. | The patch applies after every source and sets that axis's basis to `override`. | `data/catalog/overrides.yaml` `products`: `{entity id: {field: value}}`. Authority: the file header | R, T |
| A record is genuinely bad or invalid. Looking redundant does not count. | `docs/OBJECTIVES.md` 1. Re-home its barcodes before retracting it (OBJECTIVES 3). | The entity is suppressed from the catalog entirely, and the resolver refuses any join, alias or supersession that points at it. | `data/catalog/overrides.yaml` `retract`: `[entity id]`. Authority: `resolve_catalog` in `resolve/resolver.py` (the header states no bar) | R, T |
| A boxed set's member lands under `unresolved` because the maker mistyped a code in its own contents text. | A human states the correction for one product, with the evidence beside it. The mistyped ref must still be in that product's `contentSkus`, and the corrected code must name exactly one paint. | The member looks up the corrected code. `ref` keeps the printed string, and the member carries `resolvedBy: correction`. | `data/catalog/set-refs.yaml` `setRefs`: `{product id: {printed ref: real code}}`. Authority: `SetRefs` in `models/catalog.py` | S, T |
| The guard reports a published barcode `lost` because a source changed the barcode on a listing it already had, and nothing attests the old value any more. | `git log -S <ean>` over `data/catalog/products` shows it was published, and no source attests it now. A barcode that was only ever seen does not qualify. | Re-attached to that record's `additionalEans`. It is additive only: it never touches a primary, never removes anything, and never resurrects a retracted record. | `data/catalog/retained-eans.yaml` `retained`: `{product id: [ean]}`. Authority: the file header and `RetainedEans` | R, T |
| A published barcode has been shown to belong to something else, and removing it with `rejectEans` makes the guard report it `lost`. | `docs/OBJECTIVES.md` 1: the value belongs to a different named product, or a reseller minted it. An uncorroborated barcode stays published and `conflicted`. | The guard reports the barcode `withdrawn` rather than `lost`. An entry only ever records a removal and never adds a barcode. The removal itself is the paired `rejectEans` entry, and this file is what tells the guard it was deliberate. | `data/catalog/withdrawn-eans.yaml` `withdrawn`: `{id the release published: [ean]}`. Authority: the file header and `WithdrawnEans` | R, T |

Paint records are corrected in `data/paints/overrides.yaml`, whose header is the reference, and
the paint catalog is regenerated as [AGENTS.md](../AGENTS.md) describes.
