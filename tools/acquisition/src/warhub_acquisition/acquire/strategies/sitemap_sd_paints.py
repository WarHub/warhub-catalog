"""Sitemap + structured-data PAINTS strategy (Green Stuff World): PrestaShop 1.7
manufacturer-store harvest driven by the shop's own language sitemap.

Registered as `STRATEGIES["sitemap-sd-paints"]`. Derived from sitemap_sd.py's enumeration (its
sitemap fetch/parse helpers are imported, not duplicated) but this is a `mfr-*` paints source,
not a retailer EAN-enricher, so almost every other posture flips (full-population claim,
pinned manufacturer, rich per-page fields, mr_hobby-style detail-queue cursor):

**Enumeration** (every run, cheap): `scope.sitemaps` lists explicit sitemap URLs --
greenstuffworld.com publishes one single-`urlset` sitemap per shop language
(`/1_en_0_sitemap.xml`: 2.8 MB, 3,929 locs of which 3,370 are product URLs, CDATA-wrapped;
live-verified 2026-07-24). `sitemap_sd._enumerate_urls` handles it verbatim: stdlib
ElementTree folds CDATA into `.text`, and `_parse_sitemap_locs` iterates depth-2 children
only, so the `<image:image><image:loc>` blocks nested one level deeper are never mistaken for
page locs. A sitemap-level `FetchError` propagates (enumeration failures are fatal, only
per-page detail fetches are error-tolerant -- same convention as every other strategy).
`scope.urlInclude` (regex, `re.search`) narrows to the paint category slugs; surviving URLs
must then parse as PrestaShop product URLs (`.../{category-slug}/{id}-{slug}.html`, the id
being PrestaShop's `id_product` -- the stable local key). Filter-passing URLs without that
shape (e.g. the `/en/122-acrylic-paints` category landing page under a loose filter) count
`skipped_non_product` and are never fetched. The category slug in the URL feeds
`hints.categorySlug` (the sitemap is the only place it appears; product-page microdata has no
category field).

**Budgeted detail fetches, cursor discipline** (same shape as mr_hobby.py / shopify_paints.py;
a sitemap `<loc>` carries no product fields at all, so unlike those strategies an id with no
fetched detail yet contributes NO observation -- there is no bulk-listing tier to fall back
on):

    {"details": {"<id>": {"name": ..., "reference": ..., "mpn": ..., "ean": ...,
                          "priceEur": ..., "imageUrl": ..., "availability": ...}  # parsed OK
                         | {"detailMisses": <n>}},                # page fetched, not parseable
     "pending_details": ["<id>", ...]}

New ids first (numeric order), then parse-miss retries below DETAIL_MISS_CAP. A parsed detail
is never re-fetched (one-off snapshot model -- a fresh-eyes re-harvest means deleting the
cursor), and cached details whose id the budget doesn't reach this run are carried forward
untouched. A 404 is a definitive absence (sitemap staleness): it caps immediately rather than
staying pending, so a dead loc can never pin `full_sweep` False forever. Any other
`FetchError` keeps the id pending (transient; retried next run, never counted against the
cap). Ids that drop out of the filtered sitemap are pruned from the cursor.

**Extraction is Product-scoped microdata** (all shapes live-verified 2026-07-24 on
greenstuffworld.com product pages; the site emits NO JSON-LD Product node): the page is sliced
from its `itemtype="https://schema.org/Product"` match onward before any `itemprop` lookup,
because the breadcrumb block ABOVE it carries its own `itemprop="name"` entries ("Home",
"Paint", ...) that a whole-page first-match lookup would return instead of the product name.
Within the slice:

- name: the `<h1 ... itemprop="name">` product title (fallback: first `itemprop="name"`).
- reference: `itemprop="sku"` -- GSW's internal reference, the EAN with an `ES` suffix
  (`8435646505800ES`), NOT the printed paint number.
- mpn: `<meta itemprop="mpn">` -- the TRUE paint number (`3220`). Observation.sku = mpn when
  present, else the reference; the reference rides along in `hints.reference` when it differs.
- ean: `itemprop="gtin13"` digits (GS1 prefixes 8435646/8436574).
- priceEur: `itemprop="price"` content (the current selling price -- a pre-rounding decimal
  like `2.592` when discounted), recorded ONLY when `itemprop="priceCurrency"` confirms EUR
  (guards against a geo/currency-module drift silently landing non-euro numbers in priceEur).
- availability: the `<link itemprop="availability" href="https://schema.org/InStock"/>` HREF
  (a link/href shape extract.py's content/text helper cannot see), normalized to snake_case
  (`in_stock` / `out_of_stock` / ...), matching the shopify strategies' vocabulary.
- imageUrl: the `js-qv-product-cover` cover `<img src>`.

`hints`: category="paint", categorySlug from the URL, ml parsed off the NAME ("Dipping ink
60 ml - PAPYRUS DIP" -> 60; volume appears nowhere else structured), reference as above. A
fetched page with no Product block or no extractable name is a parse miss (counts toward
DETAIL_MISS_CAP); missing individual fields on an otherwise-parsed page are just absent (the
descriptor's requiredFieldRates make systemic drift loud).

**Manufacturer is pinned** via `scope.manufacturer` through the taxonomy (same mechanism as
wp_rest_paints/mr_hobby) -- this is the manufacturer's own store, and the on-page brand
microdata is deliberately ignored (attribution must not depend on a theme block). An
unresolvable pinned vendor observes nothing and lets minCount fail the run loudly.

**full_sweep** is True exactly when the detail queue is drained (nothing pending) -- unlike
sitemap_sd.py's hard-coded False: absence from the MANUFACTURER'S OWN sitemap is a genuine
discontinuation signal, the same claim wp_rest_paints makes, so mark_missed may fire once
every enumerated id has been fetched (or capped out). Budget-starved runs leave ids pending
and therefore never claim a sweep.
"""
import re
from urllib.parse import urlsplit

