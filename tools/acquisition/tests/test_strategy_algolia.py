"""Algolia strategy (Games Workshop): POST-paginated search index full-sweep enumeration."""
import json
from pathlib import Path

import httpx
import pytest

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.algolia import (
    SEARCH_URL,
    _extract_gw_sku,
    _raw_faction,
    algolia_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy
from warhub_acquisition.yamlio import read_yaml

FIXTURES = Path(__file__).parent / "fixtures" / "algolia"
REPO_MAPPING = Path(__file__).resolve().parents[3] / "data" / "catalog" / "mappings" / "mfr-gw-algolia.yaml"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def gw_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "games-workshop": Manufacturer(
                slug="games-workshop",
                name="Games Workshop",
                codePattern=r"\d{11}",
                vendorNames=["Games Workshop", "Citadel", "Forge World"],
            )
        }
    )


def descriptor(**scope_overrides: object) -> SourceDescriptor:
    scope: dict[str, object] = {"manufacturer": "Games Workshop"}
    scope.update(scope_overrides)
    return SourceDescriptor(
        id="mfr-gw-algolia", kind="manufacturer", strategy="algolia", baseUrl="https://www.warhammer.com", scope=scope
    )


def context(taxonomy: Taxonomy, budget: int | None = None, mappings: dict | None = None) -> AcquireContext:
    return AcquireContext(taxonomy=taxonomy, mappings=mappings or {}, run_date="2026-07-13", budget=budget)


def real_gw_mapping() -> dict:
    return {"mfr-gw-algolia": read_yaml(REPO_MAPPING)}


