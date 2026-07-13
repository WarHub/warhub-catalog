"""Sitemap + structured-data strategy: budgeted per-page EAN enrichment across retailer sites
that expose no bulk product API at all (Miniaturicum, Radaddel, Game Nerdz) -- the only
enumeration signal available is each site's own XML sitemap(s).

Registered as `STRATEGIES["sitemap-structured-data"]`. Pure EAN-enrichment: unlike
shopify.py/woo.py/algolia.py, a sitemap `<loc>` carries no name/sku/price/vendor at all -- every
field on an observation (name, sku, ean, brand -> manufacturer) can ONLY come from actually
fetching and extracting the product page itself. There is no "bulk-only" observation tier here.

**Enumeration**: `descriptor.scope.sitemaps` is a list of sitemap URLs to fetch. Each may be a
`<sitemapindex>` (one level of nesting handled: every child `<sitemap><loc>` is fetched and its
`<url><loc>` entries collected) or a plain `<urlset>` (its `<url><loc>` entries collected
directly). Parsed with stdlib `xml.etree.ElementTree` (no defusedxml -- these are our own site
fetches, not untrusted third-party XML, and no new dependency is warranted). XML namespaces are
stripped by local-name comparison so both namespaced and bare sitemap XML parse identically.
Radaddel's child sitemap is a literal `.xml.gz` FILE (`Content-Type: application/x-gzip`, no
`Content-Encoding` header -- confirmed live 2026-07-13, curl required an explicit `gunzip` step)
-- `_fetch_sitemap_text` sniffs the gzip magic bytes on every sitemap fetch (regardless of URL
suffix) and transparently decompresses via stdlib `gzip`, so this works for gzipped and plain XML
sitemaps alike. A sitemap-level `FetchError` is NOT caught (propagates up), matching
shopify.py/woo.py's "enumeration failures propagate, only per-item detail fetches are
error-tolerant" convention.

`descriptor.scope.urlInclude` (optional regex, `re.search`'d against the full URL) narrows the
enumerated set to GW-relevant products "where feasible" per the task brief -- see
task-11-report.md for the per-site feasibility finding (Radaddel's product slugs are pure
name-based with no reliable brand/category token -- e.g. the real `necrons-combat-patrol` slug
contains no "warhammer"/"games-workshop" -- so no filter is set there; Game Nerdz's slugs carry a
decent density of `warhammer`/`citadel` tokens, so a best-effort filter is set there).

**Budgeted page fetches**: `local id = URL path` (via `urllib.parse.urlsplit`). Cursor is a single
flat map `{"fetched": {"<url path>": "<run_date last successfully fetched>"}}` -- simpler than
shopify.py/woo.py's cursor because there is no separate "pending_details" list: a path absent
from `fetched` (or present with an old date) IS the pending state, there is no other bulk-listing
signal to reconcile it against. Priority: paths never in `fetched` first (sorted for determinism),
then paths in `fetched` oldest-date-first ("stalest first", same rationale as shopify.py's stale
bucket, but the entire population is eligible for restaling here since there is no
`updated_at`-style change signal to gate it on -- see task brief: "priority: URLs never fetched,
then oldest-fetched"). `context.budget` caps how many paths from that priority queue are actually
fetched this run; `None` means fetch the whole queue. A path whose fetch raises `FetchError` is
NOT recorded into the new cursor's `fetched` map (stats["fetch_errors"] counts it, and it stays
queued -- next run it is still either "never fetched" or "oldest", per its prior state) -- this
also means "every filtered URL has been fetched at least once" (the `full_sweep` condition, see
below) is automatically false while any FetchError-affected path exists, with no separate pending
list needed.

**Per-page extraction, in priority order, MERGED field-by-field (first non-null wins per field)**:

1. JSON-LD `Product` node (`@graph` unwrapped): `gtin13`/`gtin`/`gtin12` (in that priority),
   `sku`, `name`, `brand` (string or `{"name": ...}` object, both observed live).
2. Microdata: `itemtype="https://schema.org/Product"` (or `http://`) block; `itemprop="gtin13"`,
   `sku`, `name` (+ `brand`, which real Radaddel markup nests as `itemprop="brand"` containing a
   NESTED `itemprop="name"` span -- handled by `_microdata_brand`, not covered by the brief's
   explicit field list for this extractor but present in real captured markup and free to grab).
3. BigCommerce `var BCData = {...}` (a literal JS statement, not JSON on its own -- located via
   regex then parsed with `json.JSONDecoder().raw_decode` so trailing `;`/script content after the
   object never has to be balanced by hand): `product_attributes.sku`/`upc`. Carries NO name/brand
   field at all (probe-confirmed) -- this is the one extractor that can never independently supply
   `name`.

Fields are merged, NOT "whole extractor wins": this is deliberate and probe-driven. Game Nerdz's
own JSON-LD Product node carries `name`/`sku`/`brand` but a null `gtin` (confirmed live
2026-07-13, matches the 2026-07-12 probe's "JSON-LD carries sku/mpn only (gtin null there)"
finding) -- if the first extractor to find a Product node "won" outright, Game Nerdz's BCData
`upc` (the entire reason this retailer is worth scraping) would never be reached. Instead, each
field (`name`/`sku`/`ean`/`brand`) independently takes the first non-null value found scanning
extractors 1->2->3 in order. This still satisfies "JSON-LD wins" whenever JSON-LD's OWN `gtin` is
present (its `ean` value is claimed first, so a later extractor's differing gtin for the same
field is never even looked at) while still letting Game Nerdz's page combine JSON-LD's `name` with
BCData's `ean`. If no extractor ever supplies `name` but at least one supplies `sku`/`ean`/`brand`,
`_fallback_name` grabs the page's `<h1>` or `<title>` text as a last resort (Observation.name is a
required field -- a page with real product data but literally no extractable name anywhere would
otherwise have to be dropped entirely). A page where NO extractor supplies anything usable at all
(no name, sku, ean, or brand) counts `stats["extraction_failed"]` and contributes no observation.

**No price/availability/hints extraction.** The task brief's per-extractor field lists name only
gtin/sku/name/brand -- no price field anywhere, and these sites have no game-system/faction
taxonomy signal exposed the way Shopify tags or Woo categories are (a sitemap `<loc>` carries
nothing at all, and product pages here were only probed for gtin/sku/name/brand). `scope.currency`
is still recorded on each descriptor (EUR for Radaddel/Miniaturicum, USD for Game Nerdz -- verified
live from each captured fixture's `priceCurrency`/BCData `price.currency`) purely as accurate
metadata for a possible future price-extraction task; nothing in this strategy reads it.
`context.mappings` is likewise never consulted (empty mapping-file scaffolds exist only for the
repo's own `test_repo_mappings_parse_when_present` convention).

**Manufacturer attribution** (no `scope.vendors` -- these are multi-brand retailers, per the task
brief): 1) the extracted `brand` string through `taxonomy.manufacturer_for_vendor`; 2) failing
that (brand absent, or present but not a known vendor name), a GS1-prefix match of the extracted
`ean` against each taxonomy manufacturer's `gs1Prefixes` (`_manufacturer_by_gs1_prefix`, checked in
sorted-slug order for determinism); 3) failing both, `stats["skipped_unknown_manufacturer"]` and no
observation for that page (mirrors shopify.py/woo.py's unknown-vendor skip -- the fetch itself
still counts as "fetched" for cursor/full_sweep purposes; only the observation is dropped).

**`full_sweep`**: hard-coded `False`, always (final fix wave, item 2 -- this is a correctness fix,
not a tightening of an edge case). An earlier revision computed `full_sweep` as `True` once every
URL passing the filter had a `fetched` cursor entry (i.e. had been successfully fetched at least
once, ever) and called that "practically always False" given sitemap sizes observed live
(Radaddel: 12,806 URLs; Game Nerdz: ~145,000 URLs across 27 product-sitemap pages) against any
sane per-run budget. That reasoning was wrong past the coverage horizon: given enough nights,
budget rotation eventually DOES fetch every filtered URL at least once, at which point the old
condition flips to `True` -- e.g. around night 4 for Radaddel at its observed per-run pace. When
that happens, `run_source` treats
`full_sweep=True` as "this run's observations are the full population of this source" and calls
`EvidenceStore.mark_missed` on everything not re-observed -- but a retailer sitemap enumerating a
product at some point in the past, and this run's budget-limited slice simply not re-touching it
today, is NOT the same claim as "this retailer no longer carries it." Retailer absence is not
manufacturer discontinuation, and even "this retailer's own sitemap doesn't currently list a page
it once listed" is a weak, budget-confounded signal that must never inflate `missStreak` on
out-of-slice records (which, at `resolve`'s missStreak-threshold-3 default, silently flips
retailer-only entities to `suspected-discontinued`). So `full_sweep` is `False` here always, by
design, regardless of the `fetched` map's coverage of the filtered URL set: `run_source` only
calls `mark_missed` when `full_sweep` is `True`, so this source can never drive another source's
product into a `missStreak` at all.

**Extraction helpers live in `acquire/extract.py`** (Task 2 refactor): the JSON-LD/microdata/BCData
parsing and GS1-prefix manufacturer fallback below were moved there so `strategies/cdx_archive.py`'s
`shopify-jsonld` extractor can reuse them verbatim against archived Shopify markup (identical
`gtin13`/`sku`/`name`/`brand` JSON-LD shape). Imported here by name so this module's own namespace
-- and every existing test that imports e.g. `_extract_jsonld` from this module -- is unaffected.
"""
import gzip
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.extract import (
    _extract_bcdata,
    _extract_jsonld,
    _extract_microdata,
    _extract_page,
    _manufacturer_by_gs1_prefix,
    _resolve_manufacturer,
)
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "sitemap-structured-data@1"

