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

from pydantic import BaseModel, ConfigDict, model_validator

from warhub_acquisition.yamlio import read_yaml

_FORMS = ("nameMatches", "hintEquals", "hintContainsAny")


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
    # Scalar hint == value. Dotted keys reach into a nested hint: `hierarchy.lvl1` is how GW's
    # Algolia levels are addressed (see decide.py::flatten_hints).
    hintEquals: dict[str, str] | None = None
    # List hint intersects these values. EXACT membership, never substring.
    hintContainsAny: dict[str, list[str]] | None = None

    category: str | None = None
    packaging: str | None = None

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
        if not self.category and not self.packaging:
            raise ValueError("a category clause must set `category`, `packaging`, or both")
        return self


class SourceRules(BaseModel):
    """One store's table. Clause ORDER is load-bearing: the first match wins, so narrow clauses
    go first -- the same convention crossover descriptors follow."""

    model_config = ConfigDict(extra="forbid")

    source: str
    # Why this table's author believed the mapping, in the repo's usual measured style. Required,
    # because a table of 70 bare `word: slug` pairs is exactly the artefact nobody can later audit.
    reason: str
    clauses: list[CategoryClause]

    @model_validator(mode="after")
    def _non_empty(self) -> "SourceRules":
        if not self.clauses:
            raise ValueError(f"{self.source}: a rule file with no clauses decides nothing")
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
        if table.source != path.stem:
            raise ValueError(
                f"{path.name} declares source {table.source!r}; the filename must match the id"
            )
        rules[table.source] = table
    return rules
