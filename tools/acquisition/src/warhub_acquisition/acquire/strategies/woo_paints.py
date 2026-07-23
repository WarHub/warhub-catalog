"""WooCommerce Store API paints strategy (AK Interactive): category-scoped enumeration.

Differs from the generic `woo-store-api` strategy in three paint-catalog-specific ways
(everything else -- pinned manufacturer, minor-unit prices, HTML-unescaped names, empty-page
termination -- mirrors woo.py):

1. **Category-scoped enumeration.** The store carries thousands of non-paint products
   (books, dioramas, tools); `scope.categories` lists the store category slugs to enumerate
   (the Store API accepts `category=<slug>`, live-verified 2026-07-23 on ak-interactive.com).
   Each is swept fully; overlapping membership dedupes by product id.
2. **`scope.extraParams`** merged into every enumeration request (AK needs `lang: en` --
   WPML returns the default locale otherwise).
3. **hints.categorySlugs** (each product's own category slug list, sorted) rides along for
   the harvest bridge to classify ranges/sets/singles; hints.category = "paint". No
   gameSystem/faction mapping -- these are paint catalogs.

No detail fetches: AK product pages carry no gtin in their JSON-LD (live-checked), so there
is nothing worth a per-product request. Paint ranges are near-static (one-off snapshot model
-- see docs/research/2026-07-23-paint-manufacturer-harvest-design.md): the cursor stays empty.
"""
import html as html_lib

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.acquire.strategies.woo import (
    PAGE_SIZE,
    PRODUCTS_PATH,
    _availability,
    _image_url,
    _price_major_units,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "woo-paints@1"

_PRICE_FIELDS = {"gbp": "priceGbp", "usd": "priceUsd", "eur": "priceEur", "cad": "priceCad"}


def _price_field_for(product: dict, scope: dict) -> str:
    """Prefer the currency the Store API itself declares per product (AK: EUR), falling back
    to scope.currency, then GBP -- the payload is authoritative when present."""
    currency = (product.get("prices") or {}).get("currency_code") or scope.get("currency") or "gbp"
    return _PRICE_FIELDS.get(str(currency).casefold(), "priceGbp")


def woo_paints_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    category_slugs = [str(slug) for slug in (descriptor.scope.get("categories") or [None]) if slug is not None]
    extra_params = {
        str(k): str(v) for k, v in (descriptor.scope.get("extraParams") or {}).items()
    }

    stats = {
        "fetched_pages": 0,
        "categories_swept": 0,
        "products_seen": 0,
        "skipped_unknown_vendor": 0,
    }

    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = (
        context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None
    )

    # --- Enumerate each scoped category fully; dedupe by product id (categories overlap). ---
    products: dict[str, dict] = {}
    for slug in category_slugs or [None]:
        stats["categories_swept"] += 1
        page = 1
        while True:
            params: dict[str, object] = {"per_page": PAGE_SIZE, "page": page, **extra_params}
            if slug is not None:
                params["category"] = slug
            payload, _headers = client.get_json_response(PRODUCTS_PATH, params=params)
            stats["fetched_pages"] += 1
            page_products = payload if isinstance(payload, list) else []
            for product in page_products:
                products[str(product["id"])] = product
            if len(page_products) < PAGE_SIZE:
                break
            page += 1

    stats["products_seen"] = len(products)

    observations: list[Observation] = []
    if manufacturer is None:
        stats["skipped_unknown_vendor"] = len(products)
    else:
        for pid in sorted(products, key=int):
            product = products[pid]
            price_kwargs: dict[str, object] = {}
            price = _price_major_units(product.get("prices") or {})
            if price is not None:
                price_kwargs[_price_field_for(product, descriptor.scope)] = price

            hints: dict[str, object] = {"category": "paint"}
            slugs = sorted(
                category.get("slug", "")
                for category in (product.get("categories") or [])
                if isinstance(category, dict) and category.get("slug")
            )
            if slugs:
                hints["categorySlugs"] = slugs

            observations.append(
                Observation(
                    key=f"{descriptor.id}:{pid}",
                    url=product.get("permalink"),
                    manufacturer=manufacturer,
                    name=html_lib.unescape(product["name"]),
                    sku=product.get("sku") or None,
                    imageUrl=_image_url(product),
                    availability=_availability(product),
                    hints=hints,
                    firstSeen=context.run_date,
                    lastSeen=context.run_date,
                    extractor=EXTRACTOR,
                    **price_kwargs,
                )
            )

    return StrategyResult(
        observations=observations,
        # Every scoped category is swept fully each run -- within the declared scope this IS
        # the population, so absence is a real discontinuation signal.
        full_sweep=True,
        stats=stats,
        cursor={},
    )


STRATEGIES["woo-paints"] = woo_paints_strategy
