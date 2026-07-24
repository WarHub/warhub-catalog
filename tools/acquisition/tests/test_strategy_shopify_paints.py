"""Shopify paints strategy: type/vendor filtering + paint hints + barcode detail flow."""
import json
from pathlib import Path

import httpx

from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.shopify_paints import shopify_paints_strategy
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "shopify_paints"

TAP_FANATIC_HANDLE = "warpaints-fanatic-warpaints-fanatic-moldy-wine-wp3140p"
TAP_PRIMER_HANDLE = "colour-primers-colour-primer-hydra-turquoise-cp3033s"
TAP_UNTYPED_HANDLE = "warpaints-historical-historical-wwii-imperial-japanese-wp8125p"
TAP_BRUSH_HANDLE = "brushes-wargamer-brush-the-psycho-br7014p"
MONUMENT_SINGLE_HANDLE = "pro-acryl-1-step-501-royal-purple"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def paint_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "army-painter": Manufacturer(
                slug="army-painter",
                name="The Army Painter",
                vendorNames=["The Army Painter (B2C)"],
            ),
            "monument-hobbies": Manufacturer(
                slug="monument-hobbies", name="Monument Hobbies", vendorNames=["Monument Hobbies"]
            ),
        }
    )


def tap_descriptor(**extra_scope: object) -> SourceDescriptor:
    return SourceDescriptor(
        id="mfr-armypainter",
        kind="manufacturer",
        strategy="shopify-paints",
        baseUrl="https://www.thearmypainter.com",
        scope={"currency": "usd", "includeTypes": ["Paint", "Spray", ""], **extra_scope},
    )


def monument_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="mfr-monument",
        kind="manufacturer",
        strategy="shopify-paints",
        baseUrl="https://monumenthobbies.com",
        scope={
            "currency": "usd",
            "vendors": ["Monument Hobbies"],
            "includeTypes": ["Paint Singles"],
        },
    )


def context(budget: int | None = None) -> AcquireContext:
    return AcquireContext(taxonomy=paint_taxonomy(), mappings={}, run_date="2026-07-23", budget=budget)


