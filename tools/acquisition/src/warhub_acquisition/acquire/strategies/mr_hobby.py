"""Mr Hobby (GSI Creos) strategy: category listing crawl + budgeted per-detail fetch queue.

www.mr-hobby.com is a rebuilt, plain server-rendered Laravel site (live-probed 2026-07-24: no
JS needed, no JSON/ld+json/gtin anywhere, session cookies set but never required, CloudFront in
front with no bot wall -- the canonical bot UA gets byte-identical HTML to a browser UA).
Structure, all live-verified 2026-07-24:

- `/en/products/category/<N>` paginated listings, 20 items/page. Each item is a
  `<li class="products__item">` block carrying the `/en/products/detail/<id>` href, an `<img>`
  (placeholder `/images/products/no-image.png` when none), an optional
  `<p class="products__item-tag ...">` lifecycle tag ("NEW PRODUCTS" / "Out of Production"),
  a `<p class="products__item-code">` product-number string and a
  `<p class="products__item-text">` name (occasionally empty). Pagination is numbered anchors
  (`?page=N`); the last page links only LOWER pages, and an out-of-range page returns 200 with
  zero items -- enumeration therefore stops when the current page carries no `?page=<next>`
  anchor (plus the zero-items guard, plus a hard page cap in case the paginator markup drifts).
- `/en/products/detail/<id>` pages are SERIES-level or single-product pages -- e.g. detail/1 is
  ALL of "Mr.COLOR C1~C189" on one page, detail/352 is the single spray "B601". Individual
  colours are NOT separately addressable anywhere on the site (search included), and the
  colour lineup on JA pages is a raster PNG chart, not HTML -- so there are no per-colour
  observations and no colour-chip hex to harvest. The naive `<h1>` parse fails because `<h1>`
  is the site logo; the product name lives in `<h3 class="common__square-title">` inside
  `<div class="detail-prodinfo__text-area">`, next to "Product Number : <codes>" and a
  free-text volume line ("Net Amount: 10ml" on detail/1, "NET:18ml" on detail/2828 -- CMS
  free-text, hence the label-anchored regex). The main image is the
  `products__img js-thumb` div's `data-src`. No JAN/EAN appears on any probed page (EN or JA,
  singles or series); the JAN scan below is a hook that only fires if the site ever adds them.

What lands in the observation (one per detail id, deduped across categories -- several ids are
cross-listed, e.g. collaboration paints appear under their base range too):

- name: detail-page h3 verbatim (HTML-unescaped) when fetched, else the listing text, else the
  listing code string (a handful of listing texts are empty; name never is).
- sku: the verbatim "Product Number" string -- a clean item code for singles ("B601", "SMS1")
  or a range string for series pages ("C1~C189"). Range parsing is deliberately the harvest
  bridge's job: evidence stays faithful to the site, and re-tuning parsing must never require
  a re-fetch.
- ean: JAN digits if a detail page ever carries one (none do today -- see above).
- imageUrl: detail-page image, else listing image; the no-image placeholder maps to None.
- hints: category="paint", line=<first configured category label listing the id> (+ lines=all
  labels, sorted, when cross-listed), volumeMl when the free-text volume parses, tag=verbatim
  listing lifecycle tag when present.

scope keys: manufacturer (pinned vendor name resolved via taxonomy, like wp_rest_paints),
categories (list of {id|path, label}; id N maps to /en/products/category/N).

Cursor schema (same discipline as shopify_paints -- carry known data forward, budgeted queue,
give-up cap; there is no updated_at equivalent here, so a fetched detail is never re-fetched:
one-off snapshot model, a fresh-eyes re-harvest means deleting the cursor):

    {
      "details": {"<detail id>": {"name": ..., "sku": ..., "volumeMl": ..., "imageUrl": ...,
                                   "ean": ...}                   # parsed OK (keys only if found)
                  | {"detailMisses": <n>}},                      # unparseable, or EN page 404s
      "pending_details": ["<detail id>", ...]
    }

`context.budget` caps detail-page fetches per run. full_sweep is True only when the detail
queue is drained and enumeration wasn't capped (mirrors shopify_paints), so mark_missed never
fires off a partial run.
"""
import html as html_lib
import re

