"""Playwright/WordPress strategy (CMON): sitemap enumeration (both sitemaps fetched through the
injected browser fetcher, never PoliteClient/httpx), product-line reverse-mapping, per-product
name/image extraction, gameSystem mapping + unmapped-productLine counting, standalone pacing, and
the lazy-import guard that keeps `playwright` out of the non-live test path entirely.

Fixture provenance (see task-10-report.md for full detail): every `tests/fixtures/playwright/*`
file except `cmon-no-h1-product.html` is REAL, trimmed-to-skeleton HTML/XML captured live
2026-07-13 from cmon.com via an authenticated browser session (claude-in-chrome), after Cloudflare's
JS challenge had already been passed in that browsing context -- title/meta/`<h1>`/card-link markup
is exactly as served, only unrelated surrounding markup (nav, footer, prose, cookie banner) was
trimmed.
"""
import sys
import urllib.robotparser
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import pytest

from warhub_acquisition.acquire.client import FetchError, PoliteClient, RobotsDisallowedError
from warhub_acquisition.acquire.robots import RobotsPolicy
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.playwright_wp import (
    _extract_image_url,
    _extract_line_member_slugs,
    _extract_name,
    _parse_locs,
    playwright_wp_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "playwright"

BASE_URL = "https://www.cmon.com"
PRODUCT_SITEMAP_URL = f"{BASE_URL}/wp-sitemap-posts-products-1.xml"
LINE_SITEMAP_URL = f"{BASE_URL}/wp-sitemap-posts-products-line-1.xml"


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def cmon_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "cmon": Manufacturer(slug="cmon", name="CMON", vendorNames=["CMON", "Cool Mini or Not"]),
        }
    )


def cmon_descriptor(**scope_overrides: object) -> SourceDescriptor:
    scope: dict[str, object] = {"manufacturer": "CMON"}
    scope.update(scope_overrides)
    return SourceDescriptor(
        id="mfr-cmon",
        kind="manufacturer",
        strategy="playwright-wp",
        baseUrl=BASE_URL,
        scope=scope,
        politeness={"rps": 0.5},
    )


def context(taxonomy: Taxonomy, mappings: dict | None = None) -> AcquireContext:
    return AcquireContext(taxonomy=taxonomy, mappings=mappings or {}, run_date="2026-07-13", budget=None)


# --- Fake PageFetcher ---------------------------------------------------------------------------

_URL_TO_FIXTURE = {
    PRODUCT_SITEMAP_URL: "cmon-sitemap-products.xml",
    LINE_SITEMAP_URL: "cmon-sitemap-lines.xml",
    f"{BASE_URL}/product-line/massive-darkness/": "cmon-product-line-massive-darkness.html",
    f"{BASE_URL}/product-line/a-song-of-ice-fire-tmg-2/": "cmon-product-line-asoiaf-tmg.html",
    f"{BASE_URL}/products/grow-sky/": "cmon-product-standalone.html",
    f"{BASE_URL}/products/massive-darkness-dungeons-of-shadowreach/": "cmon-product.html",
    f"{BASE_URL}/products/massive-darkness-2-hellscape/": "cmon-product-hellscape.html",
    f"{BASE_URL}/products/stark-starter-set/": "cmon-product-stark.html",
    f"{BASE_URL}/products/no-h1-test-product/": "cmon-no-h1-product.html",
}


def fake_fetcher(calls: list[str] | None = None, fail_urls: set[str] | None = None) -> Callable[[str], str]:
    fail_urls = fail_urls or set()

    def fetch(url: str) -> str:
        if calls is not None:
            calls.append(url)
        if url in fail_urls:
            raise FetchError(url, 500)
        return load_text(_URL_TO_FIXTURE[url])

    return fetch


def real_client() -> PoliteClient:
    # playwright_wp_strategy receives a PoliteClient per the Strategy call signature and never
    # fetches THROUGH it (see module docstring) -- but it does read `client.robots`/
    # `client.user_agent` off it to enforce robots.txt on its own browser fetches (fix wave 3). No
    # `robots=` here means "no robots checking" (mirrors `ignoreRobots`/no-baseUrl in runner.py),
    # so this stays a no-op for every fixture-driven test below; `disallowing_client` (below) is
    # the one that attaches a real policy.
    return PoliteClient(BASE_URL, sleep=lambda s: None)


