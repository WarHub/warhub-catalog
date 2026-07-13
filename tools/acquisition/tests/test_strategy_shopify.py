"""Shopify strategy: bulk enumeration + budgeted per-handle barcode detail fetch."""
import json
from pathlib import Path

import httpx
import pytest

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.shopify import shopify_strategy
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "shopify"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def warlord_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "warlord-games": Manufacturer(
                slug="warlord-games", name="Warlord Games", vendorNames=["Warlord Games"]
            )
        }
    )


def descriptor(**scope: object) -> SourceDescriptor:
    return SourceDescriptor(
        id="mfr-warlord-store",
        kind="manufacturer",
        strategy="shopify",
        baseUrl="https://store.warlordgames.com",
        scope=scope,
    )


def context(taxonomy: Taxonomy, budget: int | None = None, mappings: dict | None = None) -> AcquireContext:
    return AcquireContext(
        taxonomy=taxonomy, mappings=mappings or {}, run_date="2026-07-13", budget=budget
    )


def fixture_transport(calls: list[str] | None = None) -> httpx.MockTransport:
    """Routes the captured real fixtures by URL: bulk page1 -> real 2 products (1 known-vendor
    Warlord Games, 1 unknown-vendor Micro Art Studio), page2 -> empty, detail -> real barcode."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        if path == "/products.json":
            page = request.url.params.get("page")
            if page == "1":
                return httpx.Response(200, json=load_fixture("warlord-bulk-page1.json"))
            if page == "2":
                return httpx.Response(200, json=load_fixture("warlord-bulk-page2.json"))
            raise AssertionError(f"unexpected page requested: {page}")
        if path == "/products/p40-medium-tank.js":
            return httpx.Response(200, json=load_fixture("warlord-detail.js.json"))
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def test_strategy_is_registered() -> None:
    assert STRATEGIES["shopify"] is shopify_strategy


def test_enumeration_and_detail_fetch_produces_ean_from_fixture() -> None:
    calls: list[str] = []
    client = PoliteClient(
        "https://store.warlordgames.com",
        transport=fixture_transport(calls),
        sleep=lambda s: None,
    )
    result = shopify_strategy(descriptor(currency="gbp"), client, {}, context(warlord_taxonomy()))

    assert result.stats["fetched_pages"] == 2
    assert result.stats["products_seen"] == 2
    assert result.stats["skipped_unknown_vendor"] == 1  # Micro Art Studio has no taxonomy entry
    assert result.stats["details_fetched"] == 1
    assert result.stats["barcodes_found"] == 1
    assert result.stats["detail_fetch_errors"] == 0

    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.key == "mfr-warlord-store:p40-medium-tank"
    assert observation.manufacturer == "warlord-games"
    assert observation.name == "P40 medium tank"
    assert observation.sku == "402615803"
    assert observation.ean == "5060917997751"  # the real barcode captured live
    assert observation.priceGbp == pytest.approx(35.50)
    assert observation.url == "https://store.warlordgames.com/products/p40-medium-tank"
    assert observation.imageUrl == (
        "https://cdn.shopify.com/s/files/1/0255/0949/4864/files/402615803_P40mediumtank01.jpg?v=1782916102"
    )
    assert observation.availability == "in_stock"
    assert observation.extractor == "shopify@1"

    assert result.full_sweep is True  # enumeration complete, nothing left pending
    assert result.cursor["pending_details"] == []
    assert result.cursor["updated_at"]["p40-medium-tank"]["ean"] == "5060917997751"
    assert result.cursor["updated_at"]["p40-medium-tank"]["updatedAt"] == "2026-07-13T03:10:32+01:00"

    # exactly 3 requests: page1, page2, one detail fetch (no request for the unknown-vendor product)
    assert len(calls) == 3


def test_unknown_vendor_is_skipped_and_counted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "1":
            return httpx.Response(
                200,
                json={
                    "products": [
                        {
                            "id": 1,
                            "handle": "mystery-item",
                            "title": "Mystery Item",
                            "vendor": "Totally Unknown Brand",
                            "product_type": "",
                            "tags": [],
                            "updated_at": "2026-07-01T00:00:00+00:00",
                            "variants": [{"sku": "X1", "price": "9.99"}],
                            "images": [],
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"products": []})

    client = PoliteClient(
        "https://store.warlordgames.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    result = shopify_strategy(descriptor(), client, {}, context(warlord_taxonomy()))

    assert result.observations == []
    assert result.stats["skipped_unknown_vendor"] == 1
    assert result.stats["details_fetched"] == 0
    assert result.full_sweep is True  # nothing kept means nothing pending either


def two_known_products_page() -> dict:
    return {
        "products": [
            {
                "id": 1,
                "handle": "alpha",
                "title": "Alpha",
                "vendor": "Warlord Games",
                "product_type": "Bolt Action",
                "tags": ["infantry"],
                "updated_at": "2026-07-01T00:00:00+00:00",
                "variants": [{"sku": "A1", "price": "10.00", "available": True}],
                "images": [{"src": "https://example.test/alpha.jpg"}],
            },
            {
                "id": 2,
                "handle": "bravo",
                "title": "Bravo",
                "vendor": "Warlord Games",
                "product_type": "Bolt Action",
                "tags": ["vehicle"],
                "updated_at": "2026-07-02T00:00:00+00:00",
                "variants": [{"sku": "B1", "price": "20.00", "available": False}],
                "images": [{"src": "https://example.test/bravo.jpg"}],
            },
        ]
    }


def test_budget_zero_upserts_bulk_only_observations_and_queues_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "1":
            return httpx.Response(200, json=two_known_products_page())
        return httpx.Response(200, json={"products": []})

    client = PoliteClient(
        "https://store.warlordgames.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    result = shopify_strategy(descriptor(), client, {}, context(warlord_taxonomy(), budget=0))

    assert len(result.observations) == 2
    assert all(observation.ean is None for observation in result.observations)
    assert result.stats["details_fetched"] == 0
    assert result.cursor["pending_details"] == ["alpha", "bravo"]
    assert result.full_sweep is False


def test_second_run_with_unchanged_updated_at_and_existing_ean_skips_detail_fetch() -> None:
    first_calls: list[str] = []
    client1 = PoliteClient(
        "https://store.warlordgames.com", transport=fixture_transport(first_calls), sleep=lambda s: None
    )
    first_result = shopify_strategy(descriptor(), client1, {}, context(warlord_taxonomy()))
    assert first_result.cursor["updated_at"]["p40-medium-tank"]["ean"] == "5060917997751"

    second_calls: list[str] = []
    client2 = PoliteClient(
        "https://store.warlordgames.com", transport=fixture_transport(second_calls), sleep=lambda s: None
    )
    second_result = shopify_strategy(
        descriptor(), client2, first_result.cursor, context(warlord_taxonomy())
    )

    # only the two enumeration pages -- no detail fetch, since updated_at is unchanged and an
    # ean is already recorded in the cursor.
    assert len(second_calls) == 2
    assert not any("p40-medium-tank.js" in call for call in second_calls)
    assert second_result.stats["details_fetched"] == 0

    observation = second_result.observations[0]
    assert observation.ean == "5060917997751"  # carried forward from cursor, not re-fetched
    assert second_result.full_sweep is True


def test_mapping_file_applies_game_system_hint_and_counts_unmapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "1":
            return httpx.Response(
                200,
                json={
                    "products": [
                        {
                            "id": 1,
                            "handle": "mapped-item",
                            "title": "Mapped Item",
                            "vendor": "Warlord Games",
                            "product_type": "Bolt Action",
                            "tags": [],
                            "updated_at": "2026-07-01T00:00:00+00:00",
                            "variants": [{"sku": "M1", "price": "5.00"}],
                            "images": [],
                        },
                        {
                            "id": 2,
                            "handle": "unmapped-item",
                            "title": "Unmapped Item",
                            "vendor": "Warlord Games",
                            "product_type": "Some New Game System",
                            "tags": [],
                            "updated_at": "2026-07-01T00:00:00+00:00",
                            "variants": [{"sku": "M2", "price": "5.00"}],
                            "images": [],
                        },
                    ]
                },
            )
        return httpx.Response(200, json={"products": []})

    client = PoliteClient(
        "https://store.warlordgames.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    mappings = {"mfr-warlord-store": {"gameSystem": {"Bolt Action": "bolt-action"}, "faction": {}}}
    result = shopify_strategy(
        descriptor(), client, {}, context(warlord_taxonomy(), budget=0, mappings=mappings)
    )

    by_handle = {obs.key.split(":", 1)[1]: obs for obs in result.observations}
    assert by_handle["mapped-item"].hints == {"gameSystem": "bolt-action"}
    assert by_handle["unmapped-item"].hints == {}
    assert result.stats["unmapped_hints"] == 1  # only "Some New Game System" is unmapped


def test_stale_bulk_updated_at_triggers_refresh_despite_existing_ean() -> None:
    """A product that already has a cursor-recorded ean still gets re-fetched when the bulk
    updated_at is newer than what's recorded -- and the refreshed ean wins."""
    stale_cursor = {
        "updated_at": {
            "p40-medium-tank": {"updatedAt": "2020-01-01T00:00:00+00:00", "ean": "0000000000000"}
        },
        "pending_details": [],
    }
    calls: list[str] = []
    client = PoliteClient(
        "https://store.warlordgames.com", transport=fixture_transport(calls), sleep=lambda s: None
    )
    result = shopify_strategy(descriptor(), client, stale_cursor, context(warlord_taxonomy()))

    assert result.stats["details_fetched"] == 1  # staleness alone triggers a re-fetch
    assert result.stats["barcodes_found"] == 1
    observation = result.observations[0]
    assert observation.ean == "5060917997751"  # freshly re-fetched, not the stale cursor value
    assert result.cursor["updated_at"]["p40-medium-tank"]["ean"] == "5060917997751"
    assert result.cursor["updated_at"]["p40-medium-tank"]["updatedAt"] == "2026-07-13T03:10:32+01:00"
    assert result.full_sweep is True


