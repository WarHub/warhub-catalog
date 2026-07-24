"""WordPress REST paints strategy (Vallejo): product CPT enumeration + media batch resolve.

acrylicosvallejo.com is a plain WordPress catalog site (no WooCommerce Store API) whose
`product` custom post type is exposed read-only at `/wp-json/wp/v2/product` (1,991 items,
live-probed 2026-07-23). One enumeration pass (~20 pages at per_page=100 with a `_fields`
projection) + one `product_cat` taxonomy pass (61 terms, 1 page) + batched `media?include=`
lookups for featured images (<=100 ids/request) is the ENTIRE request footprint -- there are no
per-product detail fetches at all, by design (see the robots/crawl-delay rationale in the
descriptor and docs/research/2026-07-23-paint-manufacturer-harvest-design.md).

What lands in the observation:
- name: title.rendered, HTML-unescaped (paint name only, e.g. "Dead White").
- sku: the raw catalog code digits parsed off the slug tail ("dead-white-72001" -> "72001");
  the harvest bridge formats Vallejo's display code ("72.001"). Slug-less/code-less products
  (rare CMS artifacts) are still observed, just with sku=None, counted in stats.
- hints.categorySlugs: the product's product_cat term slugs (sorted) -- the bridge maps these
  to range/set names; hints.category = "paint".
- imageUrl: resolved from featured_media via the media cache in the cursor (never re-fetched
  once known).

scope keys: manufacturer (pinned vendor name, resolved via taxonomy -- same mechanism as
woo.py), apiBase (default "/wp-json/wp/v2"), includeCategorySlugs (allow-list of product_cat
slugs; a product is kept when ANY of its categories matches; omitted = keep everything).

Cursor schema:

    {"media": {"<media id>": "<source_url>"}}

`context.budget` caps the number of media BATCH requests per run (each covers up to 100 ids);
unresolved images simply stay unresolved until a later run (media ids are stable, the cache
only grows). full_sweep is True whenever product enumeration completed (an unresolved image
never blocks liveness -- the product itself WAS observed).
"""
import html as html_lib
import re

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "wp-rest-paints@1"
PER_PAGE = 100
MEDIA_BATCH = 100
_PRODUCT_FIELDS = "id,slug,title,link,product_cat,featured_media,modified_gmt"
_CAT_FIELDS = "id,slug,name,parent"
_MEDIA_FIELDS = "id,source_url"

# Trailing catalog code on a product slug: "dead-white-72001" -> 72001, tolerating a short
# numeric de-dup suffix WordPress appends to colliding slugs ("...-72001-2").
_SLUG_CODE_RE = re.compile(r"-(\d{4,6})(?:-\d{1,2})?$")


def _slug_code(slug: str) -> str | None:
    match = _SLUG_CODE_RE.search(slug or "")
    return match.group(1) if match else None


def _enumerate(client: PoliteClient, path: str, fields: str, stats: dict, stat_key: str) -> list[dict]:
    """Full pagination sweep terminating ONLY on an empty/short page (mirrors woo.py's
    header-distrust: X-WP-Total is informational)."""
    items: list[dict] = []
    page = 1
    while True:
        payload = client.get_json(
            path, params={"per_page": PER_PAGE, "page": page, "_fields": fields}
        )
        stats[stat_key] += 1
        page_items = payload if isinstance(payload, list) else []
        items.extend(item for item in page_items if isinstance(item, dict))
        if len(page_items) < PER_PAGE:
            break
        page += 1
    return items


