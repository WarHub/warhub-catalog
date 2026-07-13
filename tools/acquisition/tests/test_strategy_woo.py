"""WooCommerce Store API strategy: full enumeration + budgeted JSON-LD gtin detail fetch."""
import json
from pathlib import Path

import httpx
import pytest

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.woo import _extract_gtin, woo_strategy
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "woo"

MANTIC_BASE = "https://www.manticgames.com"
PB_BASE = "https://eshop.para-bellum.com"

# Real permalinks captured live (2026-07-13) for the two products in mantic-store-page1.json.
FRACTURE_PERMALINK = f"{MANTIC_BASE}/kings-of-war/books/fracture-expansion/"
UNDEAD_PERMALINK = f"{MANTIC_BASE}/kings-of-war/undead/warband-booster/"

# A synthetic (not live-captured) product detail page with no gtin anywhere in its JSON-LD --
# stands in for the real "undead-warband-booster" product page, which was captured live and
# confirmed to have no gtin field (see task-8-report.md), but is not itself a committed fixture
# since only one real detail-page fixture was required.
NO_GTIN_HTML = """<!doctype html><html><head>
<script type="application/ld+json" class="yoast-schema-graph">{"@context":"https://schema.org","@graph":[{"@type":["WebPage","ItemPage"],"name":"Undead Warband Booster"},{"@type":"Product","name":"Undead Warband Booster","sku":"MGVAU102","offers":[{"@type":"Offer","priceSpecification":[{"price":"35.00"}]}]}]}</script>
</head><body></body></html>"""


def load_json_fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_text_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def mantic_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "mantic-games": Manufacturer(
                slug="mantic-games", name="Mantic Games", vendorNames=["Mantic Games", "Mantic"]
            )
        }
    )


def para_bellum_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "para-bellum": Manufacturer(
                slug="para-bellum", name="Para Bellum", vendorNames=["Para Bellum", "Para Bellum Wargames"]
            )
        }
    )


def mantic_descriptor(**scope_overrides: object) -> SourceDescriptor:
    scope: dict[str, object] = {"manufacturer": "Mantic Games", "currency": "gbp", "gtinFromJsonLd": True}
    scope.update(scope_overrides)
    return SourceDescriptor(
        id="mfr-manticgames", kind="manufacturer", strategy="woo-store-api", baseUrl=MANTIC_BASE, scope=scope
    )


def para_bellum_descriptor(**scope_overrides: object) -> SourceDescriptor:
    scope: dict[str, object] = {"manufacturer": "Para Bellum", "currency": "usd"}
    scope.update(scope_overrides)
    return SourceDescriptor(
        id="mfr-para-bellum", kind="manufacturer", strategy="woo-store-api", baseUrl=PB_BASE, scope=scope
    )


def context(taxonomy: Taxonomy, budget: int | None = None, mappings: dict | None = None) -> AcquireContext:
    return AcquireContext(
        taxonomy=taxonomy, mappings=mappings or {}, run_date="2026-07-13", budget=budget
    )


