"""Per-source rule tables: `data/catalog/taxonomy/category-rules/<source>.yaml`.

ONE CLAUSE VOCABULARY FOR THE WHOLE REPO. A clause here is the same shape a crossover clause is
(models/descriptor.py::CrossoverClause) and is evaluated by the same function
(resolve/crossover.py::clause_matches). That is not tidiness -- two matchers with the same three
key names and different semantics is a trap a reader cannot see, and `hintContainsAny` in
particular has a hard-won rule behind it (EXACT value membership, never substring; Army Painter's
four genuine airbrush SETS carry a tag containing the brush-set exclusion's substring).

A RULE FILE IS A CLAIM ABOUT ONE STORE'S VOCABULARY, not about products. `productType: Paints` on
goblingaming.com means the store filed that product under Paints; whether the store is RIGHT is a
separate question, answered by clause order and by which source wins the kind ladder. So each file
names its source, carries the reason its author believed the mapping, and is validated against the
declared vocabulary (data/catalog/taxonomy/categories.yaml) so a typo cannot invent a category.
"""
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from warhub_acquisition.yamlio import read_yaml

_FORMS = ("nameMatches", "codeMatches", "hintEquals", "hintContainsAny")
_OUTPUTS = ("category", "packaging", "gameSystems", "settings", "faction", "generic")
#: The axes a veto may name. `generic` is not among them: it is not a field a product carries but
#: a statement about the two membership axes at once, and it is silenced by vetoing those.
AXES = ("category", "packaging", "faction", "gameSystems", "settings")


class CategoryClause(BaseModel):
    """One signal -> one category and/or packaging.

    Exactly one signal form per clause, exactly as CrossoverClause requires and for the same
    reason: two forms in one clause would silently mean AND, which no table needs and every reader
    would have to guess at. Combine signals by writing two clauses.
    """

    model_config = ConfigDict(extra="forbid")

    # Regex against the observation's own name, case-insensitive. The escape hatch for a store
    # whose taxonomy does not separate what a rule needs -- use it last, and prefer a store field.
    nameMatches: str | None = None
    # Regex against the PRODUCT's own code. A manufacturer that numbers its range systematically
    # has already answered questions its store pages only imply: `^\d{4}02` reads "GW code digits
    # 5-6 are 02", i.e. Age of Sigmar. Only meaningful in a manufacturer table (see SourceRules),
    # because a code belongs to the product rather than to whoever is selling it.
    codeMatches: str | None = None
    # Scalar hint == value. Dotted keys reach into a nested hint: `hierarchy.lvl1` is how GW's
    # Algolia levels are addressed (see decide.py::flatten_hints).
    hintEquals: dict[str, str] | None = None
    # List hint intersects these values. EXACT membership, never substring.
    hintContainsAny: dict[str, list[str]] | None = None

    category: str | None = None
    packaging: str | None = None
    # A clause may decide any dimension the same signal settles. A store shelf that says
    # `Miniatures/Infinity/Yu Jing` answers three questions at once, and splitting it across three
    # tables keyed on the same value would be three chances to disagree with itself.
    #
    # `gameSystems` IS A LIST AND IT ACCUMULATES, unlike every other output here. A store shelves
    # one product under several games -- GW's own store shelves 183 of them (`Cerastus Knight
    # Castigator` under The Horus Heresy and Warhammer 40,000) -- so the clauses that match are the
    # source's whole claim, not a race the first one wins. The scalar outputs stay first-match:
    # a product is one thing, and two clauses naming different categories is a disagreement.
    gameSystems: list[str] = Field(default_factory=list)
    # THE SETTING, where the game cannot be named. Same shape and the same accumulation as
    # `gameSystems`, and it exists for the products a game clause could never place honestly: a
    # Black Library novel is set in Warhammer 40,000 and belongs to no game; a laser-cut Normandy
    # farmhouse is a Second World War building however many WWII games it is sold for. For a
    # product that HAS a game, its settings derive from the game and a clause here can only agree.
    settings: list[str] = Field(default_factory=list)
    faction: str | None = None
    # THIS PRODUCT BELONGS TO NO GAME AND NO SETTING, as a positive decision. A bag of dice, a
    # neoprene mat, a modular fantasy terrain kit sold for any game: the honest answer on both
    # membership axes is `not-applicable`, and until this existed a table could only VETO them --
    # which leaves `unknown`, i.e. "not decided yet", about products that are decided.
    generic: bool = False

    # WHICH AXES THIS VETO SILENCES -- `noneOf` entries only. A veto says "the signal is present
    # and settles nothing", and until now that meant nothing about ANY axis, which was measurably
    # too broad: Games Workshop's four code vetoes exist because `d34=85/86` (Forge World) and
    # `d78=81` (Black Library) do not determine the GAME, and they were also blocking every
    # category rule from reaching those 1,635 products -- even though Forge World is 99.8%
    # `miniatures` and Black Library 99.0% `book` against independent evidence. Naming the axis is
    # what lets one table refuse the question it cannot answer and still answer the one it can.
    #
    # Empty means ALL axes, which is the semantics `resolve/crossover.py`'s `noneOf` has and the
    # right default for a signal an author judged unusable outright.
    blocks: list[str] = Field(default_factory=list)

    # Free text, and the only field here that is for humans. A clause that maps a store's word to
    # one of ours is a judgement, and the next person to read it needs the judgement, not just its
    # result: `Retail` -> `paint` is obvious once you know Turbo Dork files its whole retail paint
    # line under it, and inexplicable otherwise.
    note: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> "CategoryClause":
        forms = [name for name in _FORMS if getattr(self, name)]
        if len(forms) != 1:
            raise ValueError(
                f"a category clause must set exactly one NON-EMPTY of {'/'.join(_FORMS)}, "
                f"got {forms or ['none']}"
            )
        return self


