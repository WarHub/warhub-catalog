"""Sitemap + structured-data strategy: sitemap-index nesting, per-page extraction (JSON-LD /
microdata / BCData, in that priority order), GS1-prefix manufacturer attribution, budgeted
page-fetch cursor round-trip.

Fixture provenance (see task-11-report.md for full detail):

- `radaddel-sitemap-index.xml`, `radaddel-sitemap-1.xml`(`.gz`), `radaddel-product.html`: REAL,
  captured live 2026-07-13 from radaddel.de (`radaddel-sitemap-1.xml.gz` is a genuine gzip file
  built from the real trimmed sitemap content, reproducing the live site's actual
  `Content-Type: application/x-gzip` / no-`Content-Encoding` behavior).
- `gamenerdz-sitemap-index.xml`, `gamenerdz-sitemap-pages1.xml`, `gamenerdz-sitemap-products1.xml`,
  `gamenerdz-product.html`: REAL, captured live 2026-07-13 from gamenerdz.com.
- Miniaturicum (JSON-LD extractor's primary real-world site) returned HTTP 520 on every attempt
  (product page, sitemap, homepage -- 6 attempts total across ~15 minutes) during this task's
  fixture-capture window and could not be captured; no `ret-miniaturicum.yaml` descriptor or
  fixture was built (per the task's explicit "stop after 2-3 attempts, build the other two"
  instruction). The JSON-LD extractor is still exercised below with hand-written HTML using the
  REAL gtin13/sku/name values the 2026-07-12 probe already documented for Miniaturicum's
  Primaris-Intercessors page (not a fresh live capture -- see `PROBE_DOCUMENTED_*` constants).
"""
import gzip
import json
from pathlib import Path

import httpx
import pytest

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.extract import _fallback_name
from warhub_acquisition.acquire.strategies.sitemap_sd import (
    _extract_bcdata,
    _extract_jsonld,
    _extract_microdata,
    _extract_page,
    _manufacturer_by_gs1_prefix,
    sitemap_sd_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "sitemap_sd"

RADADDEL_BASE = "https://www.radaddel.de"
GAMENERDZ_BASE = "https://www.gamenerdz.com"

# Real values documented by the 2026-07-12 probe (docs/research/2026-07-12-source-probe-retailers-
# barcodedb.md) for miniaturicum.de/Primaris-Intercessors -- Miniaturicum itself returned HTTP 520
# on every fixture-capture attempt this task made (see module docstring), so these are not a fresh
# capture, but they are not invented either.
PROBE_DOCUMENTED_GTIN13 = "5011921142361"
PROBE_DOCUMENTED_SKU = "GW-99120101309"
PROBE_DOCUMENTED_NAME = "Primaris Intercessors"


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def gw_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "games-workshop": Manufacturer(
                slug="games-workshop",
                name="Games Workshop",
                gs1Prefixes=["5011921"],
                vendorNames=["Games Workshop", "Citadel", "Forge World"],
            )
        }
    )


def radaddel_descriptor(**scope_overrides: object) -> SourceDescriptor:
    scope: dict[str, object] = {
        "sitemaps": [f"{RADADDEL_BASE}/sitemap_index.xml"],
        "currency": "eur",
    }
    scope.update(scope_overrides)
    return SourceDescriptor(
        id="ret-radaddel", kind="retailer", strategy="sitemap-structured-data", baseUrl=RADADDEL_BASE, scope=scope
    )


def gamenerdz_descriptor(**scope_overrides: object) -> SourceDescriptor:
    scope: dict[str, object] = {
        "sitemaps": [f"{GAMENERDZ_BASE}/xmlsitemap.php"],
        "urlInclude": r"(?i)(warhammer|citadel|forge-world)",
        "currency": "usd",
    }
    scope.update(scope_overrides)
    return SourceDescriptor(
        id="ret-gamenerdz", kind="retailer", strategy="sitemap-structured-data", baseUrl=GAMENERDZ_BASE, scope=scope
    )