def test_detail_fetch_error_does_not_abort_sweep_and_stays_pending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/products.json":
            if request.url.params.get("page") == "1":
                return httpx.Response(
                    200,
                    json={
                        "products": [
                            {
                                "id": 1,
                                "handle": "flaky",
                                "title": "Flaky",
                                "vendor": "Warlord Games",
                                "product_type": "",
                                "tags": [],
                                "updated_at": "2026-07-01T00:00:00+00:00",
                                "variants": [{"sku": "F1", "price": "1.00"}],
                                "images": [],
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"products": []})
        # every detail fetch attempt (retried 3x by PoliteClient) fails
        return httpx.Response(500, text="down")

    client = PoliteClient(
        "https://store.warlordgames.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    result = shopify_strategy(descriptor(), client, {}, context(warlord_taxonomy()))

    assert len(result.observations) == 1
    assert result.observations[0].ean is None
    assert result.stats["detail_fetch_errors"] == 1
    assert result.stats["barcodes_found"] == 0
    assert result.cursor["pending_details"] == ["flaky"]
    assert result.full_sweep is False


def test_detail_fetch_error_on_stale_refresh_preserves_previously_known_ean() -> None:
    """A transient failure while refreshing an already-known ean must not wipe it: the candidate
    observation keeps serving the last-known-good ean, and the handle stays queued for retry."""
    stale_cursor = {
        "updated_at": {"flaky": {"updatedAt": "2020-01-01T00:00:00+00:00", "ean": "1111111111111"}},
        "pending_details": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/products.json":
            if request.url.params.get("page") == "1":
                return httpx.Response(
                    200,
                    json={
                        "products": [
                            {
                                "id": 1,
                                "handle": "flaky",
                                "title": "Flaky",
                                "vendor": "Warlord Games",
                                "product_type": "",
                                "tags": [],
                                "updated_at": "2026-07-01T00:00:00+00:00",  # newer -> stale, re-queued
                                "variants": [{"sku": "F1", "price": "1.00"}],
                                "images": [],
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"products": []})
        return httpx.Response(500, text="down")

    client = PoliteClient(
        "https://store.warlordgames.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    result = shopify_strategy(descriptor(), client, stale_cursor, context(warlord_taxonomy()))

    assert result.stats["detail_fetch_errors"] == 1
    assert result.observations[0].ean == "1111111111111"  # preserved through the transient failure
    assert result.cursor["updated_at"]["flaky"]["ean"] == "1111111111111"
    assert result.cursor["pending_details"] == ["flaky"]  # still queued for a future retry
    assert result.full_sweep is False
