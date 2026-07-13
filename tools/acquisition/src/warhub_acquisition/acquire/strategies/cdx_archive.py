"""CDX-archive strategy: out-of-print product recovery via the Wayback Machine's CDX index.

Registered as `STRATEGIES["cdx-archive"]`. Unlike every other strategy in this package, the
source being scraped is not the retailer/manufacturer's live site at all -- it is
web.archive.org's CDX API (bulk URL enumeration) plus its snapshot server (per-URL archived HTML).
This is the out-of-print recovery engine: retailers/manufacturers that have delisted a product
(or gone out of business entirely) can still have their old product pages recovered from whatever
the Wayback Machine crawled while the page was live. See
`docs/research/2026-07-12-source-probe-webarchive.md` for the full probe this strategy is built
from -- every query shape and content pattern below is probe-verified, not assumed.

Descriptor scope: `{cdxUrlPattern, urlInclude, extractor: "shopify-jsonld" | "gw-legacy",
snapshotFrom, snapshotTo, reEnumerateAfterDays (default 30), manufacturer}`. `descriptor.baseUrl`
is `https://web.archive.org` -- both the CDX endpoint (`/cdx/search/cdx`) and the snapshot server
(`/web/<timestamp>id_/<original>`) live on that one host, so a single `PoliteClient` covers both.

**CDX enumeration (expensive -- cached across runs).** Probe lesson: server-side `filter=`
regexes on `original` time out on any domain of real size (60s, curl exit 28) -- so the CDX query
NEVER carries a filter param; every page of `output=json&collapse=urlkey&fl=original,timestamp,
statuscode` (plus `from`/`to` bounds when the descriptor sets them) is pulled raw and filtered
locally. Page count comes from a separate `showNumPages=true` request first -- its response body
is a bare plain-text integer (probe-verified live: `curl .../cdx/search/cdx?url=...&showNumPages=true`
returned the literal text `8`, not JSON), so it's read via `client.get_response(...).text`, never
`get_json`. Local filtering, across every fetched page: `statuscode == "200"`; `urlInclude`
(`re.search` against `original`) when the descriptor sets one; dedupe by URL path (this strategy's
"urlkey" -- these are per-domain product URLs, so path uniquely identifies a product) keeping
whichever row has the lexicographically-greatest (= newest, 14-digit Wayback timestamps) capture.
The result is cached into the cursor as `url_index: {path: {original, timestamp}}` alongside
`cdx_pages_fetched`/`cdx_num_pages` (bookkeeping for "did the last enumeration actually complete")
and `last_enumerated` (an ISO run-date string). **Re-enumeration only happens when**: no
`last_enumerated` yet (first run), the last enumeration was incomplete (`cdx_pages_fetched <
cdx_num_pages`), or `(run_date - last_enumerated).days >= scope.reEnumerateAfterDays` (default 30)
-- computed via `datetime.date.fromisoformat` on the two ISO date strings, deliberately NOT wall-
clock `date.today()` (matches every other strategy's `context.run_date`-only time model, so tests
never need to mock the clock). A run that doesn't need to re-enumerate makes ZERO CDX requests --
it re-uses the cursor's cached `url_index` outright.

**Budgeted snapshot fetches**, same priority convention as `sitemap_sd.py`: paths never in the
cursor's `fetched` map first (sorted), then paths already fetched at least once, oldest-date-first
(same-date ties broken on path for determinism). `context.budget` caps how many of that queue are
actually snapshot-fetched this run. Each fetch hits
`https://web.archive.org/web/<timestamp>id_/<original>` -- the `id_` suffix is Wayback's
"identity"/raw-content replay flag, verified LIVE during this task's fixture capture (see
`tests/fixtures/cdx/` provenance below): the response byte-for-byte matches the original page's
markup, with zero Wayback toolbar injection or link rewriting (`grep -c "web.archive.org"` on the
captured body returned `0`). The plain (non-`id_`) replay form was never needed -- `id_` worked
cleanly on both the archived Shopify page and the old GW webstore page, so no fallback/mangling
workaround exists in this module. A `FetchError` on one snapshot counts `stats["fetch_errors"]`
and simply leaves that path out of the new `fetched` map -- it stays queued (never-fetched or
still-stale) for a later run, exactly like `sitemap_sd.py`'s per-page fetch-error handling.

**Two extractors**, selected by `scope.extractor`:

- `"shopify-jsonld"`: reuses `acquire.extract._extract_jsonld` UNCHANGED (not the full
  jsonld+microdata+BCData merge `sitemap_sd.py`'s `_extract_page` runs -- archived Shopify pages
  are Shopify's own JSON-LD, the exact shape `_extract_jsonld` already parses; microdata/BCData
  are irrelevant to Shopify markup, so pulling in the full merge would just be dead code paths for
  this source). Manufacturer attribution reuses `acquire.extract._resolve_manufacturer` (brand
  string -> `taxonomy.manufacturer_for_vendor`, falling back to a GS1-prefix match on the
  extracted ean) -- identical logic to `sitemap_sd.py`, `stats["skipped_unknown_manufacturer"]` on
  failure of both.
- `"gw-legacy"`: old (pre-~2019) games-workshop.com webstore pages carry no JSON-LD/microdata/EAN
  at all (probe-confirmed) but do carry GW's own internal 11-digit product/SKU codes, e.g.
  `data-skuid="99020109002"` or a bare query-string `skuId=99219999037` -- `_GW_SKUID_RE` matches
  both forms case-insensitively (a single pattern, since `re.I` folds `skuId=`/`skuid="`/`SKUID=`
  identically). Name comes from `<meta property="og:title">` first, `<title>` as fallback, with
  `_strip_site_suffix` cutting the `" | Games Workshop Webstore"` (or similar `" - "`/en-dash)
  suffix these pages always append (probe-confirmed live: `<title>10-Man Kill Team | Games
  Workshop Webstore</title>`). Price is read from the first `class="price ...">£NN[<sup>.NN</sup>]`
  span (GW's markup splits pounds and pence across a `<sup>` when pence are present; whole-pound
  prices like the fixture's `£44` have no `<sup>` at all -- `_GW_PRICE_RE`'s pence group is
  optional). Manufacturer is PINNED from `scope.manufacturer` (mirrors `woo.py`'s per-source
  pinning exactly -- old-GW webstore pages are always Games Workshop's own catalog, there is no
  per-product vendor field to derive it from); an unresolvable `scope.manufacturer` skips every
  candidate and counts `stats["skipped_unknown_manufacturer"]`. `sku` is set to the extracted
  11-digit code; `ean` is deliberately left unset here -- these pages carry no barcode at all, an
  EAN for a GW-coded archived product has to be joined in from another source later.

**Observations**: `archived=True` ALWAYS (this is the entire point of the strategy -- see the
module-level "archived-only lifecycle" note below), `key = f"{descriptor.id}:{path}"` (the
ORIGINAL live URL's path, matching every other strategy's key convention), `url` = the ORIGINAL
live URL (never the wayback replay URL -- a human or downstream consumer following this URL wants
the retailer's real product page, dead or not), `hints={"archiveTimestamp": timestamp}` (the
14-digit Wayback capture timestamp, so downstream code can judge how stale the recovered data is),
`availability` deliberately omitted (an archived snapshot says nothing about current stock),
`extractor = "cdx-archive@1"`.

**`full_sweep` is hard-coded `False`, always** -- archives must never drive `missStreak` (see
`sitemap_sd.py`'s module docstring for the identical reasoning, doubly true here: a budget-limited
slice of a POSSIBLY YEARS-OLD snapshot index is about as far from "this run observed the full
current population" as a signal can get).

**Lifecycle interaction (verified against `resolve/attributes.py`)**: `resolve_attributes` builds
`live = [member for member in members if not member.archived]` and falls straight to `status =
"discontinued"` when `live` is empty. Every observation this strategy ever produces has
`archived=True`, so an entity whose ONLY evidence is a `cdx-archive` observation is, by
construction, never in `live` -- it resolves to `status="discontinued"` on its very first run, and
can only become `"current"` if some OTHER (live, non-archived) source later corroborates the same
product. This strategy can never itself flip a new entity to `"current"`.

Cursor schema (as-built):

    {
      "url_index": {"<path>": {"original": "<url>", "timestamp": "<14-digit>"}},
      "cdx_pages_fetched": <int>,
      "cdx_num_pages": <int>,
      "last_enumerated": "<run_date ISO>",
      "fetched": {"<path>": "<run_date ISO>"},
    }

`last_good_count` / `last_run_date` are added by `run_source`, never written here.

Fixture provenance (`tests/fixtures/cdx/`), all captured LIVE 2026-07-13 via curl at <=1 req/s
(4 total requests): `goblin-cdx-page.json` (real CDX page for `goblingaming.co.uk/products/*`,
trimmed from ~800 rows to ~20, header row kept -- includes a real 404 and a real `statuscode: "-"`
row alongside 200s, for local-filtering tests), `goblin-shownumpages.txt` (real
`showNumPages=true` body -- the literal `8`), `goblin-archived-product.html` (the archived
`/products/1-x-large-flying-stand` page cited by the probe doc, fetched via the `id_` form and
trimmed to its JSON-LD block + a body skeleton -- real `gtin13: 5060504044745`, `sku: "BRFLY"`,
`brand: "TT COMBAT"`), `gw-legacy-product.html` (the probe doc's `10-man-kill-team` 2016 capture,
`id_` form, trimmed to the primary product's title/skuid/price block -- real `data-skuid=
"99020109002"`, `£44`, title `"10-Man Kill Team | Games Workshop Webstore"`; the same live page
also carries related-item codes `99219999037`/`99239999068`/`99239999069`/`99020109001`/
`99020109003`/`99020109004`/`99020109007`, matching the two example codes the probe doc itself
documented, but those related-item blocks were trimmed out of the fixture to keep it a
single-product fixture).
"""
import html as html_lib
import re
from datetime import date
from urllib.parse import urlsplit

