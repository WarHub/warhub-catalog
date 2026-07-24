"""Reaper strategy: Master Series Paints via the /paints/* line pages' embedded Vue data.

POLICY STATUS (2026-07-24): implemented and unit-proven against real page captures, but the
source is currently BLOCKED from live runs by this repo's own robots stance: reapermini.com
ships Cloudflare's managed AI-crawl-control robots block (`User-agent: ClaudeBot /
Disallow: /`), and acquire/robots.py deliberately honors ClaudeBot groups as disallowing this
pipeline too (module docstring, checked-token 3) -- run_source therefore raises
RobotsDisallowedError at the preflight, before any strategy work. Do not paper over that with
ignoreRobots; see the descriptor (data/catalog/sources/mfr-reaper.yaml) for the full
rationale and revisit conditions. Everything below documents what the strategy DOES when the
policy situation allows it to run.

reapermini.com's REAL paint listing is not the shop search (/search/* sits behind a Cloudflare
managed JS challenge -- deliberately never fetched) and not an API (site JS calls no /api route;
/api is robots-disallowed anyway). It is the six /paints/<line> pages themselves: each one
bootstraps its inline Vue app with a single-line ``paints: [{...}]`` JSON array carrying the
line's COMPLETE product population -- sku ("09001"), name, price (USD cents), prices
(EUR/GBP/AUD/CAD cents), inventory (units), images (filenames on the images CDN), meta.color
(color-family filter tags), and -- on the set pages -- associatedProducts (the set's contents:
sku/name/category/material). Any other /paints/<slug> is a catch-all serving the data-less
marketing page (live-mapped 2026-07-24). One GET per configured page is the ENTIRE request
footprint: there are no per-product detail pages to queue, so no budget applies and every run
is a full sweep by construction.

Per-paint hex/RGB is NOT in the site data, despite Reaper demonstrably having it server-side:
the Power Palette tool (pp.reapermini.com) matches uploaded-image points to paints entirely
server-side (no public catalog/color endpoint -- probed 2026-07-24), and the per-sku swatch
tiles it renders (images.reapermini.com/6/<sku>.jpg, /7/) are flat-color JPEGs, i.e. raster
renders of the internal color DB, not parseable data. Observations therefore carry no
hints.hex; hex enrichment stays with overrides/paintpad (see the design doc).

scope keys:
- manufacturer: pinned vendor name, resolved via taxonomy (same mechanism as wp_rest_paints).
- linePages: ORDERED list of {path, line, kind} -- kind "single" (individual paints) or "set"
  (triads / paint sets / learn-to-paint kits). Skus recur across pages (triads are also listed
  on the core-colors page, Bones Ultra-Coverage sets on the bones page, ...) and the FIRST
  page claiming a sku wins, so the descriptor lists set-kind pages before singles pages --
  that way a 3-pack never masquerades as a single paint.

What lands in the observation:
- name/sku verbatim; priceUsd from ``price`` cents; availability from ``inventory``.
- url: the line page the sku was kept from (the only unchallenged page it appears on).
- imageUrl: the "main" image filename resolved against the images CDN bucket the pages
  themselves render from (https://images.reapermini.com/4/<filename>).
- hints.category: "paint" for kind=single pages, "paint-set" for kind=set pages;
  hints.line: the page's line label; hints.colorTags: sorted meta.color words;
  hints.contentSkus: the set's paint-material component skus (set pages only) -- the
  committed set-membership evidence the bridge can join against the singles.

Cursor: stateless -- ``{}`` (nothing to carry between runs; the runner adds its own
last_run_date/last_good_count bookkeeping).
"""
import json
import re

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "reaper@1"

# The bucket the line pages' own <img> tags resolve product filenames against ("4" is the
# storefront render size; buckets 6/7 are the Power Palette swatch tiles).
IMAGE_BASE = "https://images.reapermini.com/4"

# The Vue bootstrap emits the whole array minified on ONE line ("\t\t\tpaints: [{...}],");
# greedy-to-line-end is safe because a minified JSON literal cannot contain a raw newline.
_PAINTS_BLOB_RE = re.compile(r"^\s*paints:\s*(\[.*\])\s*,?\s*$", re.MULTILINE)