def disallowing_client(disallow_path: str) -> PoliteClient:
    """A `PoliteClient` carrying a `RobotsPolicy` that disallows exactly `disallow_path` (relative
    to `BASE_URL`) for every user-agent -- used to prove the playwright strategy checks robots.txt
    on each browser fetch, not just `descriptor.baseUrl` (see `runner.run_source`'s preflight,
    which this test bypasses entirely by calling `playwright_wp_strategy` directly)."""
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(f"User-agent: *\nAllow: /\nDisallow: {disallow_path}\n".splitlines())
    return PoliteClient(BASE_URL, sleep=lambda s: None, robots=RobotsPolicy(parser))


# --- Registration ---------------------------------------------------------------------------


def test_strategy_is_registered() -> None:
    assert STRATEGIES["playwright-wp"] is playwright_wp_strategy


# --- Per-extractor unit tests (exact values asserted per real fixture) ----------------------


def test_parse_locs_from_real_product_sitemap_fixture() -> None:
    xml = load_text("cmon-sitemap-products.xml")
    locs = _parse_locs(xml)
    assert locs == [
        "https://www.cmon.com/products/grow-sky/",
        "https://www.cmon.com/products/massive-darkness-dungeons-of-shadowreach/",
        "https://www.cmon.com/products/massive-darkness-2-hellscape/",
        "https://www.cmon.com/products/stark-starter-set/",
        "https://www.cmon.com/products/no-h1-test-product/",
    ]


def test_parse_locs_from_real_line_sitemap_fixture() -> None:
    xml = load_text("cmon-sitemap-lines.xml")
    assert _parse_locs(xml) == [
        "https://www.cmon.com/product-line/massive-darkness/",
        "https://www.cmon.com/product-line/a-song-of-ice-fire-tmg-2/",
    ]


def test_extract_name_from_real_product_fixture() -> None:
    html = load_text("cmon-product.html")
    assert _extract_name(html) == "Massive Darkness: Dungeons of Shadowreach"


def test_extract_name_from_real_standalone_product_fixture() -> None:
    assert _extract_name(load_text("cmon-product-standalone.html")) == "Grow Sky"


def test_extract_name_returns_none_when_no_h1_present() -> None:
    assert _extract_name(load_text("cmon-no-h1-product.html")) is None


def test_extract_image_url_from_real_product_fixture() -> None:
    html = load_text("cmon-product.html")
    assert (
        _extract_image_url(html)
        == "https://www.cmon.com/wp-content/uploads/2025/05/Grid2_640x430px-1.png"
    )


def test_extract_image_url_returns_none_when_absent() -> None:
    assert _extract_image_url(load_text("cmon-no-h1-product.html")) is None


def test_extract_line_name_from_real_line_fixture() -> None:
    html = load_text("cmon-product-line-massive-darkness.html")
    assert _extract_name(html) == "Massive Darkness"


def test_extract_line_member_slugs_from_real_line_fixture() -> None:
    html = load_text("cmon-product-line-massive-darkness.html")
    assert _extract_line_member_slugs(html) == {
        "massive-darkness-dungeons-of-shadowreach",
        "massive-darkness-2-hellscape",
    }


def test_extract_line_name_and_members_from_real_unmapped_line_fixture() -> None:
    html = load_text("cmon-product-line-asoiaf-tmg.html")
    assert _extract_name(html) == "A Song of Ice & Fire: TMG"
    assert _extract_line_member_slugs(html) == {"stark-starter-set"}


# --- Full strategy ----------------------------------------------------------------------------


