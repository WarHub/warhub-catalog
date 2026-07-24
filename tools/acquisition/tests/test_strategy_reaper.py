"""Reaper strategy: embedded line-page blobs, sku dedupe across pages, set contents."""
from pathlib import Path

import httpx
import pytest

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.reaper import (
    _extract_paints,
    reaper_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "reaper"

# Trimmed REAL captures (2026-07-24) of three of the six live line pages, exercising the whole
# surface: a set page with associatedProducts (paint-sets), a set page without (triads), and a
# singles page (core-colors) that ALSO lists a triad sku (09819) the triads page already claimed.
PAGES = {
    "/paints/paint-sets": "paint-sets.html",
    "/paints/master-series-paints-triads": "triads.html",
    "/paints/master-series-paints-core-colors": "core-colors.html",
}


def reaper_taxonomy() -> Taxonomy:
    return Taxonomy(
        {"reaper": Manufacturer(slug="reaper", name="Reaper", vendorNames=["Reaper Miniatures"])}
    )


def descriptor(**extra_scope: object) -> SourceDescriptor:
    return SourceDescriptor(
        id="mfr-reaper",
        kind="manufacturer",
        strategy="reaper",
        baseUrl="https://www.reapermini.com",
        scope={
            "manufacturer": "Reaper",
            # Same ordering rule as the committed descriptor: set-kind pages first, so a
            # triad recurring on the core-colors singles page keeps its set identity.
            "linePages": [
                {"path": "/paints/paint-sets", "line": "Paint Sets", "kind": "set"},
                {
                    "path": "/paints/master-series-paints-triads",
                    "line": "Master Series Paints Triads",
                    "kind": "set",
                },
                {
                    "path": "/paints/master-series-paints-core-colors",
                    "line": "Master Series Paints Core Colors",
                    "kind": "single",
                },
            ],
            **extra_scope,
        },
    )


def context() -> AcquireContext:
    return AcquireContext(taxonomy=reaper_taxonomy(), mappings={}, run_date="2026-07-24")


def transport(calls: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        fixture = PAGES.get(request.url.path)
        if fixture is None:
            raise AssertionError(f"unexpected request: {request.url}")
        return httpx.Response(200, text=(FIXTURES / fixture).read_text(encoding="utf-8"))

    return httpx.MockTransport(handler)


def run(desc: SourceDescriptor | None = None, calls: list[str] | None = None):
    client = PoliteClient(
        "https://www.reapermini.com", transport=transport(calls), sleep=lambda s: None
    )
    return reaper_strategy(desc or descriptor(), client, {}, context())


def test_strategy_is_registered() -> None:
    assert STRATEGIES["reaper"] is reaper_strategy


def test_extract_paints_raises_loudly_on_marketing_page() -> None:
    # The site serves a data-less marketing page for any unknown /paints/<slug> (catch-all):
    # silence there must be a run failure, never an empty observation set.
    with pytest.raises(ValueError, match="/paints/msp2"):
        _extract_paints("<html><body>marketing only</body></html>", "/paints/msp2")
    with pytest.raises(ValueError, match="not valid JSON"):
        _extract_paints("\t\t\tpaints: [{oops}],\n", "/paints/broken")


def test_observation_shape_singles() -> None:
    result = run()
    deep_red = next(o for o in result.observations if o.sku == "09002")
    assert deep_red.key == "mfr-reaper:09002"
    assert deep_red.name == "Deep Red"
    assert deep_red.manufacturer == "reaper"
    assert deep_red.url == "https://www.reapermini.com/paints/master-series-paints-core-colors"
    assert deep_red.imageUrl == "https://images.reapermini.com/4/09002.jpg"
    assert deep_red.priceUsd == 3.89
    assert deep_red.availability == "in_stock"
    assert deep_red.hints["category"] == "paint"
    assert deep_red.hints["line"] == "Master Series Paints Core Colors"
    assert deep_red.hints["colorTags"] == ["red"]
    assert "contentSkus" not in deep_red.hints
    assert deep_red.extractor == "reaper@1"

    # 09001 Red Brick ships with an empty images array on the live page.
    red_brick = next(o for o in result.observations if o.sku == "09001")
    assert red_brick.imageUrl is None
    assert result.stats["image_missing"] == 1

    # 09168 Mist Green had inventory 0 on the live page.
    mist_green = next(o for o in result.observations if o.sku == "09168")
    assert mist_green.availability == "out_of_stock"


def test_duplicate_sku_keeps_first_page_identity() -> None:
    result = run()
    # 09819 appears on BOTH the triads page (listed first, kind=set) and the core-colors
    # singles page: the set identity must win, and the recurrence is only a stat.
    triad = next(o for o in result.observations if o.sku == "09819")
    assert triad.name == "Tinted Glosses Triad #1"
    assert triad.hints["category"] == "paint-set"
    assert triad.hints["line"] == "Master Series Paints Triads"
    assert triad.url == "https://www.reapermini.com/paints/master-series-paints-triads"
    assert result.stats["duplicate_skus"] == 1
    assert [o.sku for o in result.observations] == sorted({o.sku for o in result.observations})


def test_set_contents_keep_paint_material_skus_only() -> None:
    result = run()
    fast_palette = next(o for o in result.observations if o.sku == "09901")
    assert fast_palette.hints["category"] == "paint-set"
    assert fast_palette.hints["contentSkus"] == [
        "09148", "09149", "09150", "09274", "09275", "09276"
    ]

    # The Learn To Paint Kit's associatedProducts mixes brushes ("accessory") and Bones
    # figures ("plastic") in with the paints -- only paint-material skus are evidence.
    ltpk = next(o for o in result.observations if o.sku == "08906")
    contents = ltpk.hints["contentSkus"]
    assert "08501" not in contents  # Small Drybrush (accessory)
    assert "77018" not in contents  # Bones figure (plastic)
    assert len(contents) == 11
    assert all(sku.startswith(("09", "29")) for sku in contents)


def test_full_sweep_stateless_cursor_and_stats() -> None:
    calls: list[str] = []
    result = run(calls=calls)
    assert result.full_sweep is True
    assert result.cursor == {}
    # One GET per configured page, in descriptor order -- the whole request footprint.
    assert [c.split("reapermini.com")[1] for c in calls] == list(
        p["path"] for p in descriptor().scope["linePages"]
    )
    assert result.stats["fetched_pages"] == 3
    assert result.stats["products_seen"] == 9  # 2 sets + 2 triads + 5 core items
    assert result.stats["kept_set_products"] == 4
    assert result.stats["kept_paint_products"] == 4  # 09819 deduped out of core
    assert len(result.observations) == 8


def test_unknown_vendor_observes_nothing() -> None:
    result = run(descriptor(manufacturer="Somebody Else"))
    assert result.observations == []
    assert result.stats["skipped_unknown_vendor"] == 9
