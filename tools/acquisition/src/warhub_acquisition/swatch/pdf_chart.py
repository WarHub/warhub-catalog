"""Text-anchored swatch sampling from manufacturer PDF colour charts.

Manufacturers publish their colours as chart/brochure PDFs (Vallejo's CC-series, AK's charts,
...). The chart's swatch VISUALS vary wildly -- flat vector chips, brushed-metallic photo
strips, texture photos on product cards -- but the LABELS are always vector text with
exact positions. So the one mechanism that works everywhere:

    render the page to pixels -> find each label (regex over positioned words, or a name
    lookup) -> sample a per-chart configured region at a fixed offset from the label ->
    robust colour.

Per-chart config supplies the anchor, the pages that carry the real chart (codes often
reappear in combination tables), and the sampling rectangle relative to each label's
(x0, top). Guards reject samples that run off the page or read the paper background.
Every accepted sample records the method and a paper-relative confidence; a contact sheet
(code + sampled crop + extracted colour side by side) is emitted per chart for human review.

TWO ANCHORS, because not every chart prints a code. `code_pattern` is the original: a regex
fullmatched against single words. `anchor_names` is for charts labelled with PAINT NAMES --
Steamforged's P3 Mixing Guide is the first, and a name is not one word ("Broken Brick",
"Illuminated Gold"), so a regex over `extract_words()` cannot see it at all. `find_name_labels`
reassembles words into label CELLS first and looks each up in a caller-supplied name -> code
map, so everything downstream (offsets, guards, confidence, `Swatch.code`, the contact sheet,
the catalog join in gen_paint_swatches.py) is unchanged and still keyed by product code. The
map is the catalog's own, which is what keeps the join here identical to the one the C#
applier does rather than a second, name-shaped guess.

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
    # Anchor on paint NAMES instead of `code_pattern`. The caller then has to pass the
    # name -> code map to `extract_chart`; `code_pattern` is ignored (and normally "").
    anchor_names: bool = False
    # Words further apart than this on one line start a new label cell. 12pt separates the
    # P3 guide's four columns (their gutters are ~19pt) from the ~3pt inter-word gaps inside
    # a name; a chart with tighter columns needs its own value rather than a global one.
    cell_gap: float = 12.0


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


def normalize_label(s: str) -> str:
    """Lowercase alphanumerics only -- the repo's name-join normalizer (paints/catalog.py's
    `norm`, restated rather than imported because this package is importable standalone and
    must not depend on the acquisition package's paint modules).

    PUBLIC because the caller has to build the name -> code map with the SAME normalizer this
    module looks it up with; a private copy on either side is a join that silently misses.
    """
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def label_cells(page, cell_gap: float = 12.0) -> list[dict]:
    """The page's text as label CELLS: `{text, x0, top}`, one per column entry per line.

    `extract_words` is per-word, and a name label is not a word. Words are grouped into lines
    by `top` (4pt tolerance -- one line of a 7pt face), then split within a line wherever the
    horizontal gap exceeds `cell_gap`, which is what separates a column gutter from the space
    between "Broken" and "Brick". Multi-LINE labels are deliberately not joined: on the P3
    guide every name fits one line, and joining across lines would merge a name with the next
    row's whenever a cell happens to be empty.
    """
    lines: dict[float, list[dict]] = {}
    for word in page.extract_words():
        key = next((t for t in lines if abs(t - word["top"]) < 4), word["top"])
        lines.setdefault(key, []).append(word)

    cells: list[dict] = []
    for top in sorted(lines):
        group: list[dict] = []
        for word in sorted(lines[top], key=lambda w: w["x0"]):
            if group and word["x0"] - group[-1]["x1"] > cell_gap:
                cells.append({"text": " ".join(g["text"] for g in group),
                              "x0": group[0]["x0"], "top": group[0]["top"]})
                group = []
            group.append(word)
        if group:
            cells.append({"text": " ".join(g["text"] for g in group),
                          "x0": group[0]["x0"], "top": group[0]["top"]})
    return cells


def find_name_labels(page, names: dict[str, str], cell_gap: float = 12.0) -> list[dict]:
    """Label cells whose text is one of `names` (normalized name -> code), as code words.

    Returns the same `{text, x0, top}` shape `find_code_words` does, with `text` already
    translated to the CODE -- so `sample_page` never learns there are two kinds of anchor.
    A chart name with no catalog paint is simply not returned; the caller reports the gap
    from the other end (a catalog code that got no swatch).
    """
    out = []
    for cell in label_cells(page, cell_gap):
        code = names.get(normalize_label(cell["text"]))
        if code is not None:
            out.append({"text": code, "x0": cell["x0"], "top": cell["top"]})
    return out


def sample_page(page, page_index: int, spec: ChartSpec, image=None,
                names: dict[str, str] | None = None) -> list[Swatch]:
    """Sample every label on one pdfplumber page. `image` allows reusing a render."""
    if image is None:
        image = page.to_image(resolution=RENDER_DPI).original
    image = image.convert("RGB")
    paper = paper_color(image)
    width_px, height_px = image.size

    if spec.anchor_names:
        labels = find_name_labels(page, names or {}, spec.cell_gap)
    else:
        labels = find_code_words(page, spec.code_pattern)

    swatches: list[Swatch] = []
    seen_codes: set[str] = set()
    for word in labels:
        code = word["text"]
        # A code chart prints each code once and repeats it in combination tables, so the
        # first occurrence is the chart's own. A NAME chart is the other shape: the P3 guide
        # names each paint in every recipe it takes part in (up to 18 cells, all four
        # columns), and those repeats are the evidence -- `extract_chart` reduces them by
        # median. Deduping here would throw the corroboration away and keep whichever cell
        # happened to come first.
        if code in seen_codes and not spec.anchor_names:
            continue

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


def _consensus(samples: list[Swatch]) -> Swatch:
    """One swatch from a code's repeated cells: the per-channel MEDIAN, reported through the
    occurrence closest to it.

    Median rather than first-seen because the repeats are independent readings of the same
    chip and a chart can misprint one. Measured on the P3 Mixing Guide (109 colours, 84 of
    them in 2+ cells): the worst cell sits a median of 0.0 from the consensus, i.e. the
    repeats are normally byte-identical, and exactly two colours disagree at all --
    `Ryn Flesh` (one cell of six reads #9A998F against five at #DCB9A1) and `Greatcoat Grey`
    (one of three reads a navy against two at #0B1717). The consensus takes the majority in
    both, and both were confirmed independently against the product-photo panel (d=17 and
    d=7). First-wins would have been right there by luck of reading order; this is right by
    rule.

    The returned swatch keeps a REAL occurrence's page and crop box -- the nearest one -- so
    the contact sheet still shows a crop that actually produced the reported colour, and
    `confidence` is that occurrence's own. Only `rgb`/`hex` are the aggregate.
    """
    rgb = (
        round(statistics.median(s.rgb[0] for s in samples)),
        round(statistics.median(s.rgb[1] for s in samples)),
        round(statistics.median(s.rgb[2] for s in samples)),
    )
    nearest = min(samples, key=lambda s: (_distance(s.rgb, rgb), s.page, s.label_top))
    return Swatch(
        code=nearest.code,
        page=nearest.page,
        hex=_rgb_hex(rgb),
        rgb=rgb,
        confidence=nearest.confidence,
        label_x0=nearest.label_x0,
        label_top=nearest.label_top,
        crop_box_px=nearest.crop_box_px,
    )


def extract_chart(pdf, spec: ChartSpec,
                  names: dict[str, str] | None = None) -> tuple[list[Swatch], dict[int, object]]:
    """Run sampling over the chart's configured pages. Returns swatches plus the rendered
    page images (for contact-sheet generation) keyed by page index. First page listed wins
    when a code appears on several configured pages -- except for a name-anchored chart,
    where every occurrence is a reading and `_consensus` reduces them.

    `names` (normalized paint name -> product code) is required by, and only used by,
    `anchor_names` charts."""
    all_swatches: dict[str, Swatch] = {}
    repeats: dict[str, list[Swatch]] = {}
    renders: dict[int, object] = {}
    for page_index in spec.pages:
        page = pdf.pages[page_index]
        image = page.to_image(resolution=RENDER_DPI).original.convert("RGB")
        renders[page_index] = image
        for swatch in sample_page(page, page_index, spec, image=image, names=names):
            if spec.anchor_names:
                repeats.setdefault(swatch.code, []).append(swatch)
            else:
                all_swatches.setdefault(swatch.code, swatch)
    for code, samples in repeats.items():
        all_swatches[code] = _consensus(samples)
    return list(all_swatches.values()), renders