def test_full_sweep_extracts_name_image_line_and_manufacturer_from_real_fixtures() -> None:
    calls: list[str] = []
    result = playwright_wp_strategy(
        cmon_descriptor(),
        real_client(),
        {},
        context(cmon_taxonomy()),
        fetcher=fake_fetcher(calls),
        sleep=lambda s: None,
    )

    assert result.stats["product_urls_total"] == 5
    assert result.stats["line_urls_total"] == 2
    assert result.stats["line_pages_fetched"] == 2
    assert result.stats["line_fetch_errors"] == 0
    assert result.stats["pages_fetched"] == 5
    assert result.stats["fetch_errors"] == 0
    assert result.stats["extraction_failed_name"] == 1  # no-h1-test-product
    assert result.stats["no_product_line"] == 1  # grow-sky
    assert result.stats["unmapped_product_line"] == 3  # both massive-darkness products + stark
    assert result.stats["mapped_game_system"] == 0
    assert result.stats["skipped_unknown_vendor"] == 0

    by_key = {o.key: o for o in result.observations}
    assert set(by_key) == {
        "mfr-cmon:grow-sky",
        "mfr-cmon:massive-darkness-dungeons-of-shadowreach",
        "mfr-cmon:massive-darkness-2-hellscape",
        "mfr-cmon:stark-starter-set",
    }

    dungeons = by_key["mfr-cmon:massive-darkness-dungeons-of-shadowreach"]
    assert dungeons.name == "Massive Darkness: Dungeons of Shadowreach"
    assert dungeons.manufacturer == "cmon"
    assert dungeons.imageUrl == "https://www.cmon.com/wp-content/uploads/2025/05/Grid2_640x430px-1.png"
    assert dungeons.url == "https://www.cmon.com/products/massive-darkness-dungeons-of-shadowreach/"
    assert dungeons.hints == {"productLine": "Massive Darkness"}
    assert dungeons.extractor == "playwright-wp@1"
    assert dungeons.ean is None
    assert dungeons.sku is None
    assert dungeons.availability is None

    hellscape = by_key["mfr-cmon:massive-darkness-2-hellscape"]
    assert hellscape.name == "Massive Darkness 2: Hellscape"
    assert hellscape.imageUrl == "https://www.cmon.com/wp-content/uploads/2023/06/Thumb-1-9.jpg"
    assert hellscape.hints == {"productLine": "Massive Darkness"}

    grow_sky = by_key["mfr-cmon:grow-sky"]
    assert grow_sky.hints == {}  # standalone product, no line

    stark = by_key["mfr-cmon:stark-starter-set"]
    assert stark.hints == {"productLine": "A Song of Ice & Fire: TMG"}

    # extraction_failed page still counts toward "fetched" bookkeeping in the calls trace, but
    # never becomes an observation:
    assert "mfr-cmon:no-h1-test-product" not in by_key

    # full_sweep is False the moment even one enumerated product URL failed to become an
    # observation (here: the extraction-failed page) -- see module docstring.
    assert result.full_sweep is False


def test_full_sweep_true_when_every_product_url_yields_an_observation() -> None:
    # Same fixtures, but the sitemap only lists the 4 URLs that DO extract cleanly.
    def fetch(url: str) -> str:
        if url == PRODUCT_SITEMAP_URL:
            xml = load_text("cmon-sitemap-products.xml")
            return xml.replace(
                '<url><loc>https://www.cmon.com/products/no-h1-test-product/</loc>'
                '<lastmod>2020-01-01T00:00:00+00:00</lastmod></url>',
                "",
            )
        return load_text(_URL_TO_FIXTURE[url])

    result = playwright_wp_strategy(
        cmon_descriptor(), real_client(), {}, context(cmon_taxonomy()), fetcher=fetch, sleep=lambda s: None
    )

    assert result.stats["product_urls_total"] == 4
    assert len(result.observations) == 4
    assert result.full_sweep is True


def test_game_system_mapping_applied_when_line_name_matches_exactly() -> None:
    mappings = {"mfr-cmon": {"gameSystem": {"Massive Darkness": "massive-darkness"}}}
    result = playwright_wp_strategy(
        cmon_descriptor(),
        real_client(),
        {},
        context(cmon_taxonomy(), mappings),
        fetcher=fake_fetcher(),
        sleep=lambda s: None,
    )

    by_key = {o.key: o for o in result.observations}
    dungeons = by_key["mfr-cmon:massive-darkness-dungeons-of-shadowreach"]
    assert dungeons.hints == {"gameSystem": "massive-darkness"}
    hellscape = by_key["mfr-cmon:massive-darkness-2-hellscape"]
    assert hellscape.hints == {"gameSystem": "massive-darkness"}
    # stark's line ("A Song of Ice & Fire: TMG") is not in this mapping -- still unmapped:
    stark = by_key["mfr-cmon:stark-starter-set"]
    assert stark.hints == {"productLine": "A Song of Ice & Fire: TMG"}

    assert result.stats["mapped_game_system"] == 2
    assert result.stats["unmapped_product_line"] == 1