_GZIP_MAGIC = b"\x1f\x8b"


# --- Sitemap parsing (enumeration) -----------------------------------------------------------


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_sitemap_locs(xml_text: str) -> tuple[str, list[str]]:
    """Parse one sitemap document. Returns (root local-name, list of <loc> text values found
    directly under its children) -- for a `sitemapindex` these are child sitemap URLs; for a
    `urlset` these are product page URLs. An unrecognized root element returns its own local-name
    with an empty list rather than raising, so a genuinely odd document just contributes nothing."""
    root = ET.fromstring(xml_text)
    kind = _localname(root.tag)
    locs: list[str] = []
    for child in root:
        for grandchild in child:
            if _localname(grandchild.tag) == "loc" and grandchild.text:
                locs.append(grandchild.text.strip())
    return kind, locs


def _fetch_sitemap_text(client: PoliteClient, url: str) -> str:
    """Fetch a sitemap URL and return decoded text, transparently gunzipping when the body is a
    literal gzip file (sniffed via magic bytes, not the URL suffix or Content-Type -- Radaddel's
    child sitemap is `.xml.gz` with no `Content-Encoding` header, confirmed live 2026-07-13)."""
    content = client.get_response(url).content
    if content[:2] == _GZIP_MAGIC:
        content = gzip.decompress(content)
    return content.decode("utf-8", errors="replace")


