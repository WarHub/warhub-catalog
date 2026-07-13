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
"""
from contextlib import contextmanager
from typing import Iterator

from warhub_acquisition.acquire.client import FetchError

_NAV_TIMEOUT_MS = 30_000


@contextmanager
def launch_page_fetcher() -> Iterator["PageFetcher"]:  # noqa: F821 (PageFetcher is a Callable alias, not importable here)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()

            def fetch(url: str) -> str:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
                except Exception as exc:  # noqa: BLE001 -- any Playwright navigation failure -> FetchError
                    raise FetchError(url, None) from exc
                return page.content()

            yield fetch
        finally:
            browser.close()
