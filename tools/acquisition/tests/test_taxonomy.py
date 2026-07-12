from pathlib import Path

import pytest

from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import write_yaml


def make_taxonomy(tmp_path: Path) -> Taxonomy:
    write_yaml(
        tmp_path / "manufacturers.yaml",
        {
            "manufacturers": [
                {
                    "slug": "games-workshop",
                    "name": "Games Workshop",
                    "codePattern": r"\d{11}",
                    "codeStrip": ["GWS", "GW-"],
                    "gs1Prefixes": ["5011921"],
                    "vendorNames": ["Games Workshop", "Citadel"],
                },
                {"slug": "wyrd-games", "name": "Wyrd Games", "codePattern": r"WYR\d+", "vendorNames": ["Wyrd Miniatures"]},
            ]
        },
    )
    return Taxonomy.load(tmp_path)


def test_manufacturer_for_vendor_is_case_insensitive(tmp_path: Path) -> None:
    taxonomy = make_taxonomy(tmp_path)
    assert taxonomy.manufacturer_for_vendor("games workshop") == "games-workshop"
    assert taxonomy.manufacturer_for_vendor("Unknown Vendor") is None


def test_normalize_code_strips_and_matches(tmp_path: Path) -> None:
    taxonomy = make_taxonomy(tmp_path)
    assert taxonomy.normalize_code("games-workshop", "GWS99120110077") == "99120110077"
    assert taxonomy.normalize_code("games-workshop", "99120110077-EN") == "99120110077"
    assert taxonomy.normalize_code("games-workshop", "49-04") is None  # short code: not identity-grade
    assert taxonomy.normalize_code("wyrd-games", "wyr21331") == "WYR21331"
    assert taxonomy.normalize_code("games-workshop", None) is None


def test_duplicate_vendor_name_raises(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "manufacturers.yaml",
        {
            "manufacturers": [
                {"slug": "a-corp", "name": "A Corp", "vendorNames": ["Shared Vendor"]},
                {"slug": "b-corp", "name": "B Corp", "vendorNames": ["shared vendor"]},
            ]
        },
    )
    with pytest.raises(ValueError, match="Shared Vendor|shared vendor"):
        Taxonomy.load(tmp_path)
