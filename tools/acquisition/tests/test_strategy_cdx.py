"""cdx-archive strategy: Wayback CDX enumeration (paging, local filtering, urlkey dedupe-newest,
cursor re-enumeration gating), budgeted `id_`-form snapshot fetches, and the two extractors
(archived Shopify JSON-LD, old-GW-webstore legacy HTML).

Fixture provenance (`tests/fixtures/cdx/`), all captured LIVE 2026-07-13 via curl at <=1 req/s (4
requests total) -- see `docs/research/2026-07-12-source-probe-webarchive.md` for the probe this is
built from and `cdx_archive.py`'s module docstring for full detail:

- `goblin-cdx-page.json`: real CDX page for `goblingaming.co.uk/products/*`, trimmed from ~800
  rows to ~20 (header row kept), including a real 404 and a real `statuscode: "-"` row.
- `goblin-shownumpages.txt`: real `showNumPages=true` response body -- the literal `8`.
- `goblin-archived-product.html`: the archived `/products/1-x-large-flying-stand` page the probe
  doc cites, fetched via the `id_` form (verified live: zero `web.archive.org` link-rewriting in
  the body) and trimmed to its JSON-LD block + a body skeleton. Real `gtin13: 5060504044745`,
  `sku: "BRFLY"`, `brand: "TT COMBAT"`.
- `gw-legacy-product.html`: the probe doc's `10-man-kill-team` 2016 capture, `id_` form, trimmed
  to the primary product's title/skuid/price block. Real `data-skuid="99020109002"`, `£44`, title
  `"10-Man Kill Team | Games Workshop Webstore"`.
"""
from pathlib import Path

import httpx
import pytest

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, run_source
from warhub_acquisition.acquire.strategies.cdx_archive import (
    _enumerate_cdx,
    _extract_gw_legacy,
    _show_num_pages,
    cdx_archive_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "cdx"
WAYBACK_BASE = "https://web.archive.org"

# Real values captured live 2026-07-13 (see module docstring).
GOBLIN_GTIN13 = "5060504044745"
GOBLIN_SKU = "BRFLY"
GOBLIN_NAME = "1 x Large Flying Stand"
GOBLIN_ORIGINAL = "https://www.goblingaming.co.uk/products/1-x-large-flying-stand"
GOBLIN_TIMESTAMP = "20210624021531"

GW_CODE = "99020109002"
GW_NAME = "10-Man Kill Team"
GW_PRICE_GBP = 44.0
GW_ORIGINAL = "https://www.games-workshop.com/en-GB/10-man-kill-team"
GW_TIMESTAMP = "20160826220543"


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "games-workshop": Manufacturer(
                slug="games-workshop",
                name="Games Workshop",
                gs1Prefixes=["5011921"],
                vendorNames=["Games Workshop", "Citadel", "Forge World"],
            ),
            "tt-combat": Manufacturer(
                slug="tt-combat", name="TT Combat", gs1Prefixes=["5060504"], vendorNames=["TT COMBAT"]
            ),
        }
    )


def context(budget: int | None = None, run_date: str = "2026-07-13") -> AcquireContext:
    return AcquireContext(taxonomy=taxonomy(), mappings={}, run_date=run_date, budget=budget)


def goblin_descriptor(**scope_overrides: object) -> SourceDescriptor:
    scope: dict[str, object] = {
        "cdxUrlPattern": "goblingaming.co.uk/products/*",
        "urlInclude": r"/products/1-x-large-flying-stand$",
        "extractor": "shopify-jsonld",
        "snapshotFrom": "2014",
        "snapshotTo": "2021",
    }
    scope.update(scope_overrides)
    return SourceDescriptor(
        id="arch-goblingaming", kind="archive", strategy="cdx-archive", baseUrl=WAYBACK_BASE, scope=scope
    )


def gw_descriptor(**scope_overrides: object) -> SourceDescriptor:
    scope: dict[str, object] = {
        "cdxUrlPattern": "games-workshop.com/en-GB/*",
        "urlInclude": r"/en-GB/10-man-kill-team$",
        "extractor": "gw-legacy",
        "manufacturer": "Games Workshop",
        "snapshotFrom": "2014",
        "snapshotTo": "2019",
    }
    scope.update(scope_overrides)
    return SourceDescriptor(
        id="arch-gw-legacy", kind="archive", strategy="cdx-archive", baseUrl=WAYBACK_BASE, scope=scope
    )


