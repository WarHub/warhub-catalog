"""AppSync strategy (Corvus Belli): GraphQL `listProducts` full-sweep across 3 game systems."""
import json
from pathlib import Path

import httpx

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.appsync import (
    API_KEY,
    GAME_SYSTEMS,
    GRAPHQL_ENDPOINT,
    _extract_faction,
    _parse_int_field,
    _status,
    appsync_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy
from warhub_acquisition.yamlio import read_yaml

FIXTURES = Path(__file__).parent / "fixtures" / "appsync"
REPO_MAPPING = Path(__file__).resolve().parents[3] / "data" / "catalog" / "mappings" / "mfr-corvus-belli.yaml"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def cb_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "corvus-belli": Manufacturer(
                slug="corvus-belli",
                name="Corvus Belli",
                codePattern=r"\d{6}",
                vendorNames=["Corvus Belli"],
            )
        }
    )


def descriptor(**scope_overrides: object) -> SourceDescriptor:
    scope: dict[str, object] = {"manufacturer": "Corvus Belli"}
    scope.update(scope_overrides)
    return SourceDescriptor(
        id="mfr-corvus-belli",
        kind="manufacturer",
        strategy="appsync",
        baseUrl="https://store.corvusbelli.com",
        scope=scope,
    )


def context(taxonomy: Taxonomy, budget: int | None = None, mappings: dict | None = None) -> AcquireContext:
    return AcquireContext(taxonomy=taxonomy, mappings=mappings or {}, run_date="2026-07-13", budget=budget)


def real_cb_mapping() -> dict:
    return {"mfr-corvus-belli": read_yaml(REPO_MAPPING)}


