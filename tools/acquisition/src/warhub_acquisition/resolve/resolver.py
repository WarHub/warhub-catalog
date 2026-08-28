"""Pure resolver: evidence + taxonomy + matches + overrides -> canonical catalog."""
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.catalog import CanonicalProduct, Overrides, RetainedEans
from warhub_acquisition.models.descriptor import SourceDescriptor, load_descriptors
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve import crossover
from warhub_acquisition.resolve.attributes import apply_overrides, resolve_attributes
from warhub_acquisition.resolve.corroborate import find_shared_eans, resolve_ean
from warhub_acquisition.resolve.join import Matches, join_observations
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.vocabulary import load_vocabulary
from warhub_acquisition.yamlio import dump_yaml, read_yaml, write_yaml


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
    def retained_eans(self) -> Path:
        """Barcodes this catalog published that no source attests any more (models/catalog.py
        ::RetainedEans). Hand-authored, like set_refs and for the same reason: overrides.yaml is
        rebuilt by `classify --apply` through plain PyYAML and cannot keep the evidence beside an
        entry."""
        return self.root / "catalog" / "retained-eans.yaml"

    @property
    def withdrawn_eans(self) -> Path:
        """Published barcodes a maintainer has established are NOT this product's
        (models/catalog.py::WithdrawnEans). Read by `report --ean-guard`, not by the resolver:
        removing the value is `matches.yaml`'s job, and this file only tells the guard the removal
        was deliberate. Hand-authored, like retained_eans and for the same reason."""
        return self.root / "catalog" / "withdrawn-eans.yaml"

    @property
    def conflicts(self) -> Path:
        return self.root / "review" / "conflicts.yaml"

    @property
    def rehomed(self) -> Path:
        """Placements the resolver made ON ITS OWN and is reporting, not asking about.

        `conflicts.yaml` is a working set: every row is a question a human answers, and answering
        them all should empty it. `supersession-stale-code` never could be answered. It says a
        declared supersession pair was bridged by a listing carrying the RETIRED code with the
        CURRENT barcode, and that `resolve/join.py` placed it by barcode -- a decision, already
        made, on the rule this repo committed to when it chose to keep both records. Nothing about
        such a row is undecided, and no edit to `matches.yaml` removes one: it lasts as long as the
        shop keeps its own stale catalogue number, which can be years. Twelve of them sitting in
        the working set meant the count could never reach zero and the exit code could never go
        quiet.

        So they live here instead. They are still WRITTEN, because the log has already earned its
        place -- it is what exposed `games-workshop/99120209100` publishing under the wrong
        product's name, by showing which listings ride across a renumber.
        """
        return self.root / "review" / "rehomed.yaml"

    @property
    def classifications(self) -> Path:
        return self.root / "catalog" / "classifications" / "products.yaml"

    @property
    def paints(self) -> Path:
        """The PAINT catalog's archive. Not an input to `resolve` -- nothing in this module reads
        it, deliberately, so the resolver stays a function of the product pipeline's own inputs.
        It lives here because `categorize` (a separate stage, run after resolve) does read it, and
        a second DataPaths would be a second place for a path to drift."""
        return self.root / "paints"

    @property
    def category_rules(self) -> Path:
        """Per-source category tables, one file per source id (categorize/rules.py)."""
        return self.root / "catalog" / "taxonomy" / "category-rules"

    @property
    def categorize_review(self) -> Path:
        """What `categorize` decided, what it could not, and what disagreed."""
        return self.root / "review" / "categorize.yaml"


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


@dataclass(frozen=True)
class ProductObservations:
    """What the PRODUCT catalog is built from, plus the receipts for what was left out.

    ONE SELECTION, TWO READERS, and that is the entire reason this is a function. `resolve_catalog`
    builds the catalog from `observations`; `classify/queue.py` re-joins the SAME list to recover
    each entity's raw per-source hints, which the resolved CanonicalProduct does not keep. If the
    two selections differ at all, the queue derives entity ids the catalog does not contain.

    THAT IS NOT HYPOTHETICAL. The queue used to join every observation in the store, paint sources
    included, and `army-painter/CP3001` -- a spray primer the product catalog publishes from
    mfr-warlord-store plus two retailers -- came back from that join as `army-painter/CP3001S`,
    because mfr-armypainter's paint row (sku CP3001S, sharing barcode 5713799300118) rejoined the
    entity and its code won the identity ordering. `build_queue` then raised "has no matching
    evidence" for a product plainly sitting in data/catalog/products/army-painter.yaml. The bug was
    invisible for as long as it was because ci.yml runs pytest only on `tools/**` changes and this
    test is not in the Data CI subset, so a data-only merge could turn it red and stay green.
    """

    observations: list[Observation]
    crossover_conflicts: list[dict]
    # Rows from `catalog: products` sources only, counted separately from `observations` ON
    # PURPOSE -- see the wipe guard in resolve_catalog.
    product_source_count: int