class SourceRules(BaseModel):
    """One store's table. Clause ORDER is load-bearing: the first match wins, so narrow clauses
    go first -- the same convention crossover descriptors follow."""

    model_config = ConfigDict(extra="forbid")

    # EXACTLY ONE SCOPE. `source` tables are evaluated against that store's own observations --
    # its shelves, its tags, its words about this product. `manufacturer` tables are evaluated
    # against the PRODUCT (its name and its code), because a maker's numbering scheme is a fact
    # about the thing rather than about whoever is reselling it.
    source: str | None = None
    manufacturer: str | None = None
    # Why this table's author believed the mapping, in the repo's usual measured style. Required,
    # because a table of 70 bare `word: slug` pairs is exactly the artefact nobody can later audit.
    reason: str
    # Vetoes, evaluated FIRST and unconditionally -- a vetoed product can never be rescued by a
    # later clause. Same shape and same semantics as a crossover descriptor's `noneOf`
    # (resolve/crossover.py::matched_clause), deliberately: this is the repo's existing way to say
    # "not these, whatever else you concluded", and a second spelling would be a trap.
    #
    # It is how a table REFUSES. Games Workshop's Forge World codes span two game systems and its
    # Black Library codes name a novel's setting rather than the kit's, so both must decide nothing
    # -- and saying so costs one clause, where a rule that quietly returned the segment's system
    # would be wrong on every one of them.
    noneOf: list[CategoryClause] = []
    clauses: list[CategoryClause]

    @property
    def scope(self) -> str:
        return self.source or self.manufacturer or "?"

    @model_validator(mode="after")
    def _non_empty(self) -> "SourceRules":
        if bool(self.source) == bool(self.manufacturer):
            raise ValueError(f"{self.scope}: a rule file must name exactly one of source/manufacturer")
        if not self.clauses:
            raise ValueError(f"{self.scope}: a rule file with no clauses decides nothing")
        # A DECIDING clause must decide something; a VETO must not. The check lives here rather
        # than on the clause because the two lists want opposite answers from the same type.
        for clause in self.clauses:
            if not any(getattr(clause, name) for name in _OUTPUTS):
                raise ValueError(
                    f"{self.scope}: a clause must decide at least one of {'/'.join(_OUTPUTS)}"
                )
        for clause in self.noneOf:
            if any(getattr(clause, name) for name in _OUTPUTS):
                raise ValueError(
                    f"{self.scope}: a `noneOf` veto must decide nothing -- it exists to say the "
                    "signal is present and settles nothing"
                )
            unknown = [axis for axis in clause.blocks if axis not in AXES]
            if unknown:
                raise ValueError(
                    f"{self.scope}: a veto's `blocks` names {unknown}, which are not axes; "
                    f"choose from {'/'.join(AXES)}"
                )
        for clause in self.clauses:
            if clause.blocks:
                raise ValueError(
                    f"{self.scope}: `blocks` is for `noneOf` vetoes -- a deciding clause silences "
                    "nothing"
                )
        if self.manufacturer is None and any(c.codeMatches for c in [*self.clauses, *self.noneOf]):
            raise ValueError(
                f"{self.source}: `codeMatches` reads the PRODUCT's code, which a source table does "
                "not own -- put it in a manufacturer table"
            )
        return self


def load_category_rules(directory: Path) -> dict[str, SourceRules]:
    """`{source_id: SourceRules}`, empty when the directory is absent.

    The FILENAME is the source id and must agree with the `source:` field inside. Two ways to say
    the same thing is how a file ends up silently applying to a source it does not name -- which
    would be invisible, since a table that matches nothing looks exactly like a store that has no
    taxonomy.
    """
    if not directory.exists():
        return {}
    rules: dict[str, SourceRules] = {}
    for path in sorted(directory.glob("*.yaml")):
        table = SourceRules.model_validate(read_yaml(path))
        if table.scope != path.stem:
            raise ValueError(
                f"{path.name} declares scope {table.scope!r}; the filename must match the id"
            )
        rules[table.scope] = table
    return rules