GOBLIN_SNAPSHOT_PATH = f"/web/{GOBLIN_TIMESTAMP}id_/{GOBLIN_ORIGINAL}"
GW_SNAPSHOT_PATH = f"/web/{GW_TIMESTAMP}id_/{GW_ORIGINAL}"

GW_CDX_PAGE = (
    '[["original","timestamp","statuscode"],'
    f'["{GW_ORIGINAL}","{GW_TIMESTAMP}","200"]]'
)


def goblin_transport(
    calls: list[str] | None = None, num_pages: int = 1, product_response: httpx.Response | None = None
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        params = request.url.params
        if path == "/cdx/search/cdx":
            if params.get("showNumPages") == "true":
                return httpx.Response(200, text=str(num_pages))
            return httpx.Response(200, text=load_text("goblin-cdx-page.json"))
        if path == GOBLIN_SNAPSHOT_PATH:
            if product_response is not None:
                return product_response
            return httpx.Response(200, text=load_text("goblin-archived-product.html"))
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def gw_transport(calls: list[str] | None = None, product_response: httpx.Response | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        params = request.url.params
        if path == "/cdx/search/cdx":
            if params.get("showNumPages") == "true":
                return httpx.Response(200, text="1")
            return httpx.Response(200, text=GW_CDX_PAGE)
        if path == GW_SNAPSHOT_PATH:
            if product_response is not None:
                return product_response
            return httpx.Response(200, text=load_text("gw-legacy-product.html"))
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def test_strategy_is_registered() -> None:
    assert STRATEGIES["cdx-archive"] is cdx_archive_strategy


# --- showNumPages parsing (real captured fixture) -----------------------------------------------


def test_show_num_pages_parses_real_captured_plain_text_body() -> None:
    """showNumPages=true's body is bare plain text, not JSON -- real captured body was the
    literal `8\\n` (curl output), confirmed live 2026-07-12 for goblingaming.co.uk/products/*."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=load_text("goblin-shownumpages.txt"))

    client = PoliteClient(WAYBACK_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert _show_num_pages(client, goblin_descriptor(), {"url": "goblingaming.co.uk/products/*"}) == 8


def test_show_num_pages_zero_body_is_a_valid_empty_index() -> None:
    """A literal `0` (with the trailing newline curl output has) means a genuinely-empty CDX
    index -- must return 0, not raise. Fix wave 1 regression guard alongside the garbled-body
    test below: zero-pages-because-empty and zero-pages-because-garbled must NOT be conflated."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="0\n")

    client = PoliteClient(WAYBACK_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert _show_num_pages(client, goblin_descriptor(), {"url": "goblingaming.co.uk/products/*"}) == 0


def test_show_num_pages_garbled_body_raises_value_error_naming_source_url_and_body() -> None:
    """Fix wave 1 (review finding, Task 2): a non-numeric showNumPages body must raise, not
    silently return 0 -- see `_show_num_pages`'s docstring for why a silent 0 is dangerous
    (indistinguishable from a real empty index, suppresses re-enumeration for a month)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>oops")

    client = PoliteClient(WAYBACK_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(ValueError) as excinfo:
        _show_num_pages(client, goblin_descriptor(), {"url": "goblingaming.co.uk/products/*"})
    message = str(excinfo.value)
    assert "arch-goblingaming" in message  # source id
    assert "showNumPages" in message
    assert "<html>oops" in message  # truncated repr of the garbled body


def test_show_num_pages_negative_body_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="-3")

    client = PoliteClient(WAYBACK_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(ValueError):
        _show_num_pages(client, goblin_descriptor(), {"url": "goblingaming.co.uk/products/*"})


def test_count_request_sends_exactly_url_bounds_and_shownumpages_only() -> None:
    """Fix wave 2 (live-run defect, controller-verified 2026-07-13): the count query must carry
    ONLY url + from/to + showNumPages=true. Live CDX behavior: `output=json` alongside
    showNumPages makes Wayback ignore showNumPages and return the full ~224KB DATA page;
    `fl=`/`collapse=` return garbage (`- - -`). The previous tests routed the mock by path and
    `params.get("showNumPages")` alone, which masked any extra params riding along -- this
    asserts the EXACT param set on the wire, via a full strategy run."""
    count_requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if request.url.path == "/cdx/search/cdx":
            if params.get("showNumPages") == "true":
                count_requests.append(dict(params))
                return httpx.Response(200, text="1")
            return httpx.Response(200, text=load_text("goblin-cdx-page.json"))
        if request.url.path == GOBLIN_SNAPSHOT_PATH:
            return httpx.Response(200, text=load_text("goblin-archived-product.html"))
        raise AssertionError(f"unexpected request: {request.url}")

    client = PoliteClient(WAYBACK_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    cdx_archive_strategy(goblin_descriptor(), client, {}, context())

    assert count_requests == [
        {
            "url": "goblingaming.co.uk/products/*",
            "from": "2014",
            "to": "2021",
            "showNumPages": "true",
        }
    ]


def test_show_num_pages_whitelists_params_even_from_a_polluted_base_params_dict() -> None:
    """Structural guard for the fix-wave-2 whitelist: even if a future refactor grows extra keys
    (output/collapse/fl/...) into the base_params dict passed in, the count request on the wire
    must still carry only url + from/to + showNumPages."""
    seen_params: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, text="3")

    client = PoliteClient(WAYBACK_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    polluted = {
        "url": "goblingaming.co.uk/products/*",
        "from": "2014",
        "to": "2021",
        "output": "json",
        "collapse": "urlkey",
        "fl": "original,timestamp,statuscode",
    }
    assert _show_num_pages(client, goblin_descriptor(), polluted) == 3
    assert seen_params == [
        {
            "url": "goblingaming.co.uk/products/*",
            "from": "2014",
            "to": "2021",
            "showNumPages": "true",
        }
    ]


def test_garbled_shownumpages_via_full_strategy_run_does_not_poison_cursor(tmp_path: Path) -> None:
    """End-to-end (via `run_source`, matching `cli.py`'s call path): a garbled showNumPages body
    must raise ValueError uncaught, and -- because `run_source` only writes the cursor AFTER the
    strategy call returns -- the cursor file for this source must never be written. This is the
    "no cache poisoning" guarantee: a transient garbled 200 must never get cached as
    `cdx_num_pages=0` and silently suppress enumeration for `reEnumerateAfterDays`."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            # Permissive (no robots.txt published) -- keeps this test focused on the garbled
            # showNumPages body, not the robots preflight (see tests/test_robots.py for that).
            return httpx.Response(404)
        if request.url.path == "/cdx/search/cdx" and request.url.params.get("showNumPages") == "true":
            return httpx.Response(200, text="<html>oops")
        raise AssertionError(f"unexpected request: {request.url}")

    paths = DataPaths(tmp_path)
    desc = goblin_descriptor()

    with pytest.raises(ValueError) as excinfo:
        run_source(desc, paths, context(), transport=httpx.MockTransport(handler))

    assert "arch-goblingaming" in str(excinfo.value)
    assert not (paths.evidence_products / "arch-goblingaming" / "cursor.yaml").exists()
    assert not (paths.evidence_products / "arch-goblingaming" / "observations.jsonl").exists()


# --- CDX enumeration: paging + local filtering + urlkey dedupe-newest ---------------------------


def test_enumerate_cdx_pages_filters_locally_and_dedupes_by_path_keeping_newest() -> None:
    page0 = (
        '[["original","timestamp","statuscode"],'
        '["https://example.test/products/widget-a","20180101000000","200"],'
        '["https://example.test/products/widget-b","20190101000000","200"],'
        '["https://example.test/products/widget-c","20200101000000","404"]]'
    )
    page1 = (
        '[["original","timestamp","statuscode"],'
        # newer capture of widget-a on a later page -- dedupe must keep THIS one
        '["https://example.test/products/widget-a","20210101000000","200"],'
        # excluded by urlInclude (not under /products/)
        '["https://example.test/other/not-a-product","20210101000000","200"],'
        # excluded: statuscode "-" (not "200")
        '["https://example.test/products/widget-d","20220101000000","-"]]'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("showNumPages") == "true":
            return httpx.Response(200, text="2")
        page = params.get("page")
        return httpx.Response(200, text=page0 if page == "0" else page1)

    client = PoliteClient(WAYBACK_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    descriptor = SourceDescriptor(
        id="arch-test",
        kind="archive",
        strategy="cdx-archive",
        baseUrl=WAYBACK_BASE,
        scope={"cdxUrlPattern": "example.test/*", "urlInclude": r"/products/", "extractor": "shopify-jsonld"},
    )
    stats = {"cdx_pages_fetched": 0}
    index, pages_fetched, num_pages = _enumerate_cdx(client, descriptor, stats)

    assert pages_fetched == 2
    assert num_pages == 2
    assert stats["cdx_pages_fetched"] == 2
    assert set(index) == {"/products/widget-a", "/products/widget-b"}
    assert index["/products/widget-a"] == {
        "original": "https://example.test/products/widget-a",
        "timestamp": "20210101000000",  # newest of the two captures kept
    }
    assert index["/products/widget-b"]["timestamp"] == "20190101000000"


def test_enumerate_cdx_against_real_goblin_fixture_filters_404_and_dash_statuscodes() -> None:
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(), sleep=lambda s: None)
    descriptor = goblin_descriptor(urlInclude=None)
    stats = {"cdx_pages_fetched": 0}
    index, pages_fetched, num_pages = _enumerate_cdx(client, descriptor, stats)

    assert pages_fetched == 1
    assert num_pages == 1
    # real fixture: header + 1 "#a" 404 row + 20 status-200 rows + 1 statuscode "-" row = 22 data rows
    assert len(index) == 20
    assert "/products/1-x-large-flying-stand" in index
    assert index["/products/1-x-large-flying-stand"] == {"original": GOBLIN_ORIGINAL, "timestamp": GOBLIN_TIMESTAMP}
    # the 404 and "-" rows must never appear
    assert "/products/%23a" not in index
    assert "/products/1.00" not in index


# --- Cursor caching: re-enumeration gating -------------------------------------------------------


def test_second_run_within_reenumerate_window_makes_no_cdx_requests() -> None:
    calls: list[str] = []
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(calls), sleep=lambda s: None)
    first = cdx_archive_strategy(goblin_descriptor(), client, {}, context(run_date="2026-07-13"))
    assert any("/cdx/search/cdx" in c for c in calls)
    assert first.cursor["last_enumerated"] == "2026-07-13"

    calls.clear()
    second = cdx_archive_strategy(
        goblin_descriptor(), client, first.cursor, context(run_date="2026-07-20")
    )
    assert not any("/cdx/search/cdx" in c for c in calls)  # cached url_index reused, no re-enumeration
    assert second.stats["cdx_pages_fetched"] == 0
    assert second.cursor["last_enumerated"] == "2026-07-13"  # unchanged


def test_reenumerates_once_reenumerate_after_days_elapses() -> None:
    old_cursor = {
        "url_index": {"/products/1-x-large-flying-stand": {"original": GOBLIN_ORIGINAL, "timestamp": GOBLIN_TIMESTAMP}},
        "cdx_pages_fetched": 1,
        "cdx_num_pages": 1,
        "last_enumerated": "2026-06-01",  # 42 days before the run below
        "fetched": {},
    }
    calls: list[str] = []
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(calls), sleep=lambda s: None)
    result = cdx_archive_strategy(
        goblin_descriptor(reEnumerateAfterDays=30), client, old_cursor, context(run_date="2026-07-13")
    )
    assert any("/cdx/search/cdx" in c for c in calls)
    assert result.cursor["last_enumerated"] == "2026-07-13"


def test_does_not_reenumerate_before_reenumerate_after_days_elapses() -> None:
    old_cursor = {
        "url_index": {"/products/1-x-large-flying-stand": {"original": GOBLIN_ORIGINAL, "timestamp": GOBLIN_TIMESTAMP}},
        "cdx_pages_fetched": 1,
        "cdx_num_pages": 1,
        "last_enumerated": "2026-06-20",  # 23 days before the run below, under the 30-day default
        "fetched": {},
    }
    calls: list[str] = []
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(calls), sleep=lambda s: None)
    result = cdx_archive_strategy(goblin_descriptor(), client, old_cursor, context(run_date="2026-07-13"))
    assert not any("/cdx/search/cdx" in c for c in calls)
    assert result.cursor["last_enumerated"] == "2026-06-20"


def test_reenumerates_when_prior_enumeration_was_incomplete() -> None:
    old_cursor = {
        "url_index": {"/products/1-x-large-flying-stand": {"original": GOBLIN_ORIGINAL, "timestamp": GOBLIN_TIMESTAMP}},
        "cdx_pages_fetched": 1,  # fewer than cdx_num_pages -> incomplete
        "cdx_num_pages": 3,
        "last_enumerated": "2026-07-13",  # same day -- would NOT trigger the age check
        "fetched": {},
    }
    calls: list[str] = []
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(calls), sleep=lambda s: None)
    cdx_archive_strategy(goblin_descriptor(), client, old_cursor, context(run_date="2026-07-13"))
    assert any("/cdx/search/cdx" in c for c in calls)


def test_reenumerate_after_days_explicit_zero_means_always_reenumerate() -> None:
    """Regression: `scope.get(...) or DEFAULT` would silently treat an explicit `0` (falsy) as
    "unset" and fall back to the 30-day default -- `reEnumerateAfterDays: 0` must mean "always
    re-enumerate," not "wait 30 days."""
    old_cursor = {
        "url_index": {"/products/1-x-large-flying-stand": {"original": GOBLIN_ORIGINAL, "timestamp": GOBLIN_TIMESTAMP}},
        "cdx_pages_fetched": 1,
        "cdx_num_pages": 1,
        "last_enumerated": "2026-07-13",  # same day as the run below
        "fetched": {},
    }
    calls: list[str] = []
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(calls), sleep=lambda s: None)
    cdx_archive_strategy(
        goblin_descriptor(reEnumerateAfterDays=0), client, old_cursor, context(run_date="2026-07-13")
    )
    assert any("/cdx/search/cdx" in c for c in calls)