def test_fetch_error_on_one_product_page_does_not_abort_the_run() -> None:
    calls: list[str] = []
    fail_url = f"{BASE_URL}/products/stark-starter-set/"
    result = playwright_wp_strategy(
        cmon_descriptor(),
        real_client(),
        {},
        context(cmon_taxonomy()),
        fetcher=fake_fetcher(calls, fail_urls={fail_url}),
        sleep=lambda s: None,
    )

    assert result.stats["fetch_errors"] == 1
    assert "mfr-cmon:stark-starter-set" not in {o.key for o in result.observations}
    assert result.full_sweep is False
    # the sitemap fetches and every other product page still ran (fetch errors are per-page, not
    # fatal to the whole run):
    assert result.stats["pages_fetched"] == 4  # 5 total - the 1 that failed


def test_line_page_fetch_error_is_non_fatal_and_leaves_its_members_line_less() -> None:
    fail_url = f"{BASE_URL}/product-line/massive-darkness/"
    result = playwright_wp_strategy(
        cmon_descriptor(),
        real_client(),
        {},
        context(cmon_taxonomy()),
        fetcher=fake_fetcher(fail_urls={fail_url}),
        sleep=lambda s: None,
    )

    assert result.stats["line_fetch_errors"] == 1
    assert result.stats["line_pages_fetched"] == 1  # only the asoiaf line page succeeded
    by_key = {o.key: o for o in result.observations}
    # massive-darkness products lost their line (the line page that would have supplied it
    # failed), but are still enumerated/observed -- retailer/line enrichment failure never drops
    # the product itself:
    assert by_key["mfr-cmon:massive-darkness-dungeons-of-shadowreach"].hints == {}
    assert by_key["mfr-cmon:massive-darkness-dungeons-of-shadowreach"].name == "Massive Darkness: Dungeons of Shadowreach"


def test_empty_enumeration_never_claims_full_sweep() -> None:
    """Regression: a page whose sitemap fetch succeeds (no FetchError) but yields zero <loc>
    entries (live evidence: Cloudflare's "Just a moment..." interstitial is a normal 200 HTML
    response with no <loc> tags at all, see task-10-report.md) must never satisfy
    `full_sweep=True` off `0 == 0` -- that would tell run_source to mark_missed every existing
    evidence entry for this source."""

    def fetch(url: str) -> str:
        if url == PRODUCT_SITEMAP_URL:
            return "<urlset></urlset>"  # well-formed, zero <loc> entries
        return load_text(_URL_TO_FIXTURE[url])

    result = playwright_wp_strategy(
        cmon_descriptor(), real_client(), {}, context(cmon_taxonomy()), fetcher=fetch, sleep=lambda s: None
    )
    assert result.stats["product_urls_total"] == 0
    assert result.observations == []
    assert result.full_sweep is False


def test_unresolvable_manufacturer_skips_every_product_and_never_claims_full_sweep() -> None:
    result = playwright_wp_strategy(
        cmon_descriptor(manufacturer="Totally Unknown Publisher"),
        real_client(),
        {},
        context(cmon_taxonomy()),
        fetcher=fake_fetcher(),
        sleep=lambda s: None,
    )

    assert result.observations == []
    assert result.stats["skipped_unknown_vendor"] == 5
    assert result.full_sweep is False


def test_product_sitemap_fetch_failure_propagates() -> None:
    def fetch(url: str) -> str:
        if url == PRODUCT_SITEMAP_URL:
            raise FetchError(url, 503)
        return load_text(_URL_TO_FIXTURE[url])

    with pytest.raises(FetchError):
        playwright_wp_strategy(
            cmon_descriptor(), real_client(), {}, context(cmon_taxonomy()), fetcher=fetch, sleep=lambda s: None
        )


def test_line_sitemap_fetch_failure_propagates() -> None:
    def fetch(url: str) -> str:
        if url == LINE_SITEMAP_URL:
            raise FetchError(url, 503)
        return load_text(_URL_TO_FIXTURE[url])

    with pytest.raises(FetchError):
        playwright_wp_strategy(
            cmon_descriptor(), real_client(), {}, context(cmon_taxonomy()), fetcher=fetch, sleep=lambda s: None
        )


