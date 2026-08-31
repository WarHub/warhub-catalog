"""Run the decision over the resolved catalog, and write down what could not be decided.

READS THE CATALOG `resolve` JUST WROTE, and rewrites the records it can improve. Reading the
resolved records rather than re-resolving is what makes this stage cheap to re-run: a rule table
edited today is applied to evidence harvested weeks ago, with no network and no re-derivation of
identity.

THE REVIEW FILE IS THE PRODUCT, as much as the catalog is. A stage that decided 8,000 categories
and said nothing about the 20,000 it did not would be indistinguishable from one whose tables had
silently stopped matching. `data/review/categorize.yaml` therefore carries three things a
maintainer works from: the disagreements, the clauses that match no evidence at all, and the raw
taxonomy values that are still unmapped, ranked by how many undecided products each would decide.

EVERYTHING IT REPORTS IS ABOUT THE CATALOG, NOT ABOUT THE RUN. Running this stage twice is a
no-op the second time -- the first run left nothing replaceable -- so a report phrased as "decided
N this run" reads `0` for a perfectly healthy catalog and would train a reader to ignore it. In
the pipeline `resolve` always precedes it and resets every undecided record, so the run figure and
the catalog figure agree there; by hand they do not, and the catalog is the one that means
something.
"""
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from warhub_acquisition.models.catalog import CanonicalProduct
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.attributes import complete_game_systems_basis
from warhub_acquisition.resolve.resolver import DataPaths, _dump_product, joined_evidence
from warhub_acquisition.taxonomy import Taxonomy, load_labels
from warhub_acquisition.vocabulary import load_vocabulary
from warhub_acquisition.yamlio import read_yaml, write_yaml

from .decide import Conflict, _clause_hit, _product_hit, _signal, decide, flatten_hints
from .lexicon import load_lexicon
from .paints import load_paint_barcodes
from .rules import SourceRules, load_category_rules

#: The one basis this stage is allowed to replace: the record has no category at all. `stated` is
#: a source's claim about one product and outranks any table; anything an override set is a
#: maintainer's decision. Neither is touched.
#:
#: It used to be the PAIR `{guessed, default}` -- the resolver's own `miniatures` fallback and an
#: upstream pipeline's blanket fill. Both were values that meant "nobody said", and collapsing them
#: into an absent category is what let this set shrink to one member.
REPLACEABLE = frozenset({"unknown"})

#: Bases that record a HUMAN's decision about one product. A rule may neither replace nor extend
#: them -- see `_apply_game_systems`.
_MAINTAINER_DECIDED = frozenset({"override"})

#: The gameSystem bases this stage may recompute. Both are DERIVED -- they say what happened
#: when nothing supplied a value -- so re-deriving them against a freshly decided category is
#: the whole point. `stated`, `mapped` and `override` trace to a claim and are never touched.
DERIVED_GAME_SYSTEM_BASES = frozenset({"unknown", "not-applicable", None})

#: The output axes, in the order `decide` reads them. Named once because three different places
#: must agree on what "an axis" is: the scan, the veto scoping, and the dead-clause count.
_AXES = ("category", "packaging", "faction", "gameSystems")

#: Hint keys that are FACTS ABOUT A PRODUCT rather than a shelf it was filed on. Everything else
#: is treated as taxonomy and counted in the unmapped ranking.
#:
#: THE LIST USED TO RUN THE OTHER WAY -- an allow-list of seven keys -- and the failure mode of
#: that shape is silence. A source whose taxonomy key was not among the seven reported an EMPTY
#: worklist, which is indistinguishable from a source that publishes no taxonomy at all. It
#: happened twice: `tradeCategory` was missing until 2026-08-25, hiding the largest single block of
#: undecided products in the catalog, and `productLine` was missing until 2026-09-01, hiding
#: mfr-cmon -- 387 products, every one of them undecided, and 24 clean product-line values.
#: Inverting it means a new source's taxonomy is visible the day it arrives and the maintenance
#: burden falls on the keys we already know are not taxonomies.
#:
#: The claims are here because the resolver already folds them into published fields; re-listing
#: them as unmapped vocabulary would rank things that are not work.
NON_TAXONOMY_HINTS = frozenset({
    # claims the resolver folds directly
    "gameSystem", "faction", "category", "packaging", "quantity", "status", "description",
    "contentSkus", "namedInSet", "namedOnlyInSets",
    # measurements and identifiers
    "volumeMl", "weightG", "grams", "ml", "reference", "sscCode", "legacyProductCode",
    "supersedes", "retiredOn", "lineageDerived", "eanSource", "modified", "archiveTimestamp",
})