def test_first_run_with_empty_cursor_always_enumerates() -> None:
    calls: list[str] = []
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(calls), sleep=lambda s: None)
    cdx_archive_strategy(goblin_descriptor(), client, {}, context())
    assert any("/cdx/search/cdx" in c for c in calls)


# --- Budget / priority (never-fetched, then oldest-fetched) --------------------------------------


def test_budget_caps_snapshot_fetches() -> None:
    calls: list[str] = []
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(calls), sleep=lambda s: None)
    result = cdx_archive_strategy(goblin_descriptor(), client, {}, context(budget=0))
    assert result.stats["snapshots_fetched"] == 0
    assert not any(GOBLIN_SNAPSHOT_PATH in c for c in calls)


def test_never_fetched_is_prioritized_before_oldest_fetched() -> None:
    """Two filtered URLs (`1-x-large-flying-stand` and `10-gift-card`), pre-seeded url_index with
    `last_enumerated` fresh + complete so no re-enumeration triggers this run (exercises the
    fetch-priority queue in isolation); one already in the cursor's `fetched` map and budget=1 --
    the never-fetched path must win priority."""
    old_cursor = {
        "url_index": {
            "/products/1-x-large-flying-stand": {"original": GOBLIN_ORIGINAL, "timestamp": GOBLIN_TIMESTAMP},
            "/products/10-gift-card": {
                "original": "https://www.goblingaming.co.uk/products/10-gift-card",
                "timestamp": "20220810182744",
            },
        },
        "cdx_pages_fetched": 1,
        "cdx_num_pages": 1,
        "last_enumerated": "2026-07-13",
        "fetched": {"/products/10-gift-card": "2020-01-01"},
    }
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == GOBLIN_SNAPSHOT_PATH:
            return httpx.Response(200, text=load_text("goblin-archived-product.html"))
        raise AssertionError(f"unexpected request: {request.url}")

    client = PoliteClient(WAYBACK_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = cdx_archive_strategy(
        goblin_descriptor(urlInclude=None), client, old_cursor, context(budget=1, run_date="2026-07-13")
    )
    assert result.stats["snapshots_fetched"] == 1
    fetched_paths = set(result.cursor["fetched"]) - {"/products/10-gift-card"}
    # the never-fetched path (flying-stand) must be the one snapshot-fetched this run, not the
    # already-fetched (however-stale) gift-card path.
    assert fetched_paths == {"/products/1-x-large-flying-stand"}
    assert result.cursor["fetched"]["/products/10-gift-card"] == "2020-01-01"  # untouched, stayed stale


# --- shopify-jsonld extractor: real fixture -------------------------------------------------------


def test_shopify_jsonld_extracts_real_gtin_sku_name_from_real_archived_fixture() -> None:
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(), sleep=lambda s: None)
    result = cdx_archive_strategy(goblin_descriptor(), client, {}, context())

    assert result.stats["snapshots_fetched"] == 1
    assert result.stats["eans_found"] == 1
    assert result.stats["extraction_failed"] == 0
    assert result.stats["skipped_unknown_manufacturer"] == 0

    by_key = {o.key: o for o in result.observations}
    assert list(by_key) == ["arch-goblingaming:/products/1-x-large-flying-stand"]
    obs = by_key["arch-goblingaming:/products/1-x-large-flying-stand"]
    assert obs.name == GOBLIN_NAME
    assert obs.sku == GOBLIN_SKU
    assert obs.ean == GOBLIN_GTIN13
    assert obs.manufacturer == "tt-combat"
    assert obs.url == GOBLIN_ORIGINAL  # ORIGINAL live url, never the wayback replay url
    assert obs.archived is True
    assert obs.hints["archiveTimestamp"] == GOBLIN_TIMESTAMP
    assert obs.availability is None
    assert obs.extractor == "cdx-archive@1"
    assert result.full_sweep is False


