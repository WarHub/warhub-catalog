"""Per-item image swatch sampling: one image per paint code.

Third extractor kind, for colour sources that are not charts but per-code images:

- URL-templated tiles: reapermini.com publishes its colour database as flat gd-rendered
  100x100 JPEGs at `images.reapermini.com/6/<sku>.jpg` -- the whole tile IS the colour.
- Harvested product images: every store harvest records an official `imageUrl` per paint;
  where those images carry a reliably-positioned flat colour area (label chip, bottle body),
  a configured relative region samples it.

The module is pure (image in, sample out) -- fetching, caching, 404 tolerance and pacing stay
with the bridge, exactly like the pdf/grid extractors receive pre-fetched bytes. Sampling and
confidence share pdf_chart's helpers; the background guard rejects regions indistinguishable
from a white/photo-studio backdrop, because a mispositioned region on a product shot reads as
near-white -- a false "white paint" is the failure mode this guard exists for.

Calibration is empirical, like the grid extractor: run the same region over paints whose hex
is already known and check the distance distribution before trusting fills (the bridge's
cross-check output).
"""
from __future__ import annotations

from dataclasses import dataclass

from warhub_acquisition.swatch.grid_image import CellSample
from warhub_acquisition.swatch.pdf_chart import (
    Swatch,
    _channel_spread,
    _distance,
    _median_rgb,
    _rgb_hex,
)

# A near-white sample on a product photo is far more likely a mispositioned region over the
# studio backdrop than a genuinely white paint; templated flat tiles disable this guard.
_BACKDROP = (247, 247, 247)
_BACKDROP_DISTANCE = 18.0


@dataclass(frozen=True)
class ItemImageSpec:
    chart_id: str
    # Exactly one URL source: a `{code}` template (code optionally zero-padded to code_pad),
    # or the catalog's own harvested imageUrl per paint (use_catalog_images).
    url_template: str | None = None
    code_pad: int = 0
    use_catalog_images: bool = False
    # Candidate regions tried IN ORDER; the first that passes every guard wins. Product-photo
    # layouts drift across a brand's label generations, so one fixed window can reject most of
    # a range while a short ordered list of known layouts covers it -- ordering encodes trust
    # (put the historically-calibrated window first). A single-region spec is just a 1-list.
    regions: tuple[CellSample, ...] = (CellSample(0.1, 0.1, 0.9, 0.9),)
    set_name: str | None = None
    reject_backdrop: bool = True
    # Uniformity ceiling: a region whose per-channel spread exceeds this is a busy photo area
    # (text, bottle edges), not a colour surface -- dropped rather than guessed.
    max_spread: float = 60.0


def template_url(spec: ItemImageSpec, code: str) -> str:
    padded = code.zfill(spec.code_pad) if spec.code_pad else code
    return (spec.url_template or "").replace("{code}", padded)


def sample_item(image, code: str, spec: ItemImageSpec) -> tuple[Swatch | None, str | None]:
    """Sample one paint's image, trying each candidate region in order.
    Returns (swatch, None) on the first region passing every guard, else (None, reasons)."""
    rgb_image = image.convert("RGB")
    w, h = rgb_image.size
    reasons: list[str] = []
    for r in spec.regions:
        box = (round(w * r.x0), round(h * r.y0), round(w * r.x1), round(h * r.y1))
        if box[2] - box[0] < 3 or box[3] - box[1] < 3:
            reasons.append("region too small")
            continue

        pixels = list(rgb_image.crop(box).getdata())
        rgb = _median_rgb(pixels)
        if spec.reject_backdrop and _distance(rgb, _BACKDROP) < _BACKDROP_DISTANCE:
            reasons.append("backdrop-white")
            continue
        spread = _channel_spread(pixels)
        if spread > spec.max_spread:
            reasons.append(f"busy (spread {spread:.0f})")
            continue

        return (
            Swatch(
                code=code,
                page=0,
                hex=_rgb_hex(rgb),
                rgb=rgb,
                confidence="high" if spread < 18.0 else "medium",
                label_x0=0.0,
                label_top=0.0,
                crop_box_px=box,
            ),
            None,
        )
    return None, "; ".join(reasons) or "no regions configured"