def select_product_observations(
    evidence: Mapping[str, Mapping[str, Observation]],
    descriptors: Mapping[str, SourceDescriptor],
    taxonomy: Taxonomy,
) -> ProductObservations:
    """Which stored observations feed the product catalog, and under what category stamp.

    Paint sources share the evidence layout but feed the PAINT catalog (see SourceDescriptor
    .catalog and scripts/gen_paint_harvest.py). Their observations are skipped here rather than
    stored elsewhere, so the acquire runner, cursors and health reporting stay uniform.

    ...except for the boxed multi-pot SETS among them, which are products (maintainer decision
    2026-08-05) and once reached NEITHER catalog: dropped here, and gated out of every bridge in
    gen_paint_harvest.py. `crossoverToProducts` is each paint source's declaration of which of its
    rows those are; `crossover.matches` is the same evaluator the bridges refuse with, so the two
    catalogs partition the source instead of both guessing. Measured 2026-08-11 across the six
    declaring sources: 562 rows selected (302 ak, 115 reaper, 69 gsw, 49 armypainter, 21 monument,
    6 scale75), 530 admitted. Not all of them are SETS: 16 of ak's 302 stamp `hobby-auxiliary` off
    a per-clause override (crossover.py::category_for).
    """
    observations: list[Observation] = []
    crossover_conflicts: list[dict] = []
    product_source_count = 0
    for source_id, source in evidence.items():
        descriptor = descriptors[source_id]
        if descriptor.catalog == "products":
            observations.extend(source.values())
            product_source_count += len(source)
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
            # DERIVED, not a second key, and the reason is the conflicts sort in resolve_catalog:
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
    return ProductObservations(observations, crossover_conflicts, product_source_count)


@dataclass(frozen=True)
class JoinedEvidence:
    """The resolver's join, replayed for a stage that needs each entity's MEMBERS.

    Two stages need what `resolve_catalog` does not return: `classify/queue.py` wants the raw
    per-source hints an entity was built from, and `categorize/stage.py` wants the same in order
    to read the stores' taxonomy. A resolved CanonicalProduct keeps only a handful of folded
    fields, so the join is replayed rather than the catalog being re-parsed.

    REPLAYING THE JOIN MEANS REPLAYING ITS INPUT. That is what `select_product_observations` is
    for and why this helper exists at all: a caller that assembles the observation list itself
    silently gets a different one, and a different one yields entity ids the catalog does not have
    (see ProductObservations for the measured case). One function, so there is nothing to keep in
    step.
    """

    entities: dict[str, list[Observation]]
    taxonomy: Taxonomy
    kinds: dict[str, str]
    descriptors: dict[str, SourceDescriptor]


def joined_evidence(paths: DataPaths) -> JoinedEvidence:
    """Re-run evidence + taxonomy + matches -> entity -> members, exactly as `resolve` does."""
    taxonomy = Taxonomy.load(paths.taxonomy)
    descriptors = load_descriptors(paths.sources)
    kinds = {sid: descriptor.kind for sid, descriptor in descriptors.items()}
    evidence = EvidenceStore(paths.evidence_products).load_all()
    selected = select_product_observations(evidence, descriptors, taxonomy)
    matches: Matches = _load_optional(paths.matches, Matches, Matches())
    sku_ids = {sid: d.skuIsListingId for sid, d in descriptors.items()}
    joined = join_observations(selected.observations, taxonomy, kinds, matches, sku_ids)
    return JoinedEvidence(joined.entities, taxonomy, kinds, descriptors)


_REHOMED_HEADER = """# data/review/rehomed.yaml -- generated by `warhub-data resolve`. NOT a working set.
#
# Every row here is a placement the resolver MADE, not a question it is asking. They are split out
# of conflicts.yaml because that file is a working set: each row there is something a human decides,
# and deciding them all should empty it. These never could be emptied that way.
#
# `supersession-stale-code` -- a shop lists one of a DECLARED supersession pair by the RETIRED
#   product code while the box it stocks scans as the CURRENT barcode. resolve/join.py places the
#   listing by its BARCODE (the barcode identifies the box; a shop's SKU is its own catalogue
#   number and goes stale across a renumber) and drops the stale code so the re-homed row cannot
#   then name the record it moved into. Nothing is undecided, and no edit to matches.yaml removes a
#   row: it lasts as long as the shop keeps its own stale number.
#
# `supersession-blocked-merge` -- the union barrier refused a merge that would have folded a
#   declared pair back together through a shared barcode.
#
# WHY THEY ARE STILL WRITTEN. This log is how `games-workshop/99120209100` was caught publishing
# under the wrong product's name: it names the listings that ride across a renumber, which is
# exactly where a curated row can drag a name onto the wrong side of a pair.
#
# A ROW LEAVING THIS FILE IS NOT A FIX -- it means the shop edited its own SKU, or the supersession
# was withdrawn. Neither is something to chase.
"""


