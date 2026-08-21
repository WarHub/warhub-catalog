# tools/acquisition/tests/test_report.py
from pathlib import Path

import pytest

from warhub_acquisition.report import build_report
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import write_yaml


def test_zero_product_manufacturer_file_renders_zeros_not_divide_by_zero(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_yaml(paths.catalog_products / "empty-mfr.yaml", {"manufacturer": "empty-mfr", "products": []})
    report = build_report(paths)
    assert "| empty-mfr | 0 | 0 | 0 | 0.0% | 0.0% |" in report


def test_products_count_includes_archival_records_reported_beside_current(tmp_path: Path) -> None:
    # A superseded record still counts as a product (people own it); `current` is the subset
    # nothing replaced, and the EAN percentages stay over the total.
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.catalog_products / "games-workshop.yaml",
        {
            "manufacturer": "games-workshop",
            "products": [
                {"id": "games-workshop/1", "name": "Widget", "manufacturer": "games-workshop",
                 "ean": "5011921179398", "eanConfidence": "confirmed", "status": "current",
                 "firstSeen": "2026-07-01", "supersedes": ["games-workshop/2"]},
                {"id": "games-workshop/2", "name": "Widget", "manufacturer": "games-workshop",
                 "ean": "5011921062164", "eanConfidence": "confirmed", "status": "discontinued",
                 "firstSeen": "2026-07-01", "supersededBy": "games-workshop/1"},
            ],
        },
    )
    assert "| games-workshop | 2 | 1 | 2 | 100.0% | 100.0% |" in build_report(paths)


def test_malformed_catalog_file_raises_value_error_naming_the_file(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    bad = paths.catalog_products / "broken.yaml"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("manufacturer: broken\n", encoding="utf-8", newline="\n")  # missing 'products' key
    with pytest.raises(ValueError, match="broken.yaml"):
        build_report(paths)


def test_paint_coverage_counts_distinct_barcodes_under_the_guard(tmp_path: Path) -> None:
    # The count the EAN guard gates must be visible on every run: a guard that quietly reads zero
    # paint files would pass forever, which is the silent failure it exists to prevent. Both roles
    # count (paints have no eanConfidence), and a barcode held twice counts once.
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.root / "paints" / "brands" / "citadel-colour.yaml",
        {
            "brand": "Citadel Colour",
            "brandSlug": "citadel-colour",
            "paints": [
                {"name": "Abaddon Black", "ean": "5011921182848",
                 "additionalEans": ["5011921199457", "5011921244379"]},
                {"name": "Administratum Grey", "ean": "5011921183340"},
                {"name": "Duplicate Pot", "ean": "5011921183340"},
                {"name": "No Barcode Yet"},
            ],
        },
    )
    report = build_report(paths)
    assert "## Paint coverage" in report
    assert "| citadel-colour | 4 | 4 |" in report
    assert "| **total** | 4 | **4** |" in report


def test_paint_coverage_section_is_absent_without_a_paint_catalog(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_yaml(paths.catalog_products / "empty-mfr.yaml", {"manufacturer": "empty-mfr", "products": []})
    assert "## Paint coverage" not in build_report(paths)


def test_malformed_paint_brand_file_raises_value_error_naming_the_file(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    bad = paths.root / "paints" / "brands" / "broken.yaml"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("brandSlug: broken\npaints: [oops\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="broken.yaml"):
        build_report(paths)


def test_category_coverage_makes_the_one_guessed_field_visible(tmp_path: Path) -> None:
    # `category` is the only published field with a fallback behind it, so a regression there is
    # silent: every product still has a value, it is just the wrong one. Printing the split each
    # run is what would make `paint` collapsing to zero -- the paint-eans index no longer being
    # read -- show up in the nightly PR body instead of nowhere. Ordered by count so the shape of
    # the catalog reads off the top of the table.
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.catalog_products / "vallejo.yaml",
        {
            "manufacturer": "vallejo",
            "products": [
                {"id": "vallejo/1", "name": "Foul Green", "manufacturer": "vallejo",
                 "category": "paint", "status": "current", "firstSeen": "2026-07-01"},
                {"id": "vallejo/2", "name": "Bright Green", "manufacturer": "vallejo",
                 "category": "paint", "status": "current", "firstSeen": "2026-07-01"},
                {"id": "vallejo/3", "name": "Brush", "manufacturer": "vallejo",
                 "category": "miniatures", "status": "current", "firstSeen": "2026-07-01"},
                {"id": "vallejo/4", "name": "Unlabelled", "manufacturer": "vallejo",
                 "status": "current", "firstSeen": "2026-07-01"},
            ],
        },
    )
    report = build_report(paths)
    assert "## Product categories" in report
    body = report.split("## Product categories", 1)[1]
    assert body.index("| paint | 2 |") < body.index("| miniatures | 1 |")
    # An absent category is reported as absent rather than folded into the majority value: the
    # whole point of this table is that a missing classification stays legible.
    assert "| (none) | 1 |" in report


def test_category_coverage_section_is_absent_without_a_product_catalog(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.root / "paints" / "brands" / "citadel-colour.yaml",
        {"brand": "Citadel Colour", "brandSlug": "citadel-colour", "paints": []},
    )
    assert "## Product categories" not in build_report(paths)
