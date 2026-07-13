"""Real Playwright Chromium `PageFetcher` for `playwright_wp.py`. Imported lazily, ONLY when
`playwright_wp_strategy` is called with no injected `fetcher` -- see that module's docstring. Never
imported by the test suite, `strategies/__init__.py`, or descriptor validation, so `playwright` (an
OPTIONAL dependency, `[project.optional-dependencies] browser` in pyproject.toml) never needs to be
installed for anything except an actual live run of this one strategy.

Vanilla Playwright Chromium defaults only (task brief's explicit "politeness line": no stealth
plugins, no fingerprint spoofing, no custom user-agent override to impersonate a different browser
-- if CMON's Cloudflare wall blocks vanilla headless Chromium, that is a BLOCKED finding to report,
not a prompt to escalate). One browser + one page is launched and reused across every fetch in a
strategy run (sitemaps, line pages, product pages alike) -- Cloudflare's JS challenge is passed once
per browsing context, not per navigation, so reusing the same page carries the challenge's clearance
cookies across all ~346 fetches instead of re-solving it every time.

**`headless` knob** (plan-5 task-5 recon): headless Chromium is blocked 3/3 by CMON's Cloudflare
managed challenge (see `playwright_wp.py`'s module docstring / `test_live_smoke_playwright_wp.py`),
but a HEADED browser was confirmed live to clear it -- live evidence 2026-07-13: a headed
`page.goto` against the product sitemap came back `status=200`, `cf-cache-status: BYPASS`, real
37,770-byte sitemap body, no interstitial at all (no re-challenge, no `cf_clearance` cookie dance
needed). `headless` therefore defaults to `True` here (so CI / every other caller of this module
stays headless-by-default) and is threaded through from `playwright_wp_strategy`, which reads
`descriptor.scope["headless"]` (also defaulting `True`) -- `data/catalog/sources/mfr-cmon.yaml` is
the one descriptor that sets `scope.headless: false`.

**`response.text()`, not `page.content()`** (live bug found running the headed EXECUTE, 2026-07-13):
`page.content()` serializes the CURRENT DOM (`document.documentElement.outerHTML`), and Chromium
renders an `application/xml`-typed response (CMON's sitemaps) through its internal XML tree-viewer
widget rather than as a plain-text DOM -- `page.content()` on that came back an EMPTY string live
(confirmed: `status=200`, `resp.body()` had the real 37,770-byte sitemap, but `page.content()` was
`len()==0`), which silently enumerated zero products and tripped the descriptor's `minCount=272`
contract with `actual=0` -- indistinguishable from a real Cloudflare block from the caller's side.
`response.text()` (the raw HTTP response body Playwright already buffered for the main-frame
navigation, decoded per its charset) sidesteps DOM serialization entirely and was confirmed live to
return correct content for BOTH the XML sitemaps (37,770 bytes, matching `resp.body()` exactly) and
ordinary HTML product pages (74,948 bytes; `page.content()`'s 76,311 differed only by Chromium's own
whitespace/DOCTYPE reformatting, not missing content) -- so this is a strict, mimetype-agnostic
improvement, not a headed-only workaround.

**The two bugs above are INDEPENDENT, and the headless block is REAL.** Directly probed 2026-07-13
AFTER the `response.text()` fix landed: `headless=True` still gets Cloudflare's challenge on both
URLs (sitemap 6,221 bytes / ZERO `<loc>` tags, product page 6,200 bytes / no `<h1>`, both containing
"Just a moment") while `headless=False` gets the real 37,770-byte sitemap and a full product page.
So the fetcher bug did NOT cause (nor even contribute to) the original BLOCKED verdict -- that
verdict was correct on its own terms, and `headless=False` is genuinely load-bearing, not a
cargo-culted workaround for the XML bug. Consequence: CMON CANNOT run in headless CI. It is a
local-only source until Cloudflare's policy changes.
"""
from contextlib import contextmanager
from typing import Iterator

from warhub_acquisition.acquire.client import FetchError

_NAV_TIMEOUT_MS = 30_000


@contextmanager
def launch_page_fetcher(headless: bool = True) -> Iterator["PageFetcher"]:  # noqa: F821 (PageFetcher is a Callable alias, not importable here)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            page = browser.new_page()

            def fetch(url: str) -> str:
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
                except Exception as exc:  # noqa: BLE001 -- any Playwright navigation failure -> FetchError
                    raise FetchError(url, None) from exc
                if response is None:
                    raise FetchError(url, None)
                return response.text()

            yield fetch
        finally:
            browser.close()