from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.extract import _extract_jsonld, _resolve_manufacturer
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "cdx-archive@1"
CDX_PATH = "/cdx/search/cdx"
CDX_FL = "original,timestamp,statuscode"
CDX_HEADER_ROW = ["original", "timestamp", "statuscode"]
DEFAULT_REENUMERATE_AFTER_DAYS = 30

_GW_SKUID_RE = re.compile(r'skuid=["\']?(\d{11})', re.I)
_GW_PRICE_RE = re.compile(r'class="price[^"]*">\s*£(\d+)(?:<sup>\.(\d+)</sup>)?')
_OGTITLE_RE = re.compile(r'property="og:title"\s+content="([^"]*)"')
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_SITE_SUFFIX_SEPS = (" | ", " – ", " — ", " - ")


# --- CDX enumeration -------------------------------------------------------------------------


def _cdx_base_params(descriptor: SourceDescriptor) -> dict[str, str]:
    scope = descriptor.scope
    params: dict[str, str] = {"url": str(scope["cdxUrlPattern"])}
    snapshot_from = scope.get("snapshotFrom")
    if snapshot_from:
        params["from"] = str(snapshot_from)
    snapshot_to = scope.get("snapshotTo")
    if snapshot_to:
        params["to"] = str(snapshot_to)
    return params


