"""GW webstore paints: Algolia roster, buildId discovery, budgeted _next/data detail, sizes."""
import json
from pathlib import Path

import httpx

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.algolia import SEARCH_URL
from warhub_acquisition.acquire.strategies.gw_webstore_paints import (
    DETAIL_MISS_CAP,
    _discover_build_id,
    _pim_key,
    _volume_from_features,
    _volume_from_image,
    gw_webstore_paints_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "gw_webstore_paints"

BASE = "https://www.warhammer.com"
# The buildId embedded in the captured 404 fixture; the strategy must discover it, never pin it.
BUILD_ID = "FkRJ2asXFO158O5rLtXr6"

# The six fixture paints are one per parse branch, captured live 2026-08-01:
#   Technical-Nihilakh-Oxide-2019  features 12ml; image's LEADING code (99189956122) is NOT the
#                                  pimKey (99189956061) -- the trap this source must not fall in
#   Chaos-Black-Spray-UK-ROW-2020  features "Can size: 400ml"; SVG tile with no size in the name
#   Dry-Dawnstone-2019             no size in features OR image (all 23 Dry paints are like this)
#   Layer-Pink-Horror-2019         no features size; image uses "-12ml-" hyphen delimiters
#   Base-Abaddon-Black-2019        features 12ml AND image "_12ML_ALT" (trailing-underscore form)
#   shade-kroak-green-18ml-2022    GW ships this name double-spaced ("Shade:  Kroak Green")
NIHILAKH = "99189956061"
SPRAY = "99209999090"
DAWNSTONE = "99189952063"
PINK_HORROR = "99189951365"
ABADDON = "99189950289"
KROAK = "99189953041"


def load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def gw_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "games-workshop": Manufacturer(
                slug="games-workshop",
                name="Games Workshop",
                codePattern=r"\d{11}",
                vendorNames=["Games Workshop", "Citadel"],
            )
        }
    )


def descriptor(**scope_overrides: object) -> SourceDescriptor:
    scope: dict[str, object] = {"manufacturer": "Games Workshop"}
    scope.update(scope_overrides)
    return SourceDescriptor(
        id="mfr-gw-webstore-paints",
        kind="manufacturer",
        strategy="gw-webstore-paints",
        baseUrl=BASE,
        scope=scope,
    )


def context(taxonomy: Taxonomy | None = None, budget: int | None = None) -> AcquireContext:
    return AcquireContext(
        taxonomy=taxonomy or gw_taxonomy(), mappings={}, run_date="2026-08-01", budget=budget
    )