#: How many unmapped values to list per source. The tail is a long one and mostly identifiers
#: rather than shelves -- 6,793 of ret-radaddel's 7,272 distinct "tags" are the product's own code,
#: occurring exactly once -- so the ranking is what keeps them out: a value seen on one undecided
#: product sorts below every real shelf and never reaches this cut. A file nobody opens is not a
#: worklist.
_UNMAPPED_LIMIT = 40


@dataclass
class Outcome:
    #: Products this RUN moved off a fallback. Zero on a second run over the same catalog.
    decided: int = 0
    #: Products this run examined -- i.e. those still carrying a replaceable basis.
    considered: int = 0
    by_basis: Counter = field(default_factory=Counter)
    conflicts: list[Conflict] = field(default_factory=list)
    unmapped: dict[str, Counter] = field(default_factory=dict)
    #: `{basis: products}` over the WHOLE catalog after this run -- the figure that survives a
    #: re-run, and the one the report and the PR body quote.
    catalog_basis: Counter = field(default_factory=Counter)
    #: `{gameSystemsBasis: products}` over the whole catalog after this run. Sibling of
    #: `catalog_basis`; `unknown` here is the real size of the classification problem, and it is
    #: the number `classify --emit-queue` turns into a queue.
    game_system_basis: Counter = field(default_factory=Counter)
    #: Products this RUN gave a gameSystem, and by which rung.
    game_system_decided: int = 0
    by_game_system_basis: Counter = field(default_factory=Counter)
    #: `{"<source> <signal>": observations matched}`, counted over ALL evidence rather than over
    #: the products this run decided. Counting the run instead made every clause look dead the
    #: moment the catalog was already categorized, which is exactly when someone would read it.
    clause_hits: Counter = field(default_factory=Counter)


def _barcodes(record: CanonicalProduct) -> list[str]:
    return [str(code) for code in [record.ean, *record.additionalEans] if code]


def _count_clause_hits(
    entities: Mapping[str, Sequence[Observation]], rules: Mapping[str, SourceRules]
) -> Counter:
    """Which clause each observation matches, over the whole evidence store.

    A clause matching NOTHING is nearly always a typo -- `hintEquals` is exact, and a store's value
    can differ by a case or a stray space ("Paint set" beside "Paint Set" at Warlord, both real) --
    or a value the store has retired. Neither announces itself: a table with a broken line and a
    store with no taxonomy produce identical output.

    SOURCE TABLES ONLY. A manufacturer table is keyed on the maker, not on a feed, and is evaluated
    against the PRODUCT -- so looking it up by `member.source_id` never matches and reported every
    one of its clauses as dead. 26 of the 42 entries in the last report were that, purely by
    construction. `_count_manufacturer_hits` counts those against the records instead.

    ONE COUNT PER AXIS, for the same reason `decide` scans per axis: a clause that answers a
    different question from the one that matched first is live, and the single `break` reported
    four working `mfr-warmachine vendor=...` clauses as dead because a `productType` clause was
    ahead of them.
    """
    hits: Counter = Counter()
    for members in entities.values():
        for member in members:
            table = rules.get(member.source_id)
            if table is None or table.manufacturer is not None:
                continue
            for axis in _AXES:
                for clause in table.clauses:
                    if getattr(clause, axis) and _clause_hit(member, clause):
                        hits[f"{member.source_id} {_signal(clause)}"] += 1
                        break
    return hits


def _count_manufacturer_hits(
    record: CanonicalProduct, rules: Mapping[str, SourceRules], hits: Counter
) -> None:
    """The same count for a manufacturer table, against one product's own name and code."""
    table = rules.get(record.manufacturer or "")
    if table is None or table.manufacturer is None:
        return
    code = record.productCode or record.sku or ""
    for axis in _AXES:
        for clause in table.clauses:
            if getattr(clause, axis) and _product_hit(record.name, code, clause):
                hits[f"{table.scope} {_signal(clause)}"] += 1
                break


