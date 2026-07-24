"""Grid-anchored swatch sampling from raster colour-chart images.

Some manufacturers publish their master chart as a plain JPG/PNG: a regular grid of colour
cells with the product code printed on each cell (AK's 235-colour briefcase chart). There is
no text layer to anchor on -- but there is something just as exact: the grid itself. Codes
run sequentially left-to-right, top-to-bottom, so a cell's POSITION determines its code:

    per-chart configured geometry (origin, cell pitch, cols/rows) -> enumerate cells ->
    assign codes from the sequence spec -> sample a sub-region of each cell -> robust colour.

The sub-region (relative fractions of the cell) dodges the printed code/name text; the
median makes any residual text bleed irrelevant. A blank-cell guard drops grid positions
that carry no print at all (whitespace past the last cell -- an overshooting maxCount),
but logo art or other non-cell CONTENT is not detectable by colour: `max_count`/`skip_cells`
are the mechanism for stopping before those, calibrated against the contact sheet.

The contact-sheet crop is the FULL cell -- printed code text included -- while the colour
comes from the sub-region only. The sheet is therefore self-verifying: a human reads the
printed code right next to the code the extractor assigned to that cell.

Colour note: chart JPGs are print-intent exports with JPEG quantisation on top; sampled
colours approximate sRGB the same way pdf_chart's pdfium renders do. Provenance is recorded
so a later colour-managed pass could re-derive from the same materials.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from warhub_acquisition.swatch.pdf_chart import (
    Swatch,
    _channel_spread,
    _median_rgb,
    _rgb_hex,
)


@dataclass(frozen=True)
class CellSample:
    """Sampling sub-region as fractions of the cell rectangle (0..1 in each axis).

    Chosen to sit strictly between the printed code text (top of the cell) and name text
    (bottom): on the AK briefcase layout the code occupies ~y 0.10-0.25 and the name
    ~y 0.63-0.75, so y 0.30-0.58 samples pure fill.
    """

    x0: float = 0.10
    y0: float = 0.30
    x1: float = 0.90
    y1: float = 0.58


@dataclass(frozen=True)
class GridSpec:
    """One raster chart: grid geometry plus the code sequence the cells spell out.

    Cell (row, col) covers pixels (origin_x + col*cell_w, origin_y + row*cell_h) to
    (+cell_w, +cell_h); pitches are floats because charts are seldom pixel-exact
    (AK: 810 px / 12 rows = 67.5). Codes are `prefix` + zero-padded counter starting at
    `code_start` and advance only over cells that EXIST on the print: `skip_cells` names
    grid positions (row*cols + col) that hold no swatch without consuming a code, and
    `max_count` stops after that many codes -- the guard against logo-covered or absent
    trailing cells, which look like anything BUT a swatch and cannot be auto-detected.
    """

    chart_id: str
    url: str
    origin_x: float
    origin_y: float
    cell_w: float
    cell_h: float
    cols: int
    rows: int
    code_prefix: str
    code_start: int
    code_pad: int = 0
    max_count: int | None = None
    skip_cells: frozenset[int] = frozenset()
    sample: CellSample = CellSample()
    set_name: str | None = None  # optional: restrict catalog matching to this set


def iter_cells(spec: GridSpec) -> Iterator[tuple[int, int, int, str]]:
    """Yield (grid_position, row, col, code) for every code-bearing cell, reading order."""
    emitted = 0
    for position in range(spec.cols * spec.rows):
        if spec.max_count is not None and emitted >= spec.max_count:
            return
        if position in spec.skip_cells:
            continue
        row, col = divmod(position, spec.cols)
        code = f"{spec.code_prefix}{spec.code_start + emitted:0{spec.code_pad}d}"
        yield position, row, col, code
        emitted += 1


def extract_grid(image, spec: GridSpec) -> list[Swatch]:
    """Sample every configured cell of a PIL chart image.

    Returned swatches carry page=0 (a raster chart is a single "page"; the bridge keys its
    render dict accordingly), the cell's top-left pixel as label_x0/label_top, and the FULL
    cell rectangle as crop_box_px -- the contact-sheet contract described in the module
    docstring. Colour and confidence come from the sub-region alone.
    """
    image = image.convert("RGB")
    width_px, height_px = image.size

    swatches: list[Swatch] = []
    for _position, row, col, code in iter_cells(spec):
        x0 = spec.origin_x + col * spec.cell_w
        y0 = spec.origin_y + row * spec.cell_h
        cell_box = (round(x0), round(y0), round(x0 + spec.cell_w), round(y0 + spec.cell_h))
        if cell_box[0] < 0 or cell_box[1] < 0 or cell_box[2] > width_px or cell_box[3] > height_px:
            continue  # geometry overshoots the image: mis-set rows/cols, nothing to sample

        s = spec.sample
        sample_box = (
            round(x0 + s.x0 * spec.cell_w),
            round(y0 + s.y0 * spec.cell_h),
            round(x0 + s.x1 * spec.cell_w),
            round(y0 + s.y1 * spec.cell_h),
        )
        if sample_box[2] - sample_box[0] < 4 or sample_box[3] - sample_box[1] < 4:
            continue

        # Blank-cell guard: every REAL cell carries printed code/name text, so the full
        # cell always has contrast. A near-uniform cell is unprinted whitespace (grid
        # overshoot past the chart's last cell), not a colour -- e.g. reading the AK
        # briefcase as its marketed "236 colours" when only 235 are printed.
        cell_pixels = list(image.crop(cell_box).getdata())
        if _channel_spread(cell_pixels) < 4.0:
            continue

        pixels = list(image.crop(sample_box).getdata())
        rgb = _median_rgb(pixels)
        spread = _channel_spread(pixels)
        swatches.append(
            Swatch(
                code=code,
                page=0,
                hex=_rgb_hex(rgb),
                rgb=rgb,
                confidence="high" if spread < 18.0 else "medium",  # same bar as pdf_chart
                label_x0=x0,
                label_top=y0,
                crop_box_px=cell_box,
            )
        )
    return swatches
