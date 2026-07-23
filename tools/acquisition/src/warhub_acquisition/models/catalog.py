"""Canonical catalog records and human overrides."""
from pydantic import BaseModel, ConfigDict, Field


class CanonicalProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    manufacturer: str
    productCode: str | None = None
    sku: str | None = None
    ean: str | None = None
    eanConfidence: str | None = None
    # Extra barcodes a repackaged product carries beyond its primary `ean` (same contents,
    # new box/barcode -- joined via matches.yaml). Empty for the single-barcode majority, so
    # the published `ean` is unchanged for existing consumers. A confirmed barcode displaced
    # by a repackaging join lands here rather than being silently dropped (see resolve_ean).
    additionalEans: list[str] = Field(default_factory=list)
    gameSystem: str | None = None
    faction: str | None = None
    category: str | None = None
    packaging: str | None = None
    quantity: int | None = None
    volumeMl: int | None = None
    status: str
    availability: str | None = None
    firstSeen: str
    priceGbp: float | None = None
    priceUsd: float | None = None
    priceEur: float | None = None
    priceCad: float | None = None
    url: str | None = None
    imageUrl: str | None = None
    description: str | None = None
    evidence: list[str] = Field(default_factory=list)


class Overrides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retract: list[str] = Field(default_factory=list)
    products: dict[str, dict[str, object]] = Field(default_factory=dict)