def multi_game_transport(
    products_by_game: dict[str, list[dict]], calls: list[dict] | None = None
) -> httpx.MockTransport:
    """Each `api_game` key in `products_by_game` returns its products on page 1 with `pages: 1`
    (so the loop stops after one page); any of the 3 real GAME_SYSTEMS api_game values NOT present
    in the dict returns an empty page-1 result (`pages: 0`) -- both cases only ever issue ONE
    request per game system, so a second request for any game system is a bug."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if calls is not None:
            calls.append(body)
        assert request.method == "POST"
        assert str(request.url) == GRAPHQL_ENDPOINT
        assert request.headers.get("x-api-key") == API_KEY
        variables = body["variables"]
        assert variables["lang"] == "en"
        assert variables["filters"] == []
        api_game = variables["category"]["game"]
        page = variables["page"]
        if page != 1:
            raise AssertionError(f"page {page} should never be requested for {api_game!r} (pages<=1)")
        products = products_by_game.get(api_game, [])
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": {
                        "products": products,
                        "pages": 1 if products else 0,
                        "currentPage": 1,
                        "total": len(products),
                    }
                }
            },
        )

    return httpx.MockTransport(handler)


def test_strategy_is_registered() -> None:
    assert STRATEGIES["appsync"] is appsync_strategy


def test_game_systems_scope_covers_infinity_warcrow_aristeia() -> None:
    assert GAME_SYSTEMS == [
        ("infinity", "wargames", "Infinity"),
        ("warcrow", "wargames", "Warcrow"),
        ("aristeia", "boardgames", "Aristeia!"),
    ]


def test_all_three_game_systems_are_queried_even_when_empty() -> None:
    calls: list[dict] = []
    client = PoliteClient(transport=multi_game_transport({}, calls), base_url=None, sleep=lambda s: None)
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy()))

    assert len(calls) == 3
    queried_games = {call["variables"]["category"]["game"] for call in calls}
    assert queried_games == {"infinity", "warcrow", "aristeia"}
    assert result.observations == []
    assert result.stats["fetched_pages"] == 3
    assert result.full_sweep is True
    assert result.cursor == {}


def test_enumeration_from_real_fixture_produces_expected_fields() -> None:
    products = load_fixture("cb-infinity-page.json")["products"]
    calls: list[dict] = []
    client = PoliteClient(
        transport=multi_game_transport({"infinity": products}, calls), base_url=None, sleep=lambda s: None
    )

    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy(), mappings=real_cb_mapping()))

    assert len(calls) == 3  # infinity + warcrow + aristeia, one request each
    assert result.stats["fetched_pages"] == 3
    assert result.stats["products_seen"] == 3
    assert result.stats["skipped_unknown_vendor"] == 0
    assert result.stats["skipped_missing_name"] == 0
    assert result.stats["skipped_missing_identifier"] == 0
    assert result.stats["unmapped_hints"] == 0
    assert len(result.observations) == 3

    by_key = {observation.key: observation for observation in result.observations}

    phalanx = by_key["mfr-corvus-belli:infinity:steel-phalanx-action-pack"]
    assert phalanx.name == "Steel Phalanx Action Pack"
    assert phalanx.sku == "280888-1149"  # RAW reference, dash suffix intact (fix wave 1)
    assert phalanx.url == "https://store.corvusbelli.com/en/wargames/infinity/steel-phalanx-action-pack"
    assert phalanx.priceEur == 92.5
    assert phalanx.imageUrl == "https://store.corvusbelli.com/media/catalog/product/steel-phalanx-action-pack.png"
    assert phalanx.availability == "current"  # outstock=false, preorder=null
    assert phalanx.ean is None
    assert phalanx.extractor == "appsync@1"
    assert phalanx.manufacturer == "corvus-belli"
    # seo[0] = "ALEPH Steel Phalanx Sectorial Pack" -- contains the "ALEPH" candidate.
    assert phalanx.hints == {"gameSystem": "infinity", "faction": "aleph"}

    death_song = by_key["mfr-corvus-belli:infinity:death-song"]
    assert death_song.name == "Death Song  "  # trailing whitespace preserved -- NOT trimmed
    assert death_song.sku == "WHP-005"  # raw reference, kept verbatim (books have no \d{6} REF)
    assert death_song.priceEur == 19.0
    assert death_song.availability == "out_of_stock"  # outstock=true
    # No Infinity faction candidate appears in seo or name -- no faction hint, and NOT counted
    # as unmapped (nothing was extracted to be unmapped).
    assert death_song.hints == {"gameSystem": "infinity"}

    bases = by_key["mfr-corvus-belli:infinity:55mm-scenery-bases-epsilon-series"]
    assert bases.sku == "285090-1092"
    assert bases.priceEur == 13.5
    assert bases.availability == "current"
    assert bases.hints == {"gameSystem": "infinity"}

    assert result.full_sweep is True
    assert result.cursor == {}


def test_shared_ref_stem_products_keep_distinct_full_skus() -> None:
    """Regression (review fix wave 1): the dash suffix in `reference` is identity-bearing. Real
    committed data (`data/catalog/products/corvus-belli.yaml`) has two UNRELATED products sharing
    the 6-digit stem 280034 -- `betrayal-characters-pack` (280034-0837) and `operation-kaldstrom`
    (280034-0878). An earlier revision truncated both to "280034", which resolve's code-based
    identity join would have merged into one corrupted entity. Both must emerge as separate
    observations carrying their exact, full, untruncated references as sku."""
    products = [
        {
            "shortname": "Betrayal Characters Pack",
            "reference": "280034-0837",
            "slug": "betrayal-characters-pack",
            "price": 30.0,
        },
        {
            "shortname": "Operation Kaldstrom",
            "reference": "280034-0878",
            "slug": "operation-kaldstrom",
            "price": 89.95,
        },
    ]
    client = PoliteClient(
        transport=multi_game_transport({"infinity": products}), base_url=None, sleep=lambda s: None
    )
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy()))

    assert len(result.observations) == 2  # never merged locally
    skus = {observation.key: observation.sku for observation in result.observations}
    assert skus == {
        "mfr-corvus-belli:infinity:betrayal-characters-pack": "280034-0837",
        "mfr-corvus-belli:infinity:operation-kaldstrom": "280034-0878",
    }


def test_status_mapping() -> None:
    assert _status({"preorder": None, "outstock": False}) == "current"
    assert _status({"preorder": None, "outstock": True}) == "out_of_stock"
    assert _status({"preorder": {"from": "2026-01-01"}, "outstock": False}) == "pre_order"
    assert _status({"preorder": {}, "outstock": True}) == "pre_order"  # preorder wins over outstock


def test_extract_faction_seo_priority_over_name_and_order() -> None:
    candidates = ["PanOceania", "Yu Jing", "ALEPH"]
    # seo[0] contains "ALEPH" -- wins even though "Yu Jing" would also match a later seo entry.
    assert _extract_faction(["ALEPH Steel Phalanx", "Yu Jing Invincible Army"], "Widget", candidates) == "ALEPH"
    # No seo match at all -- falls back to scanning name.
    assert _extract_faction(["nothing relevant"], "Yu Jing Invincible Army", candidates) == "Yu Jing"
    assert _extract_faction(None, "Yu Jing Invincible Army", candidates) == "Yu Jing"
    assert _extract_faction([], "no faction here", candidates) is None
    assert _extract_faction(None, "no faction here", []) is None  # Aristeia!: empty candidates


def test_parse_int_field() -> None:
    assert _parse_int_field(24.0) == 24  # real evidence: `pages` arrives as a float
    assert _parse_int_field(1) == 1
    assert _parse_int_field("5") == 5
    assert _parse_int_field(None) is None
    assert _parse_int_field("not-a-number") is None
    assert _parse_int_field(True) is None  # bool is an int subclass -- must not silently pass


def test_pagination_within_one_game_system_re_reads_pages_every_response() -> None:
    """Port fidelity: `page <= totalPages`, re-reading `totalPages` from EVERY response (not just
    the first) -- 2 pages of 1 product each (pages=2), then the loop stops once page(3) > pages(2).
    """

    def product(n: int) -> dict:
        return {"shortname": f"Widget {n}", "reference": f"28000{n}", "slug": f"widget-{n}", "price": 10}

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        variables = body["variables"]
        if variables["category"]["game"] != "infinity":
            return httpx.Response(
                200, json={"data": {"products": {"products": [], "pages": 0, "currentPage": 1, "total": 0}}}
            )
        page = variables["page"]
        if page in (1, 2):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "products": {"products": [product(page)], "pages": 2, "currentPage": page, "total": 2}
                    }
                },
            )
        raise AssertionError(f"page {page} should never be requested (pages=2)")

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy()))

    infinity_calls = [c for c in calls if c["variables"]["category"]["game"] == "infinity"]
    assert [c["variables"]["page"] for c in infinity_calls] == [1, 2]
    assert result.stats["products_seen"] == 2
    assert len(result.observations) == 2


def test_pagination_stops_early_on_empty_products_page() -> None:
    """An empty `products` page stops that game system's loop even if `pages` claims more remain
    -- ported directly from the .NET source's `if (productList?.Products is null || Count == 0)
    break`."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        if variables["category"]["game"] != "infinity":
            return httpx.Response(
                200, json={"data": {"products": {"products": [], "pages": 0, "currentPage": 1, "total": 0}}}
            )
        page = variables["page"]
        if page == 1:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "products": {
                            "products": [
                                {"shortname": "Only Item", "reference": "280001", "slug": "only-item", "price": 5}
                            ],
                            "pages": 5,
                            "currentPage": 1,
                            "total": 1,
                        }
                    }
                },
            )
        return httpx.Response(
            200, json={"data": {"products": {"products": [], "pages": 5, "currentPage": page, "total": 1}}}
        )

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy()))

    assert result.stats["products_seen"] == 1
    assert len(result.observations) == 1


def test_reference_is_kept_verbatim_trim_only() -> None:
    """sku = raw reference, unparsed (fix wave 1: `Sku = product.Reference` in the .NET source,
    trim at most) -- non-\\d{6} formats like book codes pass through verbatim (taxonomy's
    codePattern fullmatch handles code-identity downstream); whitespace-only becomes None."""
    products = [
        {"shortname": "Weird Item", "reference": "  not-a-ref ", "slug": "weird-item", "price": 9.99},
        {"shortname": "Blank Ref Item", "reference": "   ", "slug": "blank-ref-item", "price": 1.0},
    ]
    client = PoliteClient(
        transport=multi_game_transport({"infinity": products}), base_url=None, sleep=lambda s: None
    )
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy()))

    assert len(result.observations) == 2
    skus = {observation.key: observation.sku for observation in result.observations}
    assert skus == {
        "mfr-corvus-belli:infinity:weird-item": "not-a-ref",
        "mfr-corvus-belli:infinity:blank-ref-item": None,
    }
    assert "malformed_reference" not in result.stats  # bookkeeping removed with the parser


def test_product_with_no_name_is_skipped_and_counted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        if variables["category"]["game"] != "infinity" or variables["page"] != 1:
            return httpx.Response(
                200, json={"data": {"products": {"products": [], "pages": 0, "currentPage": 1, "total": 0}}}
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": {
                        "products": [
                            {"shortname": "", "reference": "280001", "slug": "blank-name", "price": 1},
                            {"shortname": "Real Item", "reference": "280002", "slug": "real-item", "price": 2},
                        ],
                        "pages": 1,
                        "currentPage": 1,
                        "total": 2,
                    }
                }
            },
        )

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy()))

    assert result.stats["products_seen"] == 2  # both seen/counted...
    assert len(result.observations) == 1  # ...but only 1 becomes an observation
    assert result.stats["skipped_missing_name"] == 1
    assert result.observations[0].name == "Real Item"


def test_unknown_manufacturer_scope_skips_everything() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        if variables["category"]["game"] != "infinity" or variables["page"] != 1:
            return httpx.Response(
                200, json={"data": {"products": {"products": [], "pages": 0, "currentPage": 1, "total": 0}}}
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": {
                        "products": [{"shortname": "Item", "reference": "280001", "slug": "item", "price": 1}],
                        "pages": 1,
                        "currentPage": 1,
                        "total": 1,
                    }
                }
            },
        )

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = appsync_strategy(
        descriptor(manufacturer="Totally Unknown Brand"), client, {}, context(cb_taxonomy())
    )

    assert result.observations == []
    assert result.stats["products_seen"] == 1
    assert result.stats["skipped_unknown_vendor"] == 1
    assert result.full_sweep is True


def test_no_ean_invariant_holds_even_when_price_and_seo_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        if variables["category"]["game"] != "infinity" or variables["page"] != 1:
            return httpx.Response(
                200, json={"data": {"products": {"products": [], "pages": 0, "currentPage": 1, "total": 0}}}
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": {
                        "products": [{"shortname": "Bare Item", "reference": None, "slug": "bare-item"}],
                        "pages": 1,
                        "currentPage": 1,
                        "total": 1,
                    }
                }
            },
        )

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy()))

    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.ean is None
    assert observation.priceEur is None
    assert observation.imageUrl is None
    assert observation.sku is None
    assert observation.availability == "current"


def test_mapping_unmapped_game_system_and_faction_are_counted_not_guessed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        if variables["category"]["game"] != "warcrow" or variables["page"] != 1:
            return httpx.Response(
                200, json={"data": {"products": {"products": [], "pages": 0, "currentPage": 1, "total": 0}}}
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": {
                        "products": [
                            {
                                "shortname": "Mystery Warband",
                                "reference": "290001",
                                "slug": "mystery-warband",
                                "price": 20,
                                "seo": ["Northern Tribes Warband"],
                            }
                        ],
                        "pages": 1,
                        "currentPage": 1,
                        "total": 1,
                    }
                }
            },
        )

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    mappings = {
        "mfr-corvus-belli": {
            "gameSystem": {"Infinity": "infinity"},  # deliberately missing "Warcrow"
            "factionCandidatesByGameSystem": {"Warcrow": ["Northern Tribes"]},
            "faction": {},  # deliberately no slug for "Northern Tribes"
        }
    }
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy(), mappings=mappings))

    assert result.observations[0].hints == {}
    assert result.stats["unmapped_hints"] == 2  # unmapped gameSystem + unmapped faction


def test_aristeia_never_produces_a_faction_hint_or_unmapped_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        if variables["category"]["game"] != "aristeia" or variables["page"] != 1:
            return httpx.Response(
                200, json={"data": {"products": {"products": [], "pages": 0, "currentPage": 1, "total": 0}}}
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": {
                        "products": [
                            {
                                "shortname": "Aristeia Character",
                                "reference": "300001",
                                "slug": "aristeia-character",
                                "price": 15,
                                "seo": ["PanOceania themed but Aristeia has no factions"],
                            }
                        ],
                        "pages": 1,
                        "currentPage": 1,
                        "total": 1,
                    }
                }
            },
        )

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy(), mappings=real_cb_mapping()))

    assert result.observations[0].hints == {"gameSystem": "aristeia"}
    assert result.stats["unmapped_hints"] == 0


def test_context_budget_is_ignored() -> None:
    """Per the task brief: no detail fetches, no budget consumption -- a small budget must not
    truncate enumeration or observations at all."""
    products = load_fixture("cb-infinity-page.json")["products"]
    client = PoliteClient(
        transport=multi_game_transport({"infinity": products}), base_url=None, sleep=lambda s: None
    )
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy(), budget=0))

    assert len(result.observations) == 3
    assert result.full_sweep is True


def test_deterministic_sorted_emission_across_game_systems() -> None:
    def make(game: str, page: int) -> dict:
        if page != 1:
            return {"data": {"products": {"products": [], "pages": 0, "currentPage": 1, "total": 0}}}
        products_by_game = {
            "infinity": [{"shortname": "Z Infinity Item", "reference": "280009", "slug": "z-item", "price": 1}],
            "warcrow": [{"shortname": "A Warcrow Item", "reference": "290009", "slug": "a-item", "price": 1}],
            "aristeia": [{"shortname": "M Aristeia Item", "reference": "300009", "slug": "m-item", "price": 1}],
        }
        return {
            "data": {
                "products": {
                    "products": products_by_game.get(game, []),
                    "pages": 1,
                    "currentPage": 1,
                    "total": 1,
                }
            }
        }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        return httpx.Response(200, json=make(variables["category"]["game"], variables["page"]))

    client = PoliteClient(transport=httpx.MockTransport(handler), base_url=None, sleep=lambda s: None)
    result = appsync_strategy(descriptor(), client, {}, context(cb_taxonomy()))

    keys = [observation.key for observation in result.observations]
    assert keys == sorted(keys)
    assert keys == [
        "mfr-corvus-belli:aristeia:m-item",
        "mfr-corvus-belli:infinity:z-item",
        "mfr-corvus-belli:warcrow:a-item",
    ]


def test_repo_mapping_slugs_are_all_known_taxonomy_slugs() -> None:
    """Sanity check mirroring test_repo_data.py's repo-wide invariant, scoped to this file: every
    mapped gameSystem/faction slug in the real committed mapping must exist in taxonomy labels."""
    mapping = read_yaml(REPO_MAPPING)
    game_systems = {"infinity", "warcrow", "aristeia"}
    factions = {"panoceania", "yu-jing", "ariadna", "haqqislam", "nomads", "combined-army", "aleph", "o-12"}
    for raw, slug in mapping["gameSystem"].items():
        assert slug in game_systems, f"gameSystem[{raw!r}] -> {slug!r} unexpected"
    for raw, slug in mapping["faction"].items():
        assert slug in factions, f"faction[{raw!r}] -> {slug!r} unexpected"