def _show_num_pages(client: PoliteClient, base_params: dict[str, str]) -> int:
    """`showNumPages=true`'s response body is a bare plain-text integer, NOT JSON (probe-verified
    live) -- `get_response(...).text`, not `get_json`."""
    text = client.get_response(CDX_PATH, params={**base_params, "showNumPages": "true"}).text
    try:
        return int(text.strip())
    except ValueError:
        return 0


def _fetch_cdx_page(client: PoliteClient, base_params: dict[str, str], page: int) -> list[list[str]]:
    payload = client.get_json(
        CDX_PATH, params={**base_params, "output": "json", "collapse": "urlkey", "fl": CDX_FL, "page": page}
    )
    rows = payload if isinstance(payload, list) else []
    if rows and rows[0] == CDX_HEADER_ROW:
        rows = rows[1:]
    return rows


def _enumerate_cdx(
    client: PoliteClient, descriptor: SourceDescriptor, stats: dict[str, int]
) -> tuple[dict[str, dict[str, str]], int, int]:
    """Full re-enumeration: `showNumPages=true` once, then every page 0..N-1 raw (NO server-side
    `filter=` -- probe: 60s timeouts on real domains), filtered and deduped-by-path-keeping-newest
    locally. Returns `(url_index, pages_fetched, num_pages)`."""
    base_params = _cdx_base_params(descriptor)
    num_pages = _show_num_pages(client, base_params)

    url_include = descriptor.scope.get("urlInclude")
    pattern = re.compile(str(url_include)) if url_include else None

    index: dict[str, dict[str, str]] = {}
    pages_fetched = 0
    for page in range(num_pages):
        rows = _fetch_cdx_page(client, base_params, page)
        pages_fetched += 1
        stats["cdx_pages_fetched"] += 1
        for row in rows:
            if len(row) < 3:
                continue
            original, timestamp, statuscode = row[0], row[1], row[2]
            if statuscode != "200":
                continue
            if pattern is not None and not pattern.search(original):
                continue
            path = urlsplit(original).path
            existing = index.get(path)
            if existing is None or timestamp > existing["timestamp"]:
                index[path] = {"original": original, "timestamp": timestamp}

    return index, pages_fetched, num_pages