def categorize(paths: DataPaths, apply: bool = True) -> Outcome:
    """Decide, optionally write, and always report.

    `apply=False` is the dry run: everything is computed and reported, nothing is written. It
    exists so a rule table can be measured before it is committed -- the alternative is editing
    the catalog to find out what an edit does.
    """
    rules = load_category_rules(paths.category_rules)
    vocabulary = load_vocabulary(paths.taxonomy)
    paint_barcodes = load_paint_barcodes(paths.paints)
    lexicon = load_lexicon(paths.taxonomy)
    joined = joined_evidence(paths)

    # Validate the TABLES, not just their output: a clause naming an undeclared category that
    # happens to match nothing today would sit undetected until the day a store adds that value.
    for index, entry in enumerate(lexicon.entries if lexicon else []):
        vocabulary.check(entry.category, None, f"category-lexicon entry {index}")
    manufacturers = set(Taxonomy.load(paths.taxonomy).manufacturers)
    for table in rules.values():
        for index, clause in enumerate(table.clauses):
            vocabulary.check(clause.category, clause.packaging, f"{table.scope} clause {index}")
        # A TABLE FOR A PAINT SOURCE IS DEAD BY CONSTRUCTION, and it took two of them to notice.
        # `select_product_observations` admits a `catalog: paints` source's rows only where
        # `crossoverToProducts` selects them, and every row it selects arrives with a category
        # already STAMPED by the crossover -- so it is `stated`, and this stage never reaches it.
        # Tables for mfr-monument and mfr-turbodork were written, reviewed and committed before
        # the dead-clause report showed all fourteen of their clauses matching nothing at all.
        # A MANUFACTURER TABLE IS SCOPED TO A MAKER, NOT A FEED, so it is held to the
        # manufacturer taxonomy instead -- same guard, different register: a table naming something
        # that does not exist can never fire, and a silent no-op table is indistinguishable from a
        # store that publishes no taxonomy.
        if table.manufacturer is not None:
            if table.manufacturer not in manufacturers:
                raise ValueError(
                    f"{table.manufacturer}: rules name a manufacturer with no taxonomy entry"
                )
            continue
        descriptor = joined.descriptors.get(table.source)
        if descriptor is None:
            raise ValueError(f"{table.source}: category rules name a source with no descriptor")
        if descriptor.catalog != "products":
            raise ValueError(
                f"{table.source}: category rules on a `catalog: {descriptor.catalog}` source can "
                f"never fire -- its rows reach the product catalog only through "
                f"`crossoverToProducts`, which stamps a category itself. Delete the table."
            )

    system_labels, _ = load_labels(paths.taxonomy)
    catch_alls = _load_catch_alls(paths.taxonomy)
    outcome = Outcome(clause_hits=_count_clause_hits(joined.entities, rules))
    if not paths.catalog_products.exists():
        return outcome

    for path in sorted(paths.catalog_products.glob("*.yaml")):
        document = read_yaml(path) or {}
        records = [CanonicalProduct.model_validate(row) for row in document.get("products") or []]
        touched = False
        for record in records:
            # ASKED ONCE, PER RECORD, WHATEVER IS ALREADY SETTLED. The axes are independent
            # questions and a product decided on one can be open on the others -- a GW paint pot
            # has a category from the paint catalog and no `packaging` at all, and its own name
            # says `X6`. Asking only for records whose CATEGORY was replaceable is the last place
            # the stage was still gating one axis on another; it left the 912 GW trade multipacks
            # with no packaging while a committed clause matched every one of them.
            members = joined.entities.get(record.id) or []
            decision, conflicts = decide(
                record.id, members, joined.kinds, rules, _barcodes(record), paint_barcodes,
                record.name, lexicon,
                manufacturer=record.manufacturer, code=record.productCode or record.sku,
            )
            outcome.conflicts.extend(conflicts)

            # THE CATEGORY, and only where nothing has decided it. `stated` is a source's claim
            # about one product and outranks any table; anything an override set is a maintainer's
            # decision.
            if record.categoryBasis in REPLACEABLE:
                outcome.considered += 1
                if decision is not None and decision.category is not None:
                    outcome.decided += 1
                    outcome.by_basis[decision.basis] += 1
                    record.category = decision.category
                    record.categoryBasis = decision.basis
                    touched = True
                else:
                    _count_unmapped(outcome, members)

            # PACKAGING is additive-only and independent of all of that: a source that stated it
            # stated it about this product, and a table that infers `set` from the words "Paint
            # Sets" is inferring it about a shelf.
            if decision is not None and decision.packaging and record.packaging is None:
                record.packaging = decision.packaging
                touched = True

            if _apply_game_systems(record, decision, outcome, catch_alls):
                touched = True
            # THE GAME-SYSTEM BASIS IS SETTLED HERE, NOT IN `resolve`, because it is a question
            # about the CATEGORY and `resolve` does not yet know the answer to that one. A paint
            # pot leaves the resolver with NO category at all -- nothing had decided -- and only
            # this stage turns it into `paint`. Deciding
            # `not-applicable` upstream therefore asked the question one pass too early and got
            # `unknown` for 4,189 products that are plainly hobby supplies.
            #
            # Only the two DERIVED values are ever recomputed. `stated`, `mapped` and `override`
            # trace to something and this stage has nothing to add to them -- the same rule
            # REPLACEABLE states for categoryBasis, for the same reason.
            if record.gameSystemsBasis in DERIVED_GAME_SYSTEM_BASES:
                basis = complete_game_systems_basis(record, system_labels).gameSystemsBasis
                if basis != record.gameSystemsBasis:
                    record.gameSystemsBasis = basis
                    touched = True
            _count_manufacturer_hits(record, rules, outcome.clause_hits)
            outcome.catalog_basis[record.categoryBasis or "none"] += 1
            outcome.game_system_basis[record.gameSystemsBasis or "none"] += 1
        if touched and apply:
            write_yaml(
                path,
                {
                    "manufacturer": document.get("manufacturer") or path.stem,
                    "products": [_dump_product(record) for record in records],
                },
            )

    if apply:
        _write_review(paths.categorize_review, outcome, rules)
    return outcome


