"""Source descriptors: declarative definition of one data source."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


def load_descriptors(directory: Path) -> dict[str, SourceDescriptor]:
    descriptors: dict[str, SourceDescriptor] = {}
    for path in sorted(directory.glob("*.yaml")):
        descriptor = SourceDescriptor.model_validate(read_yaml(path))
        if descriptor.id != path.stem:
            raise ValueError(f"descriptor id {descriptor.id!r} does not match filename {path.stem!r} ({path})")
        descriptors[descriptor.id] = descriptor
    return descriptors
