"""Woo paints strategy (AK Interactive): category sweeps, lang param, EUR prices, dedupe."""
import json
from pathlib import Path

import httpx

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.woo_paints import woo_paints_strategy
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "woo_paints"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def ak_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "ak-interactive": Manufacturer(
                slug="ak-interactive", name="AK Interactive", vendorNames=["AK Interactive"]
            )
        }
    )


def descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="mfr-ak-interactive",
        kind="manufacturer",
        strategy="woo-paints",
        baseUrl="https://ak-interactive.com",
        scope={
            "manufacturer": "AK Interactive",
            "extraParams": {"lang": "en"},
            "categories": ["paints-acrylics", "quick-gen"],
        },
    )


def context() -> AcquireContext:
    return AcquireContext(taxonomy=ak_taxonomy(), mappings={}, run_date="2026-07-23", budget=None)


def transport(calls: list[httpx.URL] | None = None) -> httpx.MockTransport:
    """Real captured AK Store API fixtures. paints-acrylics page1 -> [AK11001 single,
    AK11787 set], quick-gen page1 -> [AK11787 set] (overlapping id, exercises dedupe)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.url)
        assert request.url.path == "/wp-json/wc/store/products"
        assert request.url.params.get("lang") == "en"  # extraParams reach every request
        category = request.url.params.get("category")
        page = request.url.params.get("page")
        if category == "paints-acrylics":
            payload = load_fixture("ak-paints-page1.json") if page == "1" else []
        elif category == "quick-gen":
            payload = load_fixture("ak-quick-page1.json") if page == "1" else []
        else:
            raise AssertionError(f"unexpected category: {category}")
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def run(calls: list[httpx.URL] | None = None):
    client = PoliteClient(
        "https://ak-interactive.com", transport=transport(calls), sleep=lambda s: None
    )
    return woo_paints_strategy(descriptor(), client, {}, context())


def test_strategy_is_registered() -> None:
    assert STRATEGIES["woo-paints"] is woo_paints_strategy


def test_category_sweeps_dedupe_by_product_id() -> None:
    result = run()
    assert result.stats["categories_swept"] == 2
    assert result.stats["products_seen"] == 2  # AK11787 appears in both categories, kept once
    keys = sorted(obs.key for obs in result.observations)
    assert keys == ["mfr-ak-interactive:107107", "mfr-ak-interactive:704678"]


def test_observation_shape_eur_price_and_category_hints() -> None:
    result = run()
    single = next(o for o in result.observations if o.key.endswith(":107107"))
    assert single.sku == "AK11001"
    assert single.name == "WHITE – INTENSE"  # &#8211; unescaped
    assert single.priceEur == 2.27  # 227 minor units, currency_code EUR from the payload
    assert single.manufacturer == "ak-interactive"
    assert single.hints["category"] == "paint"
    assert "3rd-acrylics" in single.hints["categorySlugs"]
    assert single.availability == "in_stock"
    assert single.imageUrl


def test_full_sweep_claimed_within_declared_scope() -> None:
    result = run()
    assert result.full_sweep is True
    assert result.cursor == {}
