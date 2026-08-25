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
from warhub_acquisition.resolve.resolver import DataPaths, _dump_product, joined_evidence
from warhub_acquisition.vocabulary import load_vocabulary
from warhub_acquisition.yamlio import read_yaml, write_yaml

from .decide import Conflict, Decision, _clause_hit, _signal, decide, flatten_hints
from .paints import load_paint_barcodes
from .rules import SourceRules, load_category_rules

#: The two bases this stage is allowed to replace. `stated` is a source's claim about one product
#: and outranks any table; anything an override set is a maintainer's decision. Neither is touched.
REPLACEABLE = frozenset({"guessed", "default"})

#: Hint keys that carry a store's own taxonomy. Only these are counted in the unmapped ranking --
#: `description` and `quantity` are facts about a product, not filing categories, and listing them
#: would bury the values a rule could actually use.
TAXONOMY_HINTS = ("productType", "categories", "tags", "breadcrumbs", "hierarchy.lvl1", "vendor")

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
    joined = joined_evidence(paths)

    # Validate the TABLES, not just their output: a clause naming an undeclared category that
    # happens to match nothing today would sit undetected until the day a store adds that value.
    for table in rules.values():
        for index, clause in enumerate(table.clauses):
            vocabulary.check(clause.category, clause.packaging, f"{table.source} clause {index}")
        # A TABLE FOR A PAINT SOURCE IS DEAD BY CONSTRUCTION, and it took two of them to notice.
        # `select_product_observations` admits a `catalog: paints` source's rows only where
        # `crossoverToProducts` selects them, and every row it selects arrives with a category
        # already STAMPED by the crossover -- so it is `stated`, and this stage never reaches it.
        # Tables for mfr-monument and mfr-turbodork were written, reviewed and committed before
        # the dead-clause report showed all fourteen of their clauses matching nothing at all.
        descriptor = joined.descriptors.get(table.source)
        if descriptor is None:
            raise ValueError(f"{table.source}: category rules name a source with no descriptor")
        if descriptor.catalog != "products":
            raise ValueError(
                f"{table.source}: category rules on a `catalog: {descriptor.catalog}` source can "
                f"never fire -- its rows reach the product catalog only through "
                f"`crossoverToProducts`, which stamps a category itself. Delete the table."
            )

    outcome = Outcome(clause_hits=_count_clause_hits(joined.entities, rules))
    if not paths.catalog_products.exists():
        return outcome

    for path in sorted(paths.catalog_products.glob("*.yaml")):
        document = read_yaml(path) or {}
        records = [CanonicalProduct.model_validate(row) for row in document.get("products") or []]
        touched = False
        for record in records:
            if record.categoryBasis in REPLACEABLE:
                outcome.considered += 1
                members = joined.entities.get(record.id) or []
                decision, conflicts = decide(
                    record.id, members, joined.kinds, rules, _barcodes(record), paint_barcodes
                )
                outcome.conflicts.extend(conflicts)
                if decision is not None and decision.category is not None:
                    outcome.decided += 1
                    outcome.by_basis[decision.basis] += 1
                    _stamp(record, decision)
                    touched = True
                else:
                    _count_unmapped(outcome, members)
            outcome.catalog_basis[record.categoryBasis or "none"] += 1
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
