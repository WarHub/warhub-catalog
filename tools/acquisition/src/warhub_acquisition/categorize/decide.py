"""One product's members + the rule tables + the paint archive -> one decision, with its receipt."""
from dataclasses import dataclass
from typing import Mapping, Sequence

from warhub_acquisition.models.descriptor import KIND_PRIORITY
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve import crossover

from .lexicon import Lexicon
from .rules import AXES, CategoryClause, SourceRules

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
    #: Every SETTING this decision places the product in, accumulated like `gameSystems` and
    #: carrying its own rung and receipt for the same reason.
    settings: tuple[str, ...] = ()
    settings_basis: str | None = None
    settings_why: str | None = None
    #: The product belongs to no game and no setting -- a clause said so, and this is the receipt.
    generic: bool = False
    generic_why: str | None = None
    # Whether `gameSystems` is a CLAIM (a shelf, the product's own name, a stated value they
    # united with) or a FILL from a code range. The stage lets a claim replace a `classified`
    # guess and lets a fill only fill a hole.
    game_systems_claimed: bool = False


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


def _stated_game(
    observation: Observation, default_hints: Mapping[str, Mapping[str, object]] | None
) -> object | None:
    """This observation's own `gameSystem` hint, unless it is its source's declared fill
    (SourceDescriptor.defaultHints -- legacy-catalog's `bolt-action` bucket is not a claim)."""
    value = (observation.hints or {}).get("gameSystem")
    if value is None:
        return None
    if (default_hints or {}).get(observation.source_id, {}).get("gameSystem") == value:
        return None
    return value


def _stated_game_systems(
    members: Sequence[Observation],
    kinds: Mapping[str, str],
    default_hints: Mapping[str, Mapping[str, object]] | None,
) -> set[str]:
    """What the resolver folded as the record's stated game: the first member in kind order that
    states one. One value or none, like the resolver's own fold."""
    for member in _ordered(members, kinds):
        value = _stated_game(member, default_hints)
        if value is not None:
            return {str(value)}
    return set()


