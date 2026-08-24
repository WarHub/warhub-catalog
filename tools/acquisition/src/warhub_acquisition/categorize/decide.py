"""One product's members + the rule tables + the paint archive -> one decision, with its receipt."""
from dataclasses import dataclass
from typing import Mapping, Sequence

from warhub_acquisition.models.descriptor import KIND_PRIORITY
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve import crossover

from .rules import CategoryClause, SourceRules

#: What decided a category, in the order this module tries them. Published on the record as
#: `categoryBasis` alongside the resolver's own `stated`/`default`/`guessed`.
MAPPED = "mapped"
PAINT_BARCODE = "paint-barcode"


@dataclass(frozen=True)
class Decision:
    category: str | None
    packaging: str | None
    basis: str
    #: Human-readable receipt, e.g. `ret-goblingaming productType=Paints`. Goes in the review
    #: file, never on the published record -- the record carries the basis, and the basis plus
    #: the committed rule table reproduces this string.
    why: str


@dataclass(frozen=True)
class Conflict:
    entity: str
    kind: str
    detail: str


def flatten_hints(hints: Mapping[str, object]) -> dict[str, object]:
    """`{"hierarchy": {"lvl1": [...]}}` -> `{"hierarchy.lvl1": [...]}`, everything else verbatim.

    EXISTS SO THE CLAUSE EVALUATOR STAYS UNCHANGED. GW's Algolia rows are the only nested hint in
    the store, and their useful level is lvl1 (51 distinct values over 2,889 rows, against 1,066
    at lvl3 -- lvl1 is a taxonomy, lvl3 is a long tail). Teaching `clause_matches` to walk a path
    would fork the one evaluator crossover and categorize share; normalising the input does not.
    """
    flat: dict[str, object] = {}
    for key, value in hints.items():
        if isinstance(value, Mapping):
            for inner, nested in value.items():
                flat[f"{key}.{inner}"] = nested
        else:
            flat[key] = value
    return flat


def _clause_hit(observation: Observation, clause: CategoryClause) -> bool:
    return crossover.clause_matches(
        observation.name or "",
        flatten_hints(observation.hints),
        clause.model_dump(exclude_none=True),
    )


def _signal(clause: CategoryClause) -> str:
    if clause.hintEquals:
        return " ".join(f"{k}={v}" for k, v in sorted(clause.hintEquals.items()))
    if clause.hintContainsAny:
        return " ".join(f"{k}~{','.join(v)}" for k, v in sorted(clause.hintContainsAny.items()))
    return f"name~{clause.nameMatches}"


def _ordered(members: Sequence[Observation], kinds: Mapping[str, str]) -> list[Observation]:
    """The kind ladder, then the key -- the same ordering resolve/attributes.py folds hints by, so
    a category derived here comes from the same source that would have supplied a stated one."""
    return sorted(
        members,
        key=lambda m: (KIND_PRIORITY.get(kinds.get(m.source_id, "barcode-db"), 9), m.key),
    )


def decide(
    entity: str,
    members: Sequence[Observation],
    kinds: Mapping[str, str],
    rules: Mapping[str, SourceRules],
    barcodes: Sequence[str],
    paint_barcodes: frozenset[str],
) -> tuple[Decision | None, list[Conflict]]:
    """The decision for one undecided product, and anything a maintainer should look at.

    PRECEDENCE, and the reasoning that fixes it:

      1. `mapped` -- a clause over the taxonomy the selling store published for THIS product,
         taken from the highest-priority source that matches one.
      2. `paint-barcode` -- the paint catalog publishes this product's barcode, so the thing in
         the box is a paint. Second, not first, ON PURPOSE: a store's filing is a statement about
         one product by the party that sells it, while this is an inference drawn ACROSS the two
         catalogs. The weaker claim must not overrule the product pipeline's own evidence -- that
         is also the rule that keeps the two pipelines' CI from deadlocking (data-ci.yml header).

    A disagreement between the two is reported rather than silently resolved: it usually means a
    single pot is filed under a set's word, or a medium is filed as a paint, and both are worth a
    human deciding once rather than a rule guessing every night.
    """
    conflicts: list[Conflict] = []
    hits: list[tuple[Observation, CategoryClause]] = []
    for member in _ordered(members, kinds):
        table = rules.get(member.source_id)
        if table is None:
            continue
        for clause in table.clauses:
            if _clause_hit(member, clause):
                hits.append((member, clause))
                break

    # SAME-KIND DISAGREEMENT ONLY. Two retailers filing a product differently is a real editorial
    # split worth a look; a manufacturer and a retailer disagreeing is what the kind ladder is FOR
    # and reporting it would bury the first kind under thousands of the second.
    if hits:
        by_kind: dict[str, set[str]] = {}
        for member, clause in hits:
            if clause.category:
                by_kind.setdefault(kinds.get(member.source_id, "barcode-db"), set()).add(clause.category)
        for kind, categories in sorted(by_kind.items()):
            if len(categories) > 1:
                sources = sorted(
                    f"{m.source_id}={c.category}"
                    for m, c in hits
                    if c.category and kinds.get(m.source_id, "barcode-db") == kind
                )
                conflicts.append(
                    Conflict(entity, "category-disagreement", f"{kind}: {'; '.join(sources)}")
                )

    decision: Decision | None = None
    if hits:
        member, clause = hits[0]
        decision = Decision(
            category=clause.category,
            packaging=clause.packaging,
            basis=MAPPED,
            why=f"{member.source_id} {_signal(clause)}",
        )

    is_paint = any(code in paint_barcodes for code in barcodes)
    if is_paint:
        if decision is None or decision.category is None:
            packaging = decision.packaging if decision else None
            decision = Decision("paint", packaging, PAINT_BARCODE, "barcode published by the paint catalog")
        elif decision.category != "paint":
            conflicts.append(
                Conflict(
                    entity,
                    "paint-barcode-vs-taxonomy",
                    f"the paint catalog publishes this barcode, but {decision.why} says "
                    f"{decision.category}",
                )
            )
    return decision, conflicts
