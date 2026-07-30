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
