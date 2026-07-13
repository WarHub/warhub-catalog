"""Shopify strategy: bulk /products.json enumeration + budgeted per-handle barcode fetch.

Cursor schema (as-built -- see task-5-report.md for the full rationale):

    {
      "updated_at": {"<handle>": {"updatedAt": "<bulk updated_at ISO>", "ean": "<digits>"}},
      "pending_details": ["<handle>", ...],
    }

`last_good_count` / `last_run_date` are added by `run_source`, never written here.

Deviation from the brief's literal `"updated_at": {handle: iso}` shape: strategies never see the
EvidenceStore (only `(descriptor, client, cursor, context)`), and `EvidenceStore.upsert` fully
replaces a record except firstSeen/lastSeen. A bulk-only candidate that omits `ean` for a handle
whose ean is already known -- because this run's budget didn't reach it -- would silently WIPE
that ean on upsert. Storing the ean itself (not just the timestamp) inside the cursor's
`updated_at` map lets every run's candidate carry forward a previously-confirmed ean without a
fresh detail fetch, closing that data-loss hole while keeping the same two top-level keys/intent.
"""
from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "shopify@1"
PAGE_LIMIT = 250

_PRICE_FIELDS = {"gbp": "priceGbp", "usd": "priceUsd", "eur": "priceEur"}


def _price_field(currency: object) -> str:
    return _PRICE_FIELDS.get(str(currency).casefold(), "priceGbp")


def _availability(variants: list[dict]) -> str | None:
    flags = [v["available"] for v in variants if isinstance(v, dict) and "available" in v]
    if not flags:
        return None
    return "in_stock" if any(flags) else "out_of_stock"


def _image_url(product: dict) -> str | None:
    images = product.get("images") or []
    if not images:
        return None
    first = images[0]
    if isinstance(first, dict):
        return first.get("src")
    return first if isinstance(first, str) else None


def _apply_hints(product: dict, mapping: dict) -> tuple[dict[str, object], int]:
    """Map bulk product_type/tags -> gameSystem/faction slugs via the source's mapping file.

    Never guesses: a product_type/tags value with no entry in the mapping is counted (not
    hinted). Faction match is the first tag (in sorted order, for determinism) present in the
    faction map.
    """
    hints: dict[str, object] = {}
    unmapped = 0
    gs_map = mapping.get("gameSystem") or {}
    faction_map = mapping.get("faction") or {}

    product_type = product.get("product_type") or ""
    if product_type:
        slug = gs_map.get(product_type)
        if slug:
            hints["gameSystem"] = slug
        else:
            unmapped += 1

    tags = product.get("tags") or []
    faction_slug = None
    for tag in sorted(tags):
        if tag in faction_map:
            faction_slug = faction_map[tag]
            break
    if faction_slug:
        hints["faction"] = faction_slug
    elif tags:
        unmapped += 1

    return hints, unmapped


def _extract_barcode(detail: dict) -> str | None:
    """First non-empty variant barcode, digits-only after strip. Validation stays downstream."""
    for variant in detail.get("variants") or []:
        barcode = variant.get("barcode") if isinstance(variant, dict) else None
        if barcode:
            digits = "".join(ch for ch in str(barcode) if ch.isdigit())
            if digits:
                return digits
    return None


def _build_candidate(
    descriptor: SourceDescriptor,
    product: dict,
    manufacturer: str,
    mapping: dict,
    ean: str | None,
    run_date: str,
) -> tuple[Observation, int]:
    handle = product["handle"]
    variants = product.get("variants") or []
    first_variant = variants[0] if variants else {}
    sku = first_variant.get("sku") or None

    price_kwargs: dict[str, object] = {}
    raw_price = first_variant.get("price")
    if raw_price not in (None, ""):
        try:
            price_kwargs[_price_field(descriptor.scope.get("currency", "gbp"))] = float(raw_price)
        except (TypeError, ValueError):
            pass

    hints, unmapped = _apply_hints(product, mapping)

    observation = Observation(
        key=f"{descriptor.id}:{handle}",
        url=f"{descriptor.baseUrl}/products/{handle}",
        manufacturer=manufacturer,
        name=product["title"],
        sku=sku,
        ean=ean,
        imageUrl=_image_url(product),
        availability=_availability(variants),
        hints=hints,
        firstSeen=run_date,
        lastSeen=run_date,
        extractor=EXTRACTOR,
        **price_kwargs,
    )
    return observation, unmapped