def context(taxonomy: Taxonomy, budget: int | None = None) -> AcquireContext:
    return AcquireContext(taxonomy=taxonomy, mappings={}, run_date="2026-07-13", budget=budget)


NOT_A_PRODUCT_HTML = "<!doctype html><html><head><title>Category</title></head><body>nothing here</body></html>"


def radaddel_transport(calls: list[str] | None = None, product_response=None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        if path == "/sitemap_index.xml":
            return httpx.Response(200, text=load_text("radaddel-sitemap-index.xml"))
        if path == "/web/sitemap/shop-1/sitemap-1.xml.gz":
            return httpx.Response(
                200, content=load_bytes("radaddel-sitemap-1.xml.gz"), headers={"Content-Type": "application/x-gzip"}
            )
        if path == "/necrons-combat-patrol":
            if product_response is not None:
                return product_response
            return httpx.Response(200, text=load_text("radaddel-product.html"))
        if path.startswith("/game-color-ink-"):
            return httpx.Response(200, text=NOT_A_PRODUCT_HTML)
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def gamenerdz_transport(calls: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        params = request.url.params
        if path == "/xmlsitemap.php":
            if params.get("type") == "pages" and params.get("page") == "1":
                return httpx.Response(200, text=load_text("gamenerdz-sitemap-pages1.xml"))
            if params.get("type") == "products" and params.get("page") == "1":
                return httpx.Response(200, text=load_text("gamenerdz-sitemap-products1.xml"))
            return httpx.Response(200, text=load_text("gamenerdz-sitemap-index.xml"))
        if path == "/warhammer-40k-stormraven-gunship":
            return httpx.Response(200, text=load_text("gamenerdz-product.html"))
        if path == "/citadel-brush-medium-shade":
            return httpx.Response(200, text=NOT_A_PRODUCT_HTML)
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def test_strategy_is_registered() -> None:
    assert STRATEGIES["sitemap-structured-data"] is sitemap_sd_strategy


# --- Per-extractor unit tests (exact ean/sku/name asserted per fixture) -----------------------


def test_microdata_extraction_from_real_radaddel_fixture() -> None:
    html = load_text("radaddel-product.html")
    result = _extract_microdata(html)
    assert result == {
        "name": "Necrons: Combat Patrol",
        "sku": "127347",
        "ean": "5011921194285",
        "brand": "Games Workshop",
    }


def test_bcdata_extraction_from_real_gamenerdz_fixture() -> None:
    html = load_text("gamenerdz-product.html")
    result = _extract_bcdata(html)
    assert result == {"name": None, "sku": "GWS41-10", "ean": "5011921146000", "brand": None}


def test_jsonld_extraction_from_real_gamenerdz_fixture_has_no_gtin() -> None:
    """Real, live-confirmed 2026-07-13: Game Nerdz's own JSON-LD Product node carries
    name/sku/brand but a null gtin -- this is WHY BCData is extractor #3 in the priority chain."""
    html = load_text("gamenerdz-product.html")
    result = _extract_jsonld(html)
    assert result == {
        "name": "Warhammer 40K: Stormraven Gunship",
        "sku": "GWS41-10",
        "ean": None,
        "brand": "Games Workshop",
    }


def test_jsonld_extraction_unit_using_probe_documented_miniaturicum_values() -> None:
    """Miniaturicum itself returned HTTP 520 on every capture attempt this task made (see module
    docstring) -- this uses the REAL gtin13/sku/name values the 2026-07-12 probe already
    documented for Miniaturicum's Primaris-Intercessors JSON-LD, in a hand-written but
    schema.org-accurate Product node, since no fresh live HTML could be obtained."""
    html = f"""<!doctype html><html><head>
    <script type="application/ld+json">
    {{"@context": "https://schema.org", "@type": "Product",
      "name": "{PROBE_DOCUMENTED_NAME}", "sku": "{PROBE_DOCUMENTED_SKU}",
      "gtin13": "{PROBE_DOCUMENTED_GTIN13}",
      "brand": {{"@type": "Brand", "name": "Games Workshop"}}}}
    </script>
    </head><body></body></html>"""
    result = _extract_jsonld(html)
    assert result == {
        "name": PROBE_DOCUMENTED_NAME,
        "sku": PROBE_DOCUMENTED_SKU,
        "ean": PROBE_DOCUMENTED_GTIN13,
        "brand": "Games Workshop",
    }


def test_jsonld_extraction_handles_at_graph_nesting_and_gtin_fallback_order() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@context": "https://schema.org", "@graph": ['
        '{"@type": "WebPage", "name": "Some Page"},'
        '{"@type": "Product", "name": "Widget", "gtin": "1234567890123", "gtin12": "999999999999"}'
        "]}"
        "</script>"
    )
    result = _extract_jsonld(html)
    assert result["ean"] == "1234567890123"  # gtin13 absent -> gtin (not gtin12)


def test_jsonld_extraction_skips_malformed_block_and_finds_later_valid_one() -> None:
    html = (
        '<script type="application/ld+json">{not valid json,,,</script>'
        '<script type="application/ld+json">{"@type": "Product", "name": "Widget", "gtin13": "1234567890123"}</script>'
    )
    assert _extract_jsonld(html)["ean"] == "1234567890123"


def test_jsonld_extraction_finds_gtin_nested_in_a_single_offers_dict() -> None:
    """Real bug (2026-07-13, tistaminis.com archived-page diagnosis): many Shopify themes put the
    barcode inside the Product's `offers`, not at the Product node's own top level. `offers` can be
    a single Offer object -- this must still be found."""
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Product", "name": "Widget", "sku": "W-1",'
        ' "offers": {"@type": "Offer", "price": "9.99", "gtin13": "1234567890123"}}'
        "</script>"
    )
    assert _extract_jsonld(html) == {
        "name": "Widget",
        "sku": "W-1",
        "ean": "1234567890123",
        "brand": None,
    }


