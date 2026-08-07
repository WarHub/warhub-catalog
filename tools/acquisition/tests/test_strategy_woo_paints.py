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


def test_short_description_is_captured_verbatim() -> None:
    """AK's Store API returns `short_description` in the SAME payload the sweep already fetches --
    zero extra requests -- and it is the ONLY route by which AK's 256 boxed-set rows ever say what
    is in them (they carry no contents array, and every one of their observations today has hint
    keys exactly {category, categorySlugs}).

    VERBATIM, byte for byte: not unescaped, not tag-stripped, not sliced to the English half. The
    field is a bilingual accordion and keeping only English would save ~59% of the bytes -- and
    would be acquire-time classification, so the day that slice is wrong it costs a re-fetch
    instead of a `warhub-data resolve` run. resolve/set_refs.py makes the cut once, late.
    """
    result = run()
    fixture = {item["sku"]: item for item in load_fixture("ak-quick-page1.json")}
    boxed_set = next(o for o in result.observations if o.key.endswith(":704678"))
    assert boxed_set.hints["description"] == fixture["AK11787"]["short_description"]
    assert "ESPA" in boxed_set.hints["description"]  # the Spanish half is kept, uncut
    assert boxed_set.hints["description"].startswith('<span class="collapseomatic ')


def test_a_captured_description_carries_the_boxed_sets_membership() -> None:
    """End to end on a REAL captured payload: AK11787 "Sun & Shade Tone Collection" states 14
    colours in prose and nowhere else. This is the whole point of the capture, so it is asserted
    against the parser rather than left to be inferred from the two halves passing separately."""
    from warhub_acquisition.resolve.set_refs import content_skus_from_description

    result = run()
    boxed_set = next(o for o in result.observations if o.key.endswith(":704678"))
    refs = content_skus_from_description(boxed_set.hints["description"])
    assert refs == [
        "AK11001", "AK11029", "AK11040", "AK11051", "AK11064", "AK11087", "AK11103",
        "AK11109", "AK11112", "AK11113", "AK11121", "AK11124", "AK11151", "AK11156",
    ]
    # ...and the single pot in the same sweep states no membership at all, so capturing the field
    # on every row does not turn 999 singles into 999 one-item sets.
    single = next(o for o in result.observations if o.key.endswith(":107107"))
    assert content_skus_from_description(single.hints["description"]) is None
