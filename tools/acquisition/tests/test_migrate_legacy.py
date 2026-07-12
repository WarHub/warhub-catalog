from pathlib import Path

from warhub_acquisition.migrate.legacy import read_legacy_products
from warhub_acquisition.yamlio import write_yaml


def make_faction_file(tmp_path: Path, faction_slug: str = "space-marines", products: list | None = None) -> Path:
    directory = tmp_path / "games-workshop" / "warhammer-40k"
    payload = {
        "manufacturer": "Games Workshop",
        "manufacturerSlug": "games-workshop",
        "gameSystem": "Warhammer 40,000",
        "gameSystemSlug": "warhammer-40k",
        "faction": "Space Marines",
        "factionSlug": faction_slug,
        "products": products
        if products is not None
        else [
            {
                "name": "Adrax Agatone",
                "category": "miniatures",
                "packaging": "single",
                "status": "current",
                "availability": "in_stock",
                "firstSeen": "2026-07-07",
                "ean": "5011921140862",
                "eanSource": "shopify:goblingaming.co.uk",
                "sku": "99120101293",
                "productCode": "prod4530362-99120101293",
                "priceGbp": 29,
                "url": "https://example/adrax",
                "imageUrl": "https://example/adrax.jpg",
                "description": "A hero.\nOf Nocturne.",
            }
        ],
    }
    write_yaml(directory / f"{faction_slug}.yaml", payload)
    return tmp_path


def test_maps_record_to_observation(tmp_path: Path) -> None:
    extraction = read_legacy_products(make_faction_file(tmp_path))
    [observation] = extraction.observations
    assert observation.key == "legacy-catalog:games-workshop/warhammer-40k/space-marines/adrax-agatone"
    assert observation.manufacturer == "games-workshop"
    assert observation.sku == "99120101293"
    assert observation.ean == "5011921140862"
    assert observation.priceGbp == 29.0
    assert observation.firstSeen == "2026-07-07"
    assert observation.lastSeen == "2026-07-07"
    assert observation.extractor == "legacy-catalog@1"
    assert observation.hints["gameSystem"] == "warhammer-40k"
    assert observation.hints["faction"] == "space-marines"
    assert observation.hints["status"] == "current"
    assert observation.hints["eanSource"] == "shopify:goblingaming.co.uk"
    assert observation.hints["legacyProductCode"] == "prod4530362-99120101293"
    assert observation.hints["description"] == "A hero.\nOf Nocturne."
    assert extraction.invalid_records == []


def test_label_maps_accumulate(tmp_path: Path) -> None:
    extraction = read_legacy_products(make_faction_file(tmp_path))
    assert extraction.game_system_labels == {"warhammer-40k": "Warhammer 40,000"}
    assert extraction.faction_labels == {"space-marines": "Space Marines"}
    assert extraction.label_to_game_system == {"Warhammer 40,000": "warhammer-40k"}
    assert extraction.label_to_faction == {"Space Marines": "space-marines"}


def test_key_collision_gets_deterministic_suffix(tmp_path: Path) -> None:
    base = {
        "category": "miniatures", "packaging": "single", "status": "current",
        "availability": "in_stock", "firstSeen": "2026-07-07", "sku": "1", "url": "https://x",
    }
    extraction = read_legacy_products(
        make_faction_file(
            tmp_path,
            products=[
                {**base, "name": "Foo!"},
                {**base, "name": "Foo?", "sku": "2"},
            ],
        )
    )
    keys = [o.key for o in extraction.observations]
    assert keys == [
        "legacy-catalog:games-workshop/warhammer-40k/space-marines/foo",
        "legacy-catalog:games-workshop/warhammer-40k/space-marines/foo-2",
    ]
    assert extraction.key_collisions == [
        {"type": "key-collision",
         "key": "legacy-catalog:games-workshop/warhammer-40k/space-marines/foo-2",
         "name": "Foo?"}
    ]


def test_invalid_record_is_reported_not_fatal(tmp_path: Path) -> None:
    extraction = read_legacy_products(
        make_faction_file(tmp_path, products=[{"category": "miniatures"}])  # no name
    )
    assert extraction.observations == []
    assert len(extraction.invalid_records) == 1


def test_colliding_invalid_record_leaves_no_phantom_collision(tmp_path: Path) -> None:
    base = {
        "category": "miniatures", "packaging": "single", "status": "current",
        "availability": "in_stock", "firstSeen": "2026-07-07", "sku": "1", "url": "https://x",
    }
    extraction = read_legacy_products(
        make_faction_file(
            tmp_path,
            products=[
                {**base, "name": "Foo!"},
                {"name": "Foo?"},  # collides AND is invalid (missing required fields)
            ],
        )
    )
    assert [o.key for o in extraction.observations] == [
        "legacy-catalog:games-workshop/warhammer-40k/space-marines/foo"
    ]
    assert extraction.key_collisions == []          # no phantom entry
    assert len(extraction.invalid_records) == 1


def test_non_numeric_price_is_invalid_not_fatal(tmp_path: Path) -> None:
    base = {
        "name": "Bar", "category": "miniatures", "packaging": "single", "status": "current",
        "availability": "in_stock", "firstSeen": "2026-07-07", "sku": "1", "url": "https://x",
        "priceGbp": "N/A",
    }
    extraction = read_legacy_products(make_faction_file(tmp_path, products=[base]))
    assert extraction.observations == []
    assert len(extraction.invalid_records) == 1


def test_conflicting_label_raises(tmp_path: Path) -> None:
    import pytest

    make_faction_file(tmp_path)
    directory = tmp_path / "games-workshop" / "warhammer-40k"
    write_yaml(
        directory / "other.yaml",
        {
            "manufacturer": "Games Workshop", "manufacturerSlug": "games-workshop",
            "gameSystem": "Warhammer 40k RENAMED", "gameSystemSlug": "warhammer-40k",
            "faction": "Other", "factionSlug": "other", "products": [],
        },
    )
    with pytest.raises(ValueError, match="warhammer-40k"):
        read_legacy_products(tmp_path)