def two_page_transport(
    page1_hits: list[dict], page1_nb_pages: int, calls: list[dict] | None = None
) -> httpx.MockTransport:
    """page 1 returns `page1_hits` with `nbPages=page1_nb_pages`; every further page returns an
    empty hits list (still with the same nbPages, matching a real Algolia response's shape)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if calls is not None:
            calls.append(body)
        assert request.method == "POST"
        assert str(request.url) == SEARCH_URL
        assert request.headers.get("x-algolia-application-id") == "M5ZIQZNQ2H"
        assert request.headers.get("x-algolia-api-key") == "92c6a8254f9d34362df8e6d96475e5d8"
        assert body["filters"] == "productType:miniatureKit"
        assert body["hitsPerPage"] == 100
        page = body["page"]
        if page == 0:
            return httpx.Response(200, json={"hits": page1_hits, "nbPages": page1_nb_pages, "page": 0})
        return httpx.Response(200, json={"hits": [], "nbPages": page1_nb_pages, "page": page})

    return httpx.MockTransport(handler)


def test_strategy_is_registered() -> None:
    assert STRATEGIES["algolia"] is algolia_strategy


def test_enumeration_from_real_fixture_produces_expected_fields() -> None:
    hits = load_fixture("gw-page.json")["hits"]
    calls: list[dict] = []
    client = PoliteClient(transport=two_page_transport(hits, 1, calls), base_url=None, sleep=lambda s: None)

    result = algolia_strategy(
        descriptor(), client, {}, context(gw_taxonomy(), mappings=real_gw_mapping())
    )

    assert result.stats["fetched_pages"] == 1  # nbPages=1 -> loop stops after page 0
    assert result.stats["products_seen"] == 3
    assert result.stats["skipped_unknown_vendor"] == 0
    assert result.stats["skipped_missing_name"] == 0
    assert result.stats["malformed_object_id"] == 0
    assert len(result.observations) == 3
    assert len(calls) == 1

    by_key = {observation.key: observation for observation in result.observations}

    baggage = by_key["mfr-gw-algolia:P-253194-99112799002"]
    assert baggage.name == "Baggage Train Carts"
    assert baggage.sku == "99112799002"  # last dash-segment of the objectID
    assert baggage.url == "https://www.warhammer.com/en-GB/shop/the-old-world-baggage-train-carts-2026-mto"
    assert baggage.priceGbp == 47.0
    assert baggage.imageUrl == (
        "https://www.warhammer.com/app/resources/catalog/product/920x950/"
        "99112799002_OldWorldMetalBaggageTrainCartsRepackagedDirectMTO2026.jpg"
    )
    assert baggage.availability == "in_stock"
    assert baggage.ean is None
    assert baggage.extractor == "algolia@1"
    assert baggage.manufacturer == "games-workshop"
    # lvl3[0] = "...Armies of the Old World > Beastman Brayherds > Beastmen Brayherds Chariots"
    # -> "Armies of the Old World" is skipped, "Beastman Brayherds" is the raw faction.
    assert baggage.hints == {"gameSystem": "the-old-world", "faction": "beastman-brayherds"}

    dragons = by_key["mfr-gw-algolia:P-253193-99062799001"]
    assert dragons.sku == "99062799001"
    # only lvl1 = ["The Old World > Armies of the Old World"] -- every segment after the game
    # system is skipped, so `_raw_faction` falls back to "General".
    assert dragons.hints == {"gameSystem": "the-old-world", "faction": "general"}

    ogre = by_key["mfr-gw-algolia:P-253190-99062709042"]
    assert ogre.sku == "99062709042"
    assert ogre.priceGbp == 18.75
    # lvl3[0] = "...Dwarfen Mountain Holds > Dwarfen Infantry" -> "Dwarfen Mountain Holds"
    assert ogre.hints == {"gameSystem": "the-old-world", "faction": "dwarfen-mountain-holds"}

    assert result.full_sweep is True
    assert result.cursor == {}


def test_pagination_via_page_and_nb_pages() -> None:
    """3 pages of 1 hit each (nbPages=3), then the loop stops once page reaches nbPages -- never
    relying on an empty hits list to terminate when nbPages says otherwise."""

    def hit(n: int) -> dict:
        return {
            "objectID": f"P-1-{n:011d}",
            "name": f"Widget {n}",
            "slug": f"widget-{n}",
            "sku": f"P-1-{n:011d}",
            "price": 10,
            "isInStock": True,
            "images": [],
        }

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        page = body["page"]
        if page < 3:
            return httpx.Response(200, json={"hits": [hit(page)], "nbPages": 3, "page": page})
        raise AssertionError(f"page {page} should never be requested (nbPages=3)")

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = algolia_strategy(descriptor(), client, {}, context(gw_taxonomy()))

    assert len(calls) == 3
    assert [c["page"] for c in calls] == [0, 1, 2]
    assert result.stats["fetched_pages"] == 3
    assert result.stats["products_seen"] == 3
    assert len(result.observations) == 3


def test_pagination_stops_early_on_empty_hits_page() -> None:
    """An empty hits page stops the loop even if nbPages claims more pages remain -- ported
    directly from AlgoliaProductSource.FetchProductsAsync's `if (response.Hits.Count == 0) break`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        page = body["page"]
        if page == 0:
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "objectID": "P-1-00000000001",
                            "name": "Only Item",
                            "slug": "only-item",
                            "price": 5,
                            "isInStock": True,
                            "images": [],
                        }
                    ],
                    "nbPages": 5,
                    "page": 0,
                },
            )
        return httpx.Response(200, json={"hits": [], "nbPages": 5, "page": page})

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = algolia_strategy(descriptor(), client, {}, context(gw_taxonomy()))

    assert result.stats["fetched_pages"] == 2  # page 0 (1 hit), page 1 (empty) -> stop
    assert result.stats["products_seen"] == 1


def test_sku_extraction_from_last_dash_segment() -> None:
    assert _extract_gw_sku("P-253194-99112799002") == "99112799002"
    assert _extract_gw_sku("prod5100348-60040199167") == "60040199167"


def test_sku_extraction_malformed_object_id_edge_cases_return_none() -> None:
    assert _extract_gw_sku("no-dash-at-the-end-") is None  # dash is the very last character
    assert _extract_gw_sku("-leadingdash") is None  # dash at position 0
    assert _extract_gw_sku("nodashatall") is None  # no dash at all
    assert _extract_gw_sku(None) is None
    assert _extract_gw_sku("") is None


def test_malformed_object_id_hit_is_kept_with_no_sku_and_counted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["page"] == 0:
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "objectID": "nodashatall",
                            "name": "Weird Item",
                            "slug": "weird-item",
                            "price": 9.99,
                            "isInStock": True,
                            "images": [],
                        }
                    ],
                    "nbPages": 1,
                    "page": 0,
                },
            )
        raise AssertionError("should not fetch a second page")

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = algolia_strategy(descriptor(), client, {}, context(gw_taxonomy()))

    assert len(result.observations) == 1
    assert result.observations[0].sku is None
    assert result.stats["malformed_object_id"] == 1


