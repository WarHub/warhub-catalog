"""Mr Hobby strategy: listing pagination, series-detail parse, budget/cursor/give-up flow."""
from pathlib import Path

import httpx

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.mr_hobby import (
    _parse_detail,
    mr_hobby_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "mr_hobby"

BASE = "https://www.mr-hobby.com"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def mr_hobby_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "mr-hobby": Manufacturer(
                slug="mr-hobby", name="Mr Hobby", vendorNames=["GSI Creos", "Mr. Hobby"]
            )
        }
    )


def descriptor(**extra_scope: object) -> SourceDescriptor:
    return SourceDescriptor(
        id="mfr-mr-hobby",
        kind="manufacturer",
        strategy="mr-hobby",
        baseUrl=BASE,
        scope={
            "manufacturer": "Mr Hobby",
            "categories": [
                {"id": 1, "label": "Mr. COLOR"},
                {"id": 6, "label": "COLLABORATION PAINT"},
            ],
            **extra_scope,
        },
    )


def context(budget: int | None = None) -> AcquireContext:
    return AcquireContext(
        taxonomy=mr_hobby_taxonomy(), mappings={}, run_date="2026-07-24", budget=budget
    )


def transport(
    calls: list[str] | None = None,
    drift_details: bool = False,
    not_found: set[str] | None = None,
) -> httpx.MockTransport:
    """Real trimmed captures (2026-07-24): category 1 spans two pages (page 2 is the real last
    page, linking only lower page numbers), category 6 is a single page whose one tile
    (detail/2828) is cross-listed with category 1. `drift_details=True` serves every detail id
    the prodinfo-less drift capture instead, for the give-up-cap flow; ids in `not_found` 404
    like the live site's JA-only tiles whose EN detail pages don't exist."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        page = request.url.params.get("page")
        if path == "/en/products/category/1":
            return httpx.Response(200, text=load_fixture(f"cat1-page{page or '1'}.html"))
        if path == "/en/products/category/6":
            assert page is None  # single-page category: no ?page anchors, so no page-2 fetch
            return httpx.Response(200, text=load_fixture("cat6-page1.html"))
        if path.startswith("/en/products/detail/"):
            detail_id = path.rsplit("/", 1)[1]
            if not_found is not None and detail_id in not_found:
                return httpx.Response(404, text="not found")
            name = "detail-drift.html" if drift_details else f"detail-{detail_id}.html"
            return httpx.Response(200, text=load_fixture(name))
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def run(
    budget: int | None = None,
    cursor: dict | None = None,
    calls: list[str] | None = None,
    drift_details: bool = False,
    not_found: set[str] | None = None,
):
    client = PoliteClient(
        BASE, transport=transport(calls, drift_details, not_found), sleep=lambda s: None
    )
    return mr_hobby_strategy(descriptor(), client, cursor or {}, context(budget))


def observation(result, detail_id: str):
    return next(o for o in result.observations if o.key == f"mfr-mr-hobby:{detail_id}")


def test_strategy_is_registered() -> None:
    assert STRATEGIES["mr-hobby"] is mr_hobby_strategy


def test_listing_pagination_terminates_on_missing_next_anchor() -> None:
    calls: list[str] = []
    result = run(calls=calls)
    # Page 1 advertises ?page=2, page 2 (the real last page) links only lower pages -> exactly
    # two category-1 requests, no speculative page-3/empty-page fetch; category 6 renders no
    # pagination anchors at all -> exactly one request.
    listing_calls = [url for url in calls if "/category/" in url]
    assert listing_calls == [
        f"{BASE}/en/products/category/1",
        f"{BASE}/en/products/category/1?page=2",
        f"{BASE}/en/products/category/6",
    ]
    assert result.stats["fetched_pages"] == 3
    assert result.stats["products_seen"] == 5
    assert result.stats["enumeration_capped"] == 0


def test_detail_parse_carries_code_volume_image_and_name() -> None:
    result = run()
    mr_color = observation(result, "1")
    assert mr_color.name == "Mr.COLOR"
    assert mr_color.sku == "C1~C189"  # verbatim range string; splitting is the bridge's job
    assert mr_color.manufacturer == "mr-hobby"
    assert mr_color.url == f"{BASE}/en/products/detail/1"
    assert mr_color.hints["volumeMl"] == 10  # "Net Amount: 10ml"
    assert mr_color.hints["line"] == "Mr. COLOR"
    assert mr_color.imageUrl.endswith("/uploads/products/01JKD4H1G5C88NGK7RP4KPE036.png")

    mirror_silver = observation(result, "22")
    assert mirror_silver.name == "MIRROR SILVER"
    assert mirror_silver.sku == "SMS1"
    assert "volumeMl" not in mirror_silver.hints  # no volume line on this page

    armored_core = observation(result, "2828")
    assert armored_core.hints["volumeMl"] == 18  # free-text "NET:18ml" variant

    # No probed page carries a JAN (2026-07-24) -- the hook must stay silent, never misfire.
    assert all(o.ean is None for o in result.observations)
    assert result.stats["barcodes_found"] == 0
    assert result.stats["details_fetched"] == 5
    assert result.full_sweep is True


def test_placeholder_images_and_lifecycle_tags() -> None:
    result = run()
    ggx = observation(result, "2947")
    # Name comes from the detail h3 (nested <div>NEW</div> must not truncate the prodinfo
    # block); the full-width space is site-verbatim.
    assert ggx.name == "MR.COLOR GGX　18ml Ver."
    assert ggx.sku == "GGX"
    assert ggx.imageUrl is None  # /images/products/no-image.png placeholder on both pages
    assert ggx.hints["tag"] == "NEW PRODUCTS"
    # "18ml" inside the NAME must never parse as volume -- only the NET-labelled line counts.
    assert "volumeMl" not in ggx.hints

    metal_color = observation(result, "19")
    assert metal_color.name == "MR. METAL COLOR"
    assert metal_color.sku == "MC211~219"
    assert metal_color.imageUrl is None
    assert metal_color.hints["tag"] == "Out of Production"


def test_cross_listed_id_dedupes_with_all_category_labels() -> None:
    result = run()
    armored_core = observation(result, "2828")
    assert len([o for o in result.observations if o.key.endswith(":2828")]) == 1
    assert armored_core.hints["line"] == "Mr. COLOR"  # first configured category wins
    assert armored_core.hints["lines"] == ["COLLABORATION PAINT", "Mr. COLOR"]
    ggx = observation(result, "2947")
    assert "lines" not in ggx.hints  # single-category ids carry no redundant list


def test_jan_hook_parses_digits_when_a_page_ever_carries_one() -> None:
    # The live site publishes no JAN anywhere (probed 2026-07-24, EN+JA) -- this exercises the
    # hook against a real prodinfo block with a synthetic JAN line injected.
    page = load_fixture("detail-22.html").replace(
        "Product Number : SMS1", "Product Number : SMS1</p><p>JAN : 4973028609841"
    )
    parsed = _parse_detail(page, BASE)
    assert parsed["ean"] == "4973028609841"
    assert parsed["sku"] == "SMS1"
    # And the untouched capture yields none.
    assert "ean" not in _parse_detail(load_fixture("detail-22.html"), BASE)


def test_budget_zero_defers_details_but_observes_all_listings() -> None:
    result = run(budget=0)
    assert result.stats["details_fetched"] == 0
    assert len(result.observations) == 5  # listings alone still observe the full population
    assert result.cursor["pending_details"] == ["1", "19", "22", "2828", "2947"]
    assert result.full_sweep is False
    ggx = observation(result, "2947")
    assert ggx.name == "MR.COLOR GGX　18ml Ver."  # listing text fallback
    assert ggx.sku == "GGX"  # listing code fallback
    assert "volumeMl" not in ggx.hints


def test_cursor_carries_parsed_details_forward_without_refetch() -> None:
    first = run()
    calls: list[str] = []
    second = run(cursor=first.cursor, calls=calls)
    assert not any("/products/detail/" in url for url in calls)
    assert second.stats["details_fetched"] == 0
    mr_color = observation(second, "1")
    assert mr_color.sku == "C1~C189"
    assert mr_color.hints["volumeMl"] == 10
    assert mr_color.imageUrl.endswith(".png")
    assert second.full_sweep is True


def test_partial_budget_resumes_from_pending_queue() -> None:
    first = run(budget=2)
    assert first.stats["details_fetched"] == 2
    assert first.cursor["pending_details"] == ["22", "2828", "2947"]
    assert first.full_sweep is False
    second = run(budget=None, cursor=first.cursor)
    assert second.stats["details_fetched"] == 3  # only the pending ids, never a refetch
    assert second.full_sweep is True
    assert second.cursor["pending_details"] == []


def test_missing_en_detail_page_gives_up_immediately_but_stays_observed() -> None:
    # Live 2026-07-24: the EN listings advertise a few tiles (detail/39, 2508, 2509, 2541)
    # whose EN detail pages 404 -- definitive absence must cap instantly, never stay pending.
    calls: list[str] = []
    result = run(calls=calls, not_found={"2947"})
    assert result.stats["detail_not_found"] == 1
    assert result.stats["detail_fetch_errors"] == 0
    assert result.cursor["details"]["2947"] == {"detailMisses": 3}
    assert result.cursor["pending_details"] == []
    assert result.full_sweep is True
    ggx = observation(result, "2947")
    assert ggx.name == "MR.COLOR GGX　18ml Ver."  # listing tile still observes the product
    # And the dead link is never fetched again once capped.
    second_calls: list[str] = []
    run(cursor=result.cursor, calls=second_calls, not_found={"2947"})
    assert not any("/products/detail/2947" in url for url in second_calls)


def test_give_up_cap_stops_retrying_unparseable_pages() -> None:
    cursor: dict = {}
    for _ in range(3):
        result = run(cursor=cursor, drift_details=True)
        assert result.stats["details_fetched"] == 5
        assert result.stats["detail_parse_misses"] == 5
        cursor = result.cursor
    assert cursor["details"]["22"] == {"detailMisses": 3}
    final = run(cursor=cursor, drift_details=True)
    assert final.stats["details_fetched"] == 0
    assert final.full_sweep is True
    assert final.cursor["pending_details"] == []
    # Listing data still observes every product even though no detail ever parsed.
    assert len(final.observations) == 5
    assert observation(final, "22").name == "MIRROR SILVER"