def test_jsonld_extraction_finds_gtin_nested_in_a_list_of_offers_first_match_wins() -> None:
    """`offers` can also be a LIST of Offer objects (real shape: Shopify variants) -- the first
    offer carrying a usable gtin field wins."""
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Product", "name": "Widget", "offers": ['
        '{"@type": "Offer", "sku": "V1"},'
        '{"@type": "Offer", "sku": "V2", "gtin13": "1234567890123"},'
        '{"@type": "Offer", "sku": "V3", "gtin13": "9999999999999"}'
        "]}"
        "</script>"
    )
    assert _extract_jsonld(html)["ean"] == "1234567890123"


def test_jsonld_extraction_top_level_gtin_wins_over_offers_gtin() -> None:
    """Precedence: the Product node's own top-level gtin field is checked BEFORE `offers` -- no
    regression for pages whose gtin IS top-level (the common/original case)."""
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Product", "name": "Widget", "gtin13": "1111111111111",'
        ' "offers": {"gtin13": "2222222222222"}}'
        "</script>"
    )
    assert _extract_jsonld(html)["ean"] == "1111111111111"


def test_jsonld_extraction_offers_present_but_no_gtin_anywhere_leaves_ean_none() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Product", "name": "Widget", "sku": "W-1",'
        ' "offers": {"@type": "Offer", "price": "9.99"}}'
        "</script>"
    )
    assert _extract_jsonld(html) == {"name": "Widget", "sku": "W-1", "ean": None, "brand": None}


def test_jsonld_extraction_returns_none_without_a_product_node() -> None:
    html = '<script type="application/ld+json">{"@type": "WebPage", "name": "Home"}</script>'
    assert _extract_jsonld(html) is None


def test_microdata_extraction_returns_none_without_product_itemtype() -> None:
    assert _extract_microdata(NOT_A_PRODUCT_HTML) is None


def test_bcdata_extraction_returns_none_without_bcdata_var() -> None:
    assert _extract_bcdata(NOT_A_PRODUCT_HTML) is None


def test_bcdata_extraction_returns_none_when_neither_sku_nor_upc_present() -> None:
    html = '<script>var BCData = {"product_attributes":{"sku":"","upc":null}};</script>'
    assert _extract_bcdata(html) is None


