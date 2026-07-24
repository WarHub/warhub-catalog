"""Swatch extraction: grid-anchored sampling on a raster chart image.

Needs the `swatch` extra's Pillow (the module itself imports pure stdlib, but the fixture is
PIL-generated); without it every test here skips -- the base suite must stay green with the
imaging stack absent (see pyproject.toml). The fixture is a synthetic 4x2 grid drawn at a
non-zero origin: solid fill per cell with a dark "code bar" on top and a light "name bar" at
the bottom, so a sampler that strayed outside the configured sub-region would shift the
median away from the exact fill colour.
"""
import dataclasses

import pytest

pytest.importorskip("PIL")

from PIL import Image, ImageDraw  # noqa: E402

from warhub_acquisition.swatch.grid_image import (  # noqa: E402
    CellSample,
    GridSpec,
    extract_grid,
    iter_cells,
)
from warhub_acquisition.swatch.pdf_chart import Swatch  # noqa: E402

ORIGIN_X, ORIGIN_Y = 8, 6
CELL_W, CELL_H = 40, 30
COLS, ROWS = 4, 2
FILLS = [
    (200, 30, 30), (30, 200, 30), (30, 30, 200), (220, 220, 40),
    (40, 220, 220), (220, 40, 220), (120, 120, 120), (250, 128, 10),
]

SPEC = GridSpec(
    chart_id="fixture",
    url="file://fixture",
    origin_x=ORIGIN_X,
    origin_y=ORIGIN_Y,
    cell_w=CELL_W,
    cell_h=CELL_H,
    cols=COLS,
    rows=ROWS,
    code_prefix="TST",
    code_start=1,
    code_pad=3,
    sample=CellSample(x0=0.2, y0=0.30, x1=0.8, y1=0.70),
)


def build_grid(blank: frozenset[int] = frozenset()) -> Image.Image:
    """Draw the fixture chart; `blank` positions stay bare background (unprinted cell)."""
    im = Image.new("RGB", (ORIGIN_X + COLS * CELL_W + 8, ORIGIN_Y + ROWS * CELL_H + 6), "white")
    draw = ImageDraw.Draw(im)
    for pos, fill in enumerate(FILLS):
        if pos in blank:
            continue
        row, col = divmod(pos, COLS)
        x0, y0 = ORIGIN_X + col * CELL_W, ORIGIN_Y + row * CELL_H
        draw.rectangle((x0, y0, x0 + CELL_W - 1, y0 + CELL_H - 1), fill=fill)
        draw.rectangle((x0, y0, x0 + CELL_W - 1, y0 + 7), fill=(15, 15, 15))  # code bar
        draw.rectangle((x0, y0 + CELL_H - 8, x0 + CELL_W - 1, y0 + CELL_H - 1), fill=(245, 245, 245))  # name bar
    return im


def test_iter_cells_spells_out_the_code_sequence() -> None:
    cells = list(iter_cells(SPEC))
    assert len(cells) == COLS * ROWS
    assert cells[0] == (0, 0, 0, "TST001")
    assert cells[4] == (4, 1, 0, "TST005")  # reading order wraps to the next row
    assert cells[-1] == (7, 1, 3, "TST008")


def test_iter_cells_zero_pads_from_the_configured_start() -> None:
    ak = dataclasses.replace(SPEC, code_prefix="AK", code_start=11001, code_pad=5)
    assert [c[3] for c in iter_cells(ak)][:2] == ["AK11001", "AK11002"]


def test_iter_cells_max_count_stops_the_sequence() -> None:
    capped = dataclasses.replace(SPEC, max_count=3)
    assert [c[3] for c in iter_cells(capped)] == ["TST001", "TST002", "TST003"]


def test_iter_cells_skip_cells_hole_does_not_consume_a_code() -> None:
    holed = dataclasses.replace(SPEC, skip_cells=frozenset({1}))
    cells = list(iter_cells(holed))
    assert len(cells) == COLS * ROWS - 1
    # Position 1 is skipped; the SECOND code lands on position 2.
    assert cells[1] == (2, 0, 2, "TST002")


def test_extract_grid_samples_exact_fill_despite_code_and_name_bars() -> None:
    swatches = extract_grid(build_grid(), SPEC)
    assert [s.code for s in swatches] == [f"TST{i:03d}" for i in range(1, 9)]
    for swatch, fill in zip(swatches, FILLS):
        assert isinstance(swatch, Swatch)
        assert swatch.rgb == fill  # bars never reach the sub-region
        assert swatch.confidence == "high"  # solid fill -> uniform region
        assert swatch.page == 0


def test_extract_grid_crop_box_is_the_full_cell_including_bars() -> None:
    swatches = extract_grid(build_grid(), SPEC)
    row, col = divmod(5, COLS)
    x0, y0 = ORIGIN_X + col * CELL_W, ORIGIN_Y + row * CELL_H
    assert swatches[5].crop_box_px == (x0, y0, x0 + CELL_W, y0 + CELL_H)
    assert (swatches[5].label_x0, swatches[5].label_top) == (x0, y0)


def test_extract_grid_max_count_stops_before_trailing_cells() -> None:
    swatches = extract_grid(build_grid(), dataclasses.replace(SPEC, max_count=5))
    assert [s.code for s in swatches] == [f"TST{i:03d}" for i in range(1, 6)]


def test_extract_grid_blank_cell_is_guarded_out_but_still_consumes_its_code() -> None:
    swatches = extract_grid(build_grid(blank=frozenset({5})), SPEC)
    # Position 5's code exists in the sequence -- the cell is just not printed (the AK
    # briefcase's would-be 236th cell) -- so later codes must NOT shift down.
    assert [s.code for s in swatches] == [f"TST{i:03d}" for i in (1, 2, 3, 4, 5, 7, 8)]


def test_extract_grid_off_image_cells_are_skipped() -> None:
    # Three configured rows on a two-row image: the phantom row runs off the bottom.
    overshooting = dataclasses.replace(SPEC, rows=3)
    swatches = extract_grid(build_grid(), overshooting)
    assert [s.code for s in swatches] == [f"TST{i:03d}" for i in range(1, 9)]