def mantic_fixture_transport(calls: list[str] | None = None) -> httpx.MockTransport:
    """Routes the real captured Mantic fixtures by URL/page, plus a synthetic no-gtin detail
    page for the second (undead-warband-booster) product's permalink."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if request.url.path == "/wp-json/wc/store/products":
            page = request.url.params.get("page")
            if page == "1":
                return httpx.Response(
                    200,
                    json=load_json_fixture("mantic-store-page1.json"),
                    headers={"X-WP-Total": "2789"},
                )
            if page == "2":
                return httpx.Response(200, json=load_json_fixture("mantic-store-page2.json"))
            raise AssertionError(f"unexpected page requested: {page}")
        if str(request.url) == FRACTURE_PERMALINK:
            return httpx.Response(200, text=load_text_fixture("mantic-product-ldjson.html"))
        if str(request.url) == UNDEAD_PERMALINK:
            return httpx.Response(200, text=NO_GTIN_HTML)
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def para_bellum_fixture_transport(calls: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if request.url.path == "/wp-json/wc/store/products":
            page = request.url.params.get("page")
            if page == "1":
                return httpx.Response(
                    200,
                    json=load_json_fixture("para-bellum-store-page1.json"),
                    headers={"X-WP-Total": "384"},
                )
            if page == "2":
                return httpx.Response(200, json=[])
            raise AssertionError(f"unexpected page requested: {page}")
        raise AssertionError(f"unexpected request: {request.url} (Para Bellum must never fetch details)")

    return httpx.MockTransport(handler)


def test_strategy_is_registered() -> None:
    assert STRATEGIES["woo-store-api"] is woo_strategy


def test_enumeration_and_detail_fetch_extracts_real_gtin_from_ldjson() -> None:
    calls: list[str] = []
    client = PoliteClient(MANTIC_BASE, transport=mantic_fixture_transport(calls), sleep=lambda s: None)
    result = woo_strategy(mantic_descriptor(), client, {}, context(mantic_taxonomy()))

    assert result.stats["fetched_pages"] == 2
    assert result.stats["products_seen"] == 2
    assert result.stats["skipped_unknown_vendor"] == 0
    assert result.stats["details_fetched"] == 2  # both products lack a cursor-recorded gtin
    assert result.stats["gtins_found"] == 1  # only the Fracture hardback's page has one
    assert result.stats["detail_fetch_errors"] == 0

    by_key = {observation.key: observation for observation in result.observations}
    fracture = by_key["mfr-manticgames:546541"]
    assert fracture.name == "Kings of War FRACTURE (Hardback Edition)"
    assert fracture.sku == "MGKWM144"
    assert fracture.ean == "9781911516675"  # the real gtin captured live
    assert fracture.priceGbp == 35.00  # "3500" minor units / 10**2
    assert fracture.url == FRACTURE_PERMALINK
    assert fracture.availability == "in_stock"
    assert fracture.extractor == "woo@1"
    assert fracture.manufacturer == "mantic-games"

    undead = by_key["mfr-manticgames:22395"]
    assert undead.ean is None  # fetched successfully, but no gtin in that page's JSON-LD
    assert undead.availability == "out_of_stock"

    # the undead-warband-booster detail fetch succeeded but found no gtin -- it re-queues for a
    # future retry (matches shopify.py's "fetched but no barcode" re-queue semantics exactly).
    assert result.full_sweep is False
    assert result.cursor["pending_details"] == ["22395"]
    assert result.cursor["gtin"] == {"546541": "9781911516675"}

    # 2 enumeration pages + 2 detail fetches (one per product, budget unspecified = full queue)
    assert len(calls) == 4


def test_x_wp_total_header_is_informational_only_and_does_not_stop_enumeration() -> None:
    """X-WP-Total must never drive loop control (finding 2): even though the header claims
    the whole catalog is satisfied by page 1, enumeration must still fetch page 2 and only
    stop once an empty page is seen. The header value is recorded purely as a stat."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        if page == "1":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "Alpha",
                        "sku": "A1",
                        "permalink": "https://example.test/alpha/",
                        "prices": {"price": "1000", "currency_minor_unit": 2},
                        "images": [],
                        "categories": [],
                        "is_in_stock": True,
                    },
                    {
                        "id": 2,
                        "name": "Bravo",
                        "sku": "B1",
                        "permalink": "https://example.test/bravo/",
                        "prices": {"price": "2000", "currency_minor_unit": 2},
                        "images": [],
                        "categories": [],
                        "is_in_stock": True,
                    },
                ],
                headers={"X-WP-Total": "2"},
            )
        if page == "2":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected page requested: {page}")

    client = PoliteClient(MANTIC_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = woo_strategy(
        mantic_descriptor(gtinFromJsonLd=False), client, {}, context(mantic_taxonomy(), budget=0)
    )

    assert result.stats["fetched_pages"] == 2  # page 2 fetched despite X-WP-Total already met
    assert result.stats["products_seen"] == 2
    assert result.stats["reported_total"] == 2  # kept only as an informational stat


def test_enumeration_completes_all_non_empty_pages_when_x_wp_total_is_absent() -> None:
    """Regression for trusting X-WP-Total for loop control: a missing header used to default
    to 0 via `int(headers.get("X-WP-Total", "0"))`, which combined with a `len(products) >=
    total` check terminated enumeration after a single page even when more non-empty pages
    remained. Termination must be driven ONLY by an empty page (mirrors shopify.py)."""

    def product(product_id: int, name: str) -> dict:
        return {
            "id": product_id,
            "name": name,
            "sku": f"P{product_id}",
            "permalink": f"https://example.test/{name.lower()}/",
            "prices": {"price": "1000", "currency_minor_unit": 2},
            "images": [],
            "categories": [],
            "is_in_stock": True,
        }

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        if page == "1":
            return httpx.Response(200, json=[product(1, "Alpha")])  # no X-WP-Total at all
        if page == "2":
            return httpx.Response(200, json=[product(2, "Bravo")])
        if page == "3":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected page requested: {page}")

    client = PoliteClient(MANTIC_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = woo_strategy(
        mantic_descriptor(gtinFromJsonLd=False), client, {}, context(mantic_taxonomy(), budget=0)
    )

    assert result.stats["fetched_pages"] == 3
    assert result.stats["products_seen"] == 2
    assert "reported_total" not in result.stats


def test_minor_unit_price_conversion_is_exact() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "1":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 42,
                        "name": "Widget",
                        "sku": "W1",
                        "permalink": "https://example.test/widget/",
                        "prices": {"price": "2499", "currency_minor_unit": 2},
                        "images": [],
                        "categories": [],
                        "is_in_stock": True,
                    }
                ],
                headers={"X-WP-Total": "1"},
            )
        return httpx.Response(200, json=[], headers={"X-WP-Total": "1"})

    client = PoliteClient(MANTIC_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = woo_strategy(
        mantic_descriptor(gtinFromJsonLd=False), client, {}, context(mantic_taxonomy(), budget=0)
    )

    assert result.observations[0].priceGbp == 24.99  # "2499" minor units, currency_minor_unit 2


def test_gtin_extraction_handles_at_graph_nesting_from_real_fixture() -> None:
    html = load_text_fixture("mantic-product-ldjson.html")
    assert _extract_gtin(html) == "9781911516675"


def test_gtin_extraction_falls_back_to_gtin13_and_flat_product_node() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Product", "name": "Flat Node", "gtin13": "1234567890123"}'
        "</script>"
    )
    assert _extract_gtin(html) == "1234567890123"