def resolve_catalog(paths: DataPaths) -> dict[str, list[CanonicalProduct]]:
    taxonomy = Taxonomy.load(paths.taxonomy)
    descriptors = load_descriptors(paths.sources)
    kinds = {sid: descriptor.kind for sid, descriptor in descriptors.items()}
    category_maps = _load_mappings(paths.mappings)
    vocabulary = load_vocabulary(paths.taxonomy)
    default_hints = {sid: d.defaultHints for sid, d in descriptors.items() if d.defaultHints}
    stale_fields = {sid: d.staleFields for sid, d in descriptors.items() if d.staleFields}

    evidence = EvidenceStore(paths.evidence_products).load_all()
    unknown = set(evidence) - set(descriptors)
    if unknown:
        raise ValueError(f"evidence sources without a descriptor: {sorted(unknown)}")

    matches: Matches = _load_optional(paths.matches, Matches, Matches())
    overrides: Overrides = _load_optional(paths.overrides, Overrides, Overrides())
    retained: RetainedEans = _load_optional(paths.retained_eans, RetainedEans, RetainedEans())

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

    # Which stored observations feed THIS catalog (paint sources contribute only their boxed
    # sets, and only under a category stamp) -- shared with classify/queue.py, which must join an
    # identical set or derive entity ids this catalog does not have. See ProductObservations.
    selected = select_product_observations(evidence, descriptors, taxonomy)
    observations = selected.observations
    crossover_conflicts = selected.crossover_conflicts

    # The wipe guard asks about PRODUCT-SOURCE evidence specifically, not about `observations`.
    # Crossover broke the old `if not observations` form: a handful of boxed sets from a paint
    # source now lands in the same list, so a run where every `catalog: products` source failed to
    # load would sail past the guard with (say) 516 crossed rows, publish only the crossover
    # manufacturers, and then let the stale-file sweep below unlink every real product file.
    # Reproduced on the repo's own resolver fixtures before this fix: dropping mfr-gw and
    # ret-goblin evidence raised no exception and took games-workshop.yaml with it.
    if not selected.product_source_count and any(paths.catalog_products.glob("*.yaml")):
        raise ValueError("no evidence loaded but catalog files exist; refusing to wipe the catalog")

    sku_ids = {sid: d.skuIsListingId for sid, d in descriptors.items()}
    joined = join_observations(observations, taxonomy, kinds, matches, sku_ids)

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
        ean_resolutions[entity] = ean
        conflicts.extend(ean.conflicts)
        record = resolve_attributes(
            entity, members, kinds, ean, code, superseded=superseded, category_maps=category_maps,
            default_hints=default_hints, stale_fields=stale_fields,
            member_codes=member_codes,
        )
        # Stamped before apply_overrides so a hand override can still correct a link.
        record.supersededBy = superseded_by.get(entity)
        record.supersedes = sorted(supersedes.get(entity, []))
        # Re-attach any barcode this catalog published that no source attests any more. BEFORE
        # apply_overrides, so a hand override still has the last word, and additive only: it can
        # add to `additionalEans` and can never touch the primary `ean`. See RetainedEans for the
        # ledger hole this plugs -- a source that CHANGES a barcode on a handle it already had
        # leaves no loser for corroborate.py to keep, because upsert replaced the observation
        # whole. Retracted entities are already skipped above, so this cannot resurrect one.
        keep = [e for e in retained.retained.get(record.id, []) if e != record.ean]
        if keep:
            record.additionalEans = sorted({*record.additionalEans, *keep})
        product = apply_overrides(record, overrides)
        # AFTER overrides, so a hand-written `category:` in overrides.yaml is held to the same
        # vocabulary as a resolved one -- a typo there would otherwise mint an undeclared value
        # straight into the published catalog, which is exactly how the six ad-hoc values got in.
        vocabulary.check(product.category, product.packaging, product.id)
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

    # THE SPLIT IS BY WHETHER A ROW IS A QUESTION OR AN ANSWER, not by which type is noisy. Both
    # types below are the declared-supersession machinery reporting that it ACTED: one placed a
    # bridging listing by its barcode and dropped the stale code, the other refused a union that
    # would have re-merged a declared pair. Neither leaves anything for a human to decide, and
    # neither can be cleared by editing data -- so neither belongs in the working set. Every other
    # type is a refusal to guess, which is exactly what `conflicts.yaml` is for.
    #
    # Written unconditionally, both of them, so an empty run replaces a stale file rather than
    # leaving yesterday's rows to be read as today's.
    resolution_types = {"supersession-stale-code", "supersession-blocked-merge"}
    order = lambda row: str(sorted(row.items()))  # noqa: E731 -- the committed sort, unchanged
    write_yaml(
        paths.conflicts,
        {"conflicts": sorted((c for c in conflicts if c["type"] not in resolution_types), key=order)},
    )
    paths.rehomed.parent.mkdir(parents=True, exist_ok=True)
    paths.rehomed.write_text(
        _REHOMED_HEADER
        + dump_yaml({"rehomed": sorted((c for c in conflicts if c["type"] in resolution_types), key=order)}),
        encoding="utf-8",
        newline="\n",
    )
    return {manufacturer: sorted(records, key=lambda p: p.id) for manufacturer, records in sorted(products.items())}