from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "mr-hobby@1"

# Same rationale as shopify.py's DETAIL_MISS_CAP: after this many successful fetches that
# yielded no parseable data, stop re-queuing the page (markup drift on one page must not pin
# the source below full_sweep forever). Fetch ERRORS deliberately don't count -- they stay
# queued and retry next run.
DETAIL_MISS_CAP = 3

# Defensive ceiling per category, only reachable if the numbered-paginator markup drifts into
# always advertising a next page. The largest live category (Mr. COLOR) is 3 pages.
MAX_LISTING_PAGES = 30

_ITEM_RE = re.compile(r'<li class="products__item">(.*?)</li>', re.S)
_DETAIL_HREF_RE = re.compile(r'href="([^"]*/products/detail/(\d+))"')
_ITEM_CODE_RE = re.compile(r'class="products__item-code">\s*(.*?)\s*</p>', re.S)
_ITEM_TEXT_RE = re.compile(r'class="products__item-text">\s*(.*?)\s*</p>', re.S)
_ITEM_TAG_RE = re.compile(r'class="products__item-tag[^"]*">\s*(.*?)\s*</p>', re.S)
_IMG_SRC_RE = re.compile(r'<img\s[^>]*?src="([^"]+)"', re.S)

# The prodinfo text-area div contains nested elements (detail/2947 nests a bare <div>NEW</div>
# before the Product Number line), so "up to the first </div>" would truncate -- bound the
# block by the next structural landmark instead (the "Product Detail" common__container that
# follows the prodinfo wrap on every probed page).
_PRODINFO_RE = re.compile(r'class="detail-prodinfo__text-area"(.*?)class="common__container', re.S)
_DETAIL_NAME_RE = re.compile(r'<h3 class="common__square-title">\s*(.*?)\s*</h3>', re.S)
_PRODUCT_NUMBER_RE = re.compile(r"Product Number\s*:\s*([^<]+)")
# Volume is CMS free text: "Net Amount: 10ml" (detail/1) vs "NET:18ml" (detail/2828). Anchor on
# the NET label so an "18ml" inside a product NAME ("MR.COLOR GGX　18ml Ver.") never counts.
_VOLUME_RE = re.compile(r"\bNET(?:\s+Amount)?\s*[:：]\s*(\d+(?:\.\d+)?)\s*ml\b", re.I)
# Hook only -- no probed page carries a JAN (2026-07-24). Japanese GS1 prefixes are 45/49.
_JAN_RE = re.compile(r"\b((?:45|49)\d{11})\b")
_DETAIL_IMG_RE = re.compile(r'class="products__img js-thumb"[^>]*?data-src="([^"]+)"', re.S)


def _clean(text: str | None) -> str | None:
    """HTML-unescape and trim; collapse to None when nothing is left (empty listing texts)."""
    if text is None:
        return None
    cleaned = html_lib.unescape(re.sub(r"<[^>]+>", " ", text)).strip()
    return cleaned or None


def _image(url: str | None, base_url: str) -> str | None:
    """Absolute image URL, or None for the site's no-image placeholder."""
    if not url or "no-image" in url:
        return None
    return url if url.startswith("http") else f"{base_url}{url}"


def _parse_listing(page_html: str, base_url: str) -> list[dict]:
    """All product tiles on a listing page (detail id, verbatim code/text/tag, image)."""
    items: list[dict] = []
    for block in _ITEM_RE.findall(page_html):
        href = _DETAIL_HREF_RE.search(block)
        if href is None:
            continue
        code = _ITEM_CODE_RE.search(block)
        text = _ITEM_TEXT_RE.search(block)
        tag = _ITEM_TAG_RE.search(block)
        image = _IMG_SRC_RE.search(block)
        items.append(
            {
                "id": href.group(2),
                "url": href.group(1),
                "code": _clean(code.group(1)) if code else None,
                "text": _clean(text.group(1)) if text else None,
                "tag": _clean(tag.group(1)) if tag else None,
                "imageUrl": _image(image.group(1) if image else None, base_url),
            }
        )
    return items