def test_gtin_extraction_returns_none_when_absent() -> None:
    assert _extract_gtin(NO_GTIN_HTML) is None


def test_gtin_extraction_skips_malformed_ldjson_block_and_finds_later_graph_product() -> None:
    """Real pages carry multiple ld+json blocks; one being malformed (e.g. a theme/plugin
    emitting broken JSON) must not abort extraction -- a later, valid block's @graph'd
    Product node must still be found."""
    html = (
        '<script type="application/ld+json">{not valid json,,,</script>'
        '<script type="application/ld+json">'
        '{"@context": "https://schema.org", "@graph": ['
        '{"@type": "WebPage", "name": "Some Page"},'
        '{"@type": "Product", "name": "Widget", "gtin": "9781911516675"}'
        "]}"
        "</script>"
    )
    assert _extract_gtin(html) == "9781911516675"


def two_known_products_page() -> list[dict]:
    return [
        {
            "id": 100,
            "name": "Alpha",
            "sku": "A1",
            "permalink": "https://www.manticgames.com/alpha/",
            "prices": {"price": "1000", "currency_minor_unit": 2, "currency_code": "GBP"},
            "images": [{"src": "https://example.test/alpha.jpg"}],
            "categories": [],
            "is_in_stock": True,
        },
        {
            "id": 200,
            "name": "Bravo",
            "sku": "B1",
            "permalink": "https://www.manticgames.com/bravo/",
            "prices": {"price": "2000", "currency_minor_unit": 2, "currency_code": "GBP"},
            "images": [{"src": "https://example.test/bravo.jpg"}],
            "categories": [],
            "is_in_stock": False,
        },
    ]


