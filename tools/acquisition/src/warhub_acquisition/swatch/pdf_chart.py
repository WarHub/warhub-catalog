"""Text-anchored swatch sampling from manufacturer PDF colour charts.

Manufacturers publish their colours as chart/brochure PDFs (Vallejo's CC-series, AK's charts,
...). The chart's swatch VISUALS vary wildly -- flat vector chips, brushed-metallic photo
strips, texture photos on product cards -- but the CODE LABELS are always vector text with
exact positions. So the one mechanism that works everywhere:

    render the page to pixels -> find each code label (regex over positioned words) ->
    sample a per-chart configured region at a fixed offset from the label -> robust colour.

Per-chart config supplies the code regex, the pages that carry the real chart (codes often
reappear in combination tables), and the sampling rectangle relative to each label's
(x0, top). Guards reject samples that run off the page or read the paper background.
Every accepted sample records the method and a paper-relative confidence; a contact sheet
(code + sampled crop + extracted colour side by side) is emitted per chart for human review.

Colour note: pages are rendered by pdfium with its default colour handling -- print-intent
CMYK lands in approximate sRGB. That is the accepted trade-off of this whole feature (the
alternative is no colour at all); the output records provenance so a later ICC-accurate pass
could re-derive from the same materials.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

RENDER_DPI = 150
_SCALE = RENDER_DPI / 72.0


@dataclass(frozen=True)
class SampleSpec:
    """Sampling rectangle in PDF points, relative to a code label's (x0, top)."""

    dx: float
    dy: float  # negative = above the label
    width: float
    height: float
    # Fraction of the rectangle's border to discard before measuring (chip borders,
    # anti-aliased edges, neighbouring text bleed).
    inset: float = 0.2


@dataclass(frozen=True)
class ChartSpec:
    chart_id: str
    url: str
    code_pattern: str
    pages: tuple[int, ...]
    sample: SampleSpec
    set_name: str | None = None  # optional: restrict catalog matching to this set


@dataclass
class Swatch:
    code: str
    page: int
    hex: str
    rgb: tuple[int, int, int]
    confidence: str  # "high" (uniform region) | "medium" (textured/gradient region)
    label_x0: float
    label_top: float
    crop_box_px: tuple[int, int, int, int] = field(default=(0, 0, 0, 0))


def _median_rgb(pixels: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    """Per-channel median: robust to specular highlights and dark chip borders in a way a
    mean is not, and deterministic (no clustering seed)."""
    return (
        round(statistics.median(p[0] for p in pixels)),
        round(statistics.median(p[1] for p in pixels)),
        round(statistics.median(p[2] for p in pixels)),
    )


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _channel_spread(pixels: list[tuple[int, int, int]]) -> float:
    """Mean per-channel stdev -- uniformity measure for the confidence tag."""
    if len(pixels) < 2:
        return 0.0
    return sum(statistics.pstdev(p[i] for p in pixels) for i in range(3)) / 3.0


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return (sum((x - y) ** 2 for x, y in zip(a, b))) ** 0.5


def paper_color(image) -> tuple[int, int, int]:
    """Estimate the page background from the four corner regions of a rendered page."""
    w, h = image.size
    m = max(4, min(w, h) // 50)
    pixels: list[tuple[int, int, int]] = []
    for box in ((0, 0, m, m), (w - m, 0, w, m), (0, h - m, m, h), (w - m, h - m, w, h)):
        corner = image.crop(box).convert("RGB")
        pixels.extend(corner.getdata())
    return _median_rgb(pixels)


def find_code_words(page, code_pattern: str) -> list[dict]:
    pattern = re.compile(code_pattern)
    return [w for w in page.extract_words() if pattern.fullmatch(w["text"])]


def sample_page(page, page_index: int, spec: ChartSpec, image=None) -> list[Swatch]:
    """Sample every code label on one pdfplumber page. `image` allows reusing a render."""
    if image is None:
        image = page.to_image(resolution=RENDER_DPI).original
    image = image.convert("RGB")
    paper = paper_color(image)
    width_px, height_px = image.size

    swatches: list[Swatch] = []
    seen_codes: set[str] = set()
    for word in find_code_words(page, spec.code_pattern):
        code = word["text"]
        if code in seen_codes:
            continue  # first occurrence in reading order wins within a page

        s = spec.sample
        x0 = (word["x0"] + s.dx) * _SCALE
        y0 = (word["top"] + s.dy) * _SCALE
        x1 = x0 + s.width * _SCALE
        y1 = y0 + s.height * _SCALE
        # Inset before clipping so a border-hugging region still measures its interior.
        ix = (x1 - x0) * s.inset
        iy = (y1 - y0) * s.inset
        box = (round(x0 + ix), round(y0 + iy), round(x1 - ix), round(y1 - iy))
        if box[0] < 0 or box[1] < 0 or box[2] > width_px or box[3] > height_px:
            continue  # runs off the page: label without a chip here (e.g. an index column)
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            continue

        pixels = list(image.crop(box).getdata())
        rgb = _median_rgb(pixels)
        # Paper guard: a sample indistinguishable from the page background is a label with
        # no chip at the configured offset (chartless mention), not a white paint.
        if _distance(rgb, paper) < 12.0:
            continue

        spread = _channel_spread(pixels)
        swatches.append(
            Swatch(
                code=code,
                page=page_index,
                hex=_rgb_hex(rgb),
                rgb=rgb,
                confidence="high" if spread < 18.0 else "medium",
                label_x0=word["x0"],
                label_top=word["top"],
                crop_box_px=box,
            )
        )
        seen_codes.add(code)
    return swatches


def extract_chart(pdf, spec: ChartSpec) -> tuple[list[Swatch], dict[int, object]]:
    """Run sampling over the chart's configured pages. Returns swatches plus the rendered
    page images (for contact-sheet generation) keyed by page index. First page listed wins
    when a code appears on several configured pages."""
    all_swatches: dict[str, Swatch] = {}
    renders: dict[int, object] = {}
    for page_index in spec.pages:
        page = pdf.pages[page_index]
        image = page.to_image(resolution=RENDER_DPI).original.convert("RGB")
        renders[page_index] = image
        for swatch in sample_page(page, page_index, spec, image=image):
            all_swatches.setdefault(swatch.code, swatch)
    return list(all_swatches.values()), renders
