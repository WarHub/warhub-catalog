from pathlib import Path

import pytest

from warhub_acquisition.migrate.seed import SEED_FIRST_SEEN, read_seed_products
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy
from warhub_acquisition.yamlio import write_yaml

TAXONOMY = Taxonomy(
    {"games-workshop": Manufacturer(slug="games-workshop", name="Games Workshop", vendorNames=["Citadel"])}
)
GS = {"Warhammer 40,000": "warhammer-40k"}
FACTIONS = {"Space Marines": "space-marines"}


def make_seed(tmp_path: Path, records: list) -> Path:
    write_yaml(tmp_path / "gw.yaml", records)
    return tmp_path


def seed_record(**kw: object) -> dict:
    base: dict[str, object] = {
        "name": "Intercessors", "sku": "99120101190", "ean": "5011921142439",
        "productType": "single_kit", "priceGbp": 36, "priceUsd": 46,
        "url": "https://example/intercessors",
        "manufacturer": "Games Workshop", "gameSystem": "Warhammer 40,000",
        "faction": "Space Marines", "status": "current",
        "contents": [{"unitName": "Intercessors", "quantity": 10, "baseSize": "32mm"}],
    }
    base.update(kw)
    return base


def test_maps_seed_record(tmp_path: Path) -> None:
    [observation] = read_seed_products(make_seed(tmp_path, [seed_record()]), TAXONOMY, GS, FACTIONS)
    assert observation.key == "seed-curated:games-workshop/intercessors"
    assert observation.manufacturer == "games-workshop"
    assert observation.ean == "5011921142439"
    assert observation.priceUsd == 46.0
    assert observation.firstSeen == SEED_FIRST_SEEN
    assert observation.hints["gameSystem"] == "warhammer-40k"
    assert observation.hints["faction"] == "space-marines"
    assert observation.hints["quantity"] == 10
    assert observation.hints["productType"] == "single_kit"
    assert observation.hints["contents"] == [{"unitName": "Intercessors", "quantity": 10, "baseSize": "32mm"}]


def test_null_faction_omits_hint(tmp_path: Path) -> None:
    [observation] = read_seed_products(
        make_seed(tmp_path, [seed_record(name="Ultimate Starter Set", faction=None, contents=None)]),
        TAXONOMY, GS, FACTIONS,
    )
    assert "faction" not in observation.hints
    assert "quantity" not in observation.hints


def test_unmapped_game_system_label_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Age of Sigmar"):
        read_seed_products(make_seed(tmp_path, [seed_record(gameSystem="Age of Sigmar")]), TAXONOMY, GS, FACTIONS)


def test_duplicate_seed_key_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="intercessors"):
        read_seed_products(make_seed(tmp_path, [seed_record(), seed_record()]), TAXONOMY, GS, FACTIONS)