def _load_catch_alls(taxonomy_dir) -> frozenset[str]:
    """Slugs declared `catchAll: true` -- buckets rather than claims. Read from the taxonomy so
    the set is reviewable data, not a constant compiled into this stage."""
    data = read_yaml(taxonomy_dir / "game-systems.yaml") or {}
    return frozenset(
        e["slug"] for e in data.get("gameSystems") or [] if e.get("catchAll")
    )


def _apply_game_systems(
    record: CanonicalProduct, decision, outcome: "Outcome", catch_alls: frozenset[str]
) -> bool:
    """Fill game systems the evidence never supplied, or report a disagreement. Never overwrite.

    THE RULE ONLY EVER FILLS A HOLE. Where a source already stated a system and a rule disagrees,
    the disagreement is RECORDED and nothing changes -- OBJECTIVES value 5, and the only defensible
    treatment of `legacy-catalog`, which states a gameSystem for 12,395 of 12,395 products it
    touches and is therefore never silent about being unsure.

    ITS 99.9% AGREEMENT IS A BIASED FIGURE, and the bias runs the way that matters. Measured
    2026-08-31 it agreed with live sources 99.9% (Warlord) and 97.4% (GW) -- but that measurement
    can only be taken where a live source also states one, which for Warlord is exactly the 2,871
    products whose store `productType` names a game. Outside that bucket (2026-09-01) 1,027 of
    1,031 Warlord products are stamped `bolt-action`, and 675 of those are contradicted by the
    store's own single game tag: `Viking Hirdmen` and `Boromite Engineers` are not Bolt Action.
    So the fill IS there; the earlier number simply could not see it, because the products it is
    wrong about are the ones nothing else spoke about. Recording the disagreement rather than
    overwriting is still right -- correcting 675 published values is a data change that belongs in
    its own review -- but the report is now expected to grow, not to stay near zero.
    """
    if decision is None or not decision.gameSystems:
        return False
    proposed = list(decision.gameSystems)
    settled = set(record.gameSystems)

    # THE TEST IS CONTAINMENT, and on a set-valued field that one test covers what used to be two
    # separate cases plus the one that mattered most.
    #
    #   settled is EMPTY      -- nothing decided; the rule fills it. (`set() <= anything`.)
    #   settled is a SUBSET   -- the rule ADDS a membership and contradicts none. Mantic sells one
    #                            Forge Father squad box into both Deadzone and Firefight;
    #                            legacy-catalog had to pick one and picked `deadzone`, so the rule
    #                            saying `[deadzone, firefight]` is strictly more informative about
    #                            the same product. Under a scalar field there was no such thing as
    #                            extending a claim, which is why the rule used to be "fill a hole
    #                            or report"; on a list there is, and refusing it left 114 products
    #                            asserting half of what their manufacturer says.
    #   otherwise             -- the rule drops or replaces something the catalog states. That is a
    #                            disagreement and is reported, never applied.
    #
    # REFINING A CATCH-ALL IS THE ONE CASE CONTAINMENT DOES NOT COVER, because it REPLACES rather
    # than extends. `other-games` is Games Workshop's own shelf for everything outside its flagship
    # systems and this catalog inherited it wholesale -- 593 products spanning six games GW's own
    # codes name individually. Only slugs explicitly marked `catchAll` qualify, and ALL of the
    # record's current values must be such buckets: refining `[other-games]` is informative, but
    # replacing `[warhammer-40k, other-games]` would drop a real claim to gain a guess.
    #
    # EXTENDING IS A RATCHET, and the pipeline is what makes that safe. Once a rule has added a
    # system, NARROWING that rule cannot take it back -- the record's list is no longer a subset of
    # what the table now proposes, so the next run reports a disagreement and leaves the value
    # alone. That is correct for a stage that must never overwrite a claim, and it is harmless
    # because `resolve` always precedes `categorize` (.github/workflows/catalog-acquire.yml) and
    # rebuilds `gameSystems` from evidence first. Running this stage ALONE after narrowing a table
    # will not undo the wider value; run `resolve` first.
    #
    # A MAINTAINER'S DECISION IS NEVER EXTENDED. `override` is the one basis that means a person
    # weighed this exact product, and the 78 Kill Team entries in overrides.yaml are precisely a
    # decision that those products are `kill-team` AND NOT `warhammer-40k`. A rule proposing both
    # would quietly undo it.
    # STRICTLY MORE, or nothing. An exact agreement is NOT an extension: rewriting the record
    # because a table happens to name what a source already stated would demote its basis from
    # `stated` to `mapped` and lose the fact that a source said it. Measured when this read
    # `<=`: 4,242 products silently lost `stated` provenance to a rule that agreed with them.
    extends = (
        (not settled or settled < set(proposed))
        and record.gameSystemsBasis not in _MAINTAINER_DECIDED
    )
    refines = bool(settled) and settled <= catch_alls
    if extends or refines:
        record.gameSystems = proposed
        record.gameSystemsBasis = decision.game_systems_basis
        if decision.faction and not record.faction:
            record.faction = decision.faction
        outcome.game_system_decided += 1
        outcome.by_game_system_basis[decision.game_systems_basis or "?"] += 1
        return True
    if settled and settled != set(proposed):
        outcome.conflicts.append(
            Conflict(
                record.id,
                "gameSystem-disagreement",
                f"catalog says {'+'.join(sorted(settled))} ({record.gameSystemsBasis}); "
                f"{decision.game_systems_why or decision.why} says {'+'.join(proposed)}",
            )
        )
    return False