def _should_reenumerate(cursor: dict, run_date: str, reenumerate_after_days: int) -> bool:
    last_enumerated = cursor.get("last_enumerated")
    if not last_enumerated:
        return True
    pages_fetched = cursor.get("cdx_pages_fetched")
    num_pages = cursor.get("cdx_num_pages")
    if pages_fetched is None or num_pages is None or pages_fetched < num_pages:
        return True
    age_days = (date.fromisoformat(run_date) - date.fromisoformat(str(last_enumerated))).days
    return age_days >= reenumerate_after_days


# --- gw-legacy extraction --------------------------------------------------------------------


def _clean_text(raw: str) -> str | None:
    text = html_lib.unescape(_TAG_RE.sub("", raw)).strip()
    return text or None


def _strip_site_suffix(text: str) -> str:
    for sep in _SITE_SUFFIX_SEPS:
        if sep in text:
            return text.split(sep, 1)[0].strip()
    return text.strip()


def _extract_gw_name(html: str) -> str | None:
    match = _OGTITLE_RE.search(html)
    if match:
        cleaned = _clean_text(match.group(1))
        if cleaned:
            return _strip_site_suffix(cleaned)
    match = _TITLE_RE.search(html)
    if match:
        cleaned = _clean_text(match.group(1))
        if cleaned:
            return _strip_site_suffix(cleaned)
    return None


def _extract_gw_price(html: str) -> float | None:
    match = _GW_PRICE_RE.search(html)
    if not match:
        return None
    pounds, pence = match.group(1), match.group(2) or "0"
    try:
        return float(pounds) + float(pence.ljust(2, "0")[:2]) / 100
    except ValueError:
        return None


def _extract_gw_legacy(html: str) -> dict[str, object] | None:
    """Old-GW webstore pages carry no JSON-LD/microdata/EAN at all (probe-confirmed) -- only the
    internal 11-digit skuId/skuid code, a title, and a GBP price. Both code AND name are required
    for a usable record (Observation.name is required), matching sitemap_sd's extractors'
    "no name, no record" convention."""
    match = _GW_SKUID_RE.search(html)
    if not match:
        return None
    code = match.group(1)
    name = _extract_gw_name(html)
    if not name:
        return None
    return {"code": code, "name": name, "priceGbp": _extract_gw_price(html)}


# --- Strategy ----------------------------------------------------------------------------------


def _build_shopify_observation(
    descriptor: SourceDescriptor,
    context: AcquireContext,
    path: str,
    original: str,
    timestamp: str,
    html: str,
    stats: dict[str, int],
) -> Observation | None:
    record = _extract_jsonld(html)
    if record is None:
        stats["extraction_failed"] += 1
        return None

    manufacturer = _resolve_manufacturer(context.taxonomy, record.get("brand"), record.get("ean"))
    if manufacturer is None:
        stats["skipped_unknown_manufacturer"] += 1
        return None

    if record.get("ean"):
        stats["eans_found"] += 1

    return Observation(
        key=f"{descriptor.id}:{path}",
        url=original,
        manufacturer=manufacturer,
        name=record["name"],
        sku=record.get("sku"),
        ean=record.get("ean"),
        hints={"archiveTimestamp": timestamp},
        firstSeen=context.run_date,
        lastSeen=context.run_date,
        archived=True,
        extractor=EXTRACTOR,
    )


