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
    # Archival lineage, from matches.yaml `supersessions`. Both records are published: the retired
    # one keeps its own productCode/ean/name and points forward via `supersededBy`; the surviving
    # one lists its predecessors in `supersedes`. Deliberately NOT expressed as a `status` value --
    # `status` is a free string every consumer filters on, and a new value there would silently
    # exclude exactly the archival records this is meant to keep reachable.
    supersedes: list[str] = Field(default_factory=list)
    supersededBy: str | None = None
    gameSystem: str | None = None
    faction: str | None = None
    category: str | None = None
    packaging: str | None = None
    quantity: int | None = None
    volumeMl: int | None = None
    # NET CONTENTS in grams, for the products sold by mass rather than by volume. Sibling of
    # volumeMl, never a replacement -- either, both or neither. Measured 2026-08-06: 3 of 22,529
    # products name a mass (2 GW `WH COLOUR PLASTIC GLUE (15g)` regional SKUs, 1 Mantic
    # `Colour Forge Basing Sand - Fine Grit - 400g`) and none of them carries a volume, so this
    # closes an ABSENCE on the product side rather than correcting an error. It exists chiefly so
    # the cross-catalog seam cannot disagree with itself: a barcode resolving to both a paint and
    # a product must not have net contents on one side and silence on the other.
    #
    # NOTHING FEEDS IT YET AND THAT IS DELIBERATE. It flows the moment a source emits a `weightG`
    # hint (it is in resolve.attributes._HINT_FIELDS), and no source does today -- the only
    # mass-shaped hint in the corpus is Shopify's `grams`, which is GROSS SHIPPING weight on 1,843
    # observations (a brush 3 g, an 18 ml dropper 26-31 g) and must never be wired here.
    weightG: int | None = None
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
