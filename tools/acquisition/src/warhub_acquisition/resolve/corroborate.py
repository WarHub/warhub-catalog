"""EAN corroboration: confidence from independent source agreement."""
from dataclasses import dataclass

from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.models.descriptor import KIND_PRIORITY
from warhub_acquisition.models.observation import Observation


@dataclass
class EanResolution:
    ean: str | None
    confidence: str | None
    conflicts: list[dict]


def resolve_ean(entity: str, members: list[Observation], kinds: dict[str, str]) -> EanResolution:
    assertions: dict[str, dict[str, str]] = {}  # ean -> {source_id: kind}
    for member in members:
        ean = canonical_ean(member.ean)
        if ean is None:
            continue
        kind = kinds.get(member.source_id, "barcode-db")
        assertions.setdefault(ean, {})[member.source_id] = kind

    if not assertions:
        return EanResolution(None, None, [])

    def strength(item: tuple[str, dict[str, str]]) -> tuple[int, int, str]:
        ean, sources = item
        best_kind = min(KIND_PRIORITY.get(kind, 9) for kind in sources.values())
        return (best_kind, -len(sources), ean)

    ranked = sorted(assertions.items(), key=strength)
    ean, sources = ranked[0]
    trusted = {sid for sid, kind in sources.items() if kind != "barcode-db"}
    has_authoritative = any(kind in ("manufacturer", "curated") for kind in sources.values())
    if has_authoritative or len(sources) >= 2 and len(trusted) >= 1:
        confidence = "confirmed"
    else:
        confidence = "provisional"

    conflicts: list[dict] = []
    if len(assertions) > 1:
        confidence = "conflicted"
        conflicts.append(
            {
                "type": "ean-mismatch",
                "entity": entity,
                "chosen": ean,
                "assertions": [
                    {"ean": e, "sources": sorted(s)} for e, s in sorted(assertions.items())
                ],
            }
        )
    return EanResolution(ean, confidence, conflicts)


def find_shared_eans(resolutions: dict[str, EanResolution]) -> list[dict]:
    by_ean: dict[str, list[str]] = {}
    for entity, resolution in sorted(resolutions.items()):
        if resolution.ean is not None:
            by_ean.setdefault(resolution.ean, []).append(entity)
    return [
        {"type": "ean-shared", "ean": ean, "entities": entities}
        for ean, entities in sorted(by_ean.items())
        if len(entities) > 1
    ]