# --- Strategy ------------------------------------------------------------------------------


def _enumerate_urls(client: PoliteClient, sitemap_urls: list[str], stats: dict[str, int]) -> set[str]:
    urls: set[str] = set()
    for sitemap_url in sitemap_urls:
        text = _fetch_sitemap_text(client, sitemap_url)
        stats["fetched_sitemaps"] += 1
        kind, locs = _parse_sitemap_locs(text)
        if kind == "sitemapindex":
            for child_url in locs:
                child_text = _fetch_sitemap_text(client, child_url)
                stats["fetched_sitemaps"] += 1
                _, child_locs = _parse_sitemap_locs(child_text)
                urls.update(child_locs)
        else:
            urls.update(locs)
    return urls


def sitemap_sd_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    stats = {
        "fetched_sitemaps": 0,
        "sitemap_urls_total": 0,
        "sitemap_urls_filtered": 0,
        "pages_fetched": 0,
        "fetch_errors": 0,
        "extraction_failed": 0,
        "eans_found": 0,
        "skipped_unknown_manufacturer": 0,
        "ean_source_jsonld": 0,
        "ean_source_microdata": 0,
        "ean_source_bcdata": 0,
    }

    sitemap_urls = [str(u) for u in (descriptor.scope.get("sitemaps") or [])]
    all_urls = _enumerate_urls(client, sitemap_urls, stats)
    stats["sitemap_urls_total"] = len(all_urls)

    url_include = descriptor.scope.get("urlInclude")
    pattern = re.compile(str(url_include)) if url_include else None
    filtered_urls = {u for u in all_urls if pattern is None or pattern.search(u)}
    stats["sitemap_urls_filtered"] = len(filtered_urls)

    by_path: dict[str, str] = {urlsplit(u).path: u for u in filtered_urls}

    old_fetched: dict[str, str] = dict(cursor.get("fetched") or {})
    # Prune entries for paths no longer in the (filtered) sitemap -- keeps the cursor bounded to
    # the current live catalog instead of growing forever with delisted products.
    new_fetched: dict[str, str] = {path: date for path, date in old_fetched.items() if path in by_path}

    never = sorted(path for path in by_path if path not in new_fetched)
    # Secondary sort key `p` breaks ties deterministically when multiple paths share the same
    # fetched-date: `by_path` (the iteration source) is built from a set comprehension, so its
    # order is hash-randomized -- without a tie-break, same-date entries would land in a
    # nondeterministic order in the queue (and thus a nondeterministic cursor on the next save).
    stale = sorted((path for path in by_path if path in new_fetched), key=lambda p: (new_fetched[p], p))
    queue = never + stale

    budget = context.budget
    to_fetch = queue if budget is None else queue[: max(budget, 0)]

    observations: list[Observation] = []
    for path in to_fetch:
        url = by_path[path]
        stats["pages_fetched"] += 1
        try:
            html = client.get_text(url)
        except FetchError:
            stats["fetch_errors"] += 1
            continue  # leave new_fetched[path] as it was (absent or stale) -- retried next run

        new_fetched[path] = context.run_date

        record, ean_source = _extract_page(html)
        if record["name"] is None:
            stats["extraction_failed"] += 1
            continue

        manufacturer = _resolve_manufacturer(context.taxonomy, record["brand"], record["ean"])
        if manufacturer is None:
            stats["skipped_unknown_manufacturer"] += 1
            continue

        if record["ean"]:
            stats["eans_found"] += 1
        if ean_source is not None:
            stats[f"ean_source_{ean_source}"] += 1

        observations.append(
            Observation(
                key=f"{descriptor.id}:{path}",
                url=url,
                manufacturer=manufacturer,
                name=record["name"],
                sku=record["sku"],
                ean=record["ean"],
                firstSeen=context.run_date,
                lastSeen=context.run_date,
                extractor=EXTRACTOR,
            )
        )

    # Always False, by design -- see module docstring's "full_sweep" section (final fix wave,
    # item 2): retailer absence from a budget-limited sitemap slice must never be treated as "this
    # run observed the full population," which would let run_source's mark_missed inflate
    # missStreak on records this source simply hasn't gotten around to re-fetching yet.
    full_sweep = False

    return StrategyResult(
        observations=observations,
        full_sweep=full_sweep,
        stats=stats,
        cursor={"fetched": new_fetched},
    )


STRATEGIES["sitemap-structured-data"] = sitemap_sd_strategy