def _count_unmapped(outcome: Outcome, members: Sequence[Observation]) -> None:
    """Every raw taxonomy value on a product this stage could not decide, counted per source.

    Counted from the UNDECIDED products only, which is what makes the ranking a worklist rather
    than a census: a value appearing on 900 already-decided products is not work.
    """
    for member in members:
        bucket = outcome.unmapped.setdefault(member.source_id, Counter())
        for key, value in flatten_hints(member.hints).items():
            if value is None or key in NON_TAXONOMY_HINTS:
                continue
            for item in value if isinstance(value, (list, tuple, set)) else [value]:
                text = str(item)
                if text:
                    bucket[f"{key}={text}"] += 1


def _write_review(path: Path, outcome: Outcome, rules: Mapping[str, SourceRules]) -> None:
    undecided = sum(outcome.catalog_basis[basis] for basis in REPLACEABLE)
    total = sum(outcome.catalog_basis.values())
    write_yaml(
        path,
        {
            "summary": {
                "products": total,
                "undecided": undecided,
                "byBasis": dict(sorted(outcome.catalog_basis.items())),
                # The run's own contribution, distinct from the catalog state above: 0 here with a
                # low `undecided` means the catalog was already categorized, not that anything is
                # broken.
                "decidedThisRun": outcome.decided,
            },
            "conflicts": [
                {"entity": c.entity, "type": c.kind, "detail": c.detail}
                for c in sorted(outcome.conflicts, key=lambda c: (c.entity, c.kind, c.detail))
            ],
            # Clauses matching NO observation anywhere in the evidence -- see _count_clause_hits.
            # Reported rather than failed: a legitimately dead clause is a fact about the store
            # (a retired value), not a fault in the run, and failing the nightly for it would stop
            # the catalog because a shop renamed a shelf.
            "deadClauses": sorted(
                f"{source} {_signal(clause)}"
                for source, table in rules.items()
                for clause in table.clauses
                if f"{source} {_signal(clause)}" not in outcome.clause_hits
            ),
            # Ranked worklist: the raw values that would decide the most still-undecided products.
            "unmapped": {
                source: [
                    {"value": value, "wouldDecide": count}
                    for value, count in counter.most_common(_UNMAPPED_LIMIT)
                ]
                for source, counter in sorted(outcome.unmapped.items())
                if counter
            },
        },
    )