def _extract_paints(page_html: str, page_path: str) -> list[dict]:
    """Parse the embedded ``paints: [...]`` array, loudly: a missing/unparseable blob means the
    page layout drifted (or a catch-all marketing page answered a bad path) and the run must
    fail rather than quietly observe nothing."""
    match = _PAINTS_BLOB_RE.search(page_html)
    if match is None:
        raise ValueError(f"no embedded paints data found on {page_path} (marketing page or layout drift?)")
    try:
        items = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ValueError(f"embedded paints data on {page_path} is not valid JSON: {error}") from None
    return [item for item in items if isinstance(item, dict)]


def _image_url(product: dict) -> str | None:
    images = [img for img in (product.get("images") or []) if isinstance(img, dict) and img.get("filename")]
    if not images:
        return None
    # Prefer the "main" shot, then lowest order -- mirrors what the page itself displays.
    images.sort(key=lambda img: (img.get("type") != "main", img.get("order") or 0))
    return f"{IMAGE_BASE}/{images[0]['filename']}"


def _availability(product: dict) -> str | None:
    inventory = product.get("inventory")
    if not isinstance(inventory, int):
        return None
    return "in_stock" if inventory > 0 else "out_of_stock"


def _content_skus(product: dict) -> list[str]:
    """Paint-material component skus of a set (associatedProducts also lists brushes and Bones
    figures -- only the paint contents are paint evidence)."""
    skus = {
        str(item["sku"])
        for item in (product.get("associatedProducts") or [])
        if isinstance(item, dict) and item.get("sku") and str(item.get("material") or "").lower() == "paint"
    }
    return sorted(skus)


def reaper_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    stats = {
        "fetched_pages": 0,
        "products_seen": 0,
        "kept_paint_products": 0,
        "kept_set_products": 0,
        "duplicate_skus": 0,
        "sku_missing": 0,
        "skipped_unknown_vendor": 0,
        "image_missing": 0,
    }

    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = (
        context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None
    )

    observations_by_sku: dict[str, Observation] = {}
    for page in descriptor.scope.get("linePages") or []:
        path = str(page.get("path") or "")
        line = str(page.get("line") or "")
        kind = str(page.get("kind") or "single")
        page_html = client.get_text(path)
        stats["fetched_pages"] += 1
        products = _extract_paints(page_html, path)
        stats["products_seen"] += len(products)

        if manufacturer is None:
            stats["skipped_unknown_vendor"] += len(products)
            continue

        for product in products:
            sku = str(product.get("sku") or "")
            if not sku:
                stats["sku_missing"] += 1
                continue
            if sku in observations_by_sku:
                # Same product listed on a later page (triads recur on core-colors, set skus
                # on their line's singles page, ...): the first, more specific page won.
                stats["duplicate_skus"] += 1
                continue

            stats["kept_set_products" if kind == "set" else "kept_paint_products"] += 1

            image_url = _image_url(product)
            if image_url is None:
                stats["image_missing"] += 1

            hints: dict[str, object] = {
                "category": "paint-set" if kind == "set" else "paint",
                "line": line,
            }
            color_tags = (product.get("meta") or {}).get("color") or []
            if color_tags:
                hints["colorTags"] = sorted(str(tag) for tag in color_tags)
            content_skus = _content_skus(product)
            if content_skus:
                hints["contentSkus"] = content_skus

            price_kwargs: dict[str, object] = {}
            price_cents = product.get("price")
            if isinstance(price_cents, int) and price_cents > 0:
                price_kwargs["priceUsd"] = price_cents / 100

            observations_by_sku[sku] = Observation(
                key=f"{descriptor.id}:{sku}",
                url=f"{descriptor.baseUrl}{path}",
                manufacturer=manufacturer,
                name=str(product.get("name") or sku),
                sku=sku,
                imageUrl=image_url,
                availability=_availability(product),
                hints=hints,
                firstSeen=context.run_date,
                lastSeen=context.run_date,
                extractor=EXTRACTOR,
                **price_kwargs,
            )

    return StrategyResult(
        observations=[observations_by_sku[sku] for sku in sorted(observations_by_sku)],
        # Every configured page's blob carries its line's whole population and all pages are
        # fetched every run (no budget, no detail queue), so absence IS a discontinuation
        # signal -- the sweep claim never has anything pending.
        full_sweep=True,
        stats=stats,
        cursor={},
    )


STRATEGIES["reaper"] = reaper_strategy
