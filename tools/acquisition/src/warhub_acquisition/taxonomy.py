"""Taxonomy: manufacturer registry with code patterns and vendor-name mapping."""
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from warhub_acquisition.yamlio import read_yaml


class Manufacturer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    name: str
    codePattern: str | None = None
    codeStrip: list[str] = Field(default_factory=list)
    gs1Prefixes: list[str] = Field(default_factory=list)
    vendorNames: list[str] = Field(default_factory=list)


class Taxonomy:
    def __init__(self, manufacturers: dict[str, Manufacturer]) -> None:
        self.manufacturers = manufacturers
        self._vendor_index: dict[str, str] = {}
        for manufacturer in manufacturers.values():
            for vendor in [manufacturer.name, *manufacturer.vendorNames]:
                folded = vendor.casefold()
                existing = self._vendor_index.get(folded)
                if existing is not None and existing != manufacturer.slug:
                    raise ValueError(
                        f"vendor name {vendor!r} claimed by both {existing!r} and {manufacturer.slug!r}"
                    )
                self._vendor_index[folded] = manufacturer.slug

    @classmethod
    def load(cls, directory: Path) -> "Taxonomy":
        data = read_yaml(directory / "manufacturers.yaml")
        manufacturers = [Manufacturer.model_validate(entry) for entry in data["manufacturers"]]
        return cls({m.slug: m for m in manufacturers})

    def manufacturer_for_vendor(self, vendor: str) -> str | None:
        return self._vendor_index.get(vendor.casefold())

    def normalize_code(self, manufacturer: str, sku: str | None) -> str | None:
        spec = self.manufacturers.get(manufacturer)
        if spec is None or spec.codePattern is None or not sku:
            return None
        code = sku.upper().replace(" ", "")
        for prefix in spec.codeStrip:
            code = code.removeprefix(prefix.upper())
        code = code.removesuffix("-EN")
        match = re.fullmatch(spec.codePattern, code, flags=re.IGNORECASE)
        if match is None:
            return None
        # A NAMED GROUP DECLARES THE CANONICAL CODE, and without one the whole match is the code
        # (which is every pattern that predates this). It exists because some manufacturers' own
        # SKU carries a suffix that is not part of the identity: Corvus Belli writes the same
        # product as `280873` and as `280873-0990`, and 405 of its 794 codes appear BOTH ways
        # across the sources this repo harvests. Matching both forms as distinct codes would split
        # 405 products in two; refusing the suffixed form would drop most of the corpus. Neither is
        # what a `codeStrip` prefix list can express, because the suffix is a pattern rather than a
        # literal -- so the pattern names the part that IS the code.
        #
        # Only the FIRST non-empty named group is read, so a pattern with alternatives gives each
        # branch its own name and the branch that matched wins.
        named = [value for value in match.groupdict().values() if value]
        return named[0] if named else code


def load_labels(taxonomy_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    def read_map(path: Path, key: str) -> dict[str, str]:
        if not path.exists():
            return {}
        data = read_yaml(path)
        return {entry["slug"]: entry["label"] for entry in data[key]}

    return (
        read_map(taxonomy_dir / "game-systems.yaml", "gameSystems"),
        read_map(taxonomy_dir / "factions.yaml", "factions"),
    )
