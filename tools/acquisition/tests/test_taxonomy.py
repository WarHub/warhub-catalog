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


def test_warlord_pattern_rejects_ean13_and_letterless_junk(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "manufacturers.yaml",
        {"manufacturers": [{"slug": "warlord-games", "name": "Warlord Games",
                            "codePattern": '[0-9]{9,12}(-[0-9]{1,2})?|(?=[A-Z0-9-]*[A-Z])[A-Z0-9-]{6,}'}]},
    )
    taxonomy = Taxonomy.load(tmp_path)
    assert taxonomy.normalize_code("warlord-games", "5060393709671") is None      # EAN-13
    assert taxonomy.normalize_code("warlord-games", "402615006") == "402615006"    # 9-digit own-store sku
    assert taxonomy.normalize_code("warlord-games", "WGB-AI-02") == "WGB-AI-02"
    assert taxonomy.normalize_code("warlord-games", "------") is None              # letterless junk
    assert taxonomy.normalize_code("warlord-games", "219910001-01") == "219910001-01"  # variant dash-code


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


def test_ak_interactive_codes_its_letter_prefixed_families_but_not_the_range_pages() -> None:
    """The committed pattern, against the two things it has to get right at once.

    AK's article numbers carry a longer letter prefix than `AK` on whole families -- the Abteilung
    502 oils, the Artistic Dense acrylics, the gouaches, the signature packs -- and those rows
    cross into the product catalog, where a sku that will not normalize has no identity at all
    (AK publishes no barcode anywhere).

    THE FIVE `RANGE` SKUS ARE CODED TOO, and that reverses what this test asserted when it was
    written. They were treated as shop range pages rather than products; ak-interactive.com
    publishes `SKU: AK 3G RANGE AFV` on a 220 EUR, 8kg, 80-paint boxed set, so they are products
    with the maker's own article number. Spaces are stripped before matching, so the id is
    `ak-interactive/AK3GRANGEAFV` -- a maker's sku, not a shop's title, which is what the identity
    floor is actually protecting against.

    What must STILL fail is a pattern that loosens the TRAILING letters rather than extending the
    prefix: that one codes `AK 3G RANGE AFV` as `AK` + `3` + `GRANGEAFV`, i.e. by accident and with
    the wrong code. The two lower blocks pin the difference.
    """
    taxonomy = Taxonomy.load(Path(__file__).resolve().parents[3] / "data" / "catalog" / "taxonomy")
    for sku in ("AK11237", "AKABT301", "AKABT111", "AKAD102", "AKG25", "AKPACK74", "ABTP044",
                "ABTPF611", "ABT1001", "RC001"):
        assert taxonomy.normalize_code("ak-interactive", sku) == sku, sku
    # The maker's range skus code to themselves with the spaces removed -- never to a truncation.
    for sku, code in (("AK 3G RANGE AFV", "AK3GRANGEAFV"), ("AK 3G RANGE FIG", "AK3GRANGEFIG"),
                      ("AK 3G RANGE AIR", "AK3GRANGEAIR"),
                      ("AK 3G RANGE GENERIC", "AK3GRANGEGENERIC"),
                      ("RANGE AKAD", "RANGEAKAD")):
        assert taxonomy.normalize_code("ak-interactive", sku) == code, sku
    # A shop title must still be refused: the floor is about titles, not about spaces.
    for sku in ("3GEN AFV Series Full Range", "Full Range of AFV colours"):
        assert taxonomy.normalize_code("ak-interactive", sku) is None, sku


def test_army_painter_codes_its_tool_and_brush_prefixes() -> None:
    """TL/BR reach the PRODUCT catalog from legacy-catalog and from retailers, whatever the paint
    crossover selects, and there the pattern decides whether the record gets a product code or a
    slug of somebody's shop title. `codeStrip`/`-EN` handling still applies, and the range prefixes
    keep working.
    """
    taxonomy = Taxonomy.load(Path(__file__).resolve().parents[3] / "data" / "catalog" / "taxonomy")
    for sku in ("TL5034", "TL5057", "TL5063P", "BR7003", "BR7009", "BR7017",
                "WP8082", "BNDL212"):
        assert taxonomy.normalize_code("army-painter", sku) == sku, sku
    # A retailer's variant suffix is NOT an Army Painter article number.
    assert taxonomy.normalize_code("army-painter", "TL5034-SINGLE") is None
    # Still the one row left uncoded on purpose rather than widening further to chase it.
    assert taxonomy.normalize_code("army-painter", "75005") is None