def tap_transport(calls: list[str] | None = None) -> httpx.MockTransport:
    """Real captured TAP fixtures: bulk page1 (4 products: Paint single, Spray, untyped set,
    Brush), page2 empty, one .js detail carrying the real EAN 5713799314009."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        if path == "/products.json":
            page = request.url.params.get("page")
            if page == "1":
                return httpx.Response(200, json=load_fixture("tap-bulk-page1.json"))
            return httpx.Response(200, json=load_fixture("tap-bulk-page2.json"))
        if path.startswith("/products/") and path.endswith(".js"):
            if path == f"/products/{TAP_FANATIC_HANDLE}.js":
                return httpx.Response(200, json=load_fixture("tap-detail.js.json"))
            # every other kept handle: no barcode in detail
            return httpx.Response(200, json={"variants": [{"sku": "X", "barcode": None}]})
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def run_tap(budget: int | None = None, cursor: dict | None = None, calls: list[str] | None = None):
    from warhub_acquisition.acquire.client import PoliteClient

    client = PoliteClient(
        "https://www.thearmypainter.com", transport=tap_transport(calls), sleep=lambda s: None
    )
    return shopify_paints_strategy(tap_descriptor(), client, cursor or {}, context(budget))


def test_strategy_is_registered() -> None:
    assert STRATEGIES["shopify-paints"] is shopify_paints_strategy


def test_type_filter_keeps_paint_spray_and_untyped_drops_brush() -> None:
    result = run_tap()
    keys = {obs.key for obs in result.observations}
    assert f"mfr-armypainter:{TAP_FANATIC_HANDLE}" in keys
    assert f"mfr-armypainter:{TAP_PRIMER_HANDLE}" in keys
    assert f"mfr-armypainter:{TAP_UNTYPED_HANDLE}" in keys
    assert f"mfr-armypainter:{TAP_BRUSH_HANDLE}" not in keys
    assert result.stats["skipped_type"] == 1
    assert result.stats["kept_paint_products"] == 3


def test_paint_hints_carry_type_grams_and_tags() -> None:
    result = run_tap()
    fanatic = next(o for o in result.observations if TAP_FANATIC_HANDLE in o.key)
    assert fanatic.hints["category"] == "paint"
    assert fanatic.hints["productType"] == "Paint"
    assert fanatic.hints["grams"] == 26
    assert "WARPAINTS FANATIC" in fanatic.hints["tags"]
    assert fanatic.name == "Warpaints Fanatic: Moldy Wine"
    assert fanatic.sku == "WP3140P"
    assert fanatic.priceUsd == 4.85


def test_detail_fetch_finds_real_barcode_and_cursor_carries_it() -> None:
    result = run_tap()
    fanatic = next(o for o in result.observations if TAP_FANATIC_HANDLE in o.key)
    assert fanatic.ean == "5713799314009"
    assert result.cursor["updated_at"][TAP_FANATIC_HANDLE]["ean"] == "5713799314009"
    assert result.stats["barcodes_found"] == 1


def test_budget_zero_defers_all_details_and_blocks_full_sweep() -> None:
    result = run_tap(budget=0)
    assert result.stats["details_fetched"] == 0
    assert all(obs.ean is None for obs in result.observations)
    assert len(result.cursor["pending_details"]) == 3
    assert result.full_sweep is False


def test_known_ean_carried_forward_without_refetch() -> None:
    first = run_tap()
    calls: list[str] = []
    second = run_tap(cursor=first.cursor, calls=calls)
    fanatic = next(o for o in second.observations if TAP_FANATIC_HANDLE in o.key)
    assert fanatic.ean == "5713799314009"
    assert not any(TAP_FANATIC_HANDLE + ".js" in url for url in calls)


def test_detail_miss_cap_gives_up_after_three_runs() -> None:
    cursor: dict = {}
    for _ in range(3):
        result = run_tap(cursor=cursor)
        cursor = result.cursor
    # primer + untyped set: 3 successful no-barcode fetches each -> capped, queue empties
    assert cursor["updated_at"][TAP_PRIMER_HANDLE]["detailMisses"] == 3
    final = run_tap(cursor=cursor)
    assert final.stats["details_fetched"] == 0
    assert final.full_sweep is True


def test_monument_vendor_allowlist_excludes_third_party_stock() -> None:
    from warhub_acquisition.acquire.client import PoliteClient

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/products.json":
            if request.url.params.get("page") == "1":
                return httpx.Response(200, json=load_fixture("monument-bulk-page1.json"))
            return httpx.Response(200, json={"products": []})
        if path == f"/products/{MONUMENT_SINGLE_HANDLE}.js":
            return httpx.Response(200, json=load_fixture("monument-detail.js.json"))
        raise AssertionError(f"unexpected request: {request.url}")

    client = PoliteClient(
        "https://monumenthobbies.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    result = shopify_paints_strategy(monument_descriptor(), client, {}, context())
    assert [obs.key for obs in result.observations] == [f"mfr-monument:{MONUMENT_SINGLE_HANDLE}"]
    # Tri Art (out-of-scope vendor) and Printify T-Shirt (vendor not in allow-list either)
    assert result.stats["out_of_scope_vendor"] == 2
    single = result.observations[0]
    assert single.sku == "MPA-501"
    assert single.ean == "655368409059"


# --- Scale75: scope.collections + scope.skipDetails (see shopify_paints.py docstring) ----------

SCALE75_UMBRELLA = "pinturas-para-miniaturas-colores-pinturas-acrilicas"
SCALE75_DUP_HANDLE = "black"  # listed in scalecolor-individual AND the umbrella fixture
SCALE75_SCALECOLOR_ONLY_HANDLE = "petroleum-gray"
SCALE75_UMBRELLA_ONLY_HANDLE = "dunkelgelb-yellow"  # Warfront single: umbrella fixture only


def scale75_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "scale75": Manufacturer(
                slug="scale75",
                name="Scale75",
                # Live store vendor is 'SCALE75 - HOBBIES & GAMES' (all caps, 2026-07-24);
                # taxonomy matching is casefolded so the mixed-case entry must still attribute.
                vendorNames=["SCALE75 - Hobbies & Games", "Scale75", "SCALE75"],
            )
        }
    )


def scale75_descriptor(**extra_scope: object) -> SourceDescriptor:
    return SourceDescriptor(
        id="mfr-scale75",
        kind="manufacturer",
        strategy="shopify-paints",
        baseUrl="https://scale75.com",
        scope={
            "currency": "eur",
            # Specific range collection first, umbrella last -- mirrors the real descriptor's
            # dedupe-order convention (module docstring).
            "collections": ["scalecolor-individual", SCALE75_UMBRELLA],
            **extra_scope,
        },
    )


def scale75_transport(calls: list[str] | None = None) -> httpx.MockTransport:
    """Real captured scale75.com fixtures (2026-07-24, trimmed): scalecolor-individual page1
    (SC-00 black + SC-57 petroleum-gray), umbrella page1 (black again + SW-00
    dunkelgelb-yellow), every later page empty. Store-wide /products.json is deliberately NOT
    handled: a collection-scoped source touching it fails the test loudly."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        page = request.url.params.get("page")
        if path == "/collections/scalecolor-individual/products.json":
            if page == "1":
                return httpx.Response(200, json=load_fixture("scale75-scalecolor-p1.json"))
            return httpx.Response(200, json={"products": []})
        if path == f"/collections/{SCALE75_UMBRELLA}/products.json":
            if page == "1":
                return httpx.Response(200, json=load_fixture("scale75-umbrella-p1.json"))
            return httpx.Response(200, json={"products": []})
        if path.startswith("/products/") and path.endswith(".js"):
            # Store-wide truth on scale75.com (2026-07-24): variant barcodes are unpopulated.
            return httpx.Response(200, json={"variants": [{"sku": "SC-00", "barcode": None}]})
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def run_scale75(
    cursor: dict | None = None, calls: list[str] | None = None, **extra_scope: object
):
    from warhub_acquisition.acquire.client import PoliteClient

    client = PoliteClient(
        "https://scale75.com", transport=scale75_transport(calls), sleep=lambda s: None
    )
    ctx = AcquireContext(
        taxonomy=scale75_taxonomy(), mappings={}, run_date="2026-07-24", budget=None
    )
    return shopify_paints_strategy(scale75_descriptor(**extra_scope), client, cursor or {}, ctx)