def _build_gw_legacy_observation(
    descriptor: SourceDescriptor,
    context: AcquireContext,
    path: str,
    original: str,
    timestamp: str,
    html: str,
    stats: dict[str, int],
) -> Observation | None:
    record = _extract_gw_legacy(html)
    if record is None:
        stats["extraction_failed"] += 1
        return None

    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None
    if manufacturer is None:
        stats["skipped_unknown_manufacturer"] += 1
        return None

    stats["codes_found"] += 1

    price_kwargs: dict[str, object] = {}
    if record.get("priceGbp") is not None:
        price_kwargs["priceGbp"] = record["priceGbp"]

    return Observation(
        key=f"{descriptor.id}:{path}",
        url=original,
        manufacturer=manufacturer,
        name=str(record["name"]),
        sku=str(record["code"]),
        hints={"archiveTimestamp": timestamp},
        firstSeen=context.run_date,
        lastSeen=context.run_date,
        archived=True,
        extractor=EXTRACTOR,
        **price_kwargs,
    )


_BUILDERS = {
    "shopify-jsonld": _build_shopify_observation,
    "gw-legacy": _build_gw_legacy_observation,
}


def cdx_archive_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    stats = {
        "cdx_pages_fetched": 0,
        "urls_indexed": 0,
        "snapshots_fetched": 0,
        "eans_found": 0,
        "codes_found": 0,
        "extraction_failed": 0,
        "fetch_errors": 0,
        "skipped_unknown_manufacturer": 0,
    }

    scope = descriptor.scope
    raw_reenumerate_after_days = scope.get("reEnumerateAfterDays")
    reenumerate_after_days = (
        DEFAULT_REENUMERATE_AFTER_DAYS if raw_reenumerate_after_days is None else int(raw_reenumerate_after_days)
    )

    if _should_reenumerate(cursor, context.run_date, reenumerate_after_days):
        url_index, cdx_pages_fetched, cdx_num_pages = _enumerate_cdx(client, descriptor, stats)
        last_enumerated = context.run_date
    else:
        url_index = {path: dict(entry) for path, entry in (cursor.get("url_index") or {}).items()}
        cdx_pages_fetched = cursor.get("cdx_pages_fetched", 0)
        cdx_num_pages = cursor.get("cdx_num_pages", 0)
        last_enumerated = cursor.get("last_enumerated")

    stats["urls_indexed"] = len(url_index)

    old_fetched: dict[str, str] = dict(cursor.get("fetched") or {})
    # Prune cursor entries for paths this enumeration no longer indexes -- mirrors sitemap_sd.py.
    new_fetched: dict[str, str] = {path: value for path, value in old_fetched.items() if path in url_index}

    never = sorted(path for path in url_index if path not in new_fetched)
    stale = sorted((path for path in url_index if path in new_fetched), key=lambda p: (new_fetched[p], p))
    queue = never + stale

    budget = context.budget
    to_fetch = queue if budget is None else queue[: max(budget, 0)]

    extractor_name = str(scope.get("extractor"))
    builder = _BUILDERS.get(extractor_name)
    if builder is None:
        raise ValueError(f"{descriptor.id}: unknown cdx-archive extractor {extractor_name!r}")

    observations: list[Observation] = []
    for path in to_fetch:
        entry = url_index[path]
        original, timestamp = entry["original"], entry["timestamp"]
        snapshot_url = f"/web/{timestamp}id_/{original}"
        stats["snapshots_fetched"] += 1
        try:
            html = client.get_text(snapshot_url)
        except FetchError:
            stats["fetch_errors"] += 1
            continue  # stays queued (never-fetched or still-stale), retried next run

        new_fetched[path] = context.run_date

        observation = builder(descriptor, context, path, original, timestamp, html, stats)
        if observation is not None:
            observations.append(observation)

    return StrategyResult(
        observations=observations,
        # ALWAYS False -- archives never drive missStreak. See module docstring.
        full_sweep=False,
        stats=stats,
        cursor={
            "url_index": url_index,
            "cdx_pages_fetched": cdx_pages_fetched,
            "cdx_num_pages": cdx_num_pages,
            "last_enumerated": last_enumerated,
            "fetched": new_fetched,
        },
    )


STRATEGIES["cdx-archive"] = cdx_archive_strategy