def wp_rest_paints_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    api_base = str(descriptor.scope.get("apiBase") or "/wp-json/wp/v2").rstrip("/")
    include_slugs = descriptor.scope.get("includeCategorySlugs")
    include_set = set(include_slugs) if include_slugs is not None else None

    stats = {
        "fetched_pages": 0,
        "category_pages": 0,
        "media_batches": 0,
        "products_seen": 0,
        "kept_paint_products": 0,
        "skipped_category": 0,
        "skipped_unknown_vendor": 0,
        "code_missing": 0,
        "media_resolved": 0,
        "media_unresolved": 0,
    }

    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = (
        context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None
    )

    # --- Category taxonomy: term id -> slug (needed to evaluate the allow-list and to hand the
    # bridge readable range slugs; products only carry numeric term ids). ---
    categories = _enumerate(client, f"{api_base}/product_cat", _CAT_FIELDS, stats, "category_pages")
    slug_by_term: dict[int, str] = {
        cat["id"]: cat["slug"] for cat in categories if "id" in cat and cat.get("slug")
    }

    # --- Product enumeration (the full population, every run). ---
    products = _enumerate(client, f"{api_base}/product", _PRODUCT_FIELDS, stats, "fetched_pages")
    stats["products_seen"] = len(products)

    kept: list[dict] = []
    if manufacturer is None:
        stats["skipped_unknown_vendor"] = len(products)
    else:
        for product in products:
            term_slugs = sorted(
                slug_by_term[term]
                for term in (product.get("product_cat") or [])
                if term in slug_by_term
            )
            if include_set is not None and not include_set.intersection(term_slugs):
                stats["skipped_category"] += 1
                continue
            product["_term_slugs"] = term_slugs
            kept.append(product)
    stats["kept_paint_products"] = len(kept)

    # --- Featured images: batch-resolve unknown media ids through the cursor cache. Budget
    # caps BATCHES (not ids); already-cached urls never re-fetch. ---
    media_cache: dict[str, str] = {
        str(k): str(v) for k, v in (cursor.get("media") or {}).items()
    }
    wanted_ids = sorted(
        {
            int(product["featured_media"])
            for product in kept
            if isinstance(product.get("featured_media"), int)
            and product["featured_media"] > 0
            and str(product["featured_media"]) not in media_cache
        }
    )
    batches = [wanted_ids[i : i + MEDIA_BATCH] for i in range(0, len(wanted_ids), MEDIA_BATCH)]
    if context.budget is not None:
        batches = batches[: max(context.budget, 0)]
    for batch in batches:
        payload = client.get_json(
            f"{api_base}/media",
            params={
                "include": ",".join(str(i) for i in batch),
                "per_page": MEDIA_BATCH,
                "_fields": _MEDIA_FIELDS,
            },
        )
        stats["media_batches"] += 1
        for item in payload if isinstance(payload, list) else []:
            if isinstance(item, dict) and item.get("id") is not None and item.get("source_url"):
                media_cache[str(item["id"])] = str(item["source_url"])

    observations: list[Observation] = []
    for product in sorted(kept, key=lambda p: p.get("slug") or str(p.get("id"))):
        slug = product.get("slug") or str(product["id"])
        title = product.get("title") or {}
        raw_name = title.get("rendered") if isinstance(title, dict) else None
        code = _slug_code(slug)
        if code is None:
            stats["code_missing"] += 1
        image_url = media_cache.get(str(product.get("featured_media")))
        if image_url is not None:
            stats["media_resolved"] += 1
        else:
            stats["media_unresolved"] += 1

        hints: dict[str, object] = {"category": "paint"}
        term_slugs = product.get("_term_slugs") or []
        if term_slugs:
            hints["categorySlugs"] = term_slugs
        modified = product.get("modified_gmt")
        if modified:
            hints["modified"] = modified

        observations.append(
            Observation(
                key=f"{descriptor.id}:{slug}",
                url=product.get("link"),
                manufacturer=manufacturer,
                name=html_lib.unescape(raw_name) if raw_name else slug,
                sku=code,
                imageUrl=image_url,
                hints=hints,
                firstSeen=context.run_date,
                lastSeen=context.run_date,
                extractor=EXTRACTOR,
            )
        )

    return StrategyResult(
        observations=observations,
        # Product enumeration always covers the full population (no budget applies to it), so
        # absence IS a discontinuation signal; pending images never block the sweep claim.
        full_sweep=True,
        stats=stats,
        cursor={"media": media_cache},
    )


STRATEGIES["wp-rest-paints"] = wp_rest_paints_strategy
