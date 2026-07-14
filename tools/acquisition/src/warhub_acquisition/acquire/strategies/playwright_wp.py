"""Browser-driven WordPress strategy: CMON (cmon.com), a Cloudflare-walled marketing site with
no store API, no barcodes, no prices -- names, product lines, and hero images only.

Registered as `STRATEGIES["playwright-wp"]`. Live evidence (2026-07-13, see task-10-report.md):
CMON is WordPress behind Cloudflare's JS challenge -- curl/httpx get a 403 on every page, INCLUDING
the sitemap XML (`wp-sitemap-posts-products-1.xml`, 320 `<url>` entries; the site also has a 24-URL
`wp-sitemap-posts-products-line-1.xml` for its custom `products-line` post type). A real,
JS-executing browser passes the challenge and gets normal 200s. This strategy therefore never
touches `PoliteClient`/httpx at all for its own fetches (it still receives one, per the `Strategy`
call signature, but does not use it) -- every fetch, sitemap XML included, goes through an injected
`PageFetcher`.

**The browser is an injected seam, not a hard dependency.** `PageFetcher = Callable[[str], str]`
(URL -> page HTML/XML text, raising `warhub_acquisition.acquire.client.FetchError` on failure) is
the entire contract. Every test in this module supplies a fake fetcher backed by fixture files --
`playwright` is never imported by the test suite, this module's own top level, or descriptor
validation/registration (`STRATEGIES["playwright-wp"] = playwright_wp_strategy` below runs at
import time and must not require the browser). The REAL implementation
(`acquire/strategies/_playwright_browser.py`, a Chromium `page.goto` + `page.content()` fetcher)
lives in a separate module and is imported lazily, ONLY inside `playwright_wp_strategy` when no
`fetcher` argument was supplied -- so `import warhub_acquisition.acquire.strategies` (which
registers every strategy, this one included) succeeds with `playwright` absent, and only actually
touches it if this specific strategy is run for real. `playwright` is declared as the OPTIONAL
`[project.optional-dependencies] browser` extra in pyproject.toml, not a base dependency, for the
same reason.

**Enumeration**: two sitemaps, both fetched through the browser (`descriptor.scope["productSitemap"]`
/ `descriptor.scope["lineSitemap"]`, defaulting to
`{baseUrl}/wp-sitemap-posts-products-1.xml` / `{baseUrl}/wp-sitemap-posts-products-line-1.xml`).
`<loc>` values are pulled with a plain regex (no XML parser -- CMON's sitemap is a flat `<urlset>`,
no `<sitemapindex>` nesting to handle, unlike sitemap_sd.py's retailers). A sitemap-level fetch
failure is NOT caught (propagates, matching sitemap_sd.py's/woo.py's "enumeration failures
propagate" convention).

**Product lines are their own WordPress post type, not a taxonomy on the product post**, and a
product page carries NO link back to its line (confirmed live: `/products/<slug>/`'s rendered DOM
and raw HTML both have zero `product-line` hrefs, zero JSON-LD, zero `__NEXT_DATA__` -- this is a
plain server-rendered WP theme, not an SPA calling a JSON API; a single XHR was observed on a fresh
page load, `consentcdn.cookiebot.com`, nothing product-related). The relationship only exists in
the OTHER direction: each `/product-line/<slug>/` page lists its member products as
`<a href=".../products/<slug>/">` cards (`Core set`, `Expansion`, etc. sections, undifferentiated
here -- the brief only asks for the line name, not the per-product role within it). So this
strategy fetches every line page FIRST, extracts each line's `<h1>` display name plus its member
product slugs (`_extract_line_members`), and builds a `slug -> line name` reverse map before ever
fetching the 320 product pages. Live evidence: 264 of 320 products belong to at least one line; 56
are standalone (e.g. "Grow Sky", "Collect!") and get no line at all.

**Per-product extraction**: `name` from `<h1>` (there is no `og:title` anywhere on a CMON product
page -- confirmed by grepping the raw fetched response text, not just the rendered DOM: the site
supplies `og:image`/`og:image:width` only). `imageUrl` from `og:image`. Both via plain regex (same
"probe-driven, no real JSON-LD/microdata here" situation sitemap_sd.py documents for its own
sites, just simpler since there is exactly one candidate per field). A page whose `<h1>` cannot be
found at all (`stats["extraction_failed_name"]`) contributes no observation -- `name` is a required
`Observation` field. No sku/ean/price/availability extraction: the probe (docs/research/
2026-07-12-source-probe-manufacturers.md, CMON section) found none of these on any product page
(marketing site, no store) -- `local id = URL slug`, manufacturer PINNED via
`descriptor.scope["manufacturer"]` (mirrors woo.py's per-source pin: CMON's own site has no
per-product vendor field to derive it from, and every enumerated page IS cmon.com's own catalog).

**gameSystem mapping**: `context.mappings["mfr-cmon"]["gameSystem"]` maps a product LINE's exact
display-name string (the `<h1>` text, e.g. `"Massive Darkness"`) to an existing
`taxonomy/game-systems.yaml` slug. Checked live 2026-07-13 against all 24 real line names (see
task-10-report.md for the full list + provenance) -- NONE match any of the ~47 existing
`game-systems.yaml` labels exactly (CMON publishes board/dungeon-crawl games -- Zombicide, Massive
Darkness, Marvel United, Bloodborne, Twilight Imperium, ... -- an entirely different genre from the
historical/skirmish miniatures systems already in that file; even the one thematically-adjacent
name, `"A Song of Ice & Fire: TMG"`, differs from the existing `asoiaf` label `"A Song of Ice and
Fire"` by both the ampersand and a `": TMG"` suffix). `data/catalog/mappings/mfr-cmon.yaml` is
therefore a correctly-empty scaffold, exactly like `mfr-manticgames.yaml`'s -- never guessed. A
product whose line has NO mapping entry gets `hints["productLine"] = <raw line name>` instead (a
raw, non-taxonomy hint key, same precedent as `migrate/legacy.py`'s `legacyProductCode`): the
classification queue (`classify/queue.py::_raw_hints`) surfaces any hint key other than
gameSystem/faction/description verbatim to a human/LLM classifier, so this is exactly how CMON's
real line names ("Zombicide", "Massive Darkness", ...) become available for a *future* manual
`taxonomy/game-systems.yaml` addition + mapping, without this task inventing one. A product with NO
line at all gets no hint (`stats["no_product_line"]`), not an empty-string one.

**Politeness THROUGH THE BROWSER**: `PoliteClient`'s pacing lives entirely inside its own httpx
`_request` call, which this strategy never invokes -- so an equivalent `_Pacer` (same
min-interval-since-last-call math as `PoliteClient._pace`, standalone since there is no shared httpx
client to hang it off) paces every single browser fetch (both sitemaps, every line page, every
product page) at `descriptor.politeness["rps"]` (default 0.5, same as every other strategy). `sleep`
is an injected `Callable[[float], None]` (default `time.sleep`) purely so tests can assert pacing
calls without a real wall-clock delay -- same seam shape as `PoliteClient`'s own `sleep` parameter.

**Robots.txt THROUGH THE BROWSER too** (fix wave 3, Important #2): `PoliteClient._request`'s
per-request robots check (`client.py`) only ever fires for requests that actually go through that
method -- and this strategy's `page.goto` fetches never do (see above). `runner.run_source`'s
base-URL preflight still ran (so a source disallowed at `/` is caught before this strategy is ever
called), but every subsequent product/line/sitemap URL was going completely unchecked -- a real gap
`acquire/robots.py`'s docstring used to paper over by claiming `PoliteClient` was "the single choke
point EVERY request from EVERY strategy already passes through," which was not true for this one.
`_fetch` (below) now re-implements the exact same check `PoliteClient._request` does --
`client.robots.allows(url, client.user_agent)`, raising `RobotsDisallowedError` with the same
`disallowed_by`-derived detail on a no -- against the `RobotsPolicy` already attached to the
`client: PoliteClient` parameter every strategy receives (`client.robots`/`client.user_agent`, both
public read-only properties added for exactly this cross-transport reuse; no second robots.txt
fetch). The check runs BEFORE `pacer.wait()` and BEFORE the actual `page.goto`, so a disallowed URL
never launches a navigation. `real_client()` in this module's tests builds a `PoliteClient` with no
`robots=` (mirrors `ignoreRobots`/no-baseUrl in `runner.py` -- `client.robots is None` means "no
robots checking"), so the existing fixture-driven tests are unaffected; a dedicated test injects a
disallowing policy instead.

**`scope.headless`** (plan-5 task-5): defaults `True`. When `fetcher` is not injected (the real
run path), this value is read from `descriptor.scope` and forwarded to
`_playwright_browser.launch_page_fetcher(headless=...)`. Headless Chromium is blocked 3/3 live by
CMON's Cloudflare managed challenge (`test_live_smoke_playwright_wp.py`'s xfail); a headed browser
was confirmed live to clear it, so `mfr-cmon.yaml` is the one descriptor setting
`scope.headless: false`. Every other descriptor (and every test in this module, which always
injects `fetcher=`) is unaffected.

**No budget concept.** Unlike every budgeted strategy in this package (woo.py's detail queue,
sitemap_sd.py's page-fetch queue), `context.budget` is never consulted here: CMON's entire
population is 320 products + 24 lines, cheap enough (~11-12 minutes at rps 0.5) that every run
fetches everything, every time -- this is also why the descriptor's own EXECUTE run passes
`--budget 0`, a value with no effect on this strategy (a `SourceDescriptor.budget` dict field exists
generically but nothing in this module reads it either). `full_sweep` is `True` iff every single
sitemap-enumerated product URL produced an observation this run (fetch succeeded AND a name was
extracted) -- `False` the moment any single product fetch or extraction fails, which is the
strategy's only real per-run variability given the "always full" design.
"""
import html as html_lib
import re
import time
from typing import TYPE_CHECKING, Callable