def shopify_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    mapping = context.mappings.get(descriptor.id, {}) if context.mappings else {}
    old_updated_at: dict[str, dict] = dict(cursor.get("updated_at") or {})
    old_pending: set[str] = set(cursor.get("pending_details") or [])

    stats = {
        "fetched_pages": 0,
        "products_seen": 0,
        "details_fetched": 0,
        "barcodes_found": 0,
        "skipped_unknown_vendor": 0,
        "out_of_scope_vendor": 0,
        "unmapped_hints": 0,
        "detail_fetch_errors": 0,
    }

    # --- Enumerate: always full, cheap pages. ---
    products: dict[str, dict] = {}
    page = 1
    while True:
        payload = client.get_json("/products.json", params={"limit": PAGE_LIMIT, "page": page})
        stats["fetched_pages"] += 1
        page_products = payload.get("products") if isinstance(payload, dict) else None
        page_products = page_products or []
        if not page_products:
            break
        for product in page_products:
            products[product["handle"]] = product
        page += 1

    stats["products_seen"] = len(products)

    # --- Attribute manufacturer, bucket into priority classes for the detail queue. ---
    manufacturer_by_handle: dict[str, str] = {}
    new_candidates: list[str] = []
    missing_ean_candidates: list[str] = []
    stale_candidates: list[str] = []

    # Retailer allow-list (e.g. ret-goblingaming's scope.vendors: [Games Workshop]): when
    # declared, only these exact raw vendor strings are eligible at all -- applied BEFORE
    # taxonomy attribution, and counted separately from an ordinary unknown-vendor skip so a
    # health report can distinguish "not the brand this retailer source is scoped to" from "not
    # in the taxonomy anywhere." Manufacturer-kind sources (no scope.vendors) are unaffected.
    scope_vendors = descriptor.scope.get("vendors")

    for handle, product in sorted(products.items()):
        vendor = product.get("vendor") or ""
        if scope_vendors is not None and vendor not in scope_vendors:
            stats["out_of_scope_vendor"] += 1
            continue
        manufacturer = context.taxonomy.manufacturer_for_vendor(vendor)
        if manufacturer is None:
            stats["skipped_unknown_vendor"] += 1
            continue
        manufacturer_by_handle[handle] = manufacturer

        bulk_updated_at = product.get("updated_at") or ""
        recorded = old_updated_at.get(handle)
        if recorded is not None:
            if bulk_updated_at > recorded.get("updatedAt", ""):
                stale_candidates.append(handle)
        elif handle in old_pending:
            missing_ean_candidates.append(handle)
        else:
            new_candidates.append(handle)

    kept_handles = set(manufacturer_by_handle)
    detail_queue = (
        sorted(new_candidates)
        + sorted(missing_ean_candidates)
        + sorted(stale_candidates, key=lambda h: old_updated_at[h].get("updatedAt", ""))
    )

    budget = context.budget
    to_fetch = detail_queue if budget is None else detail_queue[: max(budget, 0)]
    to_fetch_set = set(to_fetch)

    # Carry forward every already-known ean for a handle this run isn't (re)fetching --
    # never silently drop a confirmed ean just because the budget didn't reach it this run.
    new_updated_at: dict[str, dict] = {
        handle: old_updated_at[handle]
        for handle in kept_handles
        if handle in old_updated_at and handle not in to_fetch_set
    }

    refreshed_this_run: set[str] = set()
    for handle in to_fetch:
        product = products[handle]
        stats["details_fetched"] += 1
        try:
            detail = client.get_json(f"/products/{handle}.js")
        except FetchError:
            stats["detail_fetch_errors"] += 1
            # A transient fetch failure must not destroy a previously-confirmed ean: preserve it
            # and leave the handle queued (via pending_details below) for a later run.
            if handle in old_updated_at:
                new_updated_at[handle] = old_updated_at[handle]
            continue

        barcode = _extract_barcode(detail if isinstance(detail, dict) else {})
        if barcode:
            stats["barcodes_found"] += 1
            new_updated_at[handle] = {"updatedAt": product.get("updated_at") or "", "ean": barcode}
            refreshed_this_run.add(handle)
        # else: detail fetch succeeded but no barcode -- any previously-known ean for this
        # handle is dropped (the live response is the freshest truth) and it re-queues below.

    observations: list[Observation] = []
    for handle in sorted(kept_handles):
        product = products[handle]
        ean = new_updated_at.get(handle, {}).get("ean")
        observation, unmapped = _build_candidate(
            descriptor, product, manufacturer_by_handle[handle], mapping, ean, context.run_date
        )
        stats["unmapped_hints"] += unmapped
        observations.append(observation)

    pending_details = sorted(set(detail_queue) - refreshed_this_run)
    full_sweep = not pending_details

    result_cursor = {
        "updated_at": new_updated_at,
        "pending_details": pending_details,
    }

    return StrategyResult(
        observations=observations,
        full_sweep=full_sweep,
        stats=stats,
        cursor=result_cursor,
    )


STRATEGIES["shopify"] = shopify_strategy
