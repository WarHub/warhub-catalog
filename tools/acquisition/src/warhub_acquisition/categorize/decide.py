"""One product's members + the rule tables + the paint archive -> one decision, with its receipt."""
from dataclasses import dataclass
from typing import Mapping, Sequence

from warhub_acquisition.models.descriptor import KIND_PRIORITY
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve import crossover

from .lexicon import Lexicon
from .rules import CategoryClause, SourceRules

#: What decided a category, in the order this module tries them. Published on the record as
#: `categoryBasis` alongside the resolver's own `stated` and `unknown`.
MAPPED = "mapped"
#: The manufacturer's own product code, through a committed manufacturer table. Ranked BELOW a
#: store's explicit filing of this product and ABOVE the name lexicon: a numbering scheme is a
#: statement about the range, while a shelf is a statement about the product in front of you.
CODE = "code"
PAINT_BARCODE = "paint-barcode"
LEXICON = "lexicon"


@dataclass(frozen=True)
class Decision:
    category: str | None
    packaging: str | None
    basis: str
    #: Human-readable receipt, e.g. `ret-goblingaming productType=Paints`. Goes in the review
    #: file, never on the published record -- the record carries the basis, and the basis plus
    #: the committed rule table reproduces this string.
    why: str
    #: Every game this decision places the product in. A LIST, and it accumulates across the
    #: matching clauses of ONE source -- see `decide`.
    gameSystems: tuple[str, ...] = ()
    faction: str | None = None
    #: `mapped` or `code` -- which ladder rung supplied gameSystems/faction, which need not be the
    #: rung that supplied the category. A store can shelve a product by format while its
    #: manufacturer's code says which game it is, and both are true.
    game_systems_basis: str | None = None
    #: The receipt for the game systems specifically, which is a different sentence from `why`
    #: whenever a different rung supplied them.
    game_systems_why: str | None = None


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


def _product_hit(name: str, code: str, clause: CategoryClause) -> bool:
    """A manufacturer clause against the PRODUCT -- its own name and its own code, no hints."""
    return crossover.clause_matches(name, {}, clause.model_dump(exclude_none=True), code)


def _vetoed(table: SourceRules, hit, axis: str) -> bool:
    """`noneOf` first and unconditionally, for the axes each veto silences.

    A veto is how a table says "this signal exists and it means I must not answer". GW's Forge
    World codes span two systems and its Black Library codes name a novel's setting rather than
    the kit's; both match a segment rule that would otherwise be confidently wrong.

    PER AXIS, because a signal that cannot answer one question often answers another perfectly
    well. Both of those GW vetoes are about the GAME, and blocking the whole table on them was
    silencing a `miniatures`/`book` answer that is 99%+ pure on the same products. A veto with no
    `blocks` still silences everything -- see CategoryClause.blocks.
    """
    return any(
        hit(clause)
        for clause in table.noneOf
        if not clause.blocks or axis in clause.blocks
    )