def test_bcdata_extraction_ignores_trailing_script_content_after_object() -> None:
    """raw_decode must stop at the object's own closing brace, not swallow (or choke on) whatever
    JS follows the `;` -- real captured pages always have more script content after BCData."""
    html = (
        '<script>var BCData = {"product_attributes":{"sku":"ABC","upc":"5011921000000"}};'
        "console.log('more js; with semicolons; and braces {}');</script>"
    )
    assert _extract_bcdata(html) == {"name": None, "sku": "ABC", "ean": "5011921000000", "brand": None}


# --- Extractor precedence / field-merge ---------------------------------------------------------


def test_precedence_jsonld_wins_ean_over_microdata_when_both_present() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Product", "name": "Widget", "gtin13": "1111111111111"}'
        "</script>"
        '<div itemscope itemtype="https://schema.org/Product">'
        '<span itemprop="name">Widget</span>'
        '<meta itemprop="gtin13" content="2222222222222"/>'
        "</div>"
    )
    record, ean_source = _extract_page(html)
    assert record["ean"] == "1111111111111"
    assert ean_source == "jsonld"


def test_field_merge_takes_name_from_jsonld_and_ean_from_bcdata_when_jsonld_gtin_is_absent() -> None:
    """The real Game Nerdz shape: JSON-LD has name/sku/brand but no gtin at all -- BCData's upc
    must still be picked up as the ean, without losing JSON-LD's name/brand."""
    html = load_text("gamenerdz-product.html")
    record, ean_source = _extract_page(html)
    assert record == {
        "name": "Warhammer 40K: Stormraven Gunship",
        "sku": "GWS41-10",
        "ean": "5011921146000",
        "brand": "Games Workshop",
    }
    assert ean_source == "bcdata"


def test_extraction_fails_cleanly_when_no_extractor_finds_anything() -> None:
    record, ean_source = _extract_page(NOT_A_PRODUCT_HTML)
    assert record["name"] is None
    assert ean_source is None


def test_ean_digits_only_normalization_strips_non_digits() -> None:
    html = '<script type="application/ld+json">{"@type": "Product", "name": "Widget", "gtin13": "501-192-1194285 "}</script>'
    assert _extract_jsonld(html)["ean"] == "5011921194285"


# --- HTML-entity unescaping (every text field funnels through extract._clean) -------------------


def test_jsonld_extraction_unescapes_html_entities_in_name() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Product", "name": "Foo &#8211; Bar &amp; Baz", "sku": "ABC"}'
        "</script>"
    )
    assert _extract_jsonld(html)["name"] == "Foo – Bar & Baz"


def test_microdata_extraction_unescapes_html_entities_in_name() -> None:
    html = (
        '<div itemscope itemtype="https://schema.org/Product">'
        '<span itemprop="name">Foo &#8211; Bar &amp; Baz</span>'
        "</div>"
    )
    assert _extract_microdata(html)["name"] == "Foo – Bar & Baz"


def test_fallback_name_unescapes_html_entities_from_h1() -> None:
    html = "<html><body><h1>Foo &#8211; Bar &amp; Baz</h1></body></html>"
    assert _fallback_name(html) == "Foo – Bar & Baz"


# --- GS1-prefix manufacturer attribution --------------------------------------------------------


def test_gs1_prefix_manufacturer_lookup() -> None:
    taxonomy = gw_taxonomy()
    assert _manufacturer_by_gs1_prefix(taxonomy, "5011921194285") == "games-workshop"
    assert _manufacturer_by_gs1_prefix(taxonomy, "0000000000000") is None


# --- Full strategy: Radaddel (sitemap-index -> gzipped child, microdata extraction) -------------


