"""Swatch extraction: text-anchored sampling on a rendered chart page.

The whole module needs the `swatch` extra (pdfplumber + Pillow); without it every test here
skips -- the base suite must stay green with the PDF stack absent (see pyproject.toml).
The fixture is a hand-built 652-byte PDF: one flat chip (exact #CC3333) above code label
77.101, plus label 77.999 with NO chip (paper-guard case).
"""
from pathlib import Path

import pytest

pdfplumber = pytest.importorskip("pdfplumber")

from warhub_acquisition.swatch.pdf_chart import (  # noqa: E402
    ChartSpec,
    SampleSpec,
    Swatch,
    _channel_spread,
    _median_rgb,
    _rgb_hex,
    extract_chart,
    sample_page,
)

FIXTURE = Path(__file__).parent / "fixtures" / "swatch" / "chip-chart.pdf"

# Chip geometry in the fixture: rect at PDF (20,120)-(64,150) on a 200pt page -> top 50..80;
# labels sit at top=93.7. Offsets are label-relative.
SPEC = ChartSpec(
    chart_id="fixture",
    url="file://fixture",
    code_pattern=r"77\.\d{3}",
    pages=(0,),
    sample=SampleSpec(dx=0, dy=-43.7, width=44, height=30),
)


def open_page():
    pdf = pdfplumber.open(FIXTURE)
    return pdf, pdf.pages[0]


def test_median_rgb_and_hex_are_deterministic() -> None:
    pixels = [(10, 20, 30), (12, 22, 32), (200, 200, 200)]
    assert _median_rgb(pixels) == (12, 22, 32)
    assert _rgb_hex((204, 51, 51)) == "#CC3333"
    assert _channel_spread([(10, 10, 10), (10, 10, 10)]) == 0.0


def test_sample_page_extracts_chip_and_paper_guard_drops_chipless_label() -> None:
    pdf, page = open_page()
    try:
        swatches = sample_page(page, 0, SPEC)
    finally:
        pdf.close()

    # 77.101 has the chip; 77.999's configured region is bare paper -> guarded out.
    assert [s.code for s in swatches] == ["77.101"]
    swatch = swatches[0]
    assert swatch.hex == "#CC3333"
    assert swatch.rgb == (204, 51, 51)
    assert swatch.confidence == "high"  # flat chip -> uniform region
    assert swatch.page == 0


def test_off_page_region_is_skipped() -> None:
    off_page = ChartSpec(
        chart_id="fixture",
        url="file://fixture",
        code_pattern=r"77\.\d{3}",
        pages=(0,),
        sample=SampleSpec(dx=-500, dy=-43.7, width=44, height=30),
    )
    pdf, page = open_page()
    try:
        assert sample_page(page, 0, off_page) == []
    finally:
        pdf.close()


def test_extract_chart_returns_renders_for_contact_sheets() -> None:
    pdf = pdfplumber.open(FIXTURE)
    try:
        swatches, renders = extract_chart(pdf, SPEC)
    finally:
        pdf.close()
    assert [s.code for s in swatches] == ["77.101"]
    assert 0 in renders
    assert renders[0].size[0] > 100  # a real rendered page image
    assert isinstance(swatches[0], Swatch)