def test_cursor_is_empty_no_budget_no_persisted_state() -> None:
    result = playwright_wp_strategy(
        cmon_descriptor(), real_client(), {}, context(cmon_taxonomy()), fetcher=fake_fetcher(), sleep=lambda s: None
    )
    assert result.cursor == {}


# --- Robots.txt enforcement on browser fetches (fix wave 3, Important #2) --------------------
#
# playwright_wp.py never calls PoliteClient._request (it fetches via a Chromium page.goto,
# injected here as a fake PageFetcher) -- acquire/robots.py's per-request guarantee used to stop
# at that transport boundary. These tests prove `_fetch` (wired through `_run`) now checks the
# SAME RobotsPolicy attached to the `client: PoliteClient` argument before every browser fetch,
# and -- critically -- BEFORE calling the injected fetcher at all, so a disallowed URL never
# reaches a real `page.goto` (a mocked fetcher stands in for the browser; none is launched here).


def test_robots_disallowed_product_path_raises_before_the_fetcher_is_called() -> None:
    disallowed_url = f"{BASE_URL}/products/stark-starter-set/"
    calls: list[str] = []

    with pytest.raises(RobotsDisallowedError) as excinfo:
        playwright_wp_strategy(
            cmon_descriptor(),
            disallowing_client("/products/stark-starter-set/"),
            {},
            context(cmon_taxonomy()),
            fetcher=fake_fetcher(calls),
            sleep=lambda s: None,
        )

    # The disallowed URL alphabetically sorts last among this fixture's 5 product URLs, so every
    # other product page (and both sitemaps, and both line pages) fetched cleanly first -- proving
    # this isn't a blanket "nothing ran" failure, only the specific disallowed URL was blocked.
    assert disallowed_url not in calls
    assert PRODUCT_SITEMAP_URL in calls
    assert LINE_SITEMAP_URL in calls
    assert excinfo.value.details["type"] == "robots-disallowed"
    assert excinfo.value.details["url"] == disallowed_url


def test_robots_disallowed_sitemap_raises_before_any_page_fetch() -> None:
    """Disallowing the product sitemap itself (the very first browser fetch after the line map)
    blocks before a single product page is ever reached."""
    calls: list[str] = []

    with pytest.raises(RobotsDisallowedError):
        playwright_wp_strategy(
            cmon_descriptor(),
            disallowing_client("/wp-sitemap-posts-products-1.xml"),
            {},
            context(cmon_taxonomy()),
            fetcher=fake_fetcher(calls),
            sleep=lambda s: None,
        )

    assert PRODUCT_SITEMAP_URL not in calls
    assert f"{BASE_URL}/products/grow-sky/" not in calls


def test_robots_allowing_policy_does_not_block_the_run() -> None:
    """Sanity check: a policy that allows everything behaves exactly like `real_client()`'s
    no-robots-attached default -- attaching a permissive policy is not itself the thing that
    changes behavior."""
    result = playwright_wp_strategy(
        cmon_descriptor(),
        disallowing_client("/nothing-here/"),
        {},
        context(cmon_taxonomy()),
        fetcher=fake_fetcher(),
        sleep=lambda s: None,
    )
    assert result.stats["product_urls_total"] == 5
    assert len(result.observations) == 4  # same as the no-robots full-sweep test


# --- Pacing --------------------------------------------------------------------------------


def test_pacing_sleeps_between_every_browser_fetch_at_declared_rps() -> None:
    """One sleep call is skipped only for the very first fetch (nothing to pace against yet);
    every subsequent fetch -- sitemaps, line pages, product pages alike -- waits. Total fetches
    here: 1 product sitemap + 1 line sitemap + 2 line pages + 5 product pages = 9, so 8 sleeps."""
    sleep_calls: list[float] = []
    result = playwright_wp_strategy(
        cmon_descriptor(),
        real_client(),
        {},
        context(cmon_taxonomy()),
        fetcher=fake_fetcher(),
        sleep=lambda s: sleep_calls.append(s),
    )
    assert result.stats["product_urls_total"] == 5  # sanity: the run actually did the work
    assert len(sleep_calls) == 8
    for wait in sleep_calls:
        assert wait > 0
        assert wait <= 2.0  # rps 0.5 -> min interval 2s