def _signal(clause: CategoryClause) -> str:
    if clause.hintEquals:
        return " ".join(f"{k}={v}" for k, v in sorted(clause.hintEquals.items()))
    if clause.hintContainsAny:
        return " ".join(f"{k}~{','.join(v)}" for k, v in sorted(clause.hintContainsAny.items()))
    if clause.codeMatches:
        return f"code~{clause.codeMatches}"
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
    name: str = "",
    lexicon: Lexicon | None = None,
    manufacturer: str | None = None,
    code: str | None = None,
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
      3. `lexicon` -- the published NAME matches a cross-source pattern. Last, because the first
         two are statements about this product and this is an inference from how it is written.
         It exists for the sources that publish no taxonomy at all: mfr-gw-trade is the sole
         source for 3,330 undecided products and carries only a stock-section code, but its rows
         are named `CODEX: SPACE WOLVES (HB) (FRANCAIS)`.

    A disagreement between the two is reported rather than silently resolved: it usually means a
    single pot is filed under a set's word, or a medium is filed as a paint, and both are worth a
    human deciding once rather than a rule guessing every night.
    """
    conflicts: list[Conflict] = []
    hits: list[tuple[Observation, CategoryClause]] = []
    packaging_hits: list[tuple[Observation, CategoryClause]] = []
    faction_hits: list[tuple[Observation, CategoryClause]] = []
    system_claims: list[tuple[Observation, CategoryClause]] = []
    for member in _ordered(members, kinds):
        table = rules.get(member.source_id)
        if table is None or table.manufacturer is not None:
            continue
        vetoed = {
            axis: _vetoed(table, lambda clause: _clause_hit(member, clause), axis)
            for axis in ("category", "packaging", "faction", "gameSystems")
        }
        # ONE SCAN PER OUTPUT AXIS, each taking the first clause that DECIDES THAT AXIS.
        #
        # There used to be one scan for "the first clause that matches at all", and a clause that
        # answered a different question then silently swallowed the product. Two ways that lost
        # decisions the tables had already made, both measured 2026-09-01:
        #
        #   * ACROSS SOURCES -- 83 undecided products where a higher-priority source's
        #     gameSystem-only clause displaced a lower-priority source's category clause. 80 of
        #     them are ret-goblingaming's own committed table being blocked, mostly by
        #     mfr-manticgames' `kings-of-war` and `halo-flashpoint` clauses. That is half of
        #     goblingaming's undecided population, already covered by committed rules.
        #   * WITHIN ONE TABLE -- a clause that sets only `packaging` matched first and left the
        #     record with no category at all. Five committed clauses do exactly that
        #     (mfr-steamforged and mfr-warmachine `Digital Download`/`Free Resource`,
        #     mfr-wyrd-store `Digital STL`), covering 129 undecided products; the whole catalog
        #     carries `packaging: digital` on ONE record as a result.
        #
        # A store answers several questions from different rows of the same taxonomy --
        # goblingaming's `productType` says what a thing IS while its `tags` say which game it is
        # for -- so the axes must be read independently or whichever one the table happens to
        # answer earlier vetoes the rest.
        for axis, bucket in (
            ("category", hits), ("packaging", packaging_hits), ("faction", faction_hits)
        ):
            if vetoed[axis]:
                continue
            for clause in table.clauses:
                if getattr(clause, axis) and _clause_hit(member, clause):
                    bucket.append((member, clause))
                    break
        # ...AND THE GAME AXIS TAKES EVERY MATCH, not the first. See the accumulation below.
        if not vetoed["gameSystems"]:
            for clause in table.clauses:
                if clause.gameSystems and _clause_hit(member, clause):
                    system_claims.append((member, clause))

    # The manufacturer's own table, evaluated ONCE against the product rather than per observation,
    # because a product code belongs to the thing and not to whoever is reselling it.
    # PER AXIS HERE TOO, so one clause can supply the category while a veto silences the game --
    # which is exactly Forge World and Black Library. `code_clause` is therefore a dict of the
    # first clause that answers each axis and survives that axis's vetoes.
    code_clauses: dict[str, CategoryClause | None] = dict.fromkeys(
        ("category", "packaging", "faction", "gameSystems")
    )
    mtable = rules.get(manufacturer or "")
    if mtable is not None and mtable.manufacturer is not None and (code or name):
        for axis in code_clauses:
            if _vetoed(mtable, lambda clause: _product_hit(name, code or "", clause), axis):
                continue
            code_clauses[axis] = next(
                (
                    c for c in mtable.clauses
                    if getattr(c, axis) and _product_hit(name, code or "", c)
                ),
                None,
            )

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

    # ONE DIMENSION AT A TIME, first winner down the ladder. A store that files by format and a
    # manufacturer whose code names the game are not in competition -- they answer different
    # questions, and taking the category from one and the game system from the other is the whole
    # reason a clause may decide either.
    faction = next((c.faction for _, c in faction_hits if c.faction), None)
    packaging = next((c.packaging for _, c in packaging_hits if c.packaging), None)

    # THE WINNING SOURCE'S WHOLE CLAIM, exactly as resolve/attributes.py::_winner_claims folds the
    # stated hints. A store shelves one product under several games -- GW's own store does it for
    # 183 products, `Cerastus Knight Castigator` under both The Horus Heresy and Warhammer 40,000
    # -- so every clause of that store that matched is part of its answer. Sources BELOW it on the
    # ladder are not merged in: two stores naming different games is a disagreement, and unioning
    # it would invent a membership neither of them claims.
    game_systems: tuple[str, ...] = ()
    game_systems_basis = game_systems_why = None
    if system_claims:
        winner = system_claims[0][0].source_id
        won = [(m, c) for m, c in system_claims if m.source_id == winner]
        game_systems = tuple(sorted({slug for _, c in won for slug in c.gameSystems}))
        game_systems_basis = MAPPED
        signals = sorted({_signal(c) for _, c in won})
        game_systems_why = f"{winner} {'; '.join(signals)}"
    if not game_systems and code_clauses["gameSystems"] is not None:
        systems_clause = code_clauses["gameSystems"]
        game_systems = tuple(sorted(set(systems_clause.gameSystems)))
        game_systems_basis = CODE
        game_systems_why = f"{manufacturer} {_signal(systems_clause)}"
    if not faction and code_clauses["faction"] is not None:
        faction = code_clauses["faction"].faction
    if not packaging and code_clauses["packaging"] is not None:
        packaging = code_clauses["packaging"].packaging

    decision: Decision | None = None
    if hits:
        member, clause = hits[0]
        decision = Decision(
            category=clause.category,
            packaging=packaging,
            basis=MAPPED,
            why=f"{member.source_id} {_signal(clause)}",
            gameSystems=game_systems,
            faction=faction,
            game_systems_basis=game_systems_basis,
            game_systems_why=game_systems_why,
        )
    elif code_clauses["category"] is not None:
        code_clause = code_clauses["category"]
        decision = Decision(
            category=code_clause.category,
            packaging=packaging,
            basis=CODE,
            why=f"{manufacturer} {_signal(code_clause)}",
            gameSystems=game_systems,
            faction=faction,
            game_systems_basis=game_systems_basis,
            game_systems_why=game_systems_why,
        )
    elif packaging or game_systems or faction:
        # A DECISION WITH NO CATEGORY IS STILL A DECISION. Its `basis` describes the category rung
        # and there is none, so it says so; `_stamp` writes only the fields that are present.
        decision = Decision(
            category=None,
            packaging=packaging,
            basis="",
            why="",
            gameSystems=game_systems,
            faction=faction,
            game_systems_basis=game_systems_basis,
            game_systems_why=game_systems_why,
        )

    is_paint = any(code in paint_barcodes for code in barcodes)
    if is_paint:
        if decision is None or decision.category is None:
            decision = Decision(
                "paint", packaging, PAINT_BARCODE, "barcode published by the paint catalog",
                gameSystems=game_systems, faction=faction,
                game_systems_basis=game_systems_basis, game_systems_why=game_systems_why,
            )
        elif decision.category != "paint":
            conflicts.append(
                Conflict(
                    entity,
                    "paint-barcode-vs-taxonomy",
                    f"the paint catalog publishes this barcode, but {decision.why} says "
                    f"{decision.category}",
                )
            )

    if lexicon is not None and (decision is None or decision.category is None):
        entry = lexicon.match(name)
        if entry is not None:
            decision = Decision(
                entry.category,
                decision.packaging if decision else None,
                LEXICON,
                f"name matches /{entry.nameMatches}/",
                gameSystems=game_systems,
                faction=faction,
                game_systems_basis=game_systems_basis,
                game_systems_why=game_systems_why,
            )
    return decision, conflicts