def test_collections_scope_dedupes_by_handle_and_records_membership_hints() -> None:
    calls: list[str] = []
    result = run_scale75(calls=calls)
    enumeration = [url for url in calls if "products.json" in url]
    assert enumeration and all("/collections/" in url for url in enumeration)
    assert result.stats["collections_enumerated"] == 2
    # 4 listings, 3 unique products: 'black' sits in both scoped collections
    assert result.stats["products_seen"] == 3
    assert [obs.key for obs in result.observations] == [
        f"mfr-scale75:{SCALE75_DUP_HANDLE}",
        f"mfr-scale75:{SCALE75_UMBRELLA_ONLY_HANDLE}",
        f"mfr-scale75:{SCALE75_SCALECOLOR_ONLY_HANDLE}",
    ]
    by_handle = {obs.key.split(":", 1)[1]: obs for obs in result.observations}
    assert by_handle[SCALE75_DUP_HANDLE].hints["collections"] == [
        SCALE75_UMBRELLA,
        "scalecolor-individual",
    ]
    assert by_handle[SCALE75_SCALECOLOR_ONLY_HANDLE].hints["collections"] == [
        "scalecolor-individual"
    ]
    assert by_handle[SCALE75_UMBRELLA_ONLY_HANDLE].hints["collections"] == [SCALE75_UMBRELLA]


def test_collections_scope_attributes_casefolded_vendor_and_eur_price() -> None:
    result = run_scale75()
    black = next(o for o in result.observations if o.key.endswith(f":{SCALE75_DUP_HANDLE}"))
    assert black.manufacturer == "scale75"
    assert black.name == "BLACK"
    assert black.sku == "SC-00"
    assert black.priceEur == 2.65
    assert black.hints["productType"] == ""
    assert black.hints["grams"] == 40


def test_collections_scope_still_runs_detail_queue_by_default() -> None:
    calls: list[str] = []
    result = run_scale75(calls=calls)
    assert result.stats["details_fetched"] == 3
    # No barcode anywhere on this store -> everything re-queues, full sweep blocked
    assert len(result.cursor["pending_details"]) == 3
    assert result.full_sweep is False


def test_skip_details_fetches_no_js_and_reaches_full_sweep_with_empty_cursor() -> None:
    calls: list[str] = []
    result = run_scale75(calls=calls, skipDetails=True)
    assert not any(url.endswith(".js") for url in calls)
    assert result.stats["details_fetched"] == 0
    assert all(obs.ean is None for obs in result.observations)
    assert result.cursor == {"updated_at": {}, "pending_details": []}
    assert result.full_sweep is True