def test_hit_with_no_name_is_skipped_and_counted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["page"] == 0:
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {"objectID": "P-1-00000000001", "name": "", "slug": "blank-name", "price": 1, "images": []},
                        {
                            "objectID": "P-1-00000000002",
                            "name": "Real Item",
                            "slug": "real-item",
                            "price": 2,
                            "isInStock": True,
                            "images": [],
                        },
                    ],
                    "nbPages": 1,
                    "page": 0,
                },
            )
        raise AssertionError("should not fetch a second page")

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = algolia_strategy(descriptor(), client, {}, context(gw_taxonomy()))

    assert result.stats["products_seen"] == 2  # both hits are seen/counted...
    assert len(result.observations) == 1  # ...but only 1 becomes an observation
    assert result.stats["skipped_missing_name"] == 1
    assert result.observations[0].name == "Real Item"


def test_unknown_manufacturer_scope_skips_everything() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["page"] == 0:
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "objectID": "P-1-00000000001",
                            "name": "Item",
                            "slug": "item",
                            "price": 1,
                            "isInStock": True,
                            "images": [],
                        }
                    ],
                    "nbPages": 1,
                    "page": 0,
                },
            )
        raise AssertionError("should not fetch a second page")

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = algolia_strategy(
        descriptor(manufacturer="Totally Unknown Brand"), client, {}, context(gw_taxonomy())
    )

    assert result.observations == []
    assert result.stats["products_seen"] == 1
    assert result.stats["skipped_unknown_vendor"] == 1
    assert result.full_sweep is True


def test_no_ean_invariant_holds_even_when_price_and_hierarchy_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["page"] == 0:
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {"objectID": "P-1-00000000009", "name": "Bare Item"},
                    ],
                    "nbPages": 1,
                    "page": 0,
                },
            )
        raise AssertionError("should not fetch a second page")

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = algolia_strategy(descriptor(), client, {}, context(gw_taxonomy()))

    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.ean is None
    assert observation.priceGbp is None
    assert observation.url is None
    assert observation.imageUrl is None
    assert observation.availability is None
    assert observation.hints == {}


def test_mapping_unmapped_game_system_and_faction_are_counted_not_guessed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["page"] == 0:
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "objectID": "P-1-00000000001",
                            "name": "Mystery Game Item",
                            "slug": "mystery",
                            "price": 1,
                            "isInStock": True,
                            "images": [],
                            "GameSystemsRoot": {
                                "lvl0": ["Some New Game"],
                                "lvl1": ["Some New Game > Some New Faction"],
                            },
                        }
                    ],
                    "nbPages": 1,
                    "page": 0,
                },
            )
        raise AssertionError("should not fetch a second page")

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    mappings = {"mfr-gw-algolia": {"gameSystem": {"Warhammer 40,000": "warhammer-40k"}, "faction": {}}}
    result = algolia_strategy(descriptor(), client, {}, context(gw_taxonomy(), mappings=mappings))

    assert result.observations[0].hints == {}
    assert result.stats["unmapped_hints"] == 2  # unmapped gameSystem + unmapped faction


def test_raw_faction_skips_generic_segments_and_falls_back_to_general() -> None:
    skip_terms = {"unit type", "armies of the old world"}
    assert (
        _raw_faction(
            "The Old World > Armies of the Old World > Beastman Brayherds > Chariots", skip_terms
        )
        == "Beastman Brayherds"
    )
    assert _raw_faction("The Old World > Armies of the Old World", skip_terms) == "General"


def test_context_budget_is_ignored() -> None:
    """Per the task brief: no detail fetches, no budget consumption -- a small budget must not
    truncate enumeration or observations at all."""
    hits = load_fixture("gw-page.json")["hits"]
    client = PoliteClient(transport=two_page_transport(hits, 1), base_url=None, sleep=lambda s: None)
    result = algolia_strategy(descriptor(), client, {}, context(gw_taxonomy(), budget=0))

    assert len(result.observations) == 3
    assert result.full_sweep is True
