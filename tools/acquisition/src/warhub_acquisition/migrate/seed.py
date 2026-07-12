"""Read curated seed files into seed-curated observations."""
from pathlib import Path

from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.identity import slugify
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import read_yaml

SEED_FIRST_SEEN = "2026-07-12"


def read_seed_products(
    seed_dir: Path,
    taxonomy: Taxonomy,
    label_to_game_system: dict[str, str],
    label_to_faction: dict[str, str],
    extractor: str = "seed-curated@1",
) -> list[Observation]:
    observations: dict[str, Observation] = {}
    for path in sorted(seed_dir.glob("*.yaml")):
        for record in read_yaml(path) or []:
            manufacturer = taxonomy.manufacturer_for_vendor(record["manufacturer"])
            if manufacturer is None:
                raise ValueError(f"seed manufacturer label not in taxonomy: {record['manufacturer']!r} ({path})")
            game_system = label_to_game_system.get(record["gameSystem"])
            if game_system is None:
                raise ValueError(f"seed gameSystem label not in legacy headers: {record['gameSystem']!r} ({path})")
            hints: dict[str, object] = {"gameSystem": game_system}
            faction_label = record.get("faction")
            if faction_label is not None:
                faction = label_to_faction.get(faction_label)
                if faction is None:
                    raise ValueError(f"seed faction label not in legacy headers: {faction_label!r} ({path})")
                hints["faction"] = faction
            for hint in ("status", "productType"):
                if record.get(hint) is not None:
                    hints[hint] = record[hint]
            contents = record.get("contents")
            if contents:
                hints["contents"] = contents
                hints["quantity"] = sum(int(unit["quantity"]) for unit in contents)
            key = f"seed-curated:{manufacturer}/{slugify(record['name'])}"
            if key in observations:
                raise ValueError(f"duplicate seed product key: {key}")
            observations[key] = Observation(
                key=key,
                url=record.get("url"),
                manufacturer=manufacturer,
                name=record["name"],
                sku=record.get("sku"),
                ean=record.get("ean"),
                priceGbp=float(record["priceGbp"]) if record.get("priceGbp") is not None else None,
                priceUsd=float(record["priceUsd"]) if record.get("priceUsd") is not None else None,
                priceEur=float(record["priceEur"]) if record.get("priceEur") is not None else None,
                imageUrl=record.get("imageUrl"),
                hints=hints,
                firstSeen=SEED_FIRST_SEEN,
                lastSeen=SEED_FIRST_SEEN,
                extractor=extractor,
            )
    return [observations[key] for key in sorted(observations)]