def test_pacing_uses_descriptor_rps_not_a_hardcoded_default() -> None:
    sleep_calls: list[float] = []
    fast_descriptor = cmon_descriptor()
    fast_descriptor = fast_descriptor.model_copy(update={"politeness": {"rps": 10.0}})
    playwright_wp_strategy(
        fast_descriptor,
        real_client(),
        {},
        context(cmon_taxonomy()),
        fetcher=fake_fetcher(),
        sleep=lambda s: sleep_calls.append(s),
    )
    for wait in sleep_calls:
        assert wait <= 0.1 + 1e-6  # rps 10 -> min interval 0.1s


# --- Lazy-import guard: `playwright` must never be required for the non-live path -------------


def test_strategy_runs_with_injected_fetcher_when_playwright_module_is_absent(monkeypatch) -> None:
    """`sys.modules["playwright"] = None` makes any `import playwright...` raise ImportError
    immediately (standard Python behavior for a None sentinel) without needing the real package
    uninstalled. Supplying `fetcher=` explicitly must bypass the lazy-import branch entirely, so
    the strategy runs to completion regardless."""
    monkeypatch.setitem(sys.modules, "playwright", None)
    result = playwright_wp_strategy(
        cmon_descriptor(), real_client(), {}, context(cmon_taxonomy()), fetcher=fake_fetcher(), sleep=lambda s: None
    )
    assert len(result.observations) == 4


def test_lazy_import_is_only_attempted_when_no_fetcher_is_injected(monkeypatch) -> None:
    """The mirror case: with no `fetcher=` argument and `playwright` absent, the lazy import
    inside `playwright_wp_strategy` (not this module, not `strategies/__init__.py`) is what
    raises -- proving the import genuinely is deferred to call time, not hoisted to module import
    time."""
    monkeypatch.setitem(sys.modules, "playwright", None)
    with pytest.raises(ImportError):
        playwright_wp_strategy(cmon_descriptor(), real_client(), {}, context(cmon_taxonomy()))


# --- `scope.headless` knob: reaches the (mocked) browser launcher, no real browser launched ----


def _fake_launcher(captured: dict) -> Callable[..., object]:
    @contextmanager
    def fake_launch_page_fetcher(headless: bool = True):
        captured["headless"] = headless
        yield fake_fetcher()

    return fake_launch_page_fetcher


def test_headless_defaults_to_true_when_scope_omits_it(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "warhub_acquisition.acquire.strategies._playwright_browser.launch_page_fetcher",
        _fake_launcher(captured),
    )
    result = playwright_wp_strategy(
        cmon_descriptor(), real_client(), {}, context(cmon_taxonomy()), sleep=lambda s: None
    )
    assert captured["headless"] is True
    assert result.stats["product_urls_total"] == 5  # sanity: the mocked launcher's fetcher ran


def test_headless_false_in_scope_reaches_the_browser_launcher(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "warhub_acquisition.acquire.strategies._playwright_browser.launch_page_fetcher",
        _fake_launcher(captured),
    )
    playwright_wp_strategy(
        cmon_descriptor(headless=False), real_client(), {}, context(cmon_taxonomy()), sleep=lambda s: None
    )
    assert captured["headless"] is False


def test_headless_true_explicit_in_scope_still_reaches_the_browser_launcher(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "warhub_acquisition.acquire.strategies._playwright_browser.launch_page_fetcher",
        _fake_launcher(captured),
    )
    playwright_wp_strategy(
        cmon_descriptor(headless=True), real_client(), {}, context(cmon_taxonomy()), sleep=lambda s: None
    )
    assert captured["headless"] is True


def test_module_import_itself_never_touches_playwright(monkeypatch) -> None:
    """Importing the strategies package (which registers every STRATEGIES entry, including this
    one) must succeed even with `playwright` absent -- descriptor validation and the strategy
    registry are used by every acquire run, not just CMON's."""
    monkeypatch.setitem(sys.modules, "playwright", None)
    import importlib

    import warhub_acquisition.acquire.strategies as strategies_pkg

    importlib.reload(strategies_pkg)
    assert STRATEGIES["playwright-wp"] is playwright_wp_strategy