def _parse_detail(page_html: str, base_url: str) -> dict:
    """Parse a detail page's prodinfo area into cursor-cacheable fields.

    Empty dict = parse miss (no prodinfo block, or one carrying neither a name nor a product
    number) -- counted against DETAIL_MISS_CAP by the caller.
    """
    block_match = _PRODINFO_RE.search(page_html)
    if block_match is None:
        return {}
    block = block_match.group(1)

    fields: dict[str, object] = {}
    name_match = _DETAIL_NAME_RE.search(block)
    name = _clean(name_match.group(1)) if name_match else None
    if name is not None:
        fields["name"] = name
    number_match = _PRODUCT_NUMBER_RE.search(block)
    number = _clean(number_match.group(1)) if number_match else None
    if number is not None:
        fields["sku"] = number
    if not fields:
        return {}

    volume = _VOLUME_RE.search(block)
    if volume is not None:
        parsed = float(volume.group(1))
        fields["volumeMl"] = int(parsed) if parsed.is_integer() else parsed
    jan = _JAN_RE.search(block)
    if jan is not None:
        fields["ean"] = jan.group(1)
    image_match = _DETAIL_IMG_RE.search(page_html)
    image = _image(image_match.group(1) if image_match else None, base_url)
    if image is not None:
        fields["imageUrl"] = image
    return fields


