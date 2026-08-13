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
    _consensus,
    _median_rgb,
    _rgb_hex,
    extract_chart,
    find_name_labels,
    label_cells,
    normalize_label,
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


# --- name anchoring (Steamforged's P3 Mixing Guide is the first chart that needs it) ------------


class FakePage:
    """The only thing `label_cells` asks of a page. Real pages come from pdfplumber; this keeps
    the grouping rules testable at exact coordinates, which a hand-built PDF cannot express as
    legibly."""

    def __init__(self, words):
        self._words = words

    def extract_words(self):
        return [{"text": t, "x0": x0, "x1": x1, "top": top} for t, x0, x1, top in self._words]


def test_label_cells_joins_a_multi_word_name_and_splits_at_the_column_gutter() -> None:
    """The reason a code regex cannot read this chart: no single word is the label."""
    page = FakePage([
        ("Broken", 35.5, 61.0, 34.3), ("Brick", 63.0, 78.6, 34.3),      # BASE column
        ("Ruddy", 132.2, 155.5, 34.3), ("Blush", 157.8, 178.0, 34.3),   # SHADE column
        ("Illuminated", 228.9, 272.0, 52.0), ("Gold", 274.2, 291.0, 52.0),
    ])
    assert [(c["text"], c["x0"]) for c in label_cells(page)] == [
        ("Broken Brick", 35.5),
        ("Ruddy Blush", 132.2),
        ("Illuminated Gold", 228.9),
    ]


def test_the_cell_gap_is_load_bearing_not_decorative() -> None:
    """Same words, a gap wide enough to swallow the gutter -> one nonsense label. Pinned so the
    default is understood as calibration (P3's gutters are ~19pt, its word spaces ~3pt) rather
    than an arbitrary constant."""
    page = FakePage([
        ("Broken", 35.5, 61.0, 34.3), ("Brick", 63.0, 78.6, 34.3),
        ("Ruddy", 132.2, 155.5, 34.3), ("Blush", 157.8, 178.0, 34.3),
    ])
    assert [c["text"] for c in label_cells(page, cell_gap=100.0)] == [
        "Broken Brick Ruddy Blush"
    ]


def test_find_name_labels_translates_to_codes_through_the_caller_s_map() -> None:
    page = FakePage([("Broken", 35.5, 61.0, 34.3), ("Brick", 63.0, 78.6, 34.3),
                     ("Not", 132.2, 145.0, 34.3), ("Mine", 147.0, 165.0, 34.3)])
    labels = find_name_labels(page, {normalize_label("Broken Brick"): "SFP3-N135-S"})
    # The unknown cell is simply absent -- a chart naming a paint this catalog does not have is
    # not an error here; the caller reports it from the other end (a code that got no swatch).
    assert [(x["text"], x["x0"]) for x in labels] == [("SFP3-N135-S", 35.5)]


def test_consensus_takes_the_median_reading_not_the_first() -> None:
    """The Ryn Flesh shape: five cells agree, one dissents, and reading order favours nobody.

    The returned swatch must keep a REAL occurrence's page and crop box (the contact sheet crops
    by them), so it is the nearest reading rather than a synthetic one.
    """
    def reading(rgb, page, top):
        return Swatch(code="X", page=page, hex=_rgb_hex(rgb), rgb=rgb, confidence="high",
                      label_x0=0.0, label_top=top, crop_box_px=(page, top, page + 4, top + 4))

    dissenter = reading((154, 153, 143), 3, 282)
    agreed = [reading((220, 185, 161), p, t) for p, t in ((0, 391), (2, 140), (2, 247), (3, 87))]
    out = _consensus([dissenter, *agreed])
    assert out.rgb == (220, 185, 161)
    assert (out.page, out.crop_box_px) in {(s.page, s.crop_box_px) for s in agreed}


def test_name_anchored_extraction_runs_end_to_end_on_the_fixture() -> None:
    """The fixture's two labels sit on ONE line 75.5pt apart, so they exercise the gutter split
    on real pdfplumber output. `77.101` normalizes to `77101`, which is all a name needs to be."""
    spec = ChartSpec(
        chart_id="fixture",
        url="file://fixture",
        code_pattern="",  # unused: anchor_names branches before it is read
        anchor_names=True,
        pages=(0,),
        sample=SampleSpec(dx=0, dy=-43.7, width=44, height=30),
    )
    names = {normalize_label("77.101"): "CHIP-1", normalize_label("77.999"): "CHIP-2"}
    pdf = pdfplumber.open(FIXTURE)
    try:
        swatches, _ = extract_chart(pdf, spec, names=names)
    finally:
        pdf.close()
    # CHIP-2's region is bare paper -- the paper guard drops it exactly as in the code-anchored
    # run, so name anchoring changes WHICH labels are found and nothing about the sampling.
    assert [(s.code, s.hex) for s in swatches] == [("CHIP-1", "#CC3333")]