def transport(
    calls: list[str] | None = None,
    detail_404: set[str] | None = None,
    build_id_broken: bool = False,
    drift_details: bool = False,
) -> httpx.MockTransport:
    """Algolia POST -> the trimmed roster page; `_next/data` GET -> per-slug detail fixture.

    `build_id_broken` serves a 404 body with no buildId in it (the shape-drift case);
    `drift_details` serves a product payload with no attributes (the parse-miss case).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(f"{request.method} {request.url}")
        if str(request.url) == SEARCH_URL:
            return httpx.Response(200, json=load_json("roster-page.json"))
        path = request.url.path
        if path.startswith("/_next/data/"):
            _, _, _, build_id, _, _, leaf = path.split("/", 6)
            slug = leaf.removesuffix(".json")
            if slug == "_":
                # The deliberate bad-buildId probe: Next.js's own 404 page, which embeds the
                # live buildId. Any OTHER buildId here would mean the strategy pinned one.
                assert build_id == "0", f"probe must use the invalid sentinel, got {build_id!r}"
                body = "<html><head></head><body>404</body></html>" if build_id_broken else (
                    (FIXTURES / "build-id-404.html").read_text(encoding="utf-8")
                )
                return httpx.Response(404, text=body)
            assert build_id == BUILD_ID, f"detail fetched with stale buildId {build_id!r}"
            if detail_404 is not None and slug in detail_404:
                return httpx.Response(404, text="not found")
            if drift_details:
                return httpx.Response(200, json={"pageProps": {}})
            return httpx.Response(200, json=load_json(f"detail-{slug}.json"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.MockTransport(handler)


def run(
    budget: int | None = None,
    cursor: dict | None = None,
    calls: list[str] | None = None,
    taxonomy: Taxonomy | None = None,
    **transport_kwargs: object,
):
    client = PoliteClient(
        BASE, transport=transport(calls, **transport_kwargs), sleep=lambda s: None  # type: ignore[arg-type]
    )
    return gw_webstore_paints_strategy(
        descriptor(), client, cursor or {}, context(taxonomy, budget)
    )


def observation(result, pim_key: str):
    return next(o for o in result.observations if o.key == f"mfr-gw-webstore-paints:{pim_key}")


def test_strategy_is_registered() -> None:
    assert STRATEGIES["gw-webstore-paints"] is gw_webstore_paints_strategy


# --- unit: the two size readers and the product-code reader ---------------------------------


def test_pim_key_is_the_trailing_eleven_digit_segment() -> None:
    assert _pim_key("prod4210388-99189956061") == "99189956061"
    # Guard the shape: a short/long trailing run is not a GW product code, and returning it
    # anyway would put a junk join key into evidence.
    assert _pim_key("prod4210388-9918995606") is None
    assert _pim_key("prod4210388") is None
    assert _pim_key(None) is None


def test_volume_from_image_reads_every_delimiter_form_gw_ships() -> None:
    base = "/app/resources/catalog/product/920x950/"
    assert _volume_from_image(f"{base}99189956122_x_TECHNICAL_NIHILAKH_OXIDE_12ML.jpg") == 12
    assert _volume_from_image(f"{base}99189950289_x_BASE_ABADDON_BLACK_12ML_ALT.jpg") == 12
    assert _volume_from_image(f"{base}99189951365_x_LAYER-12ml-Pink-Horror-v2.jpg") == 12
    assert _volume_from_image(f"{base}99189960262_x_CONTRAST_NIGHTHAUNT_GLOOM_18ML.jpg") == 18


def test_volume_from_image_ignores_the_directory_dimensions_and_sizeless_tiles() -> None:
    # "/920x950/" is the CDN render size and must never be read as a volume -- hence basename-only.
    assert _volume_from_image("/app/resources/catalog/product/920x950/dryDawnstone.svg") is None
    assert _volume_from_image("/app/resources/catalog/product/920x950/sprayChaosBlack.svg") is None
    assert _volume_from_image(None) is None


def test_volume_from_features_reads_both_labels_gw_uses() -> None:
    assert _volume_from_features([{"en-GB": "Pot size: 12ml"}]) == 12
    assert _volume_from_features([{"en-GB": "Can size: 400ml"}]) == 400
    assert _volume_from_features([{"en-GB": "Water-based formula"}]) is None
    assert _volume_from_features(None) is None


# --- buildId discovery ----------------------------------------------------------------------


def test_build_id_is_discovered_from_the_404_body_of_an_invalid_build_id() -> None:
    client = PoliteClient(BASE, transport=transport(), sleep=lambda s: None)
    assert _discover_build_id(client, BASE) == BUILD_ID


def test_build_id_probe_is_one_request_and_details_use_what_it_returned() -> None:
    calls: list[str] = []
    run(calls=calls)
    probes = [c for c in calls if "/_next/data/0/" in c]
    assert len(probes) == 1, probes
    # The transport asserts every detail carries BUILD_ID, so reaching here proves the discovered
    # id was threaded through rather than a pinned constant.
    assert all(f"/_next/data/{BUILD_ID}/" in c for c in calls if "/shop/" in c and "/0/" not in c)


def test_unreadable_build_id_degrades_to_roster_only_instead_of_failing() -> None:
    result = run(build_id_broken=True)
    assert result.stats["build_id_discovery_failed"] == 1
    assert result.stats["details_fetched"] == 0
    # Every paint is still observed, and the image-derived sizes still land.
    assert len(result.observations) == 6
    assert observation(result, NIHILAKH).hints["volumeMl"] == 12
    assert observation(result, NIHILAKH).hints["volumeSource"] == "image"
    # The detail work is not lost -- it stays queued for the next run.
    assert set(result.cursor["pending_details"])
    assert result.full_sweep is False


# --- roster -> observations -------------------------------------------------------------------


def test_every_roster_paint_becomes_an_observation_keyed_by_gw_product_code() -> None:
    result = run()
    assert result.stats["products_seen"] == 6
    assert result.stats["reported_nbhits"] == 331  # GW's own population count for the facet
    assert {o.sku for o in result.observations} == {
        NIHILAKH, SPRAY, DAWNSTONE, PINK_HORROR, ABADDON, KROAK
    }
    assert all(o.key == f"mfr-gw-webstore-paints:{o.sku}" for o in result.observations)
    assert all(o.manufacturer == "games-workshop" for o in result.observations)
    assert all(o.hints["category"] == "paint" for o in result.observations)
    assert all(o.extractor == "gw-webstore-paints@1" for o in result.observations)


def test_product_code_is_gws_pim_key_not_the_image_filenames_leading_code() -> None:
    # The Nihilakh Oxide tile is 99189956122_..., but GW's product code is 99189956061. Reading
    # the image would produce a code that joins to nothing in mfr-gw-trade.
    nihilakh = observation(result_cache(), NIHILAKH)
    assert nihilakh.sku == "99189956061"
    assert "99189956122" in (nihilakh.imageUrl or "")


def test_observation_carries_range_colour_price_image_and_url() -> None:
    nihilakh = observation(result_cache(), NIHILAKH)
    assert nihilakh.name == "Technical: Nihilakh Oxide"
    assert nihilakh.hints["line"] == "Technical"
    assert nihilakh.hints["colourRange"] == "Green"
    assert nihilakh.priceGbp == 2.75
    assert nihilakh.url == f"{BASE}/en-GB/shop/Technical-Nihilakh-Oxide-2019"
    assert nihilakh.imageUrl.startswith(f"{BASE}/app/resources/catalog/product/")
    # Same reader as mfr-gw-algolia -- two sources over one index must not disagree on the word.
    assert nihilakh.availability == "in_stock"


def test_double_spaced_gw_name_is_collapsed() -> None:
    # GW ships "Shade:  Kroak Green"; the paint catalog has it single-spaced, so an uncollapsed
    # name would fail to join for no reason.
    assert observation(result_cache(), KROAK).name == "Shade: Kroak Green"


def test_index_and_product_record_agree_on_the_product_code() -> None:
    # The source rests on GW's two systems reporting the same 11-digit code; a divergence must be
    # counted, not silently resolved. All six fixtures were captured live and agree.
    assert result_cache().stats["pim_key_disagreements"] == 0


def test_lifecycle_flags_are_emitted_verbatim() -> None:
    nihilakh = observation(result_cache(), NIHILAKH)
    assert nihilakh.hints["lastChanceToBuy"] is False
    assert nihilakh.hints["availableWhileStocksLast"] is False
    assert nihilakh.hints["statusCode"] == "A"
    assert nihilakh.hints["launchDate"] == "2022-05-28"


# --- sizes: features first, image fallback, silence when GW is silent -------------------------


def test_features_size_wins_and_is_recorded_as_such() -> None:
    abaddon = observation(result_cache(), ABADDON)
    assert abaddon.hints["volumeMl"] == 12
    assert abaddon.hints["volumeSource"] == "features"


def test_spray_can_size_comes_only_from_features() -> None:
    # The spray tile is an SVG with no size in its name -- 400ml exists nowhere but features[].
    spray = observation(result_cache(), SPRAY)
    assert spray.hints["volumeMl"] == 400
    assert spray.hints["volumeSource"] == "features"


def test_image_filename_supplies_the_size_features_omits() -> None:
    pink = observation(result_cache(), PINK_HORROR)
    assert pink.hints["volumeMl"] == 12
    assert pink.hints["volumeSource"] == "image"


def test_paint_with_no_stated_size_anywhere_gets_no_volume() -> None:
    # Every Dry paint really is a 12ml pot, but GW does not say so here and this source will not
    # invent it -- the evidence pipeline records assertions, not knowledge.
    dawnstone = observation(result_cache(), DAWNSTONE)
    assert "volumeMl" not in dawnstone.hints
    assert "volumeSource" not in dawnstone.hints
    assert result_cache().stats["volume_missing"] == 1


def test_volume_source_counts_are_reported() -> None:
    stats = result_cache().stats
    assert stats["volume_from_features"] == 3   # Nihilakh, Abaddon, Chaos Black spray
    assert stats["volume_from_image"] == 2      # Pink Horror, Kroak Green
    assert stats["volume_missing"] == 1         # Dawnstone (Dry)


# --- budget / cursor / give-up ---------------------------------------------------------------


def test_budget_rations_detail_fetches_but_never_the_roster() -> None:
    result = run(budget=2)
    assert result.stats["details_fetched"] == 2
    assert len(result.observations) == 6  # full population regardless of budget
    assert len(result.cursor["pending_details"]) == 4
    assert result.full_sweep is False


def test_cached_details_are_carried_forward_and_never_refetched() -> None:
    first = run()
    assert first.full_sweep is True
    assert not first.cursor["pending_details"]

    calls: list[str] = []
    second = run(cursor=first.cursor, calls=calls)
    assert second.stats["details_fetched"] == 0
    assert not [c for c in calls if "/shop/" in c]  # no detail re-fetch, no buildId probe either
    # and the cached enrichment still reaches the observations
    assert observation(second, SPRAY).hints["volumeMl"] == 400
    assert observation(second, NIHILAKH).hints["launchDate"] == "2022-05-28"


def test_detail_404_gives_up_immediately_so_it_cannot_pin_full_sweep() -> None:
    result = run(detail_404={"Dry-Dawnstone-2019"})
    assert result.stats["detail_not_found"] == 1
    assert result.cursor["details"]["Dry-Dawnstone-2019"] == {"detailMisses": DETAIL_MISS_CAP}
    assert not result.cursor["pending_details"]
    assert result.full_sweep is True  # a dead slug must not block the sweep forever
    assert len(result.observations) == 6  # still observed from the roster


def test_parse_misses_retry_up_to_the_cap_then_stop() -> None:
    result = run(drift_details=True)
    assert result.stats["detail_parse_misses"] == 6
    assert all(d == {"detailMisses": 1} for d in result.cursor["details"].values())

    for expected in (2, 3):
        result = run(cursor=result.cursor, drift_details=True)
        assert all(d == {"detailMisses": expected} for d in result.cursor["details"].values())

    # At the cap the slugs are no longer re-queued, so the source can reach full_sweep again.
    capped = run(cursor=result.cursor, drift_details=True)
    assert capped.stats["details_fetched"] == 0
    assert capped.full_sweep is True
    assert len(capped.observations) == 6


def test_unknown_vendor_observes_nothing_rather_than_emitting_unattributed_evidence() -> None:
    result = run(taxonomy=Taxonomy({}))
    assert result.observations == []
    assert result.stats["skipped_unknown_vendor"] == 6
    assert result.stats["details_fetched"] == 0


_CACHE: dict[str, object] = {}


def result_cache():
    """One default run shared by the assertion-only tests above (the mock transport is
    deterministic, so re-running it per test would only cost time)."""
    if "result" not in _CACHE:
        _CACHE["result"] = run()
    return _CACHE["result"]
