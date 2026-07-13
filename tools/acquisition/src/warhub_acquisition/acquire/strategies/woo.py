"""WooCommerce Store API strategy: full enumeration + budgeted JSON-LD gtin detail fetch.

Registered as `STRATEGIES["woo-store-api"]`. Mirrors shopify.py's architecture (see
task-5-report.md) with two deliberate, evidence-driven deviations documented in
task-8-report.md:

1. **Manufacturer is PINNED from `descriptor.scope["manufacturer"]`, not derived per-product.**
   WooCommerce's Store API has no vendor/brand field at all (unlike Shopify's bulk payload) --
   every product returned by a descriptor's own `baseUrl` store IS that manufacturer's own
   catalog. `descriptor.scope["manufacturer"]` is a vendor-name string resolved through the
   *same* `Taxonomy.manufacturer_for_vendor` mechanism shopify.py uses per-product (this just
   calls it once per source instead of once per product), so a descriptor whose declared
   manufacturer name doesn't (yet) exist in taxonomy/manufacturers.yaml fails safely: every
   enumerated product is skipped and counted under `stats["skipped_unknown_vendor"]`, exactly
   mirroring shopify's per-product unknown-vendor skip semantics.
2. **No staleness/"updated_at" bucket.** Woo's Store API product objects carry no modification
   timestamp field at all (confirmed absent from the live schema during fixture capture), so
   unlike shopify's cursor (`{handle: {updatedAt, ean}}`), the cursor here is simply
   `{"gtin": {"<id>": "<digits>"}, "pending_details": ["<id>", ...]}` -- once a product's gtin is
   known there is no signal that would ever justify re-fetching it, so the detail queue is
   strictly "new products first, then previously-queued-but-still-missing", never "stale."

Cursor schema:

    {
      "gtin": {"<product id>": "<digits>"},
      "pending_details": ["<product id>", ...],
    }

`last_good_count` / `last_run_date` are added by `run_source`, never written here.
"""
import json
import re

from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "woo@1"
PRODUCTS_PATH = "/wp-json/wc/store/products"
PAGE_SIZE = 100

_PRICE_FIELDS = {"gbp": "priceGbp", "usd": "priceUsd", "eur": "priceEur"}

_LDJSON_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def _price_field(currency: object) -> str:
    return _PRICE_FIELDS.get(str(currency).casefold(), "priceGbp")


def _price_major_units(prices: dict) -> float | None:
    """Woo Store API prices are strings in MINOR units + a `currency_minor_unit` exponent --
    e.g. `{"price": "2499", "currency_minor_unit": 2}` -> 24.99. A malformed/missing price is
    silently omitted (matches shopify.py's price-parse-failure handling), not a hard failure."""
    raw = prices.get("price")
    if raw in (None, ""):
        return None
    try:
        minor_units = int(raw)
    except (TypeError, ValueError):
        return None
    try:
        exponent = int(prices.get("currency_minor_unit", 2))
    except (TypeError, ValueError):
        exponent = 2
    return minor_units / (10**exponent)


def _image_url(product: dict) -> str | None:
    images = product.get("images") or []
    if not images:
        return None
    first = images[0]
    if isinstance(first, dict):
        return first.get("src")
    return first if isinstance(first, str) else None


def _availability(product: dict) -> str | None:
    if "is_in_stock" not in product:
        return None
    return "in_stock" if product["is_in_stock"] else "out_of_stock"


def _apply_hints(categories: list, mapping: dict) -> tuple[dict[str, object], int]:
    """Map Woo category slugs -> gameSystem/faction taxonomy slugs via the source's mapping
    file. Woo's Store API exposes one flat `categories` list per product (no separate
    product_type/tags split like Shopify) -- the same slug set is checked against both the
    gameSystem and faction maps, first (sorted, for determinism) match wins each. Never guesses:
    a non-empty category list with no match in a given map is counted (not hinted), mirroring
    shopify.py's tag-based unmapped-counting exactly.
    """
    hints: dict[str, object] = {}
    unmapped = 0
    gs_map = mapping.get("gameSystem") or {}
    faction_map = mapping.get("faction") or {}

    slugs = sorted(
        category.get("slug", "")
        for category in categories
        if isinstance(category, dict) and category.get("slug")
    )

    gs_slug = next((gs_map[slug] for slug in slugs if slug in gs_map), None)
    if gs_slug:
        hints["gameSystem"] = gs_slug
    elif slugs:
        unmapped += 1

    faction_slug = next((faction_map[slug] for slug in slugs if slug in faction_map), None)
    if faction_slug:
        hints["faction"] = faction_slug
    elif slugs:
        unmapped += 1

    return hints, unmapped


def _is_product_node(node: dict) -> bool:
    node_type = node.get("@type")
    return node_type == "Product" or (isinstance(node_type, list) and "Product" in node_type)


def _extract_gtin(html: str) -> str | None:
    """Regex every `<script type="application/ld+json">` block (real captures carry >1, only
    one of which holds the Product node), parse each as JSON, unwrap `@graph` nesting, and take
    `gtin`/`gtin13` off the first Product node found. Digits-only after strip, no EAN-13
    validation (stays downstream, matching shopify.py's barcode extraction)."""
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
            raw = node.get("gtin") or node.get("gtin13")
            if raw:
                digits = "".join(ch for ch in str(raw) if ch.isdigit())
                if digits:
                    return digits
    return None


