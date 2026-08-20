"""Pure resolver: evidence + taxonomy + matches + overrides -> canonical catalog."""
from dataclasses import dataclass
from pathlib import Path

from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.catalog import CanonicalProduct, Overrides
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.resolve import crossover
from warhub_acquisition.resolve.attributes import apply_overrides, resolve_attributes
from warhub_acquisition.resolve.corroborate import find_shared_eans, resolve_ean
from warhub_acquisition.resolve.join import Matches, join_observations
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import read_yaml, write_yaml


@dataclass
class DataPaths:
    root: Path

    @property
    def evidence_products(self) -> Path:
        return self.root / "evidence" / "products"

    @property
    def catalog_products(self) -> Path:
        return self.root / "catalog" / "products"

    @property
    def sources(self) -> Path:
        return self.root / "catalog" / "sources"

    @property
    def snapshots(self) -> Path:
        """Committed normalized extracts of live third-party sources, per source id -- so a source
        that rotates or disappears can still be re-parsed offline (see gw_trade_sheets)."""
        return self.root / "snapshots"

    @property
    def mappings(self) -> Path:
        return self.root / "catalog" / "mappings"

    @property
    def taxonomy(self) -> Path:
        return self.root / "catalog" / "taxonomy"

    @property
    def matches(self) -> Path:
        return self.root / "catalog" / "matches.yaml"

    @property
    def overrides(self) -> Path:
        return self.root / "catalog" / "overrides.yaml"

    @property
    def set_refs(self) -> Path:
        """Maintainer-declared repairs for codes a manufacturer mistyped in its own contents prose
        (models/catalog.py::SetRefs). Separate from `overrides` because classify/apply.py rewrites
        overrides.yaml wholesale and would delete a hand-authored key -- as it did, 2026-08-11."""
        return self.root / "catalog" / "set-refs.yaml"

    @property
    def paint_eans(self) -> Path:
        """Every barcode the PAINT catalog publishes (scripts/gen_paint_eans.py).

        Committed rather than read out of data/paints/ directly because this resolver
        deliberately never loads the paint catalog -- see models/catalog.py:59-62, the same reason
        the boxed-set relation is generated into data/catalog/set-contents/ instead of joined
        inline. The cross-catalog question is answered once, in the generator; here it is an exact
        set-membership test."""
        return self.root / "catalog" / "paint-eans.yaml"

    @property
    def conflicts(self) -> Path:
        return self.root / "review" / "conflicts.yaml"

    @property
    def classifications(self) -> Path:
        return self.root / "catalog" / "classifications" / "products.yaml"


def _load_optional(path: Path, model: type, default: object) -> object:
    if path.exists():
        return model.model_validate(read_yaml(path))
    return default


def _dump_product(record: CanonicalProduct) -> dict:
    # `additionalEans`/`supersedes` are empty for the vast majority; omit them entirely there so
    # the published shape is byte-identical for existing products (only repackaged/superseded
    # entities carry them). `supersededBy` is None there and exclude_none already drops it.
    data = record.model_dump(mode="json", exclude_none=True)
    for optional_list in ("additionalEans", "supersedes"):
        if not data.get(optional_list):
            data.pop(optional_list, None)
    return data


def _load_mappings(directory: Path) -> dict[str, dict]:
    """`{source_id: mapping}` from data/catalog/mappings/*.yaml (empty dict if the dir is absent).

    A local copy of acquire.runner.load_mappings so this "pure resolver" module keeps its layer
    boundary -- resolve consumes the same mapping files the strategies do, but must not import the
    acquire stack (client/robots/cursor) to do it.
    """
    if not directory.exists():
        return {}
    return {path.stem: (read_yaml(path) or {}) for path in sorted(directory.glob("*.yaml"))}


