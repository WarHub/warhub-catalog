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


def test_category_basis_leads_with_the_share_that_rests_on_nothing(tmp_path: Path) -> None:
    """The section exists for ONE number: how much of `category` is not evidence. `category` is the
    only published product field with a fallback behind it, so a regression there is silent --
    every product keeps a value, it is just not about that product. Measured on
    catalog/acquisition (fc3ff62): 28,793 of 30,747 (93.6%) are `default` or `guessed`.

    `default` and `guessed` are counted together against `stated` (both mean undecided) and printed
    apart from each other (they are undecided for different reasons)."""
    paths = DataPaths(tmp_path)
    def product(pid: str, category: str, basis: str) -> dict:
        return {"id": pid, "name": pid, "manufacturer": "vallejo", "category": category,
                "categoryBasis": basis, "status": "current", "firstSeen": "2026-07-01"}
    write_yaml(
        paths.catalog_products / "vallejo.yaml",
        {"manufacturer": "vallejo", "products": [
            product("vallejo/1", "paint", "stated"),
            product("vallejo/2", "miniatures", "default"),
            product("vallejo/3", "miniatures", "guessed"),
            product("vallejo/4", "miniatures", "guessed"),
        ]},
    )
    report = build_report(paths)
    assert "## Product categories" in report
    assert "**3 of 4 (75.0%) rest on no evidence**" in report
    assert "| miniatures | guessed | 2 |" in report
    assert "| paint | stated | 1 |" in report


def test_category_section_is_absent_without_a_product_catalog(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.root / "paints" / "brands" / "citadel-colour.yaml",
        {"brand": "Citadel Colour", "brandSlug": "citadel-colour", "paints": []},
    )
    assert "## Product categories" not in build_report(paths)
