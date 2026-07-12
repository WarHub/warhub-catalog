"""One source's latest claim about one product."""
from pydantic import BaseModel, ConfigDict, Field


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    url: str | None = None
    manufacturer: str | None = None
    name: str
    sku: str | None = None
    ean: str | None = None
    priceGbp: float | None = None
    priceUsd: float | None = None
    priceEur: float | None = None
    availability: str | None = None
    hints: dict[str, object] = Field(default_factory=dict)
    firstSeen: str
    lastSeen: str
    missStreak: int = 0
    archived: bool = False
    extractor: str

    @property
    def source_id(self) -> str:
        return self.key.split(":", 1)[0]