def mr_hobby_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    base_url = (descriptor.baseUrl or "").rstrip("/")
    old_details: dict[str, dict] = dict(cursor.get("details") or {})
    old_pending: set[str] = set(cursor.get("pending_details") or [])

    stats = {
        "fetched_pages": 0,
        "products_seen": 0,
        "skipped_unknown_vendor": 0,
        "details_fetched": 0,
        "detail_fetch_errors": 0,
        "detail_not_found": 0,
        "detail_parse_misses": 0,
        "barcodes_found": 0,
        "volume_parsed": 0,
        "enumeration_capped": 0,
    }

    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = (
        context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None
    )

    # --- Enumerate every configured category listing (the full population, every run). ---
    entries: dict[str, dict] = {}
    enumeration_capped = False
    for category in descriptor.scope.get("categories") or []:
        label = str(category.get("label") or "")
        path = str(category.get("path") or f"/en/products/category/{category['id']}")
        page = 1
        while True:
            page_html = client.get_response(path, params={"page": page} if page > 1 else None).text
            stats["fetched_pages"] += 1
            items = _parse_listing(page_html, base_url)
            if not items:
                break  # out-of-range pages are 200-with-zero-items (live-verified) -- belt for the anchor check below
            for item in items:
                entry = entries.setdefault(item["id"], {**item, "labels": []})
                if label and label not in entry["labels"]:
                    entry["labels"].append(label)
                # Cross-listed ids repeat the same tile; fill blanks the first listing lacked.
                for field in ("code", "text", "tag", "imageUrl"):
                    if entry.get(field) is None and item.get(field) is not None:
                        entry[field] = item[field]
            # Numbered paginator: the last page never links a HIGHER page number, so no
            # `?page=<next>` anchor means done (single-page categories render no anchors at
            # all). Anchored to this category's path + the href's closing quote so stray
            # "?page=N" text elsewhere in the page can never fake a next page (the live
            # anchors are absolute URLs ending in exactly this suffix).
            if f'{path}?page={page + 1}"' not in page_html:
                break
            page += 1
            if page > MAX_LISTING_PAGES:
                enumeration_capped = True
                stats["enumeration_capped"] = 1
                break

    stats["products_seen"] = len(entries)

    if manufacturer is None:
        # Same posture as wp_rest_paints: an unattributable pinned vendor observes nothing
        # (and the descriptor's minCount then fails the run loudly) rather than emitting
        # manufacturer-less evidence.
        stats["skipped_unknown_vendor"] = len(entries)
        entries = {}

    # --- Detail queue: new ids first, then parse-miss retries below the give-up cap. ---
    new_candidates: list[str] = []
    retry_candidates: list[str] = []
    for detail_id in entries:
        recorded = old_details.get(detail_id)
        if recorded is None:
            (retry_candidates if detail_id in old_pending else new_candidates).append(detail_id)
        elif not (recorded.get("sku") or recorded.get("name")):
            if recorded.get("detailMisses", 0) < DETAIL_MISS_CAP:
                retry_candidates.append(detail_id)
            # else: capped out -- never re-queued (listing data still observes the product).
        # else: parsed data known; never re-fetched (no staleness signal exists -- see docstring).

    detail_queue = sorted(new_candidates, key=int) + sorted(retry_candidates, key=int)
    budget = context.budget
    to_fetch = detail_queue if budget is None else detail_queue[: max(budget, 0)]
    to_fetch_set = set(to_fetch)

    # Carry forward every cached detail this run isn't fetching -- parsed data must never be
    # dropped just because the budget didn't reach its id (shopify_paints' ean rule).
    new_details: dict[str, dict] = {
        detail_id: old_details[detail_id]
        for detail_id in entries
        if detail_id in old_details and detail_id not in to_fetch_set
    }

    refreshed: set[str] = set()
    for detail_id in to_fetch:
        stats["details_fetched"] += 1
        try:
            page_html = client.get_text(entries[detail_id]["url"])
        except FetchError as error:
            if error.status == 404:
                # The EN listings advertise a handful of tiles whose EN detail pages simply do
                # not exist (live 2026-07-24: detail/39, 2508, 2509, 2541 -- JA-only products
                # with an unpublished EN page). A 404 is a definitive absence, not a transient
                # fault: give up NOW (cap, not pending) so four dead links can't pin
                # full_sweep=False forever. The listing tile still observes the product.
                stats["detail_not_found"] += 1
                new_details[detail_id] = {"detailMisses": DETAIL_MISS_CAP}
                refreshed.add(detail_id)
                continue
            stats["detail_fetch_errors"] += 1
            if detail_id in old_details:
                new_details[detail_id] = old_details[detail_id]
            continue  # stays pending; transient fetch errors never count against the miss cap
        parsed = _parse_detail(page_html, base_url)
        if parsed:
            new_details[detail_id] = parsed
            refreshed.add(detail_id)
        else:
            stats["detail_parse_misses"] += 1
            misses = old_details.get(detail_id, {}).get("detailMisses", 0)
            new_details[detail_id] = {"detailMisses": misses + 1}

    observations: list[Observation] = []
    for detail_id in sorted(entries, key=int):
        entry = entries[detail_id]
        detail = new_details.get(detail_id, {})
        name = detail.get("name") or entry["text"] or entry["code"] or f"detail-{detail_id}"
        sku = detail.get("sku") or entry["code"]
        image_url = detail.get("imageUrl") or entry["imageUrl"]
        ean = detail.get("ean")
        if ean:
            stats["barcodes_found"] += 1

        hints: dict[str, object] = {"category": "paint"}
        labels = entry["labels"]
        if labels:
            hints["line"] = labels[0]
            if len(labels) > 1:
                hints["lines"] = sorted(labels)
        volume = detail.get("volumeMl")
        if volume is not None:
            hints["volumeMl"] = volume
            stats["volume_parsed"] += 1
        if entry["tag"]:
            hints["tag"] = entry["tag"]

        observations.append(
            Observation(
                key=f"{descriptor.id}:{detail_id}",
                url=entry["url"],
                manufacturer=manufacturer,
                name=name,
                sku=sku,
                ean=ean,
                imageUrl=image_url,
                hints=hints,
                firstSeen=context.run_date,
                lastSeen=context.run_date,
                extractor=EXTRACTOR,
            )
        )

    pending_details = sorted(set(detail_queue) - refreshed, key=int)
    full_sweep = not pending_details and not enumeration_capped

    return StrategyResult(
        observations=observations,
        full_sweep=full_sweep,
        stats=stats,
        cursor={"details": new_details, "pending_details": pending_details},
    )


STRATEGIES["mr-hobby"] = mr_hobby_strategy