def _states_one_of(
    observation: Observation, systems: set[str],
    default_hints: Mapping[str, Mapping[str, object]] | None = None,
) -> bool:
    """Whether this observation's own `gameSystem` hint names one of `systems`."""
    value = _stated_game(observation, default_hints)
    if value is None:
        return False
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return any(str(v) in systems for v in values)


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
    default_hints: Mapping[str, Mapping[str, object]] | None = None,
    catch_alls: frozenset[str] = frozenset(),
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
    setting_claims: list[tuple[Observation, CategoryClause]] = []
    generic_hits: list[tuple[Observation, CategoryClause]] = []
    for member in _ordered(members, kinds):
        table = rules.get(member.source_id)
        if table is None or table.manufacturer is not None:
            continue
        vetoed = {
            axis: _vetoed(table, lambda clause: _clause_hit(member, clause), axis)
            for axis in AXES
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
        # `generic` FIRST, AND IT IS THE WHOLE VERDICT. A shelf of dice or gaming mats carries every
        # game tag the store can think of -- `D6 Dice - white (30)` is tagged black-powder,
        # black-seas, bolt-action, hail-caesar and pike-shotte, each individually true and their
        # union false. A table that files that shelf `generic` has answered the membership
        # question for this source, and its game and setting clauses are not consulted: the
        # alternative was a veto, which answers nothing and left the product `unknown`.
        generic_clause = next(
            (c for c in table.clauses if c.generic and _clause_hit(member, c)), None
        )
        if generic_clause is not None:
            generic_hits.append((member, generic_clause))
            continue
        # ...AND THE GAME AXIS TAKES EVERY MATCH, not the first. See the accumulation below.
        if not vetoed["gameSystems"]:
            for clause in table.clauses:
                if clause.gameSystems and _clause_hit(member, clause):
                    system_claims.append((member, clause))
        # The setting axis likewise.
        if not vetoed["settings"]:
            for clause in table.clauses:
                if clause.settings and _clause_hit(member, clause):
                    setting_claims.append((member, clause))

    # The manufacturer's own table, evaluated ONCE against the product rather than per observation,
    # because a product code belongs to the thing and not to whoever is reselling it.
    # PER AXIS HERE TOO, so one clause can supply the category while a veto silences the game --
    # which is exactly Forge World and Black Library. `code_clause` is therefore a dict of the
    # first clause that answers each axis and survives that axis's vetoes.
    code_clauses: dict[str, CategoryClause | None] = dict.fromkeys((*AXES, "generic"))
    name_system_clauses: list[CategoryClause] = []
    mtable = rules.get(manufacturer or "")
    if mtable is not None and mtable.manufacturer is not None and (code or name):
        for axis in AXES:
            if _vetoed(mtable, lambda clause: _product_hit(name, code or "", clause), axis):
                continue
            code_clauses[axis] = next(
                (
                    c for c in mtable.clauses
                    if getattr(c, axis) and _product_hit(name, code or "", c)
                ),
                None,
            )
        # A generic clause is a decision, not a veto, and it is read whatever the vetoes say: the
        # author who wrote `generic: true` on a code block meant that block.
        code_clauses["generic"] = next(
            (c for c in mtable.clauses if c.generic and _product_hit(name, code or "", c)),
            None,
        )
        # Every NAME clause that answers the game axis, for the union below; a code-range clause is
        # a fill and is read through `code_clauses` only.
        if name and not _vetoed(mtable, lambda clause: _product_hit(name, code or "", clause), "gameSystems"):
            name_system_clauses = [
                c for c in mtable.clauses
                if c.gameSystems and c.nameMatches and _product_hit(name, code or "", c)
            ]

    # THE TOP KIND DECIDES, AND WITHIN IT THE VOTE. `hits` is in kind-then-key order, so the first
    # hit's kind is the highest that answered; among that kind's sources the category most of them
    # give wins. A TIE DECIDES NOTHING: it falls through to the code and name rungs below and is
    # reported. Measured 2026-09-02 over the 77 same-kind splits then open: 7 were two retailers
    # against one and every one had gone to the one because its id sorted first; 10 were 1:1 ties
    # settled by the alphabet and the alphabet was wrong in all 10 (`Acrylic Thinner` paint,
    # `Adeptus Titanicus: Traitor Legios` board-game).
    #
    # SAME-KIND DISAGREEMENT ONLY, AND ONLY THE KIND THAT DECIDES. Two retailers filing a product
    # differently is a real editorial split worth a look; a manufacturer and a retailer disagreeing
    # is what the kind ladder is FOR, and a split among retailers when a manufacturer's shelf
    # decided is a row nobody can act on -- 21 of the 53 rows then open were exactly that.
    top_kind = kinds.get(hits[0][0].source_id, "barcode-db") if hits else None
    top = [(m, c) for m, c in hits if kinds.get(m.source_id, "barcode-db") == top_kind]
    votes: dict[str, set[str]] = {}
    for m, c in top:
        votes.setdefault(c.category, set()).add(m.source_id)
    most = max((len(v) for v in votes.values()), default=0)
    leading = [category for category, voters in votes.items() if len(voters) == most]
    tied = len(leading) > 1
    if len(votes) > 1:
        sources = sorted(f"{m.source_id}={c.category}" for m, c in top)
        outcome = "a tie, left to the code and name rungs" if tied else f"decided {leading[0]}"
        conflicts.append(
            Conflict(entity, "category-disagreement", f"{top_kind}: {'; '.join(sources)} -- {outcome}")
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
    # WHICH SOURCE SPEAKS FOR THE MEMBERSHIP AXES: the first, in kind order, that said anything at
    # all -- a game, a setting, or that the product is generic. Its answer is the whole answer;
    # sources below it on the ladder are not merged in.
    rank = {m.source_id: i for i, m in reversed(list(enumerate(_ordered(members, kinds))))}
    spoke = [m.source_id for m, _ in [*system_claims, *setting_claims, *generic_hits]]
    winner_source = min(spoke, key=rank.__getitem__, default=None)
    generic = any(m.source_id == winner_source for m, _ in generic_hits)
    generic_why = None
    if generic:
        member, clause = next((m, c) for m, c in generic_hits if m.source_id == winner_source)
        generic_why = f"{member.source_id} {_signal(clause)}"
        system_claims = []
        setting_claims = []

    game_systems: tuple[str, ...] = ()
    game_systems_basis = game_systems_why = None
    claimed: set[str] = set()
    whys: list[str] = []
    claim_kind: int | None = None
    if system_claims:
        winner = system_claims[0][0].source_id
        won = [(m, c) for m, c in system_claims if m.source_id == winner]
        claimed |= {slug for _, c in won for slug in c.gameSystems}
        whys.append(f"{winner} {'; '.join(sorted({_signal(c) for _, c in won}))}")
        claim_kind = KIND_PRIORITY.get(kinds.get(winner, "barcode-db"), 9)
        game_systems_basis = MAPPED
    # THE PRODUCT'S OWN NAME IS THE MAKER SPEAKING, and it is a claim beside the shelves, not a
    # fill behind them. `Kill Team: Imperial Navy Breachers` is a Kill Team product whatever
    # department a store files it under, so a NAME clause in the manufacturer's table joins the
    # union at manufacturer rank. A CODE-RANGE clause stays a fill (below): GW's `02` range spans
    # two settings across a decade, and a range can only say what a product PROBABLY is.
    # Measured 2026-09-02: 8 products named for Kill Team stayed `warhammer-40k` because a shelf
    # had spoken first and the name could only report against it.
    if name_system_clauses:
        claimed |= {slug for c in name_system_clauses for slug in c.gameSystems}
        whys.append(f"{manufacturer} {'; '.join(sorted(_signal(c) for c in name_system_clauses))}")
        claim_kind = min(KIND_PRIORITY["manufacturer"], claim_kind if claim_kind is not None else 9)
        game_systems_basis = game_systems_basis or CODE
    # A SOURCE'S WHOLE CLAIM IS ITS STATED GAME PLUS ITS SHELVES. Warlord's store types
    # `productType: Bolt Action` on its Order Dice (the stated hint the resolver folded) and tags
    # them `gates-of-antares` (a mapped clause); both are the same store's answer, and the dice are
    # sold for both games. So where SOME source that stated the record's value is no more
    # authoritative than the claim assembled here, the stated set joins the union and the stage
    # extends the record instead of reporting a disagreement -- the store's own statement is part
    # of the store's own claim, whoever else agreed with it. A claim ranked below EVERY source that
    # stated the value still only reports: a manufacturer's shelf does not overrule a curated
    # import's word, it argues with it in the review file. Measured 2026-09-02: 22 of the 46 open
    # `gameSystem-disagreement` rows were one source contradicting itself this way (8 Order Dice,
    # 5 scenery packs, 3 Kill Team boxes, ...).
    #
    # THE STATED VALUE IS RE-READ FROM THE MEMBERS HERE -- the first row in kind order carrying a
    # `gameSystem` hint that is not its source's declared fill, the same fold resolve/attributes.py
    # does -- and not taken from the record, so that a second run of this stage over its own output
    # reaches the same union instead of reporting it as a disagreement (measured 2026-09-02: 431
    # rows, every one the previous run's own extension). A catch-all (`other-games`) is left out of
    # it: it says "one of these, unknown which", and a specific claim REFINES it in the stage
    # rather than sitting beside it.
    stated = {
        slug for slug in _stated_game_systems(members, kinds, default_hints) if slug not in catch_alls
    }
    if claimed and stated and claim_kind is not None:
        weakest_stater = max(
            (
                KIND_PRIORITY.get(kinds.get(m.source_id, "barcode-db"), 9)
                for m in members
                if _states_one_of(m, stated, default_hints)
            ),
            default=None,
        )
        if weakest_stater is not None and claim_kind <= weakest_stater:
            claimed |= stated
    if claimed:
        game_systems = tuple(sorted(claimed))
        game_systems_why = "; ".join(whys)
    # A GENERIC VERDICT OUTRANKS A CODE-RANGE FILL AND NOT THE NAME. A store filing a product on
    # its dice or terrain shelf has said it belongs to no game; a code range saying "this block is
    # Bolt Action" is a probability and yields to that, but a name printed on the box does not --
    # `Bolt Action Objective Marker Set` is a Bolt Action product on any shelf.
    if not game_systems and not generic and code_clauses["gameSystems"] is not None:
        systems_clause = code_clauses["gameSystems"]
        game_systems = tuple(sorted(set(systems_clause.gameSystems)))
        game_systems_basis = CODE
        game_systems_why = f"{manufacturer} {_signal(systems_clause)}"

    # THE SETTINGS, by the same two rungs and the same accumulation.
    settings: tuple[str, ...] = ()
    settings_basis = settings_why = None
    if setting_claims:
        winner = setting_claims[0][0].source_id
        won = [(m, c) for m, c in setting_claims if m.source_id == winner]
        settings = tuple(sorted({slug for _, c in won for slug in c.settings}))
        settings_basis = MAPPED
        settings_why = f"{winner} {'; '.join(sorted({_signal(c) for _, c in won}))}"
    if not settings and not generic and code_clauses["settings"] is not None:
        settings_clause = code_clauses["settings"]
        settings = tuple(sorted(set(settings_clause.settings)))
        settings_basis = CODE
        settings_why = f"{manufacturer} {_signal(settings_clause)}"

    # The manufacturer's own generic clause is the answer only where no rung placed the product
    # anywhere -- a code table's game clause, if one matched, already said which.
    if not generic and not game_systems and not settings and code_clauses["generic"] is not None:
        generic, generic_why = True, f"{manufacturer} {_signal(code_clauses['generic'])}"
    if not faction and code_clauses["faction"] is not None:
        faction = code_clauses["faction"].faction
    if not packaging and code_clauses["packaging"] is not None:
        packaging = code_clauses["packaging"].packaging

    decision: Decision | None = None
    if hits and not tied:
        member, clause = next((m, c) for m, c in top if c.category == leading[0])
        decision = Decision(
            category=clause.category,
            packaging=packaging,
            basis=MAPPED,
            why=f"{member.source_id} {_signal(clause)}",
            gameSystems=game_systems,
            faction=faction,
            game_systems_basis=game_systems_basis,
            game_systems_why=game_systems_why,
            settings=settings,
            settings_basis=settings_basis,
            settings_why=settings_why,
            generic=generic,
            generic_why=generic_why,
            game_systems_claimed=bool(claimed),
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
            settings=settings,
            settings_basis=settings_basis,
            settings_why=settings_why,
            generic=generic,
            generic_why=generic_why,
            game_systems_claimed=bool(claimed),
        )
    elif packaging or game_systems or faction or settings or generic:
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
            settings=settings,
            settings_basis=settings_basis,
            settings_why=settings_why,
            generic=generic,
            generic_why=generic_why,
            game_systems_claimed=bool(claimed),
        )

    is_paint = any(code in paint_barcodes for code in barcodes)
    if is_paint:
        if decision is None or decision.category is None:
            decision = Decision(
                "paint", packaging, PAINT_BARCODE, "barcode published by the paint catalog",
                gameSystems=game_systems, faction=faction,
                game_systems_basis=game_systems_basis, game_systems_why=game_systems_why,
                settings=settings, settings_basis=settings_basis, settings_why=settings_why,
                generic=generic, generic_why=generic_why,
                game_systems_claimed=bool(claimed),
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
                settings=settings,
                settings_basis=settings_basis,
                settings_why=settings_why,
                generic=generic,
                generic_why=generic_why,
                game_systems_claimed=bool(claimed),
            )
    return decision, conflicts


def game_axis_vetoed(
    rules: Mapping[str, SourceRules], manufacturer: str | None, name: str, code: str | None
) -> bool:
    """Whether the manufacturer's table vetoes the game axis for this product -- Black Library's
    segment, say. A classifier's guess there is a guess in a place the maker's own table says no
    game applies; the stage asks this for `classified` records and clears the guess."""
    table = rules.get(manufacturer or "")
    if table is None or table.manufacturer is None or not (code or name):
        return False
    return _vetoed(table, lambda clause: _product_hit(name, code or "", clause), "gameSystems")