from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.extract import (
    _PRODUCT_ITEMTYPE_RE,
    _clean,
    _digits,
    _microdata_value,
)
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.acquire.strategies.sitemap_sd import _enumerate_urls
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "sitemap-sd-paints@1"

# Same rationale as mr_hobby.py/shopify.py: after this many successful fetches that yielded no
# parseable Product block, stop re-queuing the page (markup drift on one page must not pin the
# source below full_sweep forever). Fetch ERRORS deliberately don't count -- they stay queued.
DETAIL_MISS_CAP = 3

# PrestaShop 1.7 friendly product URL: /{lang}/{category-slug}/{id_product}-{slug}.html.
# Anchored on the last two path segments so any language prefix works.
_PRODUCT_URL_RE = re.compile(r"/([^/]+)/(\d+)-[^/]+\.html$")

_H1_NAME_RE = re.compile(r'<h1[^>]*itemprop="name"[^>]*>\s*(.*?)\s*</h1>', re.S)
_COVER_IMG_RE = re.compile(r'<img[^>]*class="[^"]*js-qv-product-cover[^"]*"[^>]*\bsrc="([^"]+)"')
# PrestaShop emits availability as <link itemprop="availability" href="https://schema.org/InStock"/>
# -- an href value, which extract._microdata_value (content= / element-text shapes) cannot see.
_AVAILABILITY_RE = re.compile(r'itemprop="availability"[^>]*\bhref="([^"]*)"')
# Volume off the product NAME: "Dipping ink 60 ml - PAPYRUS DIP" / "Dipping ink 17 ml - ...".
# Word-bounded so a name like "17ml" (no space) still parses but "html" never does.
_ML_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*ml\b", re.I)


def _availability(product_html: str) -> str | None:
    """schema.org availability URL tail -> the shopify strategies' snake_case vocabulary
    (InStock -> in_stock, OutOfStock -> out_of_stock, PreOrder -> pre_order, ...)."""
    match = _AVAILABILITY_RE.search(product_html)
    if match is None:
        return None
    tail = match.group(1).rstrip("/").rsplit("/", 1)[-1].strip()
    if not tail:
        return None
    return re.sub(r"(?<!^)(?=[A-Z])", "_", tail).lower()