def test_budget_zero_upserts_bulk_only_observations_and_queues_all_missing_gtin_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "1":
            return httpx.Response(200, json=two_known_products_page(), headers={"X-WP-Total": "2"})
        return httpx.Response(200, json=[])

    client = PoliteClient(MANTIC_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = woo_strategy(mantic_descriptor(), client, {}, context(mantic_taxonomy(), budget=0))

    assert len(result.observations) == 2
    assert all(observation.ean is None for observation in result.observations)
    assert result.stats["details_fetched"] == 0
    assert result.cursor["pending_details"] == ["100", "200"]
    assert result.full_sweep is False


def test_para_bellum_never_fetches_details_even_without_a_budget_cap() -> None:
    calls: list[str] = []
    client = PoliteClient(PB_BASE, transport=para_bellum_fixture_transport(calls), sleep=lambda s: None)
    result = woo_strategy(para_bellum_descriptor(), client, {}, context(para_bellum_taxonomy()))

    assert result.stats["details_fetched"] == 0
    assert result.stats["gtins_found"] == 0
    assert all(observation.ean is None for observation in result.observations)
    assert result.cursor == {"gtin": {}, "pending_details": []}
    assert result.full_sweep is True

    by_key = {observation.key: observation for observation in result.observations}
    sorcerer_kings = by_key["mfr-para-bellum:18209"]
    assert sorcerer_kings.priceUsd == 26.99  # "2699" minor units / 10**2
    assert sorcerer_kings.manufacturer == "para-bellum"

    # only the two enumeration pages -- never a product permalink
    assert len(calls) == 2
    assert not any("/product/" in call for call in calls)


def test_unknown_manufacturer_scope_skips_everything() -> None:
    """No per-product vendor field exists in Woo's Store API (see woo.py's module docstring) --
    the analog of shopify's per-product unknown-vendor skip is an unresolvable
    scope.manufacturer, which must skip every enumerated product the same way."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "1":
            return httpx.Response(200, json=two_known_products_page(), headers={"X-WP-Total": "2"})
        return httpx.Response(200, json=[])

    client = PoliteClient(MANTIC_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = woo_strategy(
        mantic_descriptor(manufacturer="Totally Unknown Brand"),
        client,
        {},
        context(mantic_taxonomy(), budget=0),
    )

    assert result.observations == []
    assert result.stats["products_seen"] == 2
    assert result.stats["skipped_unknown_vendor"] == 2
    assert result.stats["details_fetched"] == 0
    assert result.full_sweep is True  # nothing kept means nothing pending either


def test_detail_fetch_error_on_one_product_does_not_abort_sweep_and_stays_pending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/wp-json/wc/store/products":
            if request.url.params.get("page") == "1":
                return httpx.Response(200, json=two_known_products_page(), headers={"X-WP-Total": "2"})
            return httpx.Response(200, json=[])
        if str(request.url) == "https://www.manticgames.com/alpha/":
            return httpx.Response(
                200,
                text='<script type="application/ld+json">'
                '{"@type": "Product", "gtin": "5000000000000"}</script>',
            )
        # bravo's detail fetch always fails (retried 3x by PoliteClient)
        return httpx.Response(500, text="down")

    client = PoliteClient(MANTIC_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = woo_strategy(mantic_descriptor(), client, {}, context(mantic_taxonomy()))

    by_key = {observation.key: observation for observation in result.observations}
    assert by_key["mfr-manticgames:100"].ean == "5000000000000"
    assert by_key["mfr-manticgames:200"].ean is None
    assert result.stats["detail_fetch_errors"] == 1
    assert result.stats["gtins_found"] == 1
    assert result.cursor["pending_details"] == ["200"]
    assert result.full_sweep is False


def test_second_run_with_known_gtin_never_refetches_it() -> None:
    """No staleness signal exists for Woo (see woo.py's module docstring): once a gtin is
    recorded in the cursor, it is never re-fetched on a later run."""
    cursor_with_known_gtin = {"gtin": {"100": "5000000000000"}, "pending_details": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/wp-json/wc/store/products":
            if request.url.params.get("page") == "1":
                return httpx.Response(200, json=two_known_products_page()[:1], headers={"X-WP-Total": "1"})
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.url}")

    client = PoliteClient(MANTIC_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = woo_strategy(mantic_descriptor(), client, cursor_with_known_gtin, context(mantic_taxonomy()))

    assert result.stats["details_fetched"] == 0
    assert result.observations[0].ean == "5000000000000"  # carried forward, not re-fetched
    assert result.cursor["gtin"] == {"100": "5000000000000"}
    assert result.full_sweep is True


def test_mapping_file_applies_category_hints_from_para_bellum_fixture() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "1":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "Sorcerer Kings Champion",
                        "sku": "PB1",
                        "permalink": "https://eshop.para-bellum.com/product/sorcerer-kings-champion/",
                        "prices": {"price": "1000", "currency_minor_unit": 2},
                        "images": [],
                        "categories": [
                            {"slug": "conquest"},
                            {"slug": "sorcerer-kings"},
                            {"slug": "factions"},
                        ],
                        "is_in_stock": True,
                    },
                    {
                        "id": 2,
                        "name": "Random Accessory",
                        "sku": "PB2",
                        "permalink": "https://eshop.para-bellum.com/product/random-accessory/",
                        "prices": {"price": "500", "currency_minor_unit": 2},
                        "images": [],
                        "categories": [{"slug": "accessories"}],
                        "is_in_stock": True,
                    },
                ],
                headers={"X-WP-Total": "2"},
            )
        return httpx.Response(200, json=[])

    client = PoliteClient(PB_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    mappings = {
        "mfr-para-bellum": {
            "gameSystem": {"conquest": "conquest"},
            "faction": {"sorcerer-kings": "sorcerer-kings"},
        }
    }
    result = woo_strategy(
        para_bellum_descriptor(), client, {}, context(para_bellum_taxonomy(), budget=0, mappings=mappings)
    )

    by_key = {observation.key: observation for observation in result.observations}
    assert by_key["mfr-para-bellum:1"].hints == {"gameSystem": "conquest", "faction": "sorcerer-kings"}
    assert by_key["mfr-para-bellum:2"].hints == {}
    # "Random Accessory" has non-empty categories with no match in either map -> +2
    assert result.stats["unmapped_hints"] == 2
