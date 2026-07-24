"""Item-image swatch sampling: per-code images (flat tiles / product photos)."""
import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from warhub_acquisition.swatch.grid_image import CellSample  # noqa: E402
from warhub_acquisition.swatch.item_image import (  # noqa: E402
    ItemImageSpec,
    sample_item,
    template_url,
)


def spec(**kw) -> ItemImageSpec:
    return ItemImageSpec(chart_id="t", **kw)


def flat(color, size=(100, 100)):
    return Image.new("RGB", size, color)


def test_template_url_pads_code() -> None:
    s = spec(url_template="https://x/{code}.jpg", code_pad=5)
    assert template_url(s, "9412") == "https://x/09412.jpg"
    assert template_url(s, "29182") == "https://x/29182.jpg"  # already 5 digits


def test_flat_tile_samples_exact_colour() -> None:
    s = spec(regions=(CellSample(0.2, 0.2, 0.8, 0.8),), reject_backdrop=False)
    swatch, reason = sample_item(flat((204, 51, 51)), "09002", s)
    assert reason is None
    assert swatch.hex == "#CC3333"
    assert swatch.confidence == "high"


def test_backdrop_guard_rejects_studio_white_but_not_when_disabled() -> None:
    near_white = flat((248, 248, 248))
    guarded, reason = sample_item(near_white, "1", spec())
    assert guarded is None and "backdrop" in reason
    s = spec(reject_backdrop=False)
    tile, _ = sample_item(near_white, "1", s)
    assert tile is not None  # white PAINTS exist; templated tiles disable the guard


def test_multi_region_falls_back_past_busy_region() -> None:
    # Left half: noisy checker (busy). Right half: flat colour. First region hits the noise,
    # second lands on the colour -- the fallback must recover it.
    im = flat((60, 120, 180), size=(200, 100))
    draw = ImageDraw.Draw(im)
    for x in range(0, 100, 10):
        for y in range(0, 100, 10):
            if (x + y) // 10 % 2 == 0:
                draw.rectangle((x, y, x + 9, y + 9), fill=(255, 255, 0))
    s = spec(
        regions=(CellSample(0.05, 0.1, 0.45, 0.9), CellSample(0.55, 0.1, 0.95, 0.9)),
        reject_backdrop=False,
    )
    swatch, reason = sample_item(im, "9", s)
    assert reason is None
    assert swatch.rgb == (60, 120, 180)


def test_all_regions_failing_reports_reasons() -> None:
    im = flat((248, 248, 248))
    s = spec(regions=(CellSample(0.1, 0.1, 0.9, 0.9), CellSample(0.2, 0.2, 0.8, 0.8)))
    swatch, reason = sample_item(im, "9", s)
    assert swatch is None
    assert reason.count("backdrop") == 2
