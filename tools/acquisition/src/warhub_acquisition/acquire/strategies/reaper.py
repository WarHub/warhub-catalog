"""Reaper strategy: Master Series Paints via the /paints/* line pages' embedded Vue data.

POLICY STATUS (2026-08-05): CLEARED to run under the ordinary robots preflight, no opt-out.
This paragraph previously said the opposite, and the history matters: reapermini.com ships
Cloudflare's managed AI-crawl-control robots block (`User-agent: ClaudeBot / Disallow: /`),
acquire/robots.py used to honor ClaudeBot groups as disallowing this pipeline too, and
run_source therefore raised RobotsDisallowedError at the preflight -- which is why the
descriptor carried `ignoreRobots: true` for a while. As of 2026-08-05 robots.py does not check
that token at all (maintainer decision; its module docstring carries the reasoning, the measured
evidence and the counter-argument), so the block is no longer read as addressed to us and the
descriptor's opt-out has been removed rather than left standing. Robots enforcement is now fully
ON for this source: the `*` group that does address us says `Allow: /` with no Crawl-delay, and
every /paints/* fetch below is checked per-request against it like any other source. Everything
after this paragraph describes what the strategy does; none of it changed.

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
    figures -- only the paint contents are paint evidence).

    THE SITE STATES NO QUANTITY, so neither does this. Measured live 2026-08-07 across all three
    set-kind pages: 848 associatedProducts entries on 31 set items, and the union of their keys is
    exactly {sku, name, category, filename, material} -- no count/qty/quantity field -- with 0 sets
    repeating a sku (the doubling-likely candidates 08906/08907 and the Quick-Paint Kits included).
    The set comprehension below therefore discards nothing on 100% of real data, and swapping it
    for a repeat-preserving list would be a change that can never fire. Do NOT "recover" quantity
    with a strategy change plus a re-acquire; there is nothing upstream to recover. See
    models/catalog.py::CanonicalProduct.contentSkus, which asserted the opposite reason until
    this was measured.

    `material == "paint"` is a WHITELIST, and 2 real paints fall outside it -- see the caller's
    `content_sku_material_unstated` stat for why that is reported rather than papered over.
    """
    skus = {
        str(item["sku"])
        for item in (product.get("associatedProducts") or [])
        if isinstance(item, dict) and item.get("sku") and str(item.get("material") or "").lower() == "paint"
    }
    return sorted(skus)


def _material_unstated_paints(product: dict) -> list[str]:
    """Members `_content_skus` DROPS that the site's own `category` calls a paint range.

    A silent 25% under-report, found live 2026-08-07 and invisible in committed data: set 09916
    ("Learn to Paint: Zombies Quick-Paint Kit") lists 8 paint members on reapermini.com but only 6
    reach `contentSkus`. Skus 29137 "Vampire Pallor" and 29143 "Golden Griffon Brown" sit in
    category ["Master Series Paints Core Colors"] yet carry `material: null` and `filename: false`
    -- malformed records on Reaper's side -- so the whitelist above rejects them without a word.
    These 2 are the only such entries in all 848; the other 22 rejects are genuinely brushes
    (material "accessory") and Bones figures (material "plastic").

    ADMISSION IS NOT WIDENED, deliberately. A blank `material` is UNSTATED, and admitting on the
    strength of `category` alone would be this repo inferring a taxonomy the source declined to
    state -- the guess HarvestApplier.ApplyEnrichment exists to refuse. Both entries are blank in
    TWO fields at once (`material: null` AND `filename: false`), which is what a malformed record
    looks like rather than a paint the site merely under-described.

    THE ROOT CAUSE THIS DOCSTRING USED TO NAME WAS WRONG, and it sent the next person to a dead
    end, so the correction is recorded rather than quietly swapped: it said 29107/29137/29143/29815
    were missing because "the 29xxx High Density range has no `linePages` entry" and that "the fix
    is to extend the descriptor". Re-mapped live 2026-08-08 -- reapermini.com's /paints index links
    exactly 7 pages, the 6 already configured plus /paints/msp2, which is a data-less marketing
    page. There is no High Density page, no page for any of the four, and the 6 configured pages'
    blobs still hold exactly the 541 unique skus the descriptor already claims. No descriptor entry
    could have closed this gap because there is nothing to point it at.

    What is true is narrower and fixable: the site names these paints ONLY inside
    `associatedProducts`, which is where `set_only_paints` below now picks them up. This counter
    stays because 29137 and 29143 are NOT recovered by that route either -- they fail the same
    material whitelist -- so the gap they represent must keep showing up in run stats.
    """
    return sorted(
        str(item["sku"])
        for item in (product.get("associatedProducts") or [])
        if isinstance(item, dict) and item.get("sku")
        and not str(item.get("material") or "").strip()
        and any("paint" in str(c).lower() for c in (item.get("category") or []))
    )


