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

**`full_sweep`**: `True` only when every URL passing the filter this run has a `fetched` cursor
entry (i.e. has been successfully fetched at least once, ever). Given sitemap sizes observed live
(Radaddel: 12,806 URLs; Game Nerdz: ~145,000 URLs across 27 product-sitemap pages) against any
sane per-run budget, this is "practically always False" per the task brief -- which is exactly the
point: `run_source` only calls `EvidenceStore.mark_missed` when `full_sweep` is True, so these
sources can never drive another source's product into a `missStreak` (a retailer simply never
having enumerated a given product yet, or not having refetched it recently, must never be confused
with "this product is discontinued").
"""
import gzip
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.taxonomy import Taxonomy

EXTRACTOR = "sitemap-structured-data@1"

_LDJSON_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_BCDATA_RE = re.compile(r"var\s+BCData\s*=\s*")
_PRODUCT_ITEMTYPE_RE = re.compile(r'itemtype=["\']https?://schema\.org/Product["\']')
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)

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


# --- Per-page structured-data extractors ------------------------------------------------------


def _digits(value: object) -> str | None:
    if not value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_product_node(node: dict) -> bool:
    node_type = node.get("@type")
    return node_type == "Product" or (isinstance(node_type, list) and "Product" in node_type)


def _jsonld_brand(raw: object) -> str | None:
    if isinstance(raw, dict):
        return _clean(raw.get("name"))
    return _clean(raw)


def _extract_jsonld(html: str) -> dict[str, str | None] | None:
    """First `Product` node found across every `<script type="application/ld+json">` block
    (malformed blocks are skipped, not fatal -- a later valid block can still match), unwrapping
    `@graph` nesting. Returns None only when no Product node with a usable `name` is found at
    all -- a Product node with a `name` but no gtin field still counts as a hit (`ean` is None in
    that case), matching the module docstring's "field merge, not extractor-wins" design."""
    for block in _LDJSON_RE.findall(html):
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, TypeError):
            continue
        top_level = data if isinstance(data, list) else [data]
        nodes: list[dict] = []
        for entry in top_level:
            if not isinstance(entry, dict):
                continue
            graph = entry.get("@graph")
            if isinstance(graph, list):
                nodes.extend(node for node in graph if isinstance(node, dict))
            else:
                nodes.append(entry)
        for node in nodes:
            if not _is_product_node(node):
                continue
            name = _clean(node.get("name"))
            if not name:
                continue
            raw_gtin = node.get("gtin13") or node.get("gtin") or node.get("gtin12")
            return {
                "name": name,
                "sku": _clean(node.get("sku")),
                "ean": _digits(raw_gtin),
                "brand": _jsonld_brand(node.get("brand")),
            }
    return None


def _microdata_value(html: str, prop: str) -> str | None:
    meta_match = re.search(rf'itemprop="{prop}"[^>]*\bcontent="([^"]*)"', html)
    if meta_match:
        return _clean(meta_match.group(1))
    text_match = re.search(rf'itemprop="{prop}"[^>]*>([^<]*)<', html)
    if text_match:
        return _clean(text_match.group(1))
    return None


def _microdata_brand(html: str) -> str | None:
    """Real Radaddel markup: `itemprop="brand" itemscope itemtype=".../Brand"><span
    itemprop="name">Games Workshop</span>` -- the brand name is a NESTED itemprop, not a direct
    content/text value on the itemprop="brand" element itself."""
    direct = _microdata_value(html, "brand")
    if direct:
        return direct
    idx = html.find('itemprop="brand"')
    if idx == -1:
        return None
    return _microdata_value(html[idx : idx + 500], "name")


def _extract_microdata(html: str) -> dict[str, str | None] | None:
    """Returns None when no `itemtype=".../Product"` block is found, or one is found but no
    `itemprop="name"` is present anywhere (Observation.name is required -- a page whose only
    Product-scoped data is a stray gtin13 with no name at all is not usable via this extractor)."""
    if not _PRODUCT_ITEMTYPE_RE.search(html):
        return None
    name = _microdata_value(html, "name")
    if not name:
        return None
    return {
        "name": name,
        "sku": _microdata_value(html, "sku"),
        "ean": _digits(_microdata_value(html, "gtin13")),
        "brand": _microdata_brand(html),
    }


def _extract_bcdata(html: str) -> dict[str, str | None] | None:
    """Locates the `var BCData = {...};` JS statement and parses just the object literal via
    `json.JSONDecoder.raw_decode` (stops at the object's closing brace, ignoring the trailing
    `;` and any further script content -- no hand-rolled brace balancing needed). Never carries a
    `name` or `brand` (probe-confirmed absent from `product_attributes`)."""
    match = _BCDATA_RE.search(html)
    if not match:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html, match.end())
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    attrs = data.get("product_attributes")
    if not isinstance(attrs, dict):
        return None
    sku = _clean(attrs.get("sku"))
    ean = _digits(attrs.get("upc"))
    if not sku and not ean:
        return None
    return {"name": None, "sku": sku, "ean": ean, "brand": None}


def _fallback_name(html: str) -> str | None:
    match = _H1_RE.search(html)
    if match:
        text = _clean(re.sub(r"<[^>]+>", "", match.group(1)))
        if text:
            return text
    match = _TITLE_RE.search(html)
    if match:
        return _clean(re.sub(r"<[^>]+>", "", match.group(1)))
    return None


_FIELD_EXTRACTORS = (
    ("jsonld", _extract_jsonld),
    ("microdata", _extract_microdata),
    ("bcdata", _extract_bcdata),
)


def _extract_page(html: str) -> tuple[dict[str, str | None], str | None]:
    """Runs all three extractors in priority order and merges their results field-by-field
    (first non-null value wins per field -- see module docstring for why this is not simply
    "first successful extractor wins the whole page"). Returns `(merged_fields, ean_source)`
    where `ean_source` is the label of whichever extractor's result first supplied a non-null
    `ean` (or None if none did)."""
    merged: dict[str, str | None] = {"name": None, "sku": None, "ean": None, "brand": None}
    ean_source: str | None = None
    for label, extractor in _FIELD_EXTRACTORS:
        result = extractor(html)
        if result is None:
            continue
        for field, value in result.items():
            if merged[field] is None and value:
                merged[field] = value
                if field == "ean" and ean_source is None:
                    ean_source = label
    if merged["name"] is None and (merged["sku"] or merged["ean"] or merged["brand"]):
        merged["name"] = _fallback_name(html)
    return merged, ean_source


# --- Manufacturer attribution ------------------------------------------------------------------


def _manufacturer_by_gs1_prefix(taxonomy: Taxonomy, ean: str) -> str | None:
    for slug in sorted(taxonomy.manufacturers):
        for prefix in taxonomy.manufacturers[slug].gs1Prefixes:
            if prefix and ean.startswith(prefix):
                return slug
    return None


def _resolve_manufacturer(taxonomy: Taxonomy, brand: str | None, ean: str | None) -> str | None:
    if brand:
        manufacturer = taxonomy.manufacturer_for_vendor(brand)
        if manufacturer:
            return manufacturer
    if ean:
        return _manufacturer_by_gs1_prefix(taxonomy, ean)
    return None


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
    stale = sorted((path for path in by_path if path in new_fetched), key=lambda p: new_fetched[p])
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

    full_sweep = set(by_path) <= set(new_fetched)

    return StrategyResult(
        observations=observations,
        full_sweep=full_sweep,
        stats=stats,
        cursor={"fetched": new_fetched},
    )


STRATEGIES["sitemap-structured-data"] = sitemap_sd_strategy
