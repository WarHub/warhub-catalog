"""Shared structured-data extraction helpers: JSON-LD / microdata / BigCommerce `BCData`
Product-node parsing, plus GS1-prefix manufacturer fallback attribution.

Originally lived as private helpers inside `strategies/sitemap_sd.py` (see that module's
docstring for the full field-merge rationale -- unchanged by this move). Factored out here so
`strategies/cdx_archive.py`'s `shopify-jsonld` extractor (Task 2, archived-page EAN recovery) can
reuse the exact same JSON-LD `Product` parsing and manufacturer-attribution logic without
duplicating it -- archived Shopify markup uses the identical `gtin13`/`sku`/`name`/`brand`
JSON-LD shape live Shopify storefronts do (probe-confirmed, 2026-07-12 web-archive probe).

`sitemap_sd.py` imports every name it used to define locally from here, so its own module
namespace (and every existing test that imports e.g. `from
warhub_acquisition.acquire.strategies.sitemap_sd import _extract_jsonld`) is unaffected --
`from ... import _extract_jsonld` binds the name into `sitemap_sd`'s namespace just as if it were
still defined there.
"""
import html
import json
import re

from warhub_acquisition.taxonomy import Taxonomy

_LDJSON_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_BCDATA_RE = re.compile(r"var\s+BCData\s*=\s*")
_PRODUCT_ITEMTYPE_RE = re.compile(r'itemtype=["\']https?://schema\.org/Product["\']')
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)


# --- Field normalization ------------------------------------------------------------------------


def _digits(value: object) -> str | None:
    if not value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def _clean(value: object) -> str | None:
    """Strip + HTML-entity-unescape. Every text value this module extracts (JSON-LD `name`/`sku`
    via `_jsonld_brand`, microdata `itemprop` text/content via `_microdata_value`, and the
    `<h1>`/`<title>` fallback name) funnels through here -- real pages carry entity-encoded text
    in all three shapes (JSON-LD strings included: some CMS templating HTML-escapes text before
    injecting it into a JSON-LD script block, not just literal HTML attributes/text nodes).
    `html.unescape` on text with no entities in it is a no-op, so this is safe unconditionally."""
    if value is None:
        return None
    text = html.unescape(str(value)).strip()
    return text or None


# --- JSON-LD -------------------------------------------------------------------------------------


def _is_product_node(node: dict) -> bool:
    node_type = node.get("@type")
    return node_type == "Product" or (isinstance(node_type, list) and "Product" in node_type)


def _jsonld_brand(raw: object) -> str | None:
    if isinstance(raw, dict):
        return _clean(raw.get("name"))
    return _clean(raw)


_GTIN_FIELDS = ("gtin13", "gtin", "gtin12", "gtin8")


def _first_gtin(source: dict) -> object:
    for field in _GTIN_FIELDS:
        value = source.get(field)
        if value:
            return value
    return None


def _node_gtin(node: dict) -> object:
    """gtin13/gtin/gtin12/gtin8, checked in that order, on the Product node's own top level
    FIRST (unchanged precedence). Many Shopify themes instead (or additionally) nest the gtin
    inside the Product's `offers` -- a single Offer object OR a list of them (probe-confirmed:
    tistaminis.com's archived pages carry gtin13 only inside `offers`, not at the Product's top
    level, which is why the top-level-only lookup this function replaces returned a null ean for
    a page whose HTML plainly contains the barcode). When the top level has no usable gtin, each
    offer is checked in list order and the first one carrying a usable gtin field wins."""
    raw_gtin = _first_gtin(node)
    if raw_gtin:
        return raw_gtin
    offers = node.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                raw_gtin = _first_gtin(offer)
                if raw_gtin:
                    return raw_gtin
    return None


def _extract_jsonld(html: str) -> dict[str, str | None] | None:
    """First `Product` node found across every `<script type="application/ld+json">` block
    (malformed blocks are skipped, not fatal -- a later valid block can still match), unwrapping
    `@graph` nesting. Returns None only when no Product node with a usable `name` is found at
    all -- a Product node with a `name` but no gtin field still counts as a hit (`ean` is None in
    that case), matching the field-merge design of both callers. gtin lookup: see `_node_gtin`
    for the top-level-then-offers precedence."""
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
            raw_gtin = _node_gtin(node)
            return {
                "name": name,
                "sku": _clean(node.get("sku")),
                "ean": _digits(raw_gtin),
                "brand": _jsonld_brand(node.get("brand")),
            }
    return None


# --- Microdata -----------------------------------------------------------------------------------


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


# --- BigCommerce BCData ----------------------------------------------------------------------------


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


# --- Fallback name / field-merge -----------------------------------------------------------------


def _fallback_name(html: str) -> str | None:
    """`<h1>` wins outright (real product markup, no shop chrome to worry about). `<title>` is the
    last resort, and it is frequently shop-suffixed -- e.g. radaddel.de emits
    `"<Product> | Radaddel | Radaddel Tabletop Shop"` -- so a bare `<title>` fallback mints the
    site's chrome straight into the catalog name (and, upstream, into the entity ID). `|` is the
    one separator we strip on: real product titles containing a literal pipe are vanishingly rare,
    while `<title>Product | Shop Name</title>` chrome is the norm across storefront templates. We
    deliberately do NOT split on ` - ` / en-dash / em-dash -- those appear inside legitimate
    product names (e.g. "War of the Roses - Hail Caesar Supplement")."""
    match = _H1_RE.search(html)
    if match:
        text = _clean(re.sub(r"<[^>]+>", "", match.group(1)))
        if text:
            return text
    match = _TITLE_RE.search(html)
    if match:
        text = _clean(re.sub(r"<[^>]+>", "", match.group(1)))
        if text and "|" in text:
            head = text.split("|", 1)[0].strip()
            if head:
                return head
        return text
    return None


_FIELD_EXTRACTORS = (
    ("jsonld", _extract_jsonld),
    ("microdata", _extract_microdata),
    ("bcdata", _extract_bcdata),
)


def _extract_page(html: str) -> tuple[dict[str, str | None], str | None]:
    """Runs all three extractors in priority order and merges their results field-by-field
    (first non-null value wins per field -- see sitemap_sd.py's module docstring for why this is
    not simply "first successful extractor wins the whole page"). Returns `(merged_fields,
    ean_source)` where `ean_source` is the label of whichever extractor's result first supplied a
    non-null `ean` (or None if none did)."""
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


# --- Manufacturer attribution ---------------------------------------------------------------------


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