def test_shopify_jsonld_gs1_prefix_fallback_when_brand_unresolvable() -> None:
    unbranded_html = load_text("goblin-archived-product.html").replace(
        '"name": "TT COMBAT"', '"name": "Some Unknown Reseller"'
    )
    client = PoliteClient(
        WAYBACK_BASE,
        transport=goblin_transport(product_response=httpx.Response(200, text=unbranded_html)),
        sleep=lambda s: None,
    )
    result = cdx_archive_strategy(goblin_descriptor(), client, {}, context())
    obs = result.observations[0]
    assert obs.manufacturer == "tt-combat"  # via GS1 prefix "5060504", not vendor name


def test_shopify_jsonld_skips_and_counts_unknown_brand_and_gs1_prefix() -> None:
    unresolvable_html = (
        load_text("goblin-archived-product.html")
        .replace('"name": "TT COMBAT"', '"name": "Totally Unknown Brand"')
        .replace("5060504044745", "9999999999999")
    )
    client = PoliteClient(
        WAYBACK_BASE,
        transport=goblin_transport(product_response=httpx.Response(200, text=unresolvable_html)),
        sleep=lambda s: None,
    )
    result = cdx_archive_strategy(goblin_descriptor(), client, {}, context())
    assert result.observations == []
    assert result.stats["skipped_unknown_manufacturer"] == 1
    # the snapshot was still fetched successfully -- counts toward "fetched" cursor bookkeeping
    assert "/products/1-x-large-flying-stand" in result.cursor["fetched"]


