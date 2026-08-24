"""Run the decision over the resolved catalog, and write down what could not be decided.

READS THE CATALOG `resolve` JUST WROTE, and rewrites the records it can improve. Reading the
resolved records rather than re-resolving is what makes this stage cheap to re-run: a rule table
edited today is applied to evidence harvested weeks ago, with no network and no re-derivation of
identity.

THE REVIEW FILE IS THE PRODUCT, as much as the catalog is. A stage that decided 8,000 categories
and said nothing about the 20,000 it did not would be indistinguishable from one whose tables had
silently stopped matching. `data/review/categorize.yaml` therefore carries the counts, the
disagreements, and -- the part a maintainer actually works from -- the raw taxonomy values that
are still unmapped, ranked by how many undecided products each one would decide. That ranking is
the worklist: the top ten lines of it are worth more than the next two hundred.
"""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from warhub_acquisition.models.catalog import CanonicalProduct
from warhub_acquisition.resolve.resolver import DataPaths, _dump_product, joined_evidence
from warhub_acquisition.vocabulary import load_vocabulary
from warhub_acquisition.yamlio import read_yaml, write_yaml

from .decide import Conflict, Decision, decide, flatten_hints
from .paints import load_paint_barcodes
from .rules import load_category_rules

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
    decided: int
    considered: int
    by_basis: Counter
    conflicts: list[Conflict]
    unmapped: dict[str, Counter]


def _barcodes(record: CanonicalProduct) -> list[str]:
    return [str(code) for code in [record.ean, *record.additionalEans] if code]


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

    outcome = Outcome(0, 0, Counter(), [], {})
    if not paths.catalog_products.exists():
        return outcome

    for path in sorted(paths.catalog_products.glob("*.yaml")):
        document = read_yaml(path) or {}
        records = [CanonicalProduct.model_validate(row) for row in document.get("products") or []]
        touched = False
        for record in records:
            if record.categoryBasis not in REPLACEABLE:
                continue
            outcome.considered += 1
            members = joined.entities.get(record.id) or []
            decision, conflicts = decide(
                record.id, members, joined.kinds, rules, _barcodes(record), paint_barcodes
            )
            outcome.conflicts.extend(conflicts)
            if decision is None or decision.category is None:
                _count_unmapped(outcome, members, rules)
                continue
            outcome.decided += 1
            outcome.by_basis[decision.basis] += 1
            _stamp(record, decision)
            touched = True
        if touched and apply:
            write_yaml(
                path,
                {
                    "manufacturer": document.get("manufacturer") or path.stem,
                    "products": [_dump_product(record) for record in records],
                },
            )

    if apply:
        _write_review(paths.categorize_review, outcome)
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


def _count_unmapped(outcome: Outcome, members, rules) -> None:
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


def _write_review(path: Path, outcome: Outcome) -> None:
    undecided = outcome.considered - outcome.decided
    write_yaml(
        path,
        {
            "summary": {
                "considered": outcome.considered,
                "decided": outcome.decided,
                "undecided": undecided,
                "byBasis": dict(sorted(outcome.by_basis.items())),
            },
            "conflicts": [
                {"entity": c.entity, "type": c.kind, "detail": c.detail}
                for c in sorted(outcome.conflicts, key=lambda c: (c.entity, c.kind, c.detail))
            ],
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
