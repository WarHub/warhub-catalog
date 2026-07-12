from pathlib import Path

from warhub_acquisition.models.descriptor import KIND_PRIORITY, SourceDescriptor, load_descriptors
from warhub_acquisition.yamlio import write_yaml


def test_load_descriptors(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "ret-goblin.yaml",
        {
            "id": "ret-goblin",
            "kind": "retailer",
            "strategy": "shopify",
            "baseUrl": "https://www.goblingaming.co.uk",
            "contract": {"minCount": 8000, "requiredFieldRates": {"name": 1.0, "ean": 0.6}},
        },
    )
    descriptors = load_descriptors(tmp_path)
    assert descriptors["ret-goblin"].kind == "retailer"
    assert descriptors["ret-goblin"].contract.minCount == 8000


def test_kind_priority_ordering() -> None:
    assert KIND_PRIORITY["curated"] < KIND_PRIORITY["manufacturer"] < KIND_PRIORITY["retailer"]
    assert KIND_PRIORITY["retailer"] < KIND_PRIORITY["archive"] < KIND_PRIORITY["barcode-db"]


def test_filename_must_match_id(tmp_path: Path) -> None:
    write_yaml(tmp_path / "wrong-name.yaml", {"id": "ret-goblin", "kind": "retailer", "strategy": "shopify"})
    import pytest

    with pytest.raises(ValueError, match="wrong-name"):
        load_descriptors(tmp_path)