def resolve_catalog(paths: DataPaths) -> dict[str, list[CanonicalProduct]]:
    taxonomy = Taxonomy.load(paths.taxonomy)
    descriptors = load_descriptors(paths.sources)
    kinds = {sid: descriptor.kind for sid, descriptor in descriptors.items()}
    category_maps = _load_mappings(paths.mappings)

    evidence = EvidenceStore(paths.evidence_products).load_all()
    unknown = set(evidence) - set(descriptors)
    if unknown:
        raise ValueError(f"evidence sources without a descriptor: {sorted(unknown)}")

    matches: Matches = _load_optional(paths.matches, Matches, Matches())
    overrides: Overrides = _load_optional(paths.overrides, Overrides, Overrides())

    # Barcodes the paint catalog already publishes, and the sources whose rows are trade units and
    # may therefore share one legitimately. Both feed the refusal in the entity loop below.
    paint_eans: dict[str, str] = {}
    if paths.paint_eans.exists():
        paint_eans = (read_yaml(paths.paint_eans) or {}).get("eans") or {}
    trade_sources = {sid for sid, descriptor in descriptors.items() if descriptor.tradeUnits}

    retracted = set(overrides.retract)
    for alias_target in matches.aliases.values():
        if alias_target in retracted:
            raise ValueError(f"matches.yaml alias targets retracted entity {alias_target!r}")
    for join_target in matches.joins.values():
        if join_target in retracted:
            raise ValueError(f"matches.yaml join targets retracted entity {join_target!r}")
    # A supersession is a published LINK, so a side that is retracted (or a self/cyclic chain)
    # would publish a pointer to nothing. Fail loudly rather than emit a dangling link.
    for retired, surviving in matches.supersessions.items():
        for side in (retired, surviving):
            if side in retracted:
                raise ValueError(f"matches.yaml supersession references retracted entity {side!r}")
        if retired == surviving:
            raise ValueError(f"matches.yaml supersession points {retired!r} at itself")
        seen = {retired}
        node = surviving
        while node in matches.supersessions:
            if node in seen:
                raise ValueError(f"matches.yaml supersessions form a cycle through {node!r}")
            seen.add(node)
            node = matches.supersessions[node]

    # Paint sources share the evidence layout but feed the PAINT catalog (see SourceDescriptor
    # .catalog and scripts/gen_paint_harvest.py). Their observations are skipped here rather than
    # stored elsewhere, so the acquire runner, cursors and health reporting stay uniform.
    #
    # ...except for the boxed multi-pot SETS among them, which are products (maintainer decision
    # 2026-08-05) and until now reached NEITHER catalog: dropped here, and gated out of every
    # bridge in gen_paint_harvest.py. `crossoverToProducts` is each paint source's declaration of
    # which of its rows those are; `crossover.matches` is the same evaluator the bridges refuse
    # with, so the two catalogs partition the source instead of both guessing. Measured 2026-08-11
    # across the six declaring sources: 562 rows selected (302 ak, 115 reaper, 69 gsw, 49
    # armypainter, 21 monument, 6 scale75), 530 admitted. Not all of them are SETS: 16 of ak's 302
    # stamp `hobby-auxiliary` off a per-clause override (crossover.py::category_for).
    observations = []
    crossover_conflicts: list[dict] = []
    # Counted separately from `observations` ON PURPOSE -- see the wipe guard below.
    product_source_observations = 0
    for source_id, source in evidence.items():
        descriptor = descriptors[source_id]
        if descriptor.catalog == "products":
            observations.extend(source.values())
            product_source_observations += len(source)
            continue
        rule = descriptor.crossoverToProducts
        if rule is None:
            continue
        spec = rule.model_dump()
        for observation in source.values():
            stamp = crossover.category_for(observation.model_dump(), spec)
            if stamp is None:
                continue
            # IDENTITY FLOOR. A record crossing catalogs must be addressable by a product code or
            # a barcode, or its entity id falls back to a slug of the store's TITLE -- which a
            # retitle silently orphans, minting a second entity and stranding the first. That is
            # the identity instability the archival-identity decision exists to prevent, so an
            # unaddressable row is surfaced as a conflict for a human rather than published as a
            # name slug. Measured 2026-08-11: 32 of 562, every one mfr-ak-interactive (which
            # publishes no barcode anywhere) with a SKU its codePattern does not match.
            #
            # THE REFUSAL IS TYPED BY THE STAMP THE ROW WOULD HAVE CARRIED, not by the word "set".
            # A per-clause `category` means one source can cross two kinds of thing (crossover.py
            # ::category_for), so the fixed `set-without-identity` this line used to emit filed 3
            # of those 32 -- AKABT111/112/113, the odourless / matt-effect / fast-dry thinners,
            # which the `category_for` call above stamps `hobby-auxiliary` -- under a type that
            # says BOXED SET. A maintainer triaging that list was reading "set" and finding a
            # bottle of thinner.
            #
            # DERIVED, not a second key, and the reason is the sort at the bottom of this function:
            # `str(sorted(c.items()))` orders each record's items BY KEY NAME, and of the five keys
            # here (`key` < `name` < `sku` < `source` < `type`) `key` comes first and is unique per
            # row, so the sort string is decided before `type` is ever reached. Measured 2026-08-11
            # over the committed 90-row conflicts.yaml: retyping moves 0 of 90 rows, while adding a
            # sibling `category:` key -- which would sort FIRST, ahead of `key` -- moves 33 of 90
            # and buries a 3-row correction in a 33-row reshuffle.
            has_code = taxonomy.normalize_code(observation.manufacturer, observation.sku) is not None
            if not has_code and canonical_ean(observation.ean) is None:
                crossover_conflicts.append(
                    {
                        "type": f"{stamp}-without-identity",
                        "source": source_id,
                        "key": observation.key,
                        "sku": observation.sku,
                        "name": observation.name,
                    }
                )
                continue
            # The category stamp is the ONLY mutation. `category` is folded from hints
            # (resolve/attributes.py), and 448 of the 562 selected rows carry `hints.category:
            # "paint"` -- publishing a 12-pot box under that is the same structural lie commit
            # 6b3c930 fixed on the paint side (re-measured 2026-08-11; it was 431 of 545 on
            # 2026-08-05, before the AK sweep widened this source).
            observations.append(
                observation.model_copy(update={"hints": {**observation.hints, "category": stamp}})
            )

    # The wipe guard asks about PRODUCT-SOURCE evidence specifically, not about `observations`.
    # Crossover broke the old `if not observations` form: a handful of boxed sets from a paint
    # source now lands in the same list, so a run where every `catalog: products` source failed to
    # load would sail past the guard with (say) 516 crossed rows, publish only the crossover
    # manufacturers, and then let the stale-file sweep below unlink every real product file.
    # Reproduced on the repo's own resolver fixtures before this fix: dropping mfr-gw and
    # ret-goblin evidence raised no exception and took games-workshop.yaml with it.
    if not product_source_observations and any(paths.catalog_products.glob("*.yaml")):
        raise ValueError("no evidence loaded but catalog files exist; refusing to wipe the catalog")

    joined = join_observations(observations, taxonomy, kinds, matches)

    conflicts: list[dict] = list(joined.ambiguous) + crossover_conflicts
    ean_resolutions = {}
    products: dict[str, list[CanonicalProduct]] = {}
    # Which entity each observation ended up in, and which observation keys carry a HUMAN forced
    # join (matches.yaml). Repackaging supersession is limited to product codes a maintainer
    # deliberately folded in this way -- an entity that only became multi-code by accident (e.g. a
    # retailer barcode typo that bridges two genuinely different products via a shared EAN) is NOT
    # a repackaging and must keep its `conflicted` flag, so the bad data stays visible.
    key_to_entity = {m.key: eid for eid, ms in joined.entities.items() for m in ms}
    forced_keys = set(matches.joins)
    # Declared lineage, alias-resolved on both sides and restricted to entities that actually
    # resolved (join_observations reports the ones that did not as `unresolved-supersession`).
    superseded_by: dict[str, str] = {}
    supersedes: dict[str, list[str]] = {}
    for retired, surviving in sorted(matches.supersessions.items()):
        retired = matches.aliases.get(retired, retired)
        surviving = matches.aliases.get(surviving, surviving)
        if retired in joined.entities and surviving in joined.entities:
            superseded_by[retired] = surviving
            supersedes.setdefault(surviving, []).append(retired)
    for entity, members in joined.entities.items():
        # retracted entities are fully suppressed -- including from the ean-shared check below
        if entity in retracted:
            continue
        suffix = entity.split("/", 1)[1]
        member_codes = {m.key: taxonomy.normalize_code(m.manufacturer, m.sku) for m in members}
        code = suffix if any(mc == suffix for mc in member_codes.values()) else None
        # Codes a forced join folded into THIS entity that differ from the surviving code: the
        # retired packaging of a repackaging join. Every observation carrying such a code is
        # superseded, so EAN + attribute resolution treat it as the old box. Empty unless a
        # matches.yaml join actually folded a different code in here.
        folded_codes = {
            member_codes[key]
            for key in forced_keys
            if key_to_entity.get(key) == entity and member_codes.get(key) not in (None, code)
        }
        superseded = frozenset(
            m.key for m in members if code is not None and member_codes[m.key] in folded_codes
        )
        ean = resolve_ean(entity, members, kinds, superseded, surviving_code=code, member_codes=member_codes)
        # THE PAINT CATALOG OWNS THIS BARCODE. A retailer (or a distributor -- mfr-warlord-store
        # lists Army Painter aerosols) selling a single pot would otherwise mint a second record
        # for a paint that data/paints/ already publishes: measured 2026-08-20, 1,058 of them,
        # every one `category: miniatures` and a single retail unit, 0 with a set-like name.
        # PR #75 fixed this one level up for paint SOURCES; `catalog` is per-source and cannot
        # help a source that legitimately sells both.
        #
        # The `tradeUnits` exemption is what keeps GW's 302 case packs, which share a barcode with
        # the pot inside them because gen_paint_barcodes.py reads the same trade rows.
        #
        # Tested against the PRIMARY ean only, not `additional`: the primary is the record's
        # published identity, and a repackaged product may legitimately retain an older barcode in
        # `additional` without being a paint. Widen this only against a measurement.
        #
        # REFUSED, NOT DROPPED: every refusal lands in conflicts.yaml. A silent skip here would
        # look identical to the source simply not having the product.
        if ean.ean and ean.ean in paint_eans:
            if not any(m.key.split(":", 1)[0] in trade_sources for m in members):
                conflicts.append(
                    {
                        "type": "paint-published-as-product",
                        "entity": entity,
                        "ean": ean.ean,
                        "paint": paint_eans[ean.ean],
                        "keys": sorted(m.key for m in members),
                    }
                )
                continue
        ean_resolutions[entity] = ean
        conflicts.extend(ean.conflicts)
        record = resolve_attributes(
            entity, members, kinds, ean, code, superseded=superseded, category_maps=category_maps,
            member_codes=member_codes,
        )
        # Stamped before apply_overrides so a hand override can still correct a link.
        record.supersededBy = superseded_by.get(entity)
        record.supersedes = sorted(supersedes.get(entity, []))
        product = apply_overrides(record, overrides)
        # gameSystem is OPTIONAL: a product genuinely belonging to no game system (a base, a
        # gaming mat, a paint/tool bundle, dice, an advent calendar, ...) publishes with
        # gameSystem: null rather than being parked out of the catalog. classify/queue.py
        # surfaces every such product from the resolved catalog for optional classification.
        products.setdefault(product.manufacturer, []).append(product)

    conflicts.extend(find_shared_eans(ean_resolutions))

    paths.catalog_products.mkdir(parents=True, exist_ok=True)
    produced = set()
    for manufacturer in sorted(products):
        records = sorted(products[manufacturer], key=lambda p: p.id)
        write_yaml(
            paths.catalog_products / f"{manufacturer}.yaml",
            {
                "manufacturer": manufacturer,
                "products": [_dump_product(record) for record in records],
            },
        )
        produced.add(f"{manufacturer}.yaml")
    for stale in sorted(paths.catalog_products.glob("*.yaml")):
        if stale.name not in produced:
            stale.unlink()

    write_yaml(paths.conflicts, {"conflicts": sorted(conflicts, key=lambda c: str(sorted(c.items())))})
    return {manufacturer: sorted(records, key=lambda p: p.id) for manufacturer, records in sorted(products.items())}