def test_radaddel_sweep_extracts_real_ean_via_microdata() -> None:
    calls: list[str] = []
    client = PoliteClient(RADADDEL_BASE, transport=radaddel_transport(calls), sleep=lambda s: None)
    result = sitemap_sd_strategy(radaddel_descriptor(), client, {}, context(gw_taxonomy()))

    assert result.stats["fetched_sitemaps"] == 2  # index + 1 gzipped child (one level of nesting)
    assert result.stats["sitemap_urls_total"] == 5
    assert result.stats["sitemap_urls_filtered"] == 5  # no urlInclude set for Radaddel
    assert result.stats["pages_fetched"] == 5
    assert result.stats["fetch_errors"] == 0
    assert result.stats["extraction_failed"] == 4  # the 4 "game-color-ink-*" non-product pages
    assert result.stats["eans_found"] == 1
    assert result.stats["ean_source_microdata"] == 1

    by_key = {observation.key: observation for observation in result.observations}
    assert list(by_key) == ["ret-radaddel:/necrons-combat-patrol"]
    necrons = by_key["ret-radaddel:/necrons-combat-patrol"]
    assert necrons.name == "Necrons: Combat Patrol"
    assert necrons.sku == "127347"
    assert necrons.ean == "5011921194285"
    assert necrons.manufacturer == "games-workshop"  # resolved via brand string, not GS1 fallback
    assert necrons.url == f"{RADADDEL_BASE}/necrons-combat-patrol"
    assert necrons.extractor == "sitemap-structured-data@1"

    # full_sweep is hard-coded False for this strategy always (final fix wave, item 2), even
    # though this particular tiny fixture happens to fetch every filtered URL: retailer sitemap
    # coverage is never a claim about the full population (see the dedicated full_sweep tests
    # below and the module docstring's "full_sweep" section).
    assert result.full_sweep is False
    assert set(result.cursor["fetched"]) == {
        "/necrons-combat-patrol",
        "/game-color-ink-111-yellow",
        "/game-color-ink-115-blue",
        "/game-color-ink-117-green",
        "/game-color-ink-118-black-green",
    }


def test_gs1_prefix_fallback_used_when_brand_string_is_unresolvable() -> None:
    """A page whose extracted brand string does not match any taxonomy vendor name, but whose
    ean falls under a known GS1 prefix, must still resolve via the prefix fallback."""
    unbranded_html = load_text("radaddel-product.html").replace(
        '<span itemprop="name">Games Workshop</span>', '<span itemprop="name">Some Reseller Label</span>'
    )
    client = PoliteClient(
        RADADDEL_BASE,
        transport=radaddel_transport(product_response=httpx.Response(200, text=unbranded_html)),
        sleep=lambda s: None,
    )
    result = sitemap_sd_strategy(radaddel_descriptor(), client, {}, context(gw_taxonomy()))

    by_key = {observation.key: observation for observation in result.observations}
    necrons = by_key["ret-radaddel:/necrons-combat-patrol"]
    assert necrons.manufacturer == "games-workshop"  # via GS1 prefix "5011921", not vendor name
    assert result.stats["skipped_unknown_manufacturer"] == 0


def test_unknown_brand_and_unknown_gs1_prefix_skips_and_counts() -> None:
    unresolvable_html = load_text("radaddel-product.html").replace(
        '<span itemprop="name">Games Workshop</span>', '<span itemprop="name">Totally Unknown Brand</span>'
    ).replace('content="5011921194285"', 'content="9999999999999"').replace(
        'itemprop="ean">5011921194285', 'itemprop="ean">9999999999999'
    )
    client = PoliteClient(
        RADADDEL_BASE,
        transport=radaddel_transport(product_response=httpx.Response(200, text=unresolvable_html)),
        sleep=lambda s: None,
    )
    result = sitemap_sd_strategy(radaddel_descriptor(), client, {}, context(gw_taxonomy()))

    assert result.observations == []
    assert result.stats["skipped_unknown_manufacturer"] == 1
    # the page was still successfully fetched -- it counts toward "fetched" cursor bookkeeping
    assert "/necrons-combat-patrol" in result.cursor["fetched"]


