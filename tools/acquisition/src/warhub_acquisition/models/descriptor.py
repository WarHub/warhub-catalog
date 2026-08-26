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
    # Regex against the store's own title, case-insensitive.
    #
    # The word list every declaring source uses today is
    # `\b(SET|COLLECTION|FULL RANGE|BRIEFCASE|WOODEN BOX)\b`, and it is narrow on purpose. The
    # measurement behind it is about the WORD LIST, not about any one store, so it is recorded
    # here -- where someone writing a NEW name clause reads -- instead of being restated in five
    # descriptors, which would reproduce in prose exactly the unpinned duplication the copies
    # themselves have. Measured 2026-08-05 across the committed archive names and the source titles
    # joining a catalog single: PACK, KIT, BUNDLE, STARTER, MEGA, TRIAD, PALETTE, RANGE and COMBO
    # each produce ZERO false positives, and only `\bBOX\b` genuinely breaks -- on Turbo Dork's
    # real colour "Box Wine" -- which is why WOODEN BOX stays a two-word phrase.
    #
    # A token can be justified and still be invisible to any corpus: measured 2026-08-05,
    # `\bWOODEN BOX\b` matches NOTHING at all -- not one committed paint-source name, not one
    # observation name in any evidence directory -- while BRIEFCASE and FULL RANGE rest on only a
    # handful of sole-held rows each, all of them AK's, and COLLECTION on a handful more, none of
    # them AK's. That is why the five copies are pinned by STRING equality in
    # tests/test_repo_data.py::test_crossover_name_clauses_agree_unless_declared and NOT by
    # re-evaluating them over a fixture corpus: a corpus check goes green on a silent deletion of
    # WOODEN BOX and near-green on two more tokens. Re-derive with `crossover.clause_matches` over
    # data/evidence/products/*/observations.jsonl.
    nameMatches: str | None = None
    hintEquals: dict[str, str] | None = None  # scalar hint == value (hints.categorySlug, ...)
    # Overrides the BLOCK's `category` for rows this clause selects. Absent on almost every
    # clause: a source that crosses one kind of thing needs one stamp. See
    # resolve/crossover.py::category_for for the case that needs two.
    category: str | None = None
    # list hint intersects these values. EXACT value membership, never substring: Army Painter's
    # genuine airbrush paint sets carry the tag `Airbrush Warpaints`, which CONTAINS the substring
    # of the `brushset` exclusion but is not it (measured 2026-08-05, rows AW8001P-AW8004P).
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
    per source because the direction of failure genuinely flips between stores: measured 2026-08-05,
    greenstuffworld.com's title signal is a strict superset of its category signal,
    ak-interactive.com's two signals NEITHER contain the other, and reapermini.com's category signal
    does nearly all the work where its title signal is sparse. One shared rule would therefore be
    wrong for all three. Re-derive with `crossover.matches` over
    data/evidence/products/*/observations.jsonl.

    `matches()` in resolve/crossover.py is the single evaluator: the resolver uses it to admit
    these rows and the paint bridge uses it to refuse exactly the same ones, so the two catalogs
    cannot drift into publishing the same box twice or neither time.
    """

    model_config = ConfigDict(extra="forbid")
    # REQUIRED prose, matching the house style of every other per-source declaration here. It must
    # say WHY this source needs a predicate of its own and WHICH SIGNALS carry it -- the DIRECTION
    # of the relationship between them, and how to re-derive it.
    #
    # DELIBERATELY NOT A COUNT, and that reverses what this comment used to demand. It previously
    # required "the count the block selected on the day it was written", reasoning that the
    # descriptor's `contract` measures the WHOLE source, so nothing fires if the PREDICATE rather
    # than the source collapses, and a reader diffing that number was the only signal there was.
    # The signal never actually fired: re-harvests invalidated these counts silently, nothing
    # validates them (test_repo_data only asserts this string is >= 80 chars), and every stale one
    # was eventually caught by re-measuring rather than by anyone noticing a diff. A number here
    # rots without telling anyone, so state the relationship and the re-derivation instead.
    reason: str
    # Stamped onto hints.category for every crossed row. Measured-necessary, not cosmetic:
    # `category` is folded from hints by resolve/attributes.py:7, and the large majority of crossed
    # rows arrive carrying `hints.category: "paint"`. Only reapermini.com labels its boxes
    # `paint-set` itself, and even it has an exception -- 09985 "Sophie's Mystery Paint Set" says
    # `paint` like everyone else's. Without the stamp a multi-pot box publishes as `category:
    # paint` -- the structural lie commit 6b3c930 fixed. Re-derive with `crossover.matches` over
    # each paint source's observations.
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
    # product: measured 2026-07-30, every such record is `category: paint`/`paint-set`. Re-derive by
    # taking the descriptors here that say `catalog: paints` and counting their observations under
    # data/evidence/products/. Defaults to products, so only the paint sources say so.
    catalog: Literal["products", "paints"] = "products"
    strategy: str
    baseUrl: str | None = None
    scope: dict[str, object] = Field(default_factory=dict)
    politeness: dict[str, object] = Field(default_factory=dict)
    budget: dict[str, object] = Field(default_factory=dict)
    contract: Contract | None = None
    # Observation keys this source must never contribute, WITHOUT the `<source-id>:` prefix --
    # `test-product`, not `mfr-steamforged:test-product`. Enforced in `run_source`, not in any
    # strategy, because the problem is not strategy-specific: the storefront test entries this
    # exists for were found under BOTH `shopify` (steamforged.com) and `woo-store-api`
    # (manticgames.com). See `run_source` for the two things it does (drop + retract).
    #
    # EXACT KEYS ONLY, never a pattern, and that is the whole design. The obvious rule --
    # "titles starting with Test" -- would delete Para Bellum's genuine Conquest expansion
    # "Testing the Waters" (sku PBW1073, ean 5213009017671), which is live in the catalog with a
    # real barcode. A false positive here silently removes a real product and its barcode, so
    # this list never guesses; `test_no_published_product_looks_like_a_store_test_artifact`
    # is the tripwire that catches the next one instead.
    excludeKeys: list[str] = Field(default_factory=list)
    # Hint values this source emits as a PIPELINE FILL rather than as a claim about the product --
    # `{hint: value}`, and only the exact value named. A hint matching an entry here still folds
    # exactly as it always did (nothing about `category` changes), but the resulting record is
    # marked `categoryBasis: default` instead of `stated`, so it can be counted as what it is.
    #
    # WHY THIS EXISTS AS A DECLARATION rather than a rule in resolve/attributes.py. `legacy-catalog`
    # is `kind: curated` -- KIND_PRIORITY 0, the top of the ladder, so it outranks every
    # manufacturer and retailer -- and it hints `category` on all 12,799 of its observations, of
    # which 12,533 (97.9%) say `miniatures`. That is the old .NET pipeline's own default, not
    # anyone's assertion, and it wins the fold: 12,082 published products take their category from
    # it, and a crude name regex finds 357 it is plainly wrong about (`Legion Attack Dice Pack`,
    # `Galactic Empire Command Card Pack`). Counting those as evidence is what made the catalog
    # look 54% guessed when it is 93.6% guessed. Hardcoding the source id in the resolver would
    # bury that fact in a branch; declared here it sits next to the source it describes, and the
    # next curated import that ships a default says so in its own descriptor.
    #
    # It marks provenance. It does NOT suppress the value -- doing that is a data change, and it
    # belongs in its own PR with its own before/after measurement.
    defaultHints: dict[str, str] = Field(default_factory=dict)
    # Fields whose value this source carries as a FROZEN SNAPSHOT, not as a current claim. For
    # these fields only, this source sorts LAST in the attribute fold -- behind every other member
    # regardless of kind. It still fills a field nothing else supplies; it just stops overriding
    # something live.
    #
    # WHY A SOURCE CAN BE AUTHORITATIVE AND STALE AT THE SAME TIME. `legacy-catalog` is
    # `kind: curated` (KIND_PRIORITY 0, above manufacturer and retailer) and `strategy: none` -- a
    # frozen import that is never re-observed. Its rank is right for the things it curated and
    # wrong for the things that move. Measured 2026-08-21 over the 10,245 products where it meets
    # a live source, this is not one defect but four different answers:
    #
    #   availability  1,205 overridden, and 1,175 are a stale `in_stock` beating a live
    #                 `out_of_stock`. Unambiguously wrong.
    #   priceGbp/Usd    386 overridden -- a frozen RRP beating a live retail price (108.00 vs
    #                 91.80). The live number is the one a consumer can act on.
    #   name            981 overridden, and legacy is SHORTER in 733 -- "Black Panther and
    #                 Killmonger" against a retailer's "Black Panther and Killmonger - Marvel
    #                 Crisis Protocol". The curated name is BETTER; demoting it would be a
    #                 regression.
    #   url             470 overridden, and the live winner is a retailer listing in 354 -- legacy
    #                 points at the manufacturer's own product page. Also better.
    #
    # So the fix is per FIELD, not per source: demoting the source wholesale would fix availability
    # and damage names and urls. `kind` is deliberately NOT changed -- it is read in five places
    # (this fold, `curated_status`, the live/scraped_live lifecycle, `corroborate.py`'s EAN
    # confidence, and `join.py`'s identity ordering), and legacy's curated standing is correct in
    # all four of the others.
    staleFields: list[str] = Field(default_factory=list)
    # This source's `sku` is its own LISTING id: two of its observations carrying the same sku are
    # one store listing, and `resolve/join.py` unions them. Off by default.
    #
    # WHY THIS IS A DECLARATION AND NOT A GLOBAL RULE. A source's observation KEY is a function of
    # its strategy -- a sitemap path under `sitemap-structured-data`, a handle under `shopify` --
    # so changing a source's strategy re-keys every listing it has. `EvidenceStore.upsert` is
    # keyed per observation and a `full_sweep=False` source never prunes, so both generations sit
    # in the ledger and the store is represented twice; the later generation starts life with no
    # barcode and joins nothing. The store's own article number is the identity that survives that,
    # but only where the store actually keys on it -- an article number a store recycles across
    # products would fabricate one product out of two, which is why this is opt-in and why
    # `join.py` still refuses any group whose members disagree about the barcode.
    #
    # It is about the SOURCE's own rows only. It never joins across sources; two stores using the
    # same number for different things is the normal case, not a claim about anything.
    skuIsListingId: bool = False
    # A carve-out from `catalog: paints` back into the product catalog -- see Crossover. Left None
    # by all product sources and by the paint sources that declare no carve-out; each records why
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
