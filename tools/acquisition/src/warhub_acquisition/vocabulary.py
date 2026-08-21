"""The declared vocabularies for `category` and `packaging` (data/catalog/taxonomy/categories.yaml).

Until this module existed both fields were bare `str | None` and nothing validated either, so a
value could enter the published catalog from any of five unrelated mechanisms without anyone
declaring it meant something. That is how the catalog came to hold `paint`, `paint-set` and
`hobby-auxiliary` for three products off the same shelf.

VALIDATION IS A HARD ERROR, not a warning. An undeclared category reaching `data/catalog/products/`
is a value some consumer will filter on and no one has defined; failing the resolve is cheaper than
publishing it and freezing it into the contract (docs/OBJECTIVES.md 3). The same posture
`apply_classifications` takes for an unknown game system.

`status: legacy` values validate exactly like `current` ones. They are what the catalog already
holds, and refusing them would fail the resolve on today's committed data -- the migration to their
`mapsTo` target is a separate change with its own measurement. `mapsTo` is recorded here so that
migration has one authority; NOTHING IN THIS MODULE APPLIES IT.
"""
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from warhub_acquisition.yamlio import read_yaml


class VocabularyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    status: str = "current"
    definition: str | None = None
    boundary: str | None = None
    measured: str | None = None
    # Only on `status: legacy` entries: the current value a later migration folds this one into.
    mapsTo: str | None = None
    # Only on entries kept for a reason that outlives their definition (today: `paint-set`).
    frozen_reason: str | None = Field(default=None, alias="frozen-reason")


class Vocabulary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: int = 1
    categories: list[VocabularyEntry] = Field(default_factory=list)
    packaging: list[VocabularyEntry] = Field(default_factory=list)

    @property
    def category_slugs(self) -> frozenset[str]:
        return frozenset(entry.slug for entry in self.categories)

    @property
    def packaging_slugs(self) -> frozenset[str]:
        return frozenset(entry.slug for entry in self.packaging)

    def check(self, category: str | None, packaging: str | None, product_id: str) -> None:
        """Raise if either value is not declared. Absent is always fine -- see below."""
        # None is NOT a violation. `packaging` is unknown for 60% of the catalog and `category`
        # becomes nullable the moment a categorize stage can say "undecided" honestly; a vocabulary
        # that forced a value would be re-inventing the fallback this whole effort exists to remove.
        #
        # An axis with NOTHING declared does not validate either, per axis. Otherwise an absent
        # categories.yaml would reject every value rather than permitting them -- inverting what
        # `load_vocabulary` promises and breaking the package outside the monorepo. An empty axis
        # means "no vocabulary has been declared here", never "no value is legal here".
        if category is not None and self.category_slugs and category not in self.category_slugs:
            raise ValueError(
                f"{product_id}: category {category!r} is not declared in "
                f"data/catalog/taxonomy/categories.yaml (declared: {sorted(self.category_slugs)})"
            )
        if packaging is not None and self.packaging_slugs and packaging not in self.packaging_slugs:
            raise ValueError(
                f"{product_id}: packaging {packaging!r} is not declared in "
                f"data/catalog/taxonomy/categories.yaml (declared: {sorted(self.packaging_slugs)})"
            )


def load_vocabulary(taxonomy_dir: Path) -> Vocabulary:
    """Load the vocabulary, or an empty one if the file is absent.

    Absent means every `check` passes. That is deliberate and matches how `load_labels` treats a
    missing game-systems.yaml: the package is tested outside the monorepo, and every resolver
    fixture predates this file. A repo that HAS the file gets the guard; one that does not is not
    broken by its absence -- `tests/test_vocabulary.py` is what asserts this repo has it and that
    every value the committed catalog uses is declared in it.
    """
    path = taxonomy_dir / "categories.yaml"
    if not path.exists():
        return Vocabulary()
    return Vocabulary.model_validate(read_yaml(path))