def _build_candidate(
    descriptor: SourceDescriptor,
    product: dict,
    manufacturer: str,
    mapping: dict,
    gtin: str | None,
    run_date: str,
) -> tuple[Observation, int]:
    price_kwargs: dict[str, object] = {}
    price = _price_major_units(product.get("prices") or {})
    if price is not None:
        price_kwargs[_price_field(descriptor.scope.get("currency", "gbp"))] = price

    hints, unmapped = _apply_hints(product.get("categories") or [], mapping)

    observation = Observation(
        key=f"{descriptor.id}:{product['id']}",
        url=product.get("permalink"),
        manufacturer=manufacturer,
        name=product["name"],
        sku=product.get("sku") or None,
        ean=gtin,
        imageUrl=_image_url(product),
        availability=_availability(product),
        hints=hints,
        firstSeen=run_date,
        lastSeen=run_date,
        extractor=EXTRACTOR,
        **price_kwargs,
    )
    return observation, unmapped


def woo_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    mapping = context.mappings.get(descriptor.id, {}) if context.mappings else {}
    gtin_enabled = bool(descriptor.scope.get("gtinFromJsonLd"))

    stats = {
        "fetched_pages": 0,
        "products_seen": 0,
        "details_fetched": 0,
        "gtins_found": 0,
        "skipped_unknown_vendor": 0,
        "unmapped_hints": 0,
        "detail_fetch_errors": 0,
    }

    # --- Enumerate: always full, terminate ONLY on an empty page (mirrors shopify.py). Woo's
    # `X-WP-Total` header is informational only (stats["reported_total"]) -- a missing or
    # garbled header must never end enumeration early, so it is never consulted for loop
    # control. Confirmed live during fixture capture: an out-of-range page past the last one
    # returns an empty list, which is what actually terminates the loop. ---
    products: dict[str, dict] = {}
    page = 1
    while True:
        payload, headers = client.get_json_response(
            PRODUCTS_PATH, params={"per_page": PAGE_SIZE, "page": page}
        )
        stats["fetched_pages"] += 1
        page_products = payload if isinstance(payload, list) else []
        if "reported_total" not in stats:
            reported_total = headers.get("X-WP-Total")
            if reported_total is not None:
                try:
                    stats["reported_total"] = int(reported_total)
                except (TypeError, ValueError):
                    pass
        if not page_products:
            break
        for product in page_products:
            products[str(product["id"])] = product
        page += 1

    stats["products_seen"] = len(products)

    # --- Manufacturer: pinned per-source (Woo has no per-product vendor field at all -- see
    # module docstring). An unresolvable scope.manufacturer skips everything, mirroring
    # shopify.py's per-product unknown-vendor skip. ---
    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None

    if manufacturer is None:
        stats["skipped_unknown_vendor"] = len(products)
        kept_ids: set[str] = set()
    else:
        kept_ids = set(products)

    # --- Detail queue / budget: missing-gtin-first, only when scope.gtinFromJsonLd is set. No
    # staleness bucket exists -- see module docstring for why. ---
    new_gtin_map: dict[str, str] = {}
    pending_details: list[str] = []

    if gtin_enabled and kept_ids:
        old_gtin: dict[str, str] = dict(cursor.get("gtin") or {})
        old_pending: set[str] = {str(pid) for pid in (cursor.get("pending_details") or [])}

        new_ids = sorted((pid for pid in kept_ids if pid not in old_gtin and pid not in old_pending), key=int)
        missing_ids = sorted((pid for pid in kept_ids if pid not in old_gtin and pid in old_pending), key=int)
        detail_queue = new_ids + missing_ids

        budget = context.budget
        to_fetch = detail_queue if budget is None else detail_queue[: max(budget, 0)]

        new_gtin_map = {pid: old_gtin[pid] for pid in kept_ids if pid in old_gtin}
        refreshed: set[str] = set()
        for pid in to_fetch:
            product = products[pid]
            permalink = product.get("permalink")
            if not permalink:
                continue  # nothing to fetch; stays queued via pending_details below
            stats["details_fetched"] += 1
            try:
                html = client.get_text(permalink)
            except FetchError:
                stats["detail_fetch_errors"] += 1
                continue

            gtin = _extract_gtin(html)
            if gtin:
                stats["gtins_found"] += 1
                new_gtin_map[pid] = gtin
                refreshed.add(pid)
            # else: fetched successfully but no gtin in the page's JSON-LD -- re-queues below.

        pending_details = sorted(set(detail_queue) - refreshed, key=int)

    observations: list[Observation] = []
    for pid in sorted(kept_ids, key=int):
        product = products[pid]
        gtin = new_gtin_map.get(pid)
        observation, unmapped = _build_candidate(
            descriptor, product, manufacturer, mapping, gtin, context.run_date
        )
        stats["unmapped_hints"] += unmapped
        observations.append(observation)

    full_sweep = not pending_details

    result_cursor = {
        "gtin": new_gtin_map,
        "pending_details": pending_details,
    }

    return StrategyResult(
        observations=observations,
        full_sweep=full_sweep,
        stats=stats,
        cursor=result_cursor,
    )


STRATEGIES["woo-store-api"] = woo_strategy