from warhub_acquisition.acquire.client import FetchError, PoliteClient, RobotsDisallowedError
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

if TYPE_CHECKING:
    # Only for the `robots` type hint below -- see `client.py`'s identical pattern.
    from warhub_acquisition.acquire.robots import RobotsPolicy

EXTRACTOR = "playwright-wp@1"

PageFetcher = Callable[[str], str]

_LOC_RE = re.compile(r"<loc>(.*?)</loc>", re.S)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_OG_IMAGE_RE = re.compile(r'<meta\s+property="og:image"\s+content="(.*?)"', re.I)
_LINE_MEMBER_HREF_RE = re.compile(r'href="https?://[^"]*?/products/([a-z0-9-]+)/"', re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    # `<h1>` text is real WordPress/theme markup, not JSON -- entities like `&amp;` (real, e.g.
    # CMON's "A Song of Ice & Fire: TMG" line) need decoding same as any other regex-scraped HTML
    # field in this codebase's simpler extractors.
    return html_lib.unescape(_TAG_RE.sub("", text)).strip()


def _parse_locs(xml_text: str) -> list[str]:
    return [loc.strip() for loc in _LOC_RE.findall(xml_text) if loc.strip()]


def _slug_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _extract_name(html: str) -> str | None:
    match = _H1_RE.search(html)
    if not match:
        return None
    name = _strip_tags(match.group(1))
    return name or None


def _extract_image_url(html: str) -> str | None:
    match = _OG_IMAGE_RE.search(html)
    return match.group(1) if match else None


def _extract_line_member_slugs(html: str) -> set[str]:
    return set(_LINE_MEMBER_HREF_RE.findall(html))


class _Pacer:
    """Standalone equivalent of `PoliteClient._pace` (min-interval-since-last-call), for fetches
    that never go through `PoliteClient`/httpx at all -- see module docstring."""

    def __init__(self, rps: float, sleep: Callable[[float], None]) -> None:
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._sleep = sleep
        self._last_call_at: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self._last_call_at is not None:
            remaining = self._min_interval - (now - self._last_call_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_call_at = time.monotonic()


def _fetch(
    fetcher: PageFetcher,
    pacer: _Pacer,
    url: str,
    robots: "RobotsPolicy | None",
    user_agent: str,
) -> str:
    # Per-URL robots.txt enforcement, BEFORE pacing and BEFORE the actual `page.goto` -- see
    # module docstring's "Robots.txt THROUGH THE BROWSER too" section. Mirrors
    # `PoliteClient._request`'s check (`client.py`) exactly, since this strategy's fetches never
    # go through that method at all. `robots is None` means "no robots checking" (mirrors
    # `PoliteClient`'s own `robots=None` default), a no-op for every existing fixture-driven test.
    if robots is not None and not robots.allows(url, user_agent):
        disallow = robots.disallowed_by(url, user_agent)
        token, rule = disallow if disallow is not None else (user_agent, None)
        rule_detail = f" ({rule})" if rule else ""
        raise RobotsDisallowedError(
            f"robots.txt disallows fetching {url} for user-agent {token!r}{rule_detail}",
            {"type": "robots-disallowed", "url": url, "userAgent": token, "rule": rule},
        )
    pacer.wait()
    return fetcher(url)


def _build_line_map(
    fetcher: PageFetcher,
    pacer: _Pacer,
    line_sitemap_url: str,
    stats: dict,
    robots: "RobotsPolicy | None",
    user_agent: str,
) -> dict[str, str]:
    """Fetch the products-line sitemap + every line page it lists; return `{product slug: line
    display name}`. A single failed line-page fetch is counted and skipped (non-fatal -- this is
    enrichment, not the product enumeration itself); the line sitemap fetch itself is not caught
    (see module docstring)."""
    xml_text = _fetch(fetcher, pacer, line_sitemap_url, robots, user_agent)
    line_urls = _parse_locs(xml_text)
    stats["line_urls_total"] = len(line_urls)

    slug_to_line: dict[str, str] = {}
    for line_url in sorted(line_urls):
        try:
            html = _fetch(fetcher, pacer, line_url, robots, user_agent)
        except FetchError:
            stats["line_fetch_errors"] += 1
            continue
        stats["line_pages_fetched"] += 1
        line_name = _extract_name(html)
        if line_name is None:
            continue
        for slug in _extract_line_member_slugs(html):
            slug_to_line.setdefault(slug, line_name)
    return slug_to_line


def playwright_wp_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
    fetcher: PageFetcher | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> StrategyResult:
    if fetcher is None:
        # Lazy import: only touches `playwright` (the optional `browser` extra) when this
        # strategy actually runs for real -- see module docstring.
        from warhub_acquisition.acquire.strategies._playwright_browser import launch_page_fetcher

        # `scope.headless` (plan-5 task-5): defaults True so every other caller/CI stays headless;
        # `data/catalog/sources/mfr-cmon.yaml` sets it False -- headless Chromium is blocked 3/3 by
        # CMON's Cloudflare managed challenge, a headed browser was confirmed live to clear it.
        headless = bool(descriptor.scope.get("headless", True))
        with launch_page_fetcher(headless=headless) as real_fetcher:
            return _run(descriptor, client, context, real_fetcher, sleep)
    return _run(descriptor, client, context, fetcher, sleep)


def _run(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    context: AcquireContext,
    fetcher: PageFetcher,
    sleep: Callable[[float], None],
) -> StrategyResult:
    stats = {
        "line_urls_total": 0,
        "line_pages_fetched": 0,
        "line_fetch_errors": 0,
        "product_urls_total": 0,
        "pages_fetched": 0,
        "fetch_errors": 0,
        "extraction_failed_name": 0,
        "mapped_game_system": 0,
        "unmapped_product_line": 0,
        "no_product_line": 0,
        "skipped_unknown_vendor": 0,
    }

    politeness = descriptor.politeness or {}
    rps = float(politeness.get("rps", 0.5))
    pacer = _Pacer(rps, sleep)

    # See module docstring's "Robots.txt THROUGH THE BROWSER too": the exact same policy
    # `runner.run_source` fetched and attached to `client` for its own (unused-by-this-strategy)
    # httpx requests, reused here to check every browser-fetched URL too.
    robots = client.robots
    user_agent = client.user_agent

    base_url = str(descriptor.baseUrl or "").rstrip("/")
    product_sitemap_url = str(descriptor.scope.get("productSitemap") or f"{base_url}/wp-sitemap-posts-products-1.xml")
    line_sitemap_url = str(descriptor.scope.get("lineSitemap") or f"{base_url}/wp-sitemap-posts-products-line-1.xml")

    slug_to_line = _build_line_map(fetcher, pacer, line_sitemap_url, stats, robots, user_agent)

    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None

    mapping = context.mappings.get(descriptor.id, {}) if context.mappings else {}
    game_system_map: dict[str, str] = mapping.get("gameSystem") or {}

    product_xml = _fetch(fetcher, pacer, product_sitemap_url, robots, user_agent)
    product_urls = sorted(_parse_locs(product_xml))
    stats["product_urls_total"] = len(product_urls)

    observations: list[Observation] = []

    if manufacturer is None:
        stats["skipped_unknown_vendor"] = len(product_urls)
    else:
        for url in product_urls:
            slug = _slug_from_url(url)
            try:
                html = _fetch(fetcher, pacer, url, robots, user_agent)
            except FetchError:
                stats["fetch_errors"] += 1
                continue
            stats["pages_fetched"] += 1

            name = _extract_name(html)
            if name is None:
                stats["extraction_failed_name"] += 1
                continue

            hints: dict[str, object] = {}
            line_name = slug_to_line.get(slug)
            if line_name is None:
                stats["no_product_line"] += 1
            elif line_name in game_system_map:
                hints["gameSystem"] = game_system_map[line_name]
                stats["mapped_game_system"] += 1
            else:
                hints["productLine"] = line_name
                stats["unmapped_product_line"] += 1

            observations.append(
                Observation(
                    key=f"{descriptor.id}:{slug}",
                    url=url,
                    manufacturer=manufacturer,
                    name=name,
                    imageUrl=_extract_image_url(html),
                    hints=hints,
                    firstSeen=context.run_date,
                    lastSeen=context.run_date,
                    extractor=EXTRACTOR,
                )
            )

    # True iff every enumerated product URL produced an observation this run (fetch succeeded AND
    # a name was extracted) -- see module docstring's "no budget concept" section. Always False
    # while any product is skipped for an unknown-vendor descriptor, matching every other
    # pinned-manufacturer strategy's convention that a bad `scope.manufacturer` never claims full
    # coverage. The explicit `product_urls_total > 0` guard matters live (task-10-report.md): a
    # Cloudflare-blocked sitemap fetch (page.goto succeeds, no FetchError -- the "Just a moment..."
    # interstitial IS a normal 200 HTML page, just with zero <loc> tags) would otherwise silently
    # enumerate 0 products and satisfy `0 == 0`, claiming a spurious full sweep of an empty
    # population -- which would tell run_source to mark_missed every existing evidence entry for
    # this source. The descriptor's own minCount=272 contract already catches this case too (raised
    # before any evidence write, per run_source), but this strategy must not rely on the caller for
    # a correctness property it can trivially guarantee itself.
    full_sweep = (
        manufacturer is not None
        and stats["product_urls_total"] > 0
        and len(observations) == stats["product_urls_total"]
    )

    return StrategyResult(
        observations=observations,
        full_sweep=full_sweep,
        stats=stats,
        cursor={},
    )


STRATEGIES["playwright-wp"] = playwright_wp_strategy
