# gameSystem becomes optional -- implementation report

## Summary

gameSystem is now optional end-to-end. The resolver publishes products with `gameSystem: null`
instead of parking them into `conflicts.yaml`'s `unclassified-entity` type; the .NET publisher
accepts a null gameSystem, publishes it (omitted from JSON, per this codebase's existing
null-omission convention for every other optional field), and excludes such products from every
`products/by-system/*.json` partition while keeping them in `products.json` /
`products/index.json`.

## Touchpoints changed

### Python (`tools/acquisition`)

- `src/warhub_acquisition/resolve/resolver.py` -- removed the `if product.gameSystem is None:
  park` block in `resolve_catalog`. Every resolved product is now written to
  `catalog_products/*.yaml`, including null-gameSystem ones (still `exclude_none=True`, so the
  field is simply absent from the YAML rather than `gameSystem: null`).
- `src/warhub_acquisition/classify/queue.py` -- rewrote `build_queue`'s entity-selection source.
  Renamed `_parked_entity_ids` -> `_unclassified_entity_ids`: it now reads
  `data/catalog/products/*.yaml` and collects every product id whose `gameSystem` key is absent,
  instead of reading `unclassified-entity` rows from `conflicts.yaml` (which no longer exist).
  `_joined_entities` (re-running the join step to recover raw per-source hints, since
  `CanonicalProduct` only folds in `category`/`packaging`/`quantity`/`description`) is unchanged
  and still supplies name/url/description/hints for each queue item -- same item shape as before
  (entity/name/manufacturer/url/description/hints/candidates), same shared-candidates-dict
  identity trick.
- `src/warhub_acquisition/classify/apply.py`, `src/warhub_acquisition/cli.py` -- docstring/CLI
  help text updated to stop describing a "parking" mechanism that no longer exists (no behavior
  change).
- `src/warhub_acquisition/classify/joins.py` -- **left functionally untouched** (only a
  clarifying docstring comment added). It reads `unclassified-entity` conflicts directly from
  `conflicts.yaml` via its own `_parked_entity_ids`/`_parked_entity_contexts`, independent of
  resolver.py. Since the resolver no longer emits that conflict type, those helpers now simply
  return nothing for real `resolve` runs, and every entity (including null-gameSystem ones) is
  picked up automatically by `_resolved_entity_contexts` instead (it already reads
  `catalog_products/*.yaml` unconditionally). The existing hand-seeded-conflicts unit tests in
  `test_classify_joins.py` (which write `unclassified-entity` rows directly, not via the resolver)
  keep passing unmodified because the read path itself was not removed -- I judged rewriting this
  read path out of scope since it isn't part of the stated touchpoints and isn't required for
  correctness (the resolved-catalog path already covers every entity going forward).

### Tests (Python)

- `tests/test_resolver.py` -- `test_unclassified_entity_is_parked` ->
  `test_null_game_system_entity_publishes_with_no_conflict`: now asserts the entity is IN the
  resolved catalog with `gameSystem is None`, `conflicts.yaml` has zero conflicts, and the
  written YAML omits the `gameSystem` key entirely for that record. Every other conflict-type
  test (`ean-mismatch` via `test_barcode_db_*`, `cross-manufacturer-ean`/`ambiguous-join` logic
  in join.py -- untouched, `barcode-db-unjoined` via
  `test_barcode_db_alone_two_sources_stays_provisional_not_confirmed`) is unchanged.
- `tests/test_classify_queue.py` -- `seed()` docstring updated; the shape test no longer injects
  a conflicts-filtering probe (build_queue no longer reads conflicts.yaml at all) and instead
  asserts `conflicts.yaml == {"conflicts": []}` after resolve. Renamed
  `test_build_queue_no_parked_entities_is_empty` ->
  `test_build_queue_no_null_game_system_products_is_empty` (unchanged body -- empty
  `catalog_products` still yields `[]`). Rewrote
  `test_build_queue_missing_evidence_for_conflict_raises` ->
  `..._for_null_game_system_product_raises`: now seeds a resolved-catalog product record with no
  matching evidence (instead of a hand-written `unclassified-entity` conflict) to exercise the
  same "has no matching evidence" `ValueError`. Rewrote the REPO_DATA test
  (`test_repo_build_queue_covers_all_parked_entities` ->
  `test_repo_build_queue_covers_all_null_game_system_products`): self-consistency is now checked
  against null-`gameSystem` counts in the real `data/catalog/products/*.yaml`, not against stale
  `conflicts.yaml` counts, and the `assert parked > 0` literal was dropped -- see verification
  note below on why this is legitimately 0 today.
