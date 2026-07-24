"""WP REST paints strategy (Vallejo): category filter, slug codes, media cache."""
import json
from pathlib import Path

import httpx

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.wp_rest_paints import (
    _slug_code,
    wp_rest_paints_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "wp_rest_paints"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def vallejo_taxonomy() -> Taxonomy:
    return Taxonomy(
        {"vallejo": Manufacturer(slug="vallejo", name="Vallejo", vendorNames=["Vallejo"])}
    )


def descriptor(**extra_scope: object) -> SourceDescriptor:
    return SourceDescriptor(
        id="mfr-vallejo",
        kind="manufacturer",
        strategy="wp-rest-paints",
        baseUrl="https://acrylicosvallejo.com",
        scope={
            "manufacturer": "Vallejo",
            "apiBase": "/en/wp-json/wp/v2",
            "includeCategorySlugs": ["game-color-en", "auxiliary-products-hobby"],
            **extra_scope,
        },
    )


def context(budget: int | None = None) -> AcquireContext:
    return AcquireContext(
        taxonomy=vallejo_taxonomy(), mappings={}, run_date="2026-07-23", budget=budget
    )


def transport(calls: list[str] | None = None) -> httpx.MockTransport:
    """Real captured Vallejo REST fixtures: 4 product_cat terms, 3 products (Dead White 72001
    in game-color-en; an airbrush nozzle in airbrushes-en, filtered; a code-less auxiliary),
    and the media lookup resolving Dead White's real featured image."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        page = request.url.params.get("page")
        if path == "/en/wp-json/wp/v2/product_cat":
            payload = load_fixture("vallejo-cats-page1.json") if page == "1" else []
            return httpx.Response(200, json=payload)
        if path == "/en/wp-json/wp/v2/product":
            payload = load_fixture("vallejo-products-page1.json") if page == "1" else []
            return httpx.Response(200, json=payload)
        if path == "/en/wp-json/wp/v2/media":
            assert request.url.params.get("include") == "45661"
            return httpx.Response(200, json=load_fixture("vallejo-media.json"))
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def run(budget: int | None = None, cursor: dict | None = None, calls: list[str] | None = None):
    client = PoliteClient(
        "https://acrylicosvallejo.com", transport=transport(calls), sleep=lambda s: None
    )
    return wp_rest_paints_strategy(descriptor(), client, cursor or {}, context(budget))


def test_strategy_is_registered() -> None:
    assert STRATEGIES["wp-rest-paints"] is wp_rest_paints_strategy


def test_slug_code_extraction() -> None:
    assert _slug_code("dead-white-72001") == "72001"
    assert _slug_code("primer-73601-2") == "73601"  # WP slug de-dup suffix tolerated
    assert _slug_code("nozzle-0-2-set-90011") == "90011"
    assert _slug_code("metal-medium-en") is None
    assert _slug_code("") is None


def test_category_filter_and_observation_shape() -> None:
    result = run()
    keys = [obs.key for obs in result.observations]
    assert "mfr-vallejo:dead-white-72001" in keys
    assert "mfr-vallejo:metal-medium-en" in keys
    assert not any("nozzle" in key for key in keys)  # airbrushes-en filtered
    assert result.stats["skipped_category"] == 1

    dead_white = next(o for o in result.observations if "dead-white" in o.key)
    assert dead_white.name == "Dead White"
    assert dead_white.sku == "72001"
    assert dead_white.manufacturer == "vallejo"
    assert dead_white.imageUrl.endswith("vallejo-game-color-72001-1.jpg")
    assert dead_white.hints["categorySlugs"] == ["game-color-en", "hobby"]
    assert dead_white.url.endswith("/dead-white-72001/")

    aux = next(o for o in result.observations if "metal-medium" in o.key)
    assert aux.sku is None  # no trailing code on the slug
    assert aux.name == "Metal Medium – Auxiliary"  # entities unescaped
    assert result.stats["code_missing"] == 1


def test_full_sweep_true_and_media_cached_in_cursor() -> None:
    result = run()
    assert result.full_sweep is True
    assert result.cursor["media"]["45661"].endswith("72001-1.jpg")

    # Second run with the returned cursor: no /media request at all.
    calls: list[str] = []
    second = run(cursor=result.cursor, calls=calls)
    assert not any("/media" in url for url in calls)
    dead_white = next(o for o in second.observations if "dead-white" in o.key)
    assert dead_white.imageUrl.endswith("72001-1.jpg")


def test_budget_zero_skips_media_but_still_observes_products() -> None:
    result = run(budget=0)
    assert result.stats["media_batches"] == 0
    dead_white = next(o for o in result.observations if "dead-white" in o.key)
    assert dead_white.imageUrl is None
    assert result.full_sweep is True  # unresolved images never block the sweep claim