def test_shopify_jsonld_extraction_failed_when_no_product_node() -> None:
    client = PoliteClient(
        WAYBACK_BASE,
        transport=goblin_transport(product_response=httpx.Response(200, text="<html><body>nothing</body></html>")),
        sleep=lambda s: None,
    )
    result = cdx_archive_strategy(goblin_descriptor(), client, {}, context())
    assert result.observations == []
    assert result.stats["extraction_failed"] == 1


# --- gw-legacy extractor: real fixture -------------------------------------------------------------


def test_gw_legacy_extraction_unit_from_real_fixture() -> None:
    html = load_text("gw-legacy-product.html")
    record = _extract_gw_legacy(html)
    assert record == {"code": GW_CODE, "name": GW_NAME, "priceGbp": GW_PRICE_GBP}


def test_gw_legacy_strategy_extracts_real_code_name_price_from_real_archived_fixture() -> None:
    client = PoliteClient(WAYBACK_BASE, transport=gw_transport(), sleep=lambda s: None)
    result = cdx_archive_strategy(gw_descriptor(), client, {}, context())

    assert result.stats["codes_found"] == 1
    assert result.stats["extraction_failed"] == 0
    assert result.stats["skipped_unknown_manufacturer"] == 0

    by_key = {o.key: o for o in result.observations}
    assert list(by_key) == ["arch-gw-legacy:/en-GB/10-man-kill-team"]
    obs = by_key["arch-gw-legacy:/en-GB/10-man-kill-team"]
    assert obs.name == GW_NAME
    assert obs.sku == GW_CODE
    assert obs.ean is None  # old-GW pages carry no barcode at all -- joined in elsewhere
    assert obs.priceGbp == GW_PRICE_GBP
    assert obs.manufacturer == "games-workshop"
    assert obs.url == GW_ORIGINAL
    assert obs.archived is True
    assert obs.hints["archiveTimestamp"] == GW_TIMESTAMP
    assert obs.availability is None
    assert obs.extractor == "cdx-archive@1"
    assert result.full_sweep is False


