"""Shopify paints strategy: manufacturer-owned paint stores (Army Painter, Monument, ...).

Same bulk /products.json enumeration + budgeted per-handle /products/{handle}.js barcode
machinery as the generic `shopify` strategy -- including the exact cursor schema documented in
shopify.py (updated_at map carrying confirmed eans + detailMisses give-up counter +
pending_details) -- specialized for paint catalogs:

- scope.includeTypes: product_type allow-list applied at harvest time (exact match, "" allowed
  -- some Army Painter paint ranges ship untyped). Omitted = every product observed.
- scope.vendors: optional exact vendor allow-list applied BEFORE taxonomy attribution
  (monumenthobbies.com carries Tri Art / Mesko Pinsel / ... third-party stock).
- scope.collections: optional list of collection handles. When present, enumeration walks
  /collections/{handle}/products.json (each paginated to an empty page, in descriptor order)
  INSTEAD of the store-wide /products.json; absent, behavior is exactly the store-wide
  enumeration above. Built for scale75.com (live recon 2026-07-24): that store's product_type
  is empty store-wide and its tags are generic (PINTURAS / PINTURAS INDIVIDUALES), so
  per-range collection membership is the ONLY range signal the store publishes -- it must be
  captured at harvest time, because the store-wide listing cannot ever be re-parsed into
  ranges. Every scoped collection a product was listed in is recorded as hints.collections
  (sorted) for the downstream bridge's range attribution. Products are deduped by handle: the
  FIRST collection (descriptor order) to list a handle supplies the payload -- Shopify renders
  the same product object in every collection listing (modulo updated_at, which can tick
  between page fetches), so first-wins is determinism, not data selection. Descriptor ordering
  convention: specific range collections first, catch-all/umbrella collections LAST. Range
  attribution never depends on that order (hints.collections records every membership), but a
  degraded enumeration (platform cap / mid-walk 400) loses tail collections first -- ordering
  the umbrella last means coverage of range-less strays is what degrades, never a specific
  range's attribution. A nonexistent handle 404s and fails the run loudly -- exactly what a
  descriptor typo should do. scope.maxEnumerationPages, when combined with collections,
  bounds each collection's walk individually (same platform cap either way).
- scope.skipDetails: true skips the per-handle /products/{handle}.js barcode queue entirely:
  no detail fetches, no updated_at/detailMisses/pending_details bookkeeping (the cursor stays
  empty), and full_sweep is simply "enumeration wasn't capped". For stores whose variant
  barcodes are unpopulated store-wide (scale75.com, verified 2026-07-24: sampled .js details
  all carry barcode null), the detail sweep would spend hundreds of requests per run to learn
  nothing -- and would KEEP spending them until every handle exhausts DETAIL_MISS_CAP.
- Observations keep the store title verbatim as `name`; paint-relevant raw signals ride along
  in hints for the downstream bridge (scripts/gen_paint_harvest.py) to parse into
  range/paint-name/volume per brand: hints.productType, hints.grams (first variant),
  hints.tags (sorted verbatim), hints.collections (scoped-collection mode only),
  hints.category = "paint".

Range/single classification deliberately does NOT happen here: evidence stays faithful to the
store, and re-tuning brand parsing must never require a re-fetch.
"""
from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.acquire.strategies.shopify import (
    DETAIL_MISS_CAP,
    PAGE_LIMIT,
    PLATFORM_MAX_PAGES,
    _availability,
    _extract_barcode,
    _image_url,
    _price_field,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "shopify-paints@1"


def _first_variant(product: dict) -> dict:
    variants = product.get("variants") or []
    first = variants[0] if variants else {}
    return first if isinstance(first, dict) else {}


def _grams(product: dict) -> int | None:
    grams = _first_variant(product).get("grams")
    return grams if isinstance(grams, int) and grams > 0 else None


def _build_observation(
    descriptor: SourceDescriptor,
    product: dict,
    manufacturer: str,
    ean: str | None,
    run_date: str,
    collections: set[str] | None = None,
) -> Observation:
    handle = product["handle"]
    first_variant = _first_variant(product)

    price_kwargs: dict[str, object] = {}
    raw_price = first_variant.get("price")
    if raw_price not in (None, ""):
        try:
            price_kwargs[_price_field(descriptor.scope.get("currency", "usd"))] = float(raw_price)
        except (TypeError, ValueError):
            pass

    hints: dict[str, object] = {
        "category": "paint",
        "productType": product.get("product_type") or "",
    }
    grams = _grams(product)
    if grams is not None:
        hints["grams"] = grams
    if collections:
        hints["collections"] = sorted(collections)
    tags = product.get("tags") or []
    if tags:
        hints["tags"] = sorted(str(t) for t in tags)

    return Observation(
        key=f"{descriptor.id}:{handle}",
        url=f"{descriptor.baseUrl}/products/{handle}",
        manufacturer=manufacturer,
        name=product["title"],
        sku=first_variant.get("sku") or None,
        ean=ean,
        imageUrl=_image_url(product),
        availability=_availability(product.get("variants") or []),
        hints=hints,
        firstSeen=run_date,
        lastSeen=run_date,
        extractor=EXTRACTOR,
        **price_kwargs,
    )


def _paginate_products(
    client: PoliteClient, path: str, stats: dict[str, int], max_pages: int
) -> tuple[list[dict], bool]:
    """Walk one products.json listing (store-wide or per-collection) until an empty page.

    Returns (products, capped). Same defensive posture as shopify.py: a 400 means the platform
    cap moved -- report the walk as capped, never kill the whole source over it (an empty
    page-1 store fires minCount instead).
    """
    listed: list[dict] = []
    page = 1
    while page <= max_pages:
        try:
            payload = client.get_json(path, params={"limit": PAGE_LIMIT, "page": page})
        except FetchError as error:
            if error.status == 400:
                stats["enumeration_capped_by_400"] += 1
                return listed, True
            raise
        stats["fetched_pages"] += 1
        page_products = payload.get("products") if isinstance(payload, dict) else None
        page_products = page_products or []
        if not page_products:
            return listed, False
        listed.extend(page_products)
        page += 1
    return listed, True


def shopify_paints_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    old_updated_at: dict[str, dict] = dict(cursor.get("updated_at") or {})
    old_pending: set[str] = set(cursor.get("pending_details") or [])

    stats = {
        "fetched_pages": 0,
        "products_seen": 0,
        "kept_paint_products": 0,
        "skipped_type": 0,
        "skipped_unknown_vendor": 0,
        "out_of_scope_vendor": 0,
        "details_fetched": 0,
        "barcodes_found": 0,
        "detail_fetch_errors": 0,
        "enumeration_capped": 0,
        "enumeration_capped_by_400": 0,
    }

    max_pages = PLATFORM_MAX_PAGES
    scoped_max_pages = descriptor.scope.get("maxEnumerationPages")
    if isinstance(scoped_max_pages, int):
        max_pages = min(max_pages, scoped_max_pages)

    # --- Enumerate: always full, cheap pages -- until an empty page or the platform cap. ---
    # Two modes (see module docstring): store-wide /products.json (the default), or -- when
    # scope.collections is present -- each scoped /collections/{handle}/products.json in
    # descriptor order, deduped by handle with every membership recorded for attribution.
    scope_collections = descriptor.scope.get("collections")
    products: dict[str, dict] = {}
    collections_by_handle: dict[str, set[str]] = {}
    enumeration_capped = False
    if scope_collections:
        stats["collections_enumerated"] = 0
        for collection in scope_collections:
            listed, capped = _paginate_products(
                client, f"/collections/{collection}/products.json", stats, max_pages
            )
            stats["collections_enumerated"] += 1
            enumeration_capped = enumeration_capped or capped
            for product in listed:
                handle = product["handle"]
                products.setdefault(handle, product)
                collections_by_handle.setdefault(handle, set()).add(collection)
    else:
        listed, enumeration_capped = _paginate_products(client, "/products.json", stats, max_pages)
        for product in listed:
            products[product["handle"]] = product

    if enumeration_capped:
        stats["enumeration_capped"] = 1

    stats["products_seen"] = len(products)

    # --- Filter to paint-relevant products, attribute manufacturer, bucket detail queue. ---
    include_types = descriptor.scope.get("includeTypes")
    scope_vendors = descriptor.scope.get("vendors")
    skip_details = bool(descriptor.scope.get("skipDetails"))

    manufacturer_by_handle: dict[str, str] = {}
    new_candidates: list[str] = []
    missing_ean_candidates: list[str] = []
    stale_candidates: list[str] = []

    for handle, product in sorted(products.items()):
        vendor = product.get("vendor") or ""
        if scope_vendors is not None and vendor not in scope_vendors:
            stats["out_of_scope_vendor"] += 1
            continue
        manufacturer = context.taxonomy.manufacturer_for_vendor(vendor)
        if manufacturer is None:
            stats["skipped_unknown_vendor"] += 1
            continue
        if include_types is not None and (product.get("product_type") or "") not in include_types:
            stats["skipped_type"] += 1
            continue
        manufacturer_by_handle[handle] = manufacturer

        if skip_details:
            # scope.skipDetails: the classification below only feeds the .js detail queue,
            # which this source has opted out of entirely.
            continue

        bulk_updated_at = product.get("updated_at") or ""
        recorded = old_updated_at.get(handle)
        if recorded is not None:
            if bulk_updated_at > recorded.get("updatedAt", ""):
                stale_candidates.append(handle)
            elif not recorded.get("ean") and recorded.get("detailMisses", 0) < DETAIL_MISS_CAP:
                missing_ean_candidates.append(handle)
            # else: ean known, or capped out -- excluded from every queue bucket.
        elif handle in old_pending:
            missing_ean_candidates.append(handle)
        else:
            new_candidates.append(handle)

    kept_handles = set(manufacturer_by_handle)
    stats["kept_paint_products"] = len(kept_handles)

    new_updated_at: dict[str, dict] = {}
    pending_details: list[str] = []
    if not skip_details:
        detail_queue = (
            sorted(new_candidates)
            + sorted(missing_ean_candidates)
            + sorted(stale_candidates, key=lambda h: old_updated_at[h].get("updatedAt", ""))
        )

        budget = context.budget
        to_fetch = detail_queue if budget is None else detail_queue[: max(budget, 0)]
        to_fetch_set = set(to_fetch)

        # Carry forward every known ean this run isn't (re)fetching -- never silently drop a
        # confirmed ean just because the budget didn't reach its handle (see shopify.py docstring).
        new_updated_at = {
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
                if handle in old_updated_at:
                    new_updated_at[handle] = old_updated_at[handle]
                continue

            bulk_updated_at = product.get("updated_at") or ""
            barcode = _extract_barcode(detail if isinstance(detail, dict) else {})
            if barcode:
                stats["barcodes_found"] += 1
                new_updated_at[handle] = {"updatedAt": bulk_updated_at, "ean": barcode}
                refreshed_this_run.add(handle)
            else:
                previous = old_updated_at.get(handle)
                if previous is not None and bulk_updated_at <= previous.get("updatedAt", ""):
                    misses = previous.get("detailMisses", 0)
                else:
                    misses = 0
                new_updated_at[handle] = {"updatedAt": bulk_updated_at, "detailMisses": misses + 1}

        pending_details = sorted(set(detail_queue) - refreshed_this_run)

    observations: list[Observation] = []
    for handle in sorted(kept_handles):
        ean = new_updated_at.get(handle, {}).get("ean")
        observations.append(
            _build_observation(
                descriptor,
                products[handle],
                manufacturer_by_handle[handle],
                ean,
                context.run_date,
                collections=collections_by_handle.get(handle),
            )
        )

    # skipDetails leaves pending_details empty by construction, so full_sweep degenerates to
    # "enumeration wasn't capped" -- exactly the population-completeness claim mark_missed needs.
    full_sweep = not pending_details and not enumeration_capped

    return StrategyResult(
        observations=observations,
        full_sweep=full_sweep,
        stats=stats,
        cursor={
            "updated_at": new_updated_at,
            "pending_details": pending_details,
        },
    )


STRATEGIES["shopify-paints"] = shopify_paints_strategy