- `tests/test_golden_fixture.py` -- extended `_seed()`'s in-code catalog with a third product,
  "Citadel Painting Handle" (a tool -- the same category of real product, alongside bases, gaming
  mats, dice, advent calendars, that has no game system), single manufacturer-source observation
  with a directly-asserted EAN (`5011921194803`, GS1-valid) and no `gameSystem` hint. Single
  authoritative (`kind: manufacturer`) source -> `eanConfidence: confirmed` via the same
  `resolve_ean` path Necrons exercises. Regenerated the fixture via
  `REGEN_GOLDEN=1 uv run pytest -q tests/test_golden_fixture.py` and committed the resulting byte
  diff to
  `tools/WarHub.Catalog.Publish.Tests/fixtures/canonical-golden/products/games-workshop.yaml`
  (taxonomy fixture files were regenerated too but produced no diff, as expected). The generated
  record has no `gameSystem` line at all, confirming `exclude_none` omission.

### .NET (`tools/WarHub.Catalog.Publish`)

- `ProductBuilder.cs` -- removed the `InvalidOperationException` on null `GameSystem`. Now: if
  `GameSystem` is null/empty, the built `ProductRecord` (with `GameSystem = null`) is added to a
  new `systemless` list instead of any partition dict; it flows into the consolidated
  `products.json`/`products/index.json` totals but is never added to any `partitions[key]`, so no
  `products/by-system/*.json` file ever contains it. The two other guards (unmapped
  non-null-gameSystem slug; unmapped faction slug) are untouched and still throw, independent of
  whether gameSystem is null. Consolidated ordering: partitioned products first (by partition key,
  then name/ean as before), systemless products appended after (sorted by the same name/ean
  comparator) since they have no partition key to sort by.