def test_fetch_error_on_one_page_does_not_abort_sweep_and_stays_pending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sitemap_index.xml":
            return httpx.Response(200, text=load_text("radaddel-sitemap-index.xml"))
        if path == "/web/sitemap/shop-1/sitemap-1.xml.gz":
            return httpx.Response(
                200, content=load_bytes("radaddel-sitemap-1.xml.gz"), headers={"Content-Type": "application/x-gzip"}
            )
        if path == "/necrons-combat-patrol":
            return httpx.Response(500, text="down")  # retried 3x by PoliteClient, still fails
        if path.startswith("/game-color-ink-"):
            return httpx.Response(200, text=NOT_A_PRODUCT_HTML)
        raise AssertionError(f"unexpected request: {request.url}")

    client = PoliteClient(RADADDEL_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = sitemap_sd_strategy(radaddel_descriptor(), client, {}, context(gw_taxonomy()))

    assert result.stats["fetch_errors"] == 1
    assert result.observations == []
    assert "/necrons-combat-patrol" not in result.cursor["fetched"]
    assert result.full_sweep is False  # the failed URL was never successfully fetched


def test_budget_caps_page_fetches_to_never_fetched_first_in_sorted_order() -> None:
    calls: list[str] = []
    client = PoliteClient(RADADDEL_BASE, transport=radaddel_transport(calls), sleep=lambda s: None)
    result = sitemap_sd_strategy(radaddel_descriptor(), client, {}, context(gw_taxonomy(), budget=1))

    assert result.stats["pages_fetched"] == 1
    # sorted path order: "/game-color-ink-111-yellow" sorts before "/necrons-combat-patrol"
    assert set(result.cursor["fetched"]) == {"/game-color-ink-111-yellow"}
    assert result.full_sweep is False
    # 2 sitemap fetches + exactly 1 product-page fetch
    assert len([c for c in calls if "sitemap" not in c]) == 1


def test_oldest_fetched_bucket_is_prioritized_over_never_fetched_on_second_run() -> None:
    """Round-trip: a path already in the cursor (however recently) is still eligible to be
    re-fetched -- the priority order is never-fetched first, then oldest-fetched -- so once every
    path has been seen at least once, the next run cycles through by staleness."""
    old_cursor = {
        "fetched": {
            "/necrons-combat-patrol": "2020-01-01",  # very stale -- should be first among "seen"
            "/game-color-ink-115-blue": "2026-07-01",
            "/game-color-ink-117-green": "2026-07-01",
            "/game-color-ink-118-black-green": "2026-07-01",
            # "/game-color-ink-111-yellow" intentionally absent -> "never fetched" outranks all
        }
    }
    calls: list[str] = []
    client = PoliteClient(RADADDEL_BASE, transport=radaddel_transport(calls), sleep=lambda s: None)
    result = sitemap_sd_strategy(radaddel_descriptor(), client, old_cursor, context(gw_taxonomy(), budget=2))

    fetched_paths = {c.split(RADADDEL_BASE)[-1] for c in calls if "sitemap" not in c}
    assert fetched_paths == {"/game-color-ink-111-yellow", "/necrons-combat-patrol"}


def test_stale_bucket_tie_break_is_path_sorted_when_dates_are_equal() -> None:
    """Regression (final fix wave, item 1): `stale`'s sort key must break same-date ties on the
    path itself -- without it, ties rode on `by_path`'s set-comprehension iteration order (hash-
    randomized per process), so the fetch order (and thus the resulting cursor's tie order) was
    nondeterministic across runs even for identical inputs."""
    same_date = "2026-07-01"
    old_cursor = {
        "fetched": {
            "/necrons-combat-patrol": same_date,
            "/game-color-ink-111-yellow": same_date,
            "/game-color-ink-115-blue": same_date,
            "/game-color-ink-117-green": same_date,
            "/game-color-ink-118-black-green": same_date,
        }
    }
    calls: list[str] = []
    client = PoliteClient(RADADDEL_BASE, transport=radaddel_transport(calls), sleep=lambda s: None)
    result = sitemap_sd_strategy(radaddel_descriptor(), client, old_cursor, context(gw_taxonomy(), budget=1))

    fetched_paths = [c.split(RADADDEL_BASE)[-1] for c in calls if "sitemap" not in c]
    # all 5 paths tie on date -- the alphabetically-first path must be the one fetched.
    assert fetched_paths == ["/game-color-ink-111-yellow"]


def test_cursor_prunes_paths_no_longer_in_the_filtered_sitemap() -> None:
    old_cursor = {"fetched": {"/some-delisted-product": "2020-01-01", "/necrons-combat-patrol": "2020-01-01"}}
    client = PoliteClient(RADADDEL_BASE, transport=radaddel_transport(), sleep=lambda s: None)
    result = sitemap_sd_strategy(radaddel_descriptor(), client, old_cursor, context(gw_taxonomy()))

    assert "/some-delisted-product" not in result.cursor["fetched"]


def test_full_sweep_is_false_while_any_filtered_url_has_never_been_fetched() -> None:
    client = PoliteClient(RADADDEL_BASE, transport=radaddel_transport(), sleep=lambda s: None)
    result = sitemap_sd_strategy(radaddel_descriptor(), client, {}, context(gw_taxonomy(), budget=1))
    assert result.full_sweep is False


def test_full_sweep_is_always_false_even_when_every_filtered_url_has_been_fetched() -> None:
    """Regression (final fix wave, item 2): full_sweep must be hard-coded False for this strategy,
    even for an unbudgeted run that happens to fetch every filtered URL -- retailer sitemap
    coverage is never a claim about the manufacturer's full population, and run_source's
    mark_missed must never be invoked off this source's observations. See module docstring."""
    client = PoliteClient(RADADDEL_BASE, transport=radaddel_transport(), sleep=lambda s: None)
    result = sitemap_sd_strategy(radaddel_descriptor(), client, {}, context(gw_taxonomy(), budget=None))
    assert result.full_sweep is False


# --- Full strategy: Game Nerdz (sitemap-index -> multiple children, urlInclude filter, BCData) --


def test_gamenerdz_sweep_applies_url_include_filter_and_extracts_via_bcdata_fallback() -> None:
    calls: list[str] = []
    client = PoliteClient(GAMENERDZ_BASE, transport=gamenerdz_transport(calls), sleep=lambda s: None)
    result = sitemap_sd_strategy(gamenerdz_descriptor(), client, {}, context(gw_taxonomy()))

    assert result.stats["fetched_sitemaps"] == 3  # index + 2 children (pages page1, products page1)
    # sitemap_urls_total: 3 real "pages" URLs (none GW-tagged) + 5 real "products" URLs
    assert result.stats["sitemap_urls_total"] == 8
    # urlInclude keeps only slugs containing warhammer/citadel/forge-world:
    # stormraven-gunship (warhammer) + citadel-brush-medium-shade (citadel)
    assert result.stats["sitemap_urls_filtered"] == 2
    assert result.stats["pages_fetched"] == 2
    assert result.stats["ean_source_bcdata"] == 1
    assert result.stats["extraction_failed"] == 1  # citadel-brush-medium-shade has no product data

    by_key = {observation.key: observation for observation in result.observations}
    stormraven = by_key["ret-gamenerdz:/warhammer-40k-stormraven-gunship"]
    assert stormraven.name == "Warhammer 40K: Stormraven Gunship"
    assert stormraven.sku == "GWS41-10"
    assert stormraven.ean == "5011921146000"
    assert stormraven.manufacturer == "games-workshop"
    assert stormraven.extractor == "sitemap-structured-data@1"

    # homepage/terms/contact pages were filtered out by urlInclude before ever being fetched
    assert not any("/terms-and-conditions" in c or c.endswith("gamenerdz.com/") for c in calls)


def test_gamenerdz_url_include_excludes_non_gw_pages_urls() -> None:
    client = PoliteClient(GAMENERDZ_BASE, transport=gamenerdz_transport(), sleep=lambda s: None)
    result = sitemap_sd_strategy(gamenerdz_descriptor(), client, {}, context(gw_taxonomy()))
    # 3 "pages" URLs (/, /terms-and-conditions, /contact-us) all excluded by urlInclude
    assert result.stats["sitemap_urls_filtered"] == 2
