"""Source descriptors: declarative definition of one data source."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from warhub_acquisition.yamlio import read_yaml

KIND_PRIORITY: dict[str, int] = {
    "curated": 0,
    "manufacturer": 1,
    "retailer": 2,
    "archive": 3,
    "barcode-db": 4,
}


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minCount: int = 0
    maxDropPct: float = 100.0
    requiredFieldRates: dict[str, float] = Field(default_factory=dict)


class CrossoverClause(BaseModel):
    """One signal by which a paint source's observation is recognised as a boxed SET.

    Exactly one of the three forms per clause -- a clause is a single signal, and `anyOf` is where
    signals combine. Allowing two forms in one clause would silently mean AND, which no source
    needs and every reader would have to guess at.
    """

    model_config = ConfigDict(extra="forbid")
    nameMatches: str | None = None  # regex against the store's own title, case-insensitive
    hintEquals: dict[str, str] | None = None  # scalar hint == value (hints.categorySlug, ...)
    # list hint intersects these values. EXACT value membership, never substring: Army Painter's
    # genuine airbrush paint sets carry the tag `Airbrush Warpaints`, which CONTAINS the substring
    # of the `brushset` exclusion but is not it (measured 2026-08-05, 4 rows AW8001P-AW8004P).
    hintContainsAny: dict[str, list[str]] | None = None

    @model_validator(mode="after")
    def _exactly_one_form(self) -> "CrossoverClause":
        # TRUTHINESS, not `is not None`, so this agrees with `resolve/crossover.clause_matches`,
        # which reads the same three keys with `if clause.get(...)`. Under the `is not None` form
        # an empty clause (`nameMatches: ''`, `hintEquals: {}`, `hintContainsAny: {}`) validated
        # cleanly and then silently matched nothing -- a block that selects zero rows while every
        # test in the suite passes, which is the exact failure test_repo_data's non-empty-`anyOf`
        # check exists to catch. It failed closed rather than open, and no committed descriptor was
        # affected, but a validator and an evaluator disagreeing about what "set" means is how a
        # future one gets written.
        set_forms = [
            name
            for name in ("nameMatches", "hintEquals", "hintContainsAny")
            if getattr(self, name)
        ]
        if len(set_forms) != 1:
            raise ValueError(
                "a crossover clause must set exactly one NON-EMPTY of nameMatches/hintEquals/"
                f"hintContainsAny, got {set_forms or ['none']}"
            )
        return self


class Crossover(BaseModel):
    """Which of a paint source's observations are PRODUCTS after all, and what to call them.

    Boxed multi-pot sets are products, not paints (maintainer decision 2026-08-05): before this
    they reached NEITHER catalog -- the resolver dropped the whole source (see resolver.py) and
    every bridge in gen_paint_harvest.py gates them out of data/paints/. The predicate is declared
    per source because the direction of failure genuinely flips between stores: measured
    2026-08-05, greenstuffworld.com's category signal selects 50 where the title selects 69 (a
    strict superset), ak-interactive.com's selects 216 where the title selects 153 and NEITHER
    contains the other, and reapermini.com's selects 114 where the title selects 19.

    `matches()` in resolve/crossover.py is the single evaluator: the resolver uses it to admit
    these rows and the paint bridge uses it to refuse exactly the same ones, so the two catalogs
    cannot drift into publishing the same box twice or neither time.
    """

    model_config = ConfigDict(extra="forbid")
    # REQUIRED prose, matching the house style of every other per-source declaration here. It must
    # carry the measurement AND the count the block selected on the day it was written: the
    # descriptor's `contract` measures the WHOLE source, so nothing fires if the PREDICATE (rather
    # than the source) collapses -- a future reader diffing against this number is the only signal.
    reason: str
    # Stamped onto hints.category for every crossed row. Measured-necessary, not cosmetic:
    # `category` is folded from hints by resolve/attributes.py:7, and 431 of the 545 selected rows
    # carry `hints.category: "paint"` (only 114 say `paint-set`, all Reaper's -- its 115th, 09985
    # "Sophie's Mystery Paint Set", says `paint` like everyone else's). Without the stamp a 12-pot
    # box publishes as `category: paint` -- the structural lie commit 6b3c930 just fixed.
    category: str
    anyOf: list[CrossoverClause] = Field(min_length=1)
    # Veto, evaluated FIRST and unconditionally: a row any of these match never crosses, however
    # many `anyOf` clauses it satisfies. Without it a name rule mislabels Army Painter's 7 brush
    # sets as paint-sets and there is nowhere to say otherwise.
    noneOf: list[CrossoverClause] = Field(default_factory=list)


class SourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["curated", "manufacturer", "retailer", "archive", "barcode-db"]
    # Which catalog this source feeds. Paint sources store their observations under
    # data/evidence/products/ like everything else (one evidence layout, one acquire runner), but
    # they describe PAINTS -- `gen_paint_harvest.py` projects them onto the paint catalog's own
    # identities. The product resolver must skip them, or every paint publishes a second time as a
    # product: measured 2026-07-30, 4,839 such records across 9 manufacturers, all of them
    # `category: paint`/`paint-set`. Defaults to products, so only the paint sources say so.
    catalog: Literal["products", "paints"] = "products"
    strategy: str
    baseUrl: str | None = None
    scope: dict[str, object] = Field(default_factory=dict)
    politeness: dict[str, object] = Field(default_factory=dict)
    budget: dict[str, object] = Field(default_factory=dict)
    contract: Contract | None = None
    # A carve-out from `catalog: paints` back into the product catalog -- see Crossover. Left None
    # by the 21 product sources and by the paint sources whose set-shaped rows are not products
    # (mfr-turbodork's rack/retailer-pack rows, mfr-mr-hobby's series-level rows); each records why
    # in a comment on its own descriptor.
    crossoverToProducts: Crossover | None = None

    @model_validator(mode="after")
    def _crossover_only_from_paints(self) -> "SourceDescriptor":
        # A `catalog: products` source already reaches the product catalog whole -- a carve-out
        # there would be inert, so it is far more likely a typo than an intent.
        if self.crossoverToProducts is not None and self.catalog != "paints":
            raise ValueError(
                f"{self.id}: crossoverToProducts requires `catalog: paints` (got {self.catalog!r}); "
                "a products source needs no carve-out"
            )
        return self


def load_descriptors(directory: Path) -> dict[str, SourceDescriptor]:
    descriptors: dict[str, SourceDescriptor] = {}
    for path in sorted(directory.glob("*.yaml")):
        descriptor = SourceDescriptor.model_validate(read_yaml(path))
        if descriptor.id != path.stem:
            raise ValueError(f"descriptor id {descriptor.id!r} does not match filename {path.stem!r} ({path})")
        descriptors[descriptor.id] = descriptor
    return descriptors
