"""Algolia strategy (Games Workshop): two-phase per-game-system facet sweep enumeration."""
import json
from pathlib import Path

import httpx

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.algolia import (
    GAME_SYSTEM_FACET,
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


_DERIVE_FACETS = object()  # sentinel: sliced_transport derives facet counts from `slices`


def sliced_transport(
    slices: dict[str, list[list[dict]]],
    nb_hits: int = 0,
    calls: list[dict] | None = None,
    slice_nb_hits: dict[str, int] | None = None,
    facets: dict | None | object = _DERIVE_FACETS,
) -> httpx.MockTransport:
    """Mock the two-phase flow. `slices` maps each game-system facet value to its list of hit
    PAGES (`nbPages` per slice = number of pages given). The facet-discovery response's facet
    counts default to each slice's total hit count; pass `facets=None` to omit the `facets` key
    entirely (the shape-drift case), or a dict to control the response's facet key order. Every
    request's method/URL/auth headers/filters and phase-appropriate body shape are asserted here,
    so EVERY test exercises the POST contract."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if calls is not None:
            calls.append(body)
        assert request.method == "POST"
        assert str(request.url) == SEARCH_URL
        assert request.headers.get("x-algolia-application-id") == "M5ZIQZNQ2H"
        assert request.headers.get("x-algolia-api-key") == "92c6a8254f9d34362df8e6d96475e5d8"
        assert body["filters"] == "productType:miniatureKit"
        assert body["query"] == ""

        if "facets" in body:
            # Phase 1: facet discovery.
            assert body["hitsPerPage"] == 0
            assert body["facets"] == [GAME_SYSTEM_FACET]
            response: dict = {"hits": [], "nbHits": nb_hits, "page": 0, "nbPages": 0}
            if facets is not None:
                facet_counts = (
                    {gs: sum(len(p) for p in pages) for gs, pages in slices.items()}
                    if facets is _DERIVE_FACETS
                    else facets
                )
                response["facets"] = {GAME_SYSTEM_FACET: facet_counts}
            return httpx.Response(200, json=response)

        # Phase 2: a per-game-system slice page.
        assert body["hitsPerPage"] == 100
        facet_filters = body["facetFilters"]
        assert isinstance(facet_filters, list) and len(facet_filters) == 1
        assert len(facet_filters[0]) == 1
        prefix = f"{GAME_SYSTEM_FACET}:"
        assert facet_filters[0][0].startswith(prefix)
        game_system = facet_filters[0][0][len(prefix):]
        assert game_system in slices, f"unexpected game-system slice requested: {game_system!r}"
        pages = slices[game_system]
        page = body["page"]
        page_hits = pages[page] if page < len(pages) else []
        this_slice_nb_hits = (slice_nb_hits or {}).get(game_system, sum(len(p) for p in pages))
        return httpx.Response(
            200,
            json={"hits": page_hits, "nbHits": this_slice_nb_hits, "page": page, "nbPages": len(pages)},
        )

    return httpx.MockTransport(handler)


def make_client(transport: httpx.MockTransport) -> PoliteClient:
    return PoliteClient(base_url=None, transport=transport, sleep=lambda s: None)


def simple_hit(object_id: str, name: str, game_system: str | None = None, **extra: object) -> dict:
    hit: dict = {
        "objectID": object_id,
        "name": name,
        "slug": name.lower().replace(" ", "-") if name else "no-name",
        "price": 10,
        "isInStock": True,
        "images": [],
    }
    if game_system:
        hit["GameSystemsRoot"] = {"lvl0": [game_system]}
    hit.update(extra)
    return hit


def test_strategy_is_registered() -> None:
    assert STRATEGIES["algolia"] is algolia_strategy


def test_facet_discovery_request_shape_and_reported_nbhits() -> None:
    """The FIRST request must be the facet-discovery query (port of GetGameSystemCountsAsync):
    hitsPerPage=0, facets=["GameSystemsRoot.lvl0"], same filters -- and its nbHits is recorded as
    the reported_nbhits honesty stat."""
    calls: list[dict] = []
    transport = sliced_transport(
        {"The Old World": [[simple_hit("P-1-00000000001", "Item")]]}, nb_hits=2856, calls=calls
    )
    result = algolia_strategy(descriptor(), make_client(transport), {}, context(gw_taxonomy()))

    first = calls[0]
    assert first["hitsPerPage"] == 0
    assert first["facets"] == [GAME_SYSTEM_FACET]
    assert "facetFilters" not in first
    assert result.stats["reported_nbhits"] == 2856
    # every subsequent request is a facet-filtered slice page, never another unfiltered sweep
    assert calls[1:]
    assert all("facetFilters" in call for call in calls[1:])


def test_enumeration_from_real_fixture_produces_expected_fields() -> None:
    hits = load_fixture("gw-page.json")["hits"]
    calls: list[dict] = []
    transport = sliced_transport({"The Old World": [hits]}, nb_hits=2856, calls=calls)

    result = algolia_strategy(
        descriptor(), make_client(transport), {}, context(gw_taxonomy(), mappings=real_gw_mapping())
    )

    assert result.stats["fetched_pages"] == 2  # 1 facet discovery + 1 slice page (nbPages=1)
    assert result.stats["products_seen"] == 3
    assert result.stats["reported_nbhits"] == 2856
    assert result.stats["skipped_unknown_vendor"] == 0
    assert result.stats["skipped_missing_name"] == 0
    assert result.stats["malformed_object_id"] == 0
    assert result.stats["cross_slice_duplicates"] == 0
    assert result.stats["slices_over_pagination_cap"] == 0
    assert result.stats["missing_game_system_facets"] == 0
    assert len(result.observations) == 3
    assert len(calls) == 2
    assert calls[1]["facetFilters"] == [["GameSystemsRoot.lvl0:The Old World"]]

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


def test_per_slice_facet_filters_and_pagination_via_nb_pages() -> None:
    """Each game system gets its own facet-filtered paginated sweep: pages 0..nbPages-1 requested
    with the slice's facetFilters, stopping at page >= nbPages -- never relying on an empty page
    when nbPages says the slice is done."""
    slices = {
        "Age of Sigmar": [
            [simple_hit("P-1-00000000001", "AoS One")],
            [simple_hit("P-1-00000000002", "AoS Two")],
        ],
        "Warhammer 40,000": [
            [simple_hit("P-1-00000000003", "40k One")],
        ],
    }
    calls: list[dict] = []
    result = algolia_strategy(
        descriptor(), make_client(sliced_transport(slices, nb_hits=3, calls=calls)), {}, context(gw_taxonomy())
    )

    assert result.stats["fetched_pages"] == 4  # 1 facet + 2 AoS pages + 1 40k page
    assert result.stats["products_seen"] == 3
    assert len(result.observations) == 3
    # exact request sequence: facet discovery, then slices in sorted order, pages ascending
    assert "facets" in calls[0]
    assert [c["facetFilters"][0][0] for c in calls[1:]] == [
        "GameSystemsRoot.lvl0:Age of Sigmar",
        "GameSystemsRoot.lvl0:Age of Sigmar",
        "GameSystemsRoot.lvl0:Warhammer 40,000",
    ]
    assert [c["page"] for c in calls[1:]] == [0, 1, 0]


def test_slice_pagination_stops_early_on_empty_hits_page() -> None:
    """An empty hits page ends a slice even if nbPages claims more remain -- ported directly from
    AlgoliaProductSource.FetchProductsAsync's `if (response.Hits.Count == 0) break`."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "facets" in body:
            return httpx.Response(
                200,
                json={"hits": [], "nbHits": 1, "nbPages": 0, "facets": {GAME_SYSTEM_FACET: {"The Old World": 1}}},
            )
        page = body["page"]
        if page == 0:
            return httpx.Response(
                200,
                json={"hits": [simple_hit("P-1-00000000001", "Only Item")], "nbHits": 1, "nbPages": 5, "page": 0},
            )
        assert page == 1, f"page {page} should never be requested after the empty page 1"
        return httpx.Response(200, json={"hits": [], "nbHits": 1, "nbPages": 5, "page": page})

    result = algolia_strategy(
        descriptor(), make_client(httpx.MockTransport(handler)), {}, context(gw_taxonomy())
    )

    assert result.stats["fetched_pages"] == 3  # facet + page 0 (1 hit) + page 1 (empty) -> stop
    assert result.stats["products_seen"] == 1


def test_cross_slice_duplicate_object_ids_deduped_first_slice_wins() -> None:
    """A product carrying two lvl0 values shows up in both slices: the first slice (sorted
    game-system order) wins, the duplicate is counted, and only one observation is emitted."""
    shared_from_aos = simple_hit("P-1-00000000007", "Shared Starter Set", game_system="Age of Sigmar")
    shared_from_40k = simple_hit("P-1-00000000007", "Shared Starter Set", game_system="Warhammer 40,000")
    slices = {
        "Age of Sigmar": [[shared_from_aos]],
        "Warhammer 40,000": [[shared_from_40k, simple_hit("P-1-00000000008", "40k Only Item")]],
    }
    mappings = {
        "mfr-gw-algolia": {
            "gameSystem": {"Age of Sigmar": "age-of-sigmar", "Warhammer 40,000": "warhammer-40k"},
            "faction": {},
        }
    }
    result = algolia_strategy(
        descriptor(),
        make_client(sliced_transport(slices, nb_hits=2)),
        {},
        context(gw_taxonomy(), mappings=mappings),
    )

    assert result.stats["cross_slice_duplicates"] == 1
    assert result.stats["products_seen"] == 2
    assert len(result.observations) == 2
    by_key = {observation.key: observation for observation in result.observations}
    # "Age of Sigmar" sorts before "Warhammer 40,000", so the AoS slice's copy won the dedupe:
    assert by_key["mfr-gw-algolia:P-1-00000000007"].hints == {"gameSystem": "age-of-sigmar"}


def test_game_systems_swept_in_sorted_order_regardless_of_facet_response_order() -> None:
    """The facet response's own key order is count/relevance-based and unstable across runs --
    slices must be visited in SORTED order so first-slice-wins dedupe is deterministic."""
    slices = {
        "Zeta Game": [[simple_hit("P-1-00000000001", "Zeta Item")]],
        "Alpha Game": [[simple_hit("P-1-00000000002", "Alpha Item")]],
        "Middle-Earth": [[simple_hit("P-1-00000000003", "ME Item")]],
    }
    # facet response deliberately lists them in NON-sorted (count-descending-like) order
    unsorted_facets = {"Zeta Game": 900, "Middle-Earth": 500, "Alpha Game": 100}
    calls: list[dict] = []
    algolia_strategy(
        descriptor(),
        make_client(sliced_transport(slices, nb_hits=3, calls=calls, facets=unsorted_facets)),
        {},
        context(gw_taxonomy()),
    )

    assert [c["facetFilters"][0][0] for c in calls[1:]] == [
        "GameSystemsRoot.lvl0:Alpha Game",
        "GameSystemsRoot.lvl0:Middle-Earth",
        "GameSystemsRoot.lvl0:Zeta Game",
    ]


def test_missing_facets_returns_empty_result_with_stat_for_contract_to_catch() -> None:
    """A facet response with no usable GameSystemsRoot.lvl0 facets (index shape drift) must not
    raise here: it returns an empty result + stat, and the descriptor's minCount contract fires
    loudly downstream (run_source checks contracts before any evidence write)."""
    calls: list[dict] = []
    transport = sliced_transport({}, nb_hits=2856, calls=calls, facets=None)  # no `facets` key at all
    result = algolia_strategy(descriptor(), make_client(transport), {}, context(gw_taxonomy()))

    assert result.observations == []
    assert result.stats["missing_game_system_facets"] == 1
    assert result.stats["fetched_pages"] == 1  # only the facet-discovery request, no slices
    assert result.stats["products_seen"] == 0
    assert result.stats["reported_nbhits"] == 2856  # still recorded for the health report
    assert result.full_sweep is True  # so the minCount contract actually applies
    assert len(calls) == 1


def test_slice_nbhits_over_pagination_cap_is_counted_not_silent() -> None:
    """If a single slice's own nbHits exceeds Algolia's ~1000 pagination cap, the shortfall must
    be visible in stats (single-level slicing is the faithful port of the .NET tool -- we accept
    the truncation but never hide it)."""
    slices = {
        "Warhammer 40,000": [[simple_hit("P-1-00000000001", "40k Item")]],
        "Age of Sigmar": [[simple_hit("P-1-00000000002", "AoS Item")]],
    }
    result = algolia_strategy(
        descriptor(),
        make_client(sliced_transport(slices, nb_hits=2600, slice_nb_hits={"Warhammer 40,000": 2500})),
        {},
        context(gw_taxonomy()),
    )

    assert result.stats["slices_over_pagination_cap"] == 1  # only the 40k slice tripped it
    assert len(result.observations) == 2  # counting never drops the hits that WERE returned


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
    slices = {"The Old World": [[simple_hit("nodashatall", "Weird Item")]]}
    result = algolia_strategy(
        descriptor(), make_client(sliced_transport(slices, nb_hits=1)), {}, context(gw_taxonomy())
    )

    assert len(result.observations) == 1
    assert result.observations[0].sku is None
    assert result.stats["malformed_object_id"] == 1


def test_hit_with_no_name_is_skipped_and_counted() -> None:
    slices = {
        "The Old World": [
            [
                simple_hit("P-1-00000000001", ""),  # blank name -> dropped, counted
                simple_hit("P-1-00000000002", "Real Item"),
            ]
        ]
    }
    result = algolia_strategy(
        descriptor(), make_client(sliced_transport(slices, nb_hits=2)), {}, context(gw_taxonomy())
    )

    assert result.stats["products_seen"] == 2  # both hits are seen/counted...
    assert len(result.observations) == 1  # ...but only 1 becomes an observation
    assert result.stats["skipped_missing_name"] == 1
    assert result.observations[0].name == "Real Item"


def test_unknown_manufacturer_scope_skips_everything() -> None:
    slices = {"The Old World": [[simple_hit("P-1-00000000001", "Item")]]}
    result = algolia_strategy(
        descriptor(manufacturer="Totally Unknown Brand"),
        make_client(sliced_transport(slices, nb_hits=1)),
        {},
        context(gw_taxonomy()),
    )

    assert result.observations == []
    assert result.stats["products_seen"] == 1
    assert result.stats["skipped_unknown_vendor"] == 1
    assert result.full_sweep is True


def test_no_ean_invariant_holds_even_when_price_and_hierarchy_absent() -> None:
    bare_hit = {"objectID": "P-1-00000000009", "name": "Bare Item"}
    slices = {"The Old World": [[bare_hit]]}
    result = algolia_strategy(
        descriptor(), make_client(sliced_transport(slices, nb_hits=1)), {}, context(gw_taxonomy())
    )

    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.ean is None
    assert observation.priceGbp is None
    assert observation.url is None
    assert observation.imageUrl is None
    assert observation.availability is None
    assert observation.hints == {}


def test_mapping_unmapped_game_system_and_faction_are_counted_not_guessed() -> None:
    hit = simple_hit("P-1-00000000001", "Mystery Game Item")
    hit["GameSystemsRoot"] = {
        "lvl0": ["Some New Game"],
        "lvl1": ["Some New Game > Some New Faction"],
    }
    slices = {"Some New Game": [[hit]]}
    mappings = {"mfr-gw-algolia": {"gameSystem": {"Warhammer 40,000": "warhammer-40k"}, "faction": {}}}
    result = algolia_strategy(
        descriptor(),
        make_client(sliced_transport(slices, nb_hits=1)),
        {},
        context(gw_taxonomy(), mappings=mappings),
    )

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
    transport = sliced_transport({"The Old World": [hits]}, nb_hits=2856)
    result = algolia_strategy(descriptor(), make_client(transport), {}, context(gw_taxonomy(), budget=0))

    assert len(result.observations) == 3
    assert result.full_sweep is True
