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
        return code if re.fullmatch(spec.codePattern, code, flags=re.IGNORECASE) else None
