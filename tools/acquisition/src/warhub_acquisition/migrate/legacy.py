"""Read the legacy faction-file tree into legacy-catalog observations."""
from dataclasses import dataclass, field
from pathlib import Path

from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.identity import slugify
from warhub_acquisition.yamlio import read_yaml

_HINT_KEYS = ("category", "packaging", "status")
_OPTIONAL_HINT_KEYS = ("description", "eanSource")


@dataclass
class LegacyExtraction:
    observations: list[Observation] = field(default_factory=list)
    game_system_labels: dict[str, str] = field(default_factory=dict)
    faction_labels: dict[str, str] = field(default_factory=dict)
    label_to_game_system: dict[str, str] = field(default_factory=dict)
    label_to_faction: dict[str, str] = field(default_factory=dict)
    key_collisions: list[dict] = field(default_factory=list)
    invalid_records: list[dict] = field(default_factory=list)


def _register_label(mapping: dict[str, str], reverse: dict[str, str], slug: str, label: str) -> None:
    existing = mapping.get(slug)
    if existing is not None and existing != label:
        raise ValueError(f"slug {slug!r} has conflicting labels {existing!r} and {label!r}")
    mapping[slug] = label
    existing_slug = reverse.get(label)
    if existing_slug is not None and existing_slug != slug:
        raise ValueError(f"label {label!r} maps to both {existing_slug!r} and {slug!r}")
    reverse[label] = slug


def read_legacy_products(manufacturers_dir: Path, extractor: str = "legacy-catalog@1") -> LegacyExtraction:
    extraction = LegacyExtraction()
    seen_keys: set[str] = set()
    for path in sorted(manufacturers_dir.glob("*/*/*.yaml")):
        data = read_yaml(path)
        _register_label(
            extraction.game_system_labels, extraction.label_to_game_system,
            data["gameSystemSlug"], data["gameSystem"],
        )
        _register_label(
            extraction.faction_labels, extraction.label_to_faction,
            data["factionSlug"], data["faction"],
        )
        prefix = f"legacy-catalog:{data['manufacturerSlug']}/{data['gameSystemSlug']}/{data['factionSlug']}"
        for index, record in enumerate(data.get("products") or []):
            try:
                # Read all fallible fields and build candidate dict
                name = record["name"]
                slug = slugify(name)
                hints: dict[str, object] = {
                    "gameSystem": data["gameSystemSlug"],
                    "faction": data["factionSlug"],
                }
                for hint in _HINT_KEYS:
                    hints[hint] = record[hint]
                for hint in _OPTIONAL_HINT_KEYS:
                    if record.get(hint) is not None:
                        hints[hint] = record[hint]
                if record.get("productCode") is not None:
                    hints["legacyProductCode"] = record["productCode"]
                # All float conversions (may raise ValueError)
                priceGbp = float(record["priceGbp"]) if record.get("priceGbp") is not None else None
                priceUsd = float(record["priceUsd"]) if record.get("priceUsd") is not None else None
                priceEur = float(record["priceEur"]) if record.get("priceEur") is not None else None
                # Build candidate dict with sentinel key (will be replaced)
                candidate = {
                    "url": record["url"],
                    "manufacturer": data["manufacturerSlug"],
                    "name": name,
                    "sku": record.get("sku"),
                    "ean": record.get("ean"),
                    "priceGbp": priceGbp,
                    "priceUsd": priceUsd,
                    "priceEur": priceEur,
                    "availability": record["availability"],
                    "imageUrl": record.get("imageUrl"),
                    "hints": hints,
                    "firstSeen": record["firstSeen"],
                    "lastSeen": record["firstSeen"],
                    "extractor": extractor,
                }
            except (KeyError, TypeError, ValueError) as error:
                extraction.invalid_records.append(
                    {"file": str(path), "index": index, "error": repr(error)}
                )
                continue
            # Bookkeeping only after successful record parsing
            base_key = f"{prefix}/{slug}"
            key = base_key
            suffix = 2
            while key in seen_keys:
                key = f"{base_key}-{suffix}"
                suffix += 1
            if key != base_key:
                extraction.key_collisions.append(
                    {"type": "key-collision", "key": key, "name": name}
                )
            seen_keys.add(key)
            observation = Observation(key=key, **candidate)
            extraction.observations.append(observation)
    extraction.observations.sort(key=lambda o: o.key)
    return extraction
