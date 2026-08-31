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
from warhub_acquisition.resolve.attributes import complete_game_system_basis
from warhub_acquisition.resolve.resolver import DataPaths, _dump_product, joined_evidence
from warhub_acquisition.taxonomy import Taxonomy, load_labels
from warhub_acquisition.vocabulary import load_vocabulary
from warhub_acquisition.yamlio import read_yaml, write_yaml

from .decide import Conflict, Decision, _clause_hit, _signal, decide, flatten_hints
from .lexicon import load_lexicon
from .paints import load_paint_barcodes
from .rules import SourceRules, load_category_rules

#: The two bases this stage is allowed to replace. `stated` is a source's claim about one product
#: and outranks any table; anything an override set is a maintainer's decision. Neither is touched.
REPLACEABLE = frozenset({"guessed", "default"})

#: The gameSystem bases this stage may recompute. Both are DERIVED -- they say what happened
#: when nothing supplied a value -- so re-deriving them against a freshly decided category is
#: the whole point. `stated`, `mapped` and `override` trace to a claim and are never touched.
DERIVED_GAME_SYSTEM_BASES = frozenset({"unknown", "not-applicable", None})

#: Hint keys that carry a source's own taxonomy. Only these are counted in the unmapped ranking --
#: `description` and `quantity` are facts about a product, not filing categories, and listing them
#: would bury the values a rule could actually use.
#:
#: `tradeCategory` was MISSING from this tuple until 2026-08-25, and the omission mattered:
#: mfr-gw-trade is the sole source for 3,330 undecided products, carries no Shopify-style taxonomy
#: at all, and therefore reported an EMPTY worklist -- the largest single block of undecided
#: products in the catalog looked like a source with nothing to offer. It carries 227 distinct
#: tradeCategory values over 3,016 rows.
#:
#: `sscCode` is deliberately still absent. GW's stock-section code is 4,160 distinct values over
#: 6,822 rows -- a near-unique-per-product identifier, not a taxonomy -- and listing it would put
#: 40 rows of noise at the top of that source's worklist and push the values a rule could use off
#: the end.
TAXONOMY_HINTS = (
    "productType", "categories", "tags", "breadcrumbs", "hierarchy.lvl1", "vendor", "tradeCategory",
)

