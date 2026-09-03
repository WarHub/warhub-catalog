"""The cross-source name lexicon: what a product's own NAME says when no taxonomy does.

WHY IT IS NOT A PER-SOURCE TABLE. A name belongs to the product, not to the shop that lists it, so
a lexicon entry written into eight source tables would be one rule maintained eight times -- and
the sources that need it most publish no taxonomy at all. `mfr-gw-trade` is the sole source for
3,330 undecided products and carries nothing but a stock-section code and a shipping-box code;
what it does carry is names like `CODEX: SPACE WOLVES (HB) (FRANCAIS)` and `B: KHORNE RED 12ML JUC
X6`, which say plainly what the row is.

LAST, ALWAYS. A store's per-product filing and the paint catalog's barcode are both statements
about THIS product; a name pattern is an inference from how the thing is written. It runs only
after both, and only on products still resting on a fallback.

EVERY PATTERN CARRIES ITS MEASUREMENT, and the file is where the measurement lives rather than a
commit message, because the next person to add a pattern needs the bar rather than the result.
Re-derive with scripts/measure_category_rules.py, which scores a rule against the products some
other source independently decided.

AN ENTRY ANSWERS ITS OWN AXES. Since the `role` axis (categories.yaml axis 3) exists, an entry may
name a category, a role, or both, and the match is taken PER AXIS: the first entry that answers
the category decides the category, the first that answers the role decides the role, and an entry
that only names a role never blocks a later entry from naming the category. `\bVARNISH\b` is a
varnish whatever shelf the product is on; whether it is `paint` is a different question, answered
by the boundary in categories.yaml and measured separately.
"""
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from warhub_acquisition.yamlio import read_yaml


class LexiconEntry(BaseModel):
    """One case-insensitive regex over the published name -> a category, a role, or both."""

    model_config = ConfigDict(extra="forbid")

    nameMatches: str
    category: str | None = None
    role: str | None = None
    #: Required, unlike a rule table's optional `note`. A lexicon entry is the weakest signal this
    #: stage acts on and the easiest to write carelessly, so the number that justified it has to be
    #: in the file: how many undecided products it reaches, and how it scored against products
    #: other evidence had already decided.
    measured: str

    @model_validator(mode="after")
    def _compiles(self) -> "LexiconEntry":
        try:
            re.compile(self.nameMatches)
        except re.error as exc:
            raise ValueError(f"lexicon pattern {self.nameMatches!r} does not compile: {exc}") from exc
        if self.category is None and self.role is None:
            raise ValueError(
                f"lexicon pattern {self.nameMatches!r} must decide a category, a role, or both"
            )
        return self


class Lexicon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    #: ORDER IS LOAD-BEARING, first match wins -- the same convention the rule tables and the
    #: crossover descriptors follow. Narrow patterns first.
    entries: list[LexiconEntry]

    def match(self, name: str, axis: str = "category") -> LexiconEntry | None:
        """The first entry that ANSWERS `axis` and matches -- an entry silent on the axis is
        skipped, so a role-only entry never swallows the category question."""
        for entry in self.entries:
            if getattr(entry, axis) and re.search(entry.nameMatches, name or "", re.IGNORECASE):
                return entry
        return None


def load_lexicon(taxonomy_dir: Path) -> Lexicon | None:
    """`data/catalog/taxonomy/category-lexicon.yaml`, or None when it is absent."""
    path = taxonomy_dir / "category-lexicon.yaml"
    if not path.exists():
        return None
    return Lexicon.model_validate(read_yaml(path))