def _set_only_paints(product: dict, page_path: str) -> list[dict]:
    """Paint members this set NAMES that no line page sells on its own.

    Returned raw (sku/name/line/parent/page) for the caller to emit once every line page has been
    read -- "no line page lists it" is only knowable after the whole sweep, so this cannot decide
    anything by itself.

    WHY THIS IS EVIDENCE AND NOT A GUESS. `associatedProducts` states, in the source's own fields,
    a sku, a name, a `category` naming the paint's line, and `material: "paint"`. That is strictly
    more than several line-page items carry. The only thing it lacks is a page of its own, which is
    a fact about Reaper's shop, not about the paint. Measured live 2026-08-08 across the six line
    pages: 48 members are named but unlisted -- 4 brushes and 7 Bones figures (rejected by the same
    `material` whitelist `_content_skus` uses, unchanged), 2 malformed (see
    `_material_unstated_paints`), and 35 paints. 33 of those 35 are "12 Bottle Lot Special Order"
    bulk packs whose sku still names a paint the catalog already holds once Reaper's zero-padding
    is stripped (09121 -> 9121 "Khaki Shadow"), so the bridge's ordinary `match_code` route absorbs
    them and mints nothing. The remaining 2 are the whole gap: 29107 "Gutter Grime" and 29815
    "HD Dragon Blue", which resolve to nothing under any normalization and are exactly the two refs
    sitting in data/catalog/set-contents/reaper.yaml's `unresolved:` block.

    NO IMAGE IS CARRIED, deliberately, even though `filename` is right there and 33 of the 33
    enrich-route paints currently have none. A reference's filename depicts the referenced SKU AS
    SOLD, and for a special-order lot that is a case of bottles, not a pot -- Reaper marks those
    with a distinct `_D` render (09121_D.jpg). Filling a single pot's blank image with a photo of
    twelve would be a worse record than a blank one, and telling the two apart means reading a
    filename suffix, which is a guess. A set-member reference is weaker evidence than a listing and
    is treated that way: it carries identity (sku, name, line) and nothing else. Price is not a
    judgement call at all -- `associatedProducts` has no price field.
    """
    out = []
    for item in (product.get("associatedProducts") or []):
        if not isinstance(item, dict) or not item.get("sku"):
            continue
        if str(item.get("material") or "").lower() != "paint":
            continue
        line = next((str(c) for c in (item.get("category") or []) if str(c).strip()), "")
        out.append({
            "sku": str(item["sku"]),
            "name": str(item.get("name") or item["sku"]),
            "line": line,
            "parent": str(product.get("sku") or ""),
            "page": page_path,
        })
    return out


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
        # Set members the site's `category` calls a paint but whose `material` it leaves blank,
        # so `_content_skus` drops them. 2 today (09916 -> 29137, 29143) and they are NOT a
        # rounding error -- they are a quarter of that box. See `_material_unstated_paints`.
        "content_sku_material_unstated": 0,
        # Paints named ONLY inside a set's associatedProducts, with no line page of their own.
        # 35 today; see `_set_only_paints` for why they are evidence rather than inference.
        "kept_set_only_paints": 0,
    }

    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = (
        context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None
    )

    observations_by_sku: dict[str, Observation] = {}
    # Collected across the whole sweep and emitted after it: whether a member has a page of its
    # own cannot be known until every page has been read.
    set_only_seen: dict[str, dict] = {}
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
            # Gathered for EVERY product, before the duplicate-sku `continue` below: a set listed
            # on two pages must still contribute its members, and the first-wins rule is about
            # which page owns a product, not about whether its contents were read.
            for member in _set_only_paints(product, path):
                set_only_seen.setdefault(member["sku"], member)

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
            stats["content_sku_material_unstated"] += len(_material_unstated_paints(product))

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

    # A named member with no page of its own becomes an observation in its own right. Runs after
    # the sweep so `observations_by_sku` is complete, and never overwrites a real listing -- a
    # listing is the stronger evidence and always wins.
    if manufacturer is not None:
        for sku in sorted(set_only_seen):
            if sku in observations_by_sku:
                continue
            member = set_only_seen[sku]
            stats["kept_set_only_paints"] += 1
            observations_by_sku[sku] = Observation(
                key=f"{descriptor.id}:{sku}",
                # The page the evidence was actually read from -- the set's own line page. There
                # is no page for this sku to point at, and inventing one would be the only false
                # field on the record.
                url=f"{descriptor.baseUrl}{member['page']}",
                manufacturer=manufacturer,
                name=member["name"],
                sku=sku,
                imageUrl=None,
                availability=None,
                hints={
                    "category": "paint",
                    "line": member["line"],
                    # Provenance, so a consumer can tell a referenced paint from a listed one
                    # without re-deriving it: this record came from a set's contents array, and
                    # `namedInSet` says which box was the witness.
                    "namedOnlyInSets": True,
                    "namedInSet": member["parent"],
                },
                firstSeen=context.run_date,
                lastSeen=context.run_date,
                extractor=EXTRACTOR,
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