#: How many unmapped values to list per source. The tail is a long one (ret-radaddel alone carries
#: 7,281 distinct tags) and a file nobody opens is not a worklist.
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
    #: `{gameSystemBasis: products}` over the whole catalog after this run. Sibling of
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
    """
    hits: Counter = Counter()
    for members in entities.values():
        for member in members:
            table = rules.get(member.source_id)
            if table is None:
                continue
            for clause in table.clauses:
                if _clause_hit(member, clause):
                    hits[f"{member.source_id} {_signal(clause)}"] += 1
                    break
    return hits


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
            game_system_decision = None
            if record.categoryBasis not in REPLACEABLE:
                # The category is settled, but the game system may not be. Ask anyway -- the two
                # are different questions and a product decided on one can be open on the other.
                game_system_decision, extra = decide(
                    record.id, joined.entities.get(record.id) or [], joined.kinds, rules,
                    _barcodes(record), paint_barcodes, record.name, lexicon,
                    manufacturer=record.manufacturer, code=record.productCode or record.sku,
                )
                outcome.conflicts.extend(extra)
            if record.categoryBasis in REPLACEABLE:
                outcome.considered += 1
                members = joined.entities.get(record.id) or []
                decision, conflicts = decide(
                    record.id, members, joined.kinds, rules, _barcodes(record), paint_barcodes,
                    record.name, lexicon,
                    manufacturer=record.manufacturer, code=record.productCode or record.sku,
                )
                outcome.conflicts.extend(conflicts)
                if decision is not None and decision.category is not None:
                    outcome.decided += 1
                    outcome.by_basis[decision.basis] += 1
                    _stamp(record, decision)
                    touched = True
                else:
                    _count_unmapped(outcome, members)
                game_system_decision = decision
            if _apply_game_system(record, game_system_decision, outcome, catch_alls):
                touched = True
            # THE GAME-SYSTEM BASIS IS SETTLED HERE, NOT IN `resolve`, because it is a question
            # about the CATEGORY and `resolve` does not yet know the answer to that one. A paint
            # pot leaves the resolver as `miniatures`/`guessed` -- the fallback fires precisely
            # because nothing had decided -- and only this stage turns it into `paint`. Deciding
            # `not-applicable` upstream therefore asked the question one pass too early and got
            # `unknown` for 4,189 products that are plainly hobby supplies.
            #
            # Only the two DERIVED values are ever recomputed. `stated`, `mapped` and `override`
            # trace to something and this stage has nothing to add to them -- the same rule
            # REPLACEABLE states for categoryBasis, for the same reason.
            if record.gameSystemBasis in DERIVED_GAME_SYSTEM_BASES:
                settled = complete_game_system_basis(record, system_labels).gameSystemBasis
                if settled != record.gameSystemBasis:
                    record.gameSystemBasis = settled
                    touched = True
            outcome.catalog_basis[record.categoryBasis or "none"] += 1
            outcome.game_system_basis[record.gameSystemBasis or "none"] += 1
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


def _apply_game_system(
    record: CanonicalProduct, decision, outcome: "Outcome", catch_alls: frozenset[str]
) -> bool:
    """Fill a gameSystem the evidence never supplied, or report a disagreement. Never overwrite.

    THE RULE ONLY EVER FILLS A HOLE. Where a source already stated a system and a rule disagrees,
    the disagreement is RECORDED and nothing changes -- OBJECTIVES value 5, and the only defensible
    treatment of `legacy-catalog`, which states a gameSystem for 12,395 of 12,395 products it
    touches and is therefore never silent about being unsure. Measured 2026-08-31, where it and a
    live source both state one they agree 99.9% (Warlord) and 97.4% (GW); the wrong labels are
    concentrated where nothing can corroborate it, and a rule that silently overwrote 2,800 records
    on that inference would be trading a known-good 99.9% for an unreviewed guess.
    """
    if decision is None or not decision.gameSystem:
        return False
    # REFINING A BUCKET IS NOT OVERWRITING A CLAIM. `other-games` is Games Workshop's own shelf
    # for everything outside its flagship systems, and this catalog inherited it wholesale -- 593
    # products, spanning six games GW's product codes name individually. A rule that says which one
    # is strictly more informative and contradicts nothing, so it replaces the bucket. Only slugs
    # explicitly marked `catchAll` in the taxonomy qualify.
    if record.gameSystemBasis == "unknown" or record.gameSystem in catch_alls:
        record.gameSystem = decision.gameSystem
        record.gameSystemBasis = decision.game_system_basis
        if decision.faction and not record.faction:
            record.faction = decision.faction
        outcome.game_system_decided += 1
        outcome.by_game_system_basis[decision.game_system_basis or "?"] += 1
        return True
    if record.gameSystem and record.gameSystem != decision.gameSystem:
        outcome.conflicts.append(
            Conflict(
                record.id,
                "gameSystem-disagreement",
                f"catalog says {record.gameSystem} ({record.gameSystemBasis}); "
                f"{decision.why} says {decision.gameSystem}",
            )
        )
    return False


def _stamp(record: CanonicalProduct, decision: Decision) -> None:
    """The category and its basis, and packaging ONLY where the record had none.

    Packaging is deliberately additive-only. A source that stated `packaging` stated it about this
    product; a table that infers `set` from the word "Paint Sets" is inferring it about a shelf.
    """
    record.category = decision.category
    record.categoryBasis = decision.basis
    if decision.packaging and record.packaging is None:
        record.packaging = decision.packaging


def _count_unmapped(outcome: Outcome, members: Sequence[Observation]) -> None:
    """Every raw taxonomy value on a product this stage could not decide, counted per source.

    Counted from the UNDECIDED products only, which is what makes the ranking a worklist rather
    than a census: a value appearing on 900 already-decided products is not work.
    """
    for member in members:
        bucket = outcome.unmapped.setdefault(member.source_id, Counter())
        flat = flatten_hints(member.hints)
        for key in TAXONOMY_HINTS:
            value = flat.get(key)
            if value is None:
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