- `schema/product-catalog.json` -- `gameSystem`'s type changed from `"string"` to `["string",
  "null"]`. Note: this has no observable effect on today's actual JSON output, because
  `JsonConfig.Options` already sets `DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull`
  globally, so a null `GameSystem` is *omitted* from the serialized product object, not emitted as
  a literal `"gameSystem": null` -- exactly like `faction`/`priceCad`/every other optional field
  in this schema already behaves (see `CanonicalGoldenTests.Faction_present_resolves_to_its_label_and_absent_faction_is_omitted`
  for the pre-existing precedent). I followed that established convention rather than special-
  casing `gameSystem` to serialize a literal null, to keep the wire format internally consistent.
  The schema edit is still correct/useful as documentation of the conceptual nullability, and was
  already schema-valid before my change too (gameSystem was never in the `required` list -- the
  `InvalidOperationException` was a C#-level guard, not a schema constraint).

### Tests (.NET)

- `ProductBuilderGuardTests.cs` -- `Null_game_system_throws_naming_the_product_id` ->
  `Null_game_system_publishes_and_is_excluded_from_by_system_partitions`: builds a single
  null-gameSystem product, asserts `Build` returns `1` (no throw), asserts no
  `products/by-system/*` file entry exists in `writer.Files`, and parses the written
  `products.json` to assert the product is present with `name` correct and `gameSystem` absent
  (`TryGetProperty` false) -- proving the "null in JSON" requirement means "represented as
  absent/nullable," consistent with the rest of the schema, not a literal JSON `null` token. The
  other two guard tests (`Missing_game_system_label_throws_naming_the_slug`,
  `Missing_faction_label_throws_naming_the_slug`) are byte-for-byte unchanged.
- `CanonicalGoldenTests.cs` -- `Both_products_are_published` -> `All_three_products_are_published`
  (asserts `3`). Added `Null_game_system_product_publishes_with_gameSystem_omitted_and_no_partition`:
  asserts the Painting Handle's `gameSystem` is absent, its `ean`/`eanConfidence` flow through
  correctly, and that it appears in none of the `products/by-system/*.json` partition files on
  disk (or that no such directory exists at all, if there happened to be zero partitions -- not
  the case here since Necrons/Death Guard still produce `warhammer-40k.json`).

## Cache-still-skips-decided-unknowns verification

Claim to verify: an entity previously queued (while still parked) that the LLM already answered
"unknown" for must NOT be re-queried now that it's selected via the resolved catalog instead of
`conflicts.yaml`.

`compute_input_hash` (`classify/_llm_common.py`) hashes the sorted-key canonical JSON of the
**whole queue item dict** (entity/name/manufacturer/url/description/hints/candidates). The
selection-source change in `queue.py` only affects *which entity ids* get built into queue items
-- it does not change *how* an item's fields are computed for a given entity id: `build_queue`
still calls the same `_joined_entities`/`_first`/`_raw_hints` machinery over the same evidence to
produce name/manufacturer/url/description/hints, and the same `_observed_factions_by_game_system`/
`load_labels` machinery to produce `candidates`. For an entity whose evidence and taxonomy are
unchanged between two runs, the resulting item dict -- and therefore its `compute_input_hash`
value -- is byte-identical regardless of whether the entity was found via a parked-conflicts scan
or a null-gameSystem catalog scan. `llm.py`'s cache lookup (`cache.get(input_hash)`) is keyed
purely on that hash, so a cache entry recorded under the old selection mechanism still hits under
the new one, and the "unknown" `cached_skips` branch still fires without a new API call. This
holds regardless of the fact that the entity was previously *entirely absent* from
`catalog_products/*.yaml` (parked) and is now present there with `gameSystem` omitted -- that
absence/presence is not part of the hashed item.

## Real data note

Per instructions, `resolve` was NOT run against `data/`. `data/review/conflicts.yaml` still
carries its pre-existing 1,717 `unclassified-entity` rows (stale, from the last real `resolve`
run under the old parking behavior) and `data/catalog/products/*.yaml` still has zero
null-gameSystem entries, since nothing re-resolved it. This is why
`test_repo_build_queue_covers_all_null_game_system_products` now legitimately asserts `len(queue)
== 0` against the real repo data -- it will start returning the ~1,700 previously-parked products
once the controller re-runs `resolve` against `data/` in the data wave.

## Test results

- Python (`uv run --no-sync pytest -q` in `tools/acquisition`): **453 passed, 4 deselected**
  (same totals as the stated baseline -- tests were renamed/rewritten in place rather than net
  added, except the golden fixture test which was extended, not duplicated).
- .NET (`dotnet test WarHub.Catalog.slnx`): **843 passed, 0 failed** (baseline 842 + 1 net-new
  fact: `ProductBuilderGuardTests`'s guard test was renamed/repurposed 1-for-1, and
  `CanonicalGoldenTests` gained one new fact while its `Both_products_are_published` fact was
  renamed 1-for-1 to `All_three_products_are_published`). Per-project breakdown:
  `WarHub.Catalog.Publish.Tests` 32, `WarHub.CatalogStore.Tests` 65,
  `WarHub.PaintCatalog.Tool.Tests` 283, `WarHub.ProductCatalog.Tool.Tests` 463.

## Concerns / judgment calls flagged for review

1. **"null in JSON" wording vs. actual omission.** The task text says the null-gameSystem guard
   test should assert the product "PUBLISHES (null in JSON, ...)". I implemented and tested
   "gameSystem key absent from the JSON object" rather than a literal `"gameSystem": null`
   token, because that's what `JsonConfig`'s global `WhenWritingNull` ignore condition already
   does for every other optional field (faction, priceCad, url, ...), and special-casing
   gameSystem to serialize literally would be an inconsistent wire format for no functional
   benefit (JSON Schema already treats the property as optional either way). Flagging this
   interpretation explicitly in case "literal null" was actually intended.
2. **`classify/joins.py` left unmodified.** Its `_parked_entity_ids`/`_parked_entity_contexts`
   helpers read `unclassified-entity` conflicts directly and are now effectively dead code against
   real `resolve` output (though still exercised by hand-seeded unit tests). I did not rewrite
   this path since it wasn't a listed touchpoint and doesn't need to change for correctness (every
   entity, parked or not, now flows through `_resolved_entity_contexts` once `resolve` actually
   runs) -- but it's worth a follow-up cleanup pass to delete the now-always-empty helpers once the
   controller confirms the data wave is complete and no stale `conflicts.yaml` files with that
   type remain in play.