def _ml(name: str) -> int | float | None:
    match = _ML_RE.search(name)
    if match is None:
        return None
    value = float(match.group(1).replace(",", "."))
    return int(value) if value.is_integer() else value


def _parse_product(page_html: str) -> dict:
    """Parse a product page's Product-scoped microdata into cursor-cacheable fields.

    Empty dict = parse miss (no Product itemtype block, or one with no extractable name) --
    counted against DETAIL_MISS_CAP by the caller. Field keys appear only when found.
    """
    itemtype = _PRODUCT_ITEMTYPE_RE.search(page_html)
    if itemtype is None:
        return {}
    # Everything BELOW the Product itemtype: the breadcrumb's own itemprop="name" entries
    # ("Home", ...) sit above it and must never win a first-match lookup.
    block = page_html[itemtype.start() :]

    h1 = _H1_NAME_RE.search(block)
    name = _clean(re.sub(r"<[^>]+>", " ", h1.group(1))) if h1 else _microdata_value(block, "name")
    if not name:
        return {}

    fields: dict[str, object] = {"name": name}
    reference = _microdata_value(block, "sku")
    if reference is not None:
        fields["reference"] = reference
    mpn = _microdata_value(block, "mpn")
    if mpn is not None:
        fields["mpn"] = mpn
    ean = _digits(_microdata_value(block, "gtin13"))
    if ean is not None:
        fields["ean"] = ean

    raw_price = _microdata_value(block, "price")
    currency = _microdata_value(block, "priceCurrency")
    if raw_price is not None and currency == "EUR":
        try:
            fields["priceEur"] = float(raw_price)
        except ValueError:
            pass

    availability = _availability(block)
    if availability is not None:
        fields["availability"] = availability
    cover = _COVER_IMG_RE.search(block)
    if cover is not None:
        fields["imageUrl"] = cover.group(1)
    return fields