def test_gw_legacy_pinned_manufacturer_unresolvable_skips_and_counts() -> None:
    client = PoliteClient(WAYBACK_BASE, transport=gw_transport(), sleep=lambda s: None)
    result = cdx_archive_strategy(gw_descriptor(manufacturer="Nonexistent Brand"), client, {}, context())
    assert result.observations == []
    assert result.stats["skipped_unknown_manufacturer"] == 1


def test_gw_legacy_extraction_failed_when_no_skuid_present() -> None:
    client = PoliteClient(
        WAYBACK_BASE,
        transport=gw_transport(product_response=httpx.Response(200, text="<html><title>Nothing</title></html>")),
        sleep=lambda s: None,
    )
    result = cdx_archive_strategy(gw_descriptor(), client, {}, context())
    assert result.observations == []
    assert result.stats["extraction_failed"] == 1


# --- FetchError continue --------------------------------------------------------------------------


def test_fetch_error_on_snapshot_counts_and_continues_and_stays_queued() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = request.url.params
        if path == "/cdx/search/cdx":
            if params.get("showNumPages") == "true":
                return httpx.Response(200, text="1")
            return httpx.Response(200, text=load_text("goblin-cdx-page.json"))
        if path == GOBLIN_SNAPSHOT_PATH:
            return httpx.Response(500, text="down")  # retried 3x by PoliteClient, still fails
        raise AssertionError(f"unexpected request: {request.url}")

    client = PoliteClient(WAYBACK_BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = cdx_archive_strategy(goblin_descriptor(), client, {}, context())

    assert result.stats["fetch_errors"] == 1
    assert result.observations == []
    assert "/products/1-x-large-flying-stand" not in result.cursor["fetched"]
    assert result.full_sweep is False


# --- full_sweep always False -----------------------------------------------------------------------


def test_full_sweep_is_always_false() -> None:
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(), sleep=lambda s: None)
    result = cdx_archive_strategy(goblin_descriptor(), client, {}, context(budget=None))
    assert result.full_sweep is False


# --- Wayback URL construction (id_ form) ------------------------------------------------------------


def test_snapshot_fetch_uses_id_underscore_raw_form() -> None:
    calls: list[str] = []
    client = PoliteClient(WAYBACK_BASE, transport=goblin_transport(calls), sleep=lambda s: None)
    cdx_archive_strategy(goblin_descriptor(), client, {}, context())
    snapshot_calls = [c for c in calls if "/web/" in c]
    assert snapshot_calls == [f"{WAYBACK_BASE}{GOBLIN_SNAPSHOT_PATH}"]
    assert f"/web/{GOBLIN_TIMESTAMP}id_/" in snapshot_calls[0]
