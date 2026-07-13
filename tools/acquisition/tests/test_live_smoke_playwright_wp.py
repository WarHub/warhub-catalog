"""Live smoke test: a real, small, browser-driven acquire run against mfr-cmon.

Opt-in only (`@pytest.mark.live`, excluded by default via pyproject's `addopts = "-m 'not
live'"`). Run explicitly with `uv run pytest -m live -q` -- requires the `browser` optional extra
installed (`uv sync --extra browser`) AND `playwright install chromium` having been run once, since
this exercises the REAL `_playwright_browser.py` fetcher (no injected fake), unlike every other
test in `test_strategy_playwright_wp.py`.

Deliberately NOT a full 320-product sweep (that is the task's separate EXECUTE step, run directly
via the CLI against the real `data/` directory -- see task-10-report.md, ~11-12 minutes at rps
0.5). Standing up a tiny dedicated test sitemap isn't possible against the real live site, so this
smoke test instead points BOTH `descriptor.scope["productSitemap"]` and `["lineSitemap"]` at the
real, small `wp-sitemap-posts-products-line-1.xml` (24 real URLs) -- the strategy then treats each
real product-line page as if it were both a line page (building the slug->line map from its member
links) AND a "product" page (its own `<h1>` becomes an observation's `name`); this exercises the
real Chromium fetcher against ~50 real live fetches (2 sitemap + 24 line-page + 24 "product-page"
requests, same URLs reused for both roles) in under 2 minutes rather than the full run's 346, while
still proving Cloudflare's JS challenge is passed live end-to-end (enumeration, pacing, extraction,
manufacturer pinning). The join-to-real-products path (a genuine `/products/<slug>/` page correctly
picking up its line's name) is already covered offline/deterministically by
`test_strategy_playwright_wp.py`'s real fixtures. Uses a tmp_path evidence dir so nothing here
touches the repo's real evidence/cursor state.

**UNBLOCKED as of plan-5 task-5 (2026-07-13).** History: with `headless=True`, vanilla
`playwright.chromium.launch()` + `page.goto(...)` against `wp-sitemap-posts-products-line-1.xml`
returned Cloudflare's "Just a moment..." managed-challenge interstitial (a normal 200 HTML response,
title "Just a moment...", zero `<loc>` tags) on 3/3 independent attempts, with no `cf_clearance` (or
any) cookie ever set -- so this test was `xfail`ed as BLOCKED (task-10-report.md). A **headed**
browser clears that same challenge outright: live 2026-07-13, `headless=False` + `page.goto` on the
product sitemap returned `status=200`, `cf-cache-status: BYPASS`, and the real 37,770-byte sitemap
body with no interstitial at all. `mfr-cmon.yaml` therefore now carries `scope.headless: false`
(the knob defaults True everywhere else, so CI stays headless), and the full 320-product EXECUTE run
came back clean: 320/320 pages fetched, 0 fetch_errors, 0 extraction_failed_name. The `xfail` is
consequently REMOVED -- this test is expected to pass on the live path now.

(Two Cloudflare-adjacent traps this test would NOT have caught on its own, both fixed in
`_playwright_browser.py`: `page.content()` returns an EMPTY string for an `application/xml` response
because Chromium renders XML through its tree-viewer widget rather than as a plain-text DOM -- which
enumerated zero products and looked *exactly* like a Cloudflare block from the caller's side, right
down to tripping `minCount=272` with `actual=0`. The fetcher now uses `response.text()`, the raw
buffered HTTP body, which is correct for both XML and HTML. Politeness line still held throughout:
no stealth plugins, no fingerprint spoofing, no UA impersonation -- just a visible window.)
"""
from pathlib import Path

import pytest  # noqa: F401  (kept: `pytest.mark.live` below + `pytest.skip` in the test body)

from warhub_acquisition.acquire.runner import AcquireContext, load_mappings, run_source
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import SourceDescriptor, load_descriptors
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy

REPO_DATA = Path(__file__).resolve().parents[3] / "data"


@pytest.mark.live
def test_live_cmon_small_sweep_passes_cloudflare_and_extracts_real_products(tmp_path: Path) -> None:
    if not REPO_DATA.exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")

    import warhub_acquisition.acquire.strategies  # noqa: F401  (registers STRATEGIES["playwright-wp"])

    repo_paths = DataPaths(REPO_DATA)
    descriptor = load_descriptors(repo_paths.sources)["mfr-cmon"]
    # Real single-product-line sitemap: a tiny, real, live CMON sitemap covering exactly the
    # Massive Darkness line's own page (1 line page + its few member products) instead of the
    # full 320-product/24-line population -- keeps the smoke test to a couple dozen fetches at
    # most, at the descriptor's own rps 0.5.
    # No `contract=` -- the real descriptor's minCount=272 gate would fail this deliberately-tiny
    # smoke run.
    smoke_descriptor = SourceDescriptor(
        id=descriptor.id,
        kind=descriptor.kind,
        strategy=descriptor.strategy,
        baseUrl=descriptor.baseUrl,
        scope={
            **descriptor.scope,
            "productSitemap": f"{descriptor.baseUrl}/wp-sitemap-posts-products-line-1.xml",
            "lineSitemap": f"{descriptor.baseUrl}/wp-sitemap-posts-products-line-1.xml",
        },
        politeness=descriptor.politeness,
    )

    taxonomy = Taxonomy.load(repo_paths.taxonomy)
    mappings = load_mappings(repo_paths.mappings)
    context = AcquireContext(taxonomy=taxonomy, mappings=mappings, run_date="2026-07-13", budget=None)

    tmp_paths = DataPaths(tmp_path)  # real network, but evidence/cursor land in a tmp dir
    health = run_source(smoke_descriptor, tmp_paths, context)

    assert health.observation_count >= 1
    assert health.stats["fetch_errors"] == 0

    observations = EvidenceStore(tmp_paths.evidence_products).load("mfr-cmon")
    assert observations
    for observation in observations.values():
        assert observation.name
        assert observation.manufacturer == "cmon"
        assert observation.ean is None
        assert observation.sku is None