def sitemap_sd_paints_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    old_details: dict[str, dict] = dict(cursor.get("details") or {})
    old_pending: set[str] = set(cursor.get("pending_details") or [])

    stats = {
        "fetched_sitemaps": 0,
        "sitemap_urls_total": 0,
        "sitemap_urls_filtered": 0,
        "skipped_non_product": 0,
        "products_enumerated": 0,
        "skipped_unknown_vendor": 0,
        "details_fetched": 0,
        "detail_fetch_errors": 0,
        "detail_not_found": 0,
        "detail_parse_misses": 0,
        "eans_found": 0,
        "prices_found": 0,
        "ml_parsed": 0,
    }

    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = (
        context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None
    )

    # --- Enumerate the sitemap(s) -- the full population, every run. ---
    sitemap_urls = [str(u) for u in (descriptor.scope.get("sitemaps") or [])]
    all_urls = _enumerate_urls(client, sitemap_urls, stats)
    stats["sitemap_urls_total"] = len(all_urls)

    url_include = descriptor.scope.get("urlInclude")
    pattern = re.compile(str(url_include)) if url_include else None
    filtered_urls = {u for u in all_urls if pattern is None or pattern.search(u)}
    stats["sitemap_urls_filtered"] = len(filtered_urls)

    # id_product -> {url, categorySlug}. Sorted iteration + setdefault keeps a hypothetical
    # duplicate id (not observed live -- PrestaShop emits one canonical URL per product)
    # deterministic: the lexicographically-smallest URL wins.
    products: dict[str, dict[str, str]] = {}
    for url in sorted(filtered_urls):
        match = _PRODUCT_URL_RE.search(urlsplit(url).path)
        if match is None:
            stats["skipped_non_product"] += 1
            continue
        products.setdefault(match.group(2), {"url": url, "categorySlug": match.group(1)})
    stats["products_enumerated"] = len(products)

    if manufacturer is None:
        # Same posture as wp_rest_paints/mr_hobby: an unattributable pinned vendor observes
        # nothing (and fetches nothing) -- the descriptor's minCount then fails the run loudly
        # rather than emitting manufacturer-less evidence.
        stats["skipped_unknown_vendor"] = len(products)
        products = {}

    # --- Detail queue: new ids first, then parse-miss retries below the give-up cap. ---
    new_candidates: list[str] = []
    retry_candidates: list[str] = []
    for product_id in products:
        recorded = old_details.get(product_id)
        if recorded is None:
            (retry_candidates if product_id in old_pending else new_candidates).append(product_id)
        elif not recorded.get("name"):
            if recorded.get("detailMisses", 0) < DETAIL_MISS_CAP:
                retry_candidates.append(product_id)
            # else: capped out -- never re-queued (and, with no name, never observed).
        # else: parsed data known; never re-fetched (one-off snapshot model -- see docstring).

    detail_queue = sorted(new_candidates, key=int) + sorted(retry_candidates, key=int)
    budget = context.budget
    to_fetch = detail_queue if budget is None else detail_queue[: max(budget, 0)]
    to_fetch_set = set(to_fetch)

    # Carry forward every cached detail this run isn't fetching -- parsed data must never be
    # dropped just because the budget didn't reach its id -- while pruning ids that left the
    # filtered sitemap.
    new_details: dict[str, dict] = {
        product_id: old_details[product_id]
        for product_id in products
        if product_id in old_details and product_id not in to_fetch_set
    }

    refreshed: set[str] = set()
    for product_id in to_fetch:
        stats["details_fetched"] += 1
        try:
            page_html = client.get_text(products[product_id]["url"])
        except FetchError as error:
            if error.status == 404:
                # A sitemap loc whose page is gone is a definitive absence (stale sitemap),
                # not a transient fault: cap NOW so a dead link can't stay pending forever.
                stats["detail_not_found"] += 1
                new_details[product_id] = {"detailMisses": DETAIL_MISS_CAP}
                refreshed.add(product_id)
                continue
            stats["detail_fetch_errors"] += 1
            if product_id in old_details:
                new_details[product_id] = old_details[product_id]
            continue  # stays pending; transient errors never count against the miss cap
        parsed = _parse_product(page_html)
        if parsed:
            new_details[product_id] = parsed
            refreshed.add(product_id)
        else:
            stats["detail_parse_misses"] += 1
            misses = old_details.get(product_id, {}).get("detailMisses", 0)
            new_details[product_id] = {"detailMisses": misses + 1}

    # --- Observations: only ids with parsed detail data (a bare sitemap loc has no fields). ---
    observations: list[Observation] = []
    for product_id in sorted(products, key=int):
        detail = new_details.get(product_id) or {}
        name = detail.get("name")
        if not name:
            continue  # pending (budget) or capped-out: nothing observable yet

        mpn = detail.get("mpn")
        reference = detail.get("reference")
        sku = mpn or reference

        hints: dict[str, object] = {
            "category": "paint",
            "categorySlug": products[product_id]["categorySlug"],
        }
        ml = _ml(str(name))
        if ml is not None:
            hints["ml"] = ml
            stats["ml_parsed"] += 1
        if reference and reference != sku:
            hints["reference"] = reference

        ean = detail.get("ean")
        if ean:
            stats["eans_found"] += 1
        price_eur = detail.get("priceEur")
        if price_eur is not None:
            stats["prices_found"] += 1

        observations.append(
            Observation(
                key=f"{descriptor.id}:{product_id}",
                url=products[product_id]["url"],
                manufacturer=manufacturer,
                name=str(name),
                sku=str(sku) if sku else None,
                ean=str(ean) if ean else None,
                priceEur=price_eur,
                imageUrl=detail.get("imageUrl"),
                availability=detail.get("availability"),
                hints=hints,
                firstSeen=context.run_date,
                lastSeen=context.run_date,
                extractor=EXTRACTOR,
            )
        )

    pending_details = sorted(set(detail_queue) - refreshed, key=int)
    # Queue drained == every enumerated product page fetched (or definitively capped): this IS
    # the manufacturer's full population, so the sweep claim is honest -- see docstring.
    full_sweep = not pending_details

    return StrategyResult(
        observations=observations,
        full_sweep=full_sweep,
        stats=stats,
        cursor={"details": new_details, "pending_details": pending_details},
    )


STRATEGIES["sitemap-sd-paints"] = sitemap_sd_paints_strategy
