"""Materialize committed classification decisions (data/catalog/classifications/products.yaml)
as catalog overrides, un-parking the entities they classify.

apply_classifications does not itself re-run `resolve` -- the resolver already applies
overrides.products.<entity>.gameSystem/faction *before* it checks for a null gameSystem to park
an entity (see resolve/resolver.py resolve_catalog: apply_overrides then the `if
product.gameSystem is None` park check), so writing the override here is sufficient; the
operator re-runs `resolve` afterwards to actually un-park the entities.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict

from warhub_acquisition.models.catalog import Overrides
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import load_labels
from warhub_acquisition.yamlio import read_yaml, write_yaml


class ClassificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gameSystem: str
    faction: str | None = None
    decidedBy: Literal["llm", "human"]
    model: str | None = None
    inputHash: str | None = None
    date: str


def apply_classifications(paths: DataPaths) -> int:
    """Read committed decisions, validate every slug against the taxonomy, and merge them into
    overrides.yaml. Returns the number of classifications applied. Validation happens for every
    decision before anything is written, so an unknown slug anywhere leaves overrides.yaml
    untouched (no partial merge).
    """
    if not paths.classifications.exists():
        return 0

    raw = read_yaml(paths.classifications) or {}
    decisions = {entity: ClassificationDecision.model_validate(payload) for entity, payload in raw.items()}

    game_system_labels, faction_labels = load_labels(paths.taxonomy)
    for entity, decision in sorted(decisions.items()):
        if decision.gameSystem not in game_system_labels:
            raise ValueError(f"entity {entity!r}: unknown gameSystem slug {decision.gameSystem!r}")
        if decision.faction is not None and decision.faction not in faction_labels:
            raise ValueError(f"entity {entity!r}: unknown faction slug {decision.faction!r}")

    overrides = Overrides.model_validate(read_yaml(paths.overrides)) if paths.overrides.exists() else Overrides()
    for entity, decision in sorted(decisions.items()):
        # a decision present in classifications/products.yaml is authoritative for both
        # fields: writing faction=None here (re-classification with an explicit null, or a
        # decision that never had a faction) must clear any stale prior faction override
        # rather than leaving it in place.
        patch: dict[str, object] = {"gameSystem": decision.gameSystem, "faction": decision.faction}
        overrides.products[entity] = {**overrides.products.get(entity, {}), **patch}

    write_yaml(
        paths.overrides,
        {
            "retract": sorted(overrides.retract),
            "products": {entity: overrides.products[entity] for entity in sorted(overrides.products)},
        },
    )
    return len(decisions)
