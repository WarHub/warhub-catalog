"""GW webstore paint strategy: Citadel pot sizes, ranges and product codes from GW itself.

Registered as `STRATEGIES["gw-webstore-paints"]`. Games Workshop's own storefront is the only
place the MANUFACTURER states, for the brand that dominates this catalog, a paint's pot size,
its range, its colour family and -- the reason this source is worth having at all -- GW's own
product code for it.

**Why this exists.** `data/paints/barcodes/citadel-colour.yaml` is built by
`scripts/gen_paint_barcodes.py`, which has to reach the paint catalog from `mfr-gw-trade` by
scrubbing a trade description ("BASE: ABADDON BLACK (12ML) (6-PACK)") into a name and matching it
against the catalog's own names -- because the paint catalog carries no product code. This source
publishes GW's retail name, GW's range, GW's pot size and GW's 11-digit product code as ONE
record, so that reach can be made on GW's own fields instead of on a scrubbed string.

Sizing the prize honestly, because it is smaller than it looks: of the 297 catalog paints that
bridge reaches today, only 6 need its 0.86-cutoff `difflib` fallback at all -- the other 291 are
exact name matches. The fuzzy match is not the weak link it appears to be, and the section below
measures what this source does and does not fix.

## Two phases, deliberately asymmetric in cost

**Roster (Algolia).** GW's storefront search index carries `productType:paint` as a first-class
facet -- 331 paints in 8 `paintType` ranges (live 2026-08-01). The whole population costs four
requests. Reuses `mfr-gw-algolia`'s public search-only credentials and index (same app, same
index, different facet) rather than duplicating the key.

Every hit carries `sku`/`objectID` shaped `prod<internal id>-<11-digit GW product code>` -- the
trailing segment IS the `pimKey` GW's own product record reports, verified equal on the
`_next/data` record for all 331. This is the join key, and it is 331/331.

**How far that join actually reaches, measured 2026-08-01 -- read this before assuming it
replaces the name match.** Only 191/331 (57.7%) of these codes appear in `mfr-gw-trade` at all,
and the failure is not random, it is per-range:

    Contrast 61/61   Air 45/45   Dry 23/23   Technical 21/21   Spray 12/12   Shade 16/19
    Base      8/57 (14.0%)       Layer 5/93 (5.4%)

GW's trade register and GW's storefront disagree about the product code for Base and Layer
specifically (e.g. Base: Averland Sunset is `99189950265` here and `99189950208` there, and every
trade paint row is a `(6-PACK)` trade unit). So this source does NOT let the barcode bridge drop
its name match; on the six ranges above it can, on Base/Layer it cannot. What it does supply for
Base/Layer is GW's CURRENT code for paints the trade register only knows under an older one --
which is new information, not a redundant copy.

Net effect on `data/paints/barcodes/citadel-colour.yaml` if bridged today: +3 paints
(Mechanicus Standard Grey in Air and Spray, Mortarion Green Clear in Air -- all three present in
the trade evidence but missed by the name scrub), against 297 the existing bridge already
reaches. A real gain, a small one. No bridge is wired up in this commit for exactly that reason.

**Detail (`_next/data`, budgeted).** The per-product record adds two things Algolia does not
carry: GW's explicit `"Pot size: 12ml"` / `"Can size: 400ml"` spec line, and `productLaunchDate`.
It costs ~370KB per product (the response embeds the whole site nav), so it is a budgeted,
cursor-cached queue -- a parsed slug is never re-fetched, exactly like `mr_hobby`.

Measured over all 331 paints (full live sweep, 2026-08-01), this phase is worth much less than it
looks and the honest accounting is: `productLaunchDate` 331/331, but a features[] size only
159/331, which is a mere +2 volumes over what the image filenames already give (296/331 -> union
298/331). Its real value is therefore launch dates plus CORROBORATION -- on the 157 paints where
both speak they agree 157/157, zero conflicts, which is what licenses the image fallback below.
Run it with a budget; a full detail sweep moves ~120MB for those two extra volumes.

## The access mechanics, each of which independently makes this look impossible

1. **Every HTML route is behind a bot wall.** `GET /en-GB/shop/<slug>` returns HTTP 405 to a
   bare client and an empty HTTP 202 to any browser UA, including a full Chrome header set
   (sec-ch-*, sec-fetch-*, the lot). This is what previous probes hit, and why this repo
   repeatedly concluded GW publishes nothing machine-readable.
2. **The JSON route is NOT walled.** `GET /_next/data/<buildId>/en-GB/shop/<slug>.json` returns
   200 with the full commercetools record to plain httpx with *no* headers at all -- no UA, no
   cookie, no session. `robots.txt` is `Allow: /` with only `/*/cart` and `/*?search*`
   disallowed, so both this and the Algolia index are permitted (the advertised sitemap.xml
   404s).
3. **`buildId` rotates and cannot be read from any page**, because of (1). It IS recoverable:
   a `_next/data` request carrying a deliberately invalid buildId 404s with Next.js's own error
   page, and THAT page embeds the current `buildId`. `_discover_build_id` does exactly that, once
   per run, via the client's `allow_statuses` opt-out. A wrong buildId 404s every detail fetch,
   so it is never pinned in the descriptor.

## Sizes: two GW assertions, features first

`features[]` is authoritative when present, and is the only place a spray can states 400ml. When
it is silent the size is taken from GW's own CDN image filename
(`..._TECHNICAL_NIHILAKH_OXIDE_12ML.jpg`) -- still GW's own assertion about its own product, not
an inference, but a weaker one, so `hints.volumeSource` records which of the two spoke.

Measured over all 331 (2026-08-01): features 159, image 296, union 298 (90.0%), and where both
speak they agree 157/157 with ZERO conflicts. The 33 that state no size anywhere are the 23 Dry
paints and 10 of the 12 sprays -- their tiles are SVG placeholders with no size in the filename
and their spec block omits the line. They are emitted with NO volume. Every Dry paint is in fact
a 12ml pot and every spray a 400ml can, but this source will not say so: that is catalog
knowledge, not something GW asserts here, and inventing it is exactly what the pipeline forbids.

The leading number in an image filename is NOT the product code and must never be read as one --
`Technical: Nihilakh Oxide` is pimKey `99189956061` behind `99189956122_..._12ML.jpg`.

## Lifecycle

Emitted verbatim, never interpreted: `hints.lastChanceToBuy` (GW's own end-of-life flag),
`hints.availableWhileStocksLast`, `hints.statusCode`, plus `availability` via `mfr-gw-algolia`'s
own reader, since these are hits from the same index and the two sources must not disagree about
what "in stock" means. Note that on 2026-08-01 GW flagged 0/331 paints `lastChanceToBuy`, so this
field is a live tripwire for future retirements, not a backfill of past ones.

Presence in the roster is itself the liveness signal -- `full_sweep` is True when enumeration
completed and the detail queue drained, so a paint GW has delisted decays through the normal
miss-streak path. It is False when nothing was observed, so an unattributable run can never decay
the whole source.

Cursor schema (mirrors `mr_hobby`; a fetched detail is never re-fetched -- one-off snapshot
model, a fresh-eyes re-harvest means deleting the cursor). It holds only what `_next/data` said;
`volumeSource` is derived at emission, not stored, so changing the features-vs-image precedence
never requires a re-fetch:

    {
      "buildId": "<last discovered>",                 # honesty/debug only, never reused as input
      "details": {"<slug>": {"volumeMl": ..., "launchDate": ..., "lastChanceToBuy": ...,
                             "pimKey": ...}           # keys present only when GW stated them
                  | {"detailMisses": <n>}},           # unparseable, or the detail route 404s
      "pending_details": ["<slug>", ...]
    }
"""
from __future__ import annotations

import re

from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.acquire.strategies.algolia import (
    ALGOLIA_HEADERS,
    HITS_PER_PAGE,
    SEARCH_URL,
    SITE_BASE,
    _availability,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "gw-webstore-paints@1"

# The storefront index's own product-type facet. `productType:paint` is GW's classification, not
# ours -- it is what the site's /plp?paintType=... pages filter on.
PAINT_FILTER = "productType:paint"
PAINT_TYPE_FACET = "paintType"

# Same rationale as mr_hobby.DETAIL_MISS_CAP: markup drift on one product must not pin the source
# below full_sweep forever. Fetch ERRORS deliberately don't count -- they stay queued and retry.
DETAIL_MISS_CAP = 3

# Defensive ceiling, only reachable if Algolia's paging metadata drifts. The live range is 4 pages.
MAX_ROSTER_PAGES = 30

# A buildId that cannot be a real one, so the 404 it provokes is deterministic rather than a race
# against a real deploy. Next.js build ids are opaque tokens; "0" has never been issued as one.
_INVALID_BUILD_ID = "0"
_BUILD_ID_PROBE_SLUG = "_"
_BUILD_ID_RE = re.compile(r'"buildId"\s*:\s*"([A-Za-z0-9_-]+)"')

# `prod4210388-99189956061` -> `99189956061`. Anchored to end-of-string and to exactly 11 digits
# (games-workshop's codePattern in taxonomy/manufacturers.yaml), so a shape change surfaces as a
# skipped row in stats rather than a bogus code.
_PIM_KEY_RE = re.compile(r"-(\d{11})$")

# GW writes "Pot size: 12ml" for pots and "Can size: 400ml" for sprays. Both are the same
# assertion about volume; nothing else in features[] is a volume.
_FEATURE_SIZE_RE = re.compile(r"\b(?:pot|can|bottle|tub)\s*size\s*:\s*(\d+(?:\.\d+)?)\s*ml\b", re.I)

# The size GW encodes into its own CDN filename. Delimiter is `_` or `-`; the trailing guard is
# what makes `..._12ML_ALT.jpg` and `...-12ml-Pink-Horror-v2.jpg` both parse while refusing to
# read a digit run that merely happens to precede the letters "ml" inside a word.
_IMAGE_SIZE_RE = re.compile(r"[_-](\d+(?:\.\d+)?)\s*ml(?![a-z0-9])", re.I)

# Path to the commercetools record inside the Next.js page payload.
_PRODUCT_PATH = ("pageProps", "context", "productInformation", "inStore", "product")


def _dig(payload: object, path: tuple[str, ...]) -> object:
    for key in path:
        if not isinstance(payload, dict):
            return None
        payload = payload.get(key)
    return payload


def _localised(value: object) -> object:
    """commercetools stores most attributes as `{"en-GB": ...}`; a few are bare scalars."""
    if isinstance(value, dict) and "en-GB" in value:
        return value["en-GB"]
    return value


def _clean_name(raw: object) -> str | None:
    """Collapse internal whitespace -- GW ships at least one double-spaced name
    ("Shade:  Kroak Green"), which would otherwise not match the paint catalog."""
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    return text or None


def _as_number(raw: str) -> float | int:
    parsed = float(raw)
    return int(parsed) if parsed.is_integer() else parsed


def _pim_key(sku: object) -> str | None:
    match = _PIM_KEY_RE.search(str(sku or ""))
    return match.group(1) if match else None


def _volume_from_image(image_path: object) -> float | int | None:
    """GW's own CDN filename. Read from the BASENAME only: the directory segments carry image
    dimensions (`/920x950/`) that must never be mistaken for a volume."""
    basename = str(image_path or "").rsplit("/", 1)[-1]
    match = _IMAGE_SIZE_RE.search(basename)
    return _as_number(match.group(1)) if match else None


def _volume_from_features(features: object) -> float | int | None:
    for feature in features if isinstance(features, list) else []:
        match = _FEATURE_SIZE_RE.search(str(_localised(feature) or ""))
        if match is not None:
            return _as_number(match.group(1))
    return None


def _flag(value: object) -> bool | None:
    """commercetools ships these booleans as the STRINGS "true"/"false"; Algolia ships real
    bools. Anything else (absent, empty, unexpected) is None -- never silently False."""
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return True if text == "true" else False if text == "false" else None


def _discover_build_id(client: PoliteClient, base_url: str) -> str:
    """Read the current Next.js buildId out of the 404 page a bad buildId provokes.

    This is the only route to it: every HTML page on the site is bot-walled (see the module
    docstring), so `__NEXT_DATA__` cannot be read from a real page. The 404 body is Next.js's own
    error page and embeds the live buildId in its `__NEXT_DATA__` and its `/_next/static/<id>/`
    asset URLs.
    """
    url = f"{base_url}/_next/data/{_INVALID_BUILD_ID}/en-GB/shop/{_BUILD_ID_PROBE_SLUG}.json"
    response = client.get_response(url, allow_statuses=(404,))
    match = _BUILD_ID_RE.search(response.text)
    if match is None:
        raise FetchError(url, response.status_code)
    return match.group(1)


def _parse_detail(payload: object) -> dict:
    """Pull the fields Algolia does not carry out of one `_next/data` product record.

    Empty dict = parse miss (no product record, or a record with no attributes) -- counted
    against DETAIL_MISS_CAP by the caller.
    """
    variant = _dig(payload, (*_PRODUCT_PATH, "masterData", "current", "masterVariant"))
    if not isinstance(variant, dict):
        return {}
    raw_attributes = variant.get("attributesRaw")
    if not isinstance(raw_attributes, list):
        return {}
    attributes = {
        str(entry.get("name")): entry.get("value")
        for entry in raw_attributes
        if isinstance(entry, dict) and entry.get("name")
    }
    if not attributes:
        return {}

    fields: dict[str, object] = {}
    volume = _volume_from_features(_localised(attributes.get("features")))
    if volume is not None:
        fields["volumeMl"] = volume
    launch = str(_localised(attributes.get("productLaunchDate")) or "").strip()
    if launch:
        # "2022-05-28 00:00:00" -> "2022-05-28". GW states a date; the 00:00:00 is padding, and
        # every non-midnight value observed is a CMS edit timestamp, not a launch time.
        fields["launchDate"] = launch.split(" ", 1)[0]
    last_chance = _flag(_localised(attributes.get("lastChanceToBuy")))
    if last_chance is not None:
        fields["lastChanceToBuy"] = last_chance
    pim_key = _localised(attributes.get("pimKey"))
    if pim_key:
        fields["pimKey"] = str(pim_key)
    return fields


def _fetch_roster(client: PoliteClient, stats: dict) -> tuple[list[dict], bool]:
    """Every `productType:paint` hit in GW's storefront index, plus a truncation flag."""
    hits_by_id: dict[str, dict] = {}
    page = 0
    capped = False
    while True:
        payload = client.post_json(
            SEARCH_URL,
            {
                "query": "",
                "hitsPerPage": HITS_PER_PAGE,
                "page": page,
                "filters": PAINT_FILTER,
                "facets": [PAINT_TYPE_FACET],
            },
            headers=ALGOLIA_HEADERS,
        )
        stats["fetched_pages"] += 1
        if not isinstance(payload, dict):
            break
        if page == 0:
            # GW's own population count, the honesty baseline products_seen is measured against.
            reported = payload.get("nbHits")
            if isinstance(reported, int):
                stats["reported_nbhits"] = reported
        hits = payload.get("hits") or []
        if not hits:
            break
        for hit in hits:
            if isinstance(hit, dict) and hit.get("objectID"):
                hits_by_id.setdefault(str(hit["objectID"]), hit)
        page += 1
        pages = payload.get("nbPages")
        if isinstance(pages, int) and page >= pages:
            break
        if page >= MAX_ROSTER_PAGES:
            capped = True
            stats["enumeration_capped"] = 1
            break
    return list(hits_by_id.values()), capped


def gw_webstore_paints_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    base_url = (descriptor.baseUrl or SITE_BASE).rstrip("/")
    old_details: dict[str, dict] = dict(cursor.get("details") or {})
    old_pending: set[str] = set(cursor.get("pending_details") or [])

    stats = {
        "fetched_pages": 0,
        "products_seen": 0,
        "skipped_unknown_vendor": 0,
        "skipped_no_product_code": 0,
        "details_fetched": 0,
        "detail_fetch_errors": 0,
        "detail_not_found": 0,
        "detail_parse_misses": 0,
        "build_id_discovery_failed": 0,
        "pim_key_disagreements": 0,
        "volume_from_features": 0,
        "volume_from_image": 0,
        "volume_missing": 0,
        "last_chance_to_buy": 0,
        "enumeration_capped": 0,
    }

    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = (
        context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None
    )

    hits, enumeration_capped = _fetch_roster(client, stats)
    stats["products_seen"] = len(hits)

    entries: dict[str, dict] = {}
    for hit in hits:
        pim_key = _pim_key(hit.get("sku") or hit.get("objectID"))
        name = _clean_name(hit.get("name"))
        slug = str(hit.get("slug") or "").strip()
        if pim_key is None or name is None or not slug:
            # No product code means no join key, which is this source's entire reason to exist --
            # emitting a code-less paint would add a name-matched row of exactly the kind this
            # source exists to replace.
            stats["skipped_no_product_code"] += 1
            continue
        entries.setdefault(slug, {"hit": hit, "pimKey": pim_key, "name": name, "slug": slug})

    if manufacturer is None:
        # Same posture as mr_hobby/wp_rest_paints: an unattributable pinned vendor observes
        # nothing (and the descriptor's minCount then fails the run loudly) rather than emitting
        # manufacturer-less evidence.
        stats["skipped_unknown_vendor"] = len(entries)
        entries = {}

    # --- Detail queue: new slugs first, then parse-miss retries below the give-up cap. ---
    new_candidates: list[str] = []
    retry_candidates: list[str] = []
    for slug in entries:
        recorded = old_details.get(slug)
        if recorded is None:
            (retry_candidates if slug in old_pending else new_candidates).append(slug)
        elif recorded.get("detailMisses", 0) and recorded.get("detailMisses", 0) < DETAIL_MISS_CAP:
            retry_candidates.append(slug)
        # else: parsed data known; never re-fetched (no staleness signal exists -- see docstring).

    detail_queue = sorted(new_candidates) + sorted(retry_candidates)
    budget = context.budget
    to_fetch = detail_queue if budget is None else detail_queue[: max(budget, 0)]
    to_fetch_set = set(to_fetch)

    # Carry forward every cached detail this run isn't fetching -- parsed data must never be
    # dropped just because the budget didn't reach its slug.
    new_details: dict[str, dict] = {
        slug: old_details[slug]
        for slug in entries
        if slug in old_details and slug not in to_fetch_set
    }

    build_id: str | None = None
    if to_fetch:
        try:
            build_id = _discover_build_id(client, base_url)
        except FetchError:
            # Detail data is an enrichment, not the point of the source: without a buildId every
            # roster observation is still emitted (with the image-derived size), the run degrades
            # rather than fails, and the queue stays pending for next run.
            stats["build_id_discovery_failed"] = 1
            to_fetch = []
            to_fetch_set = set()
            new_details = {
                slug: old_details[slug] for slug in entries if slug in old_details
            }

    refreshed: set[str] = set()
    for slug in to_fetch:
        stats["details_fetched"] += 1
        url = f"{base_url}/_next/data/{build_id}/en-GB/shop/{slug}.json"
        try:
            payload = client.get_json(url)
        except FetchError as error:
            if error.status == 404:
                # A roster slug whose detail route 404s is a definitive absence (a stale index
                # entry), not a transient fault: give up NOW so it can't pin full_sweep forever.
                # The roster hit still observes the product.
                stats["detail_not_found"] += 1
                new_details[slug] = {"detailMisses": DETAIL_MISS_CAP}
                refreshed.add(slug)
                continue
            stats["detail_fetch_errors"] += 1
            if slug in old_details:
                new_details[slug] = old_details[slug]
            continue  # stays pending; transient fetch errors never count against the miss cap
        parsed = _parse_detail(payload)
        if parsed:
            new_details[slug] = parsed
            refreshed.add(slug)
        else:
            stats["detail_parse_misses"] += 1
            misses = old_details.get(slug, {}).get("detailMisses", 0)
            new_details[slug] = {"detailMisses": misses + 1}

    observations: list[Observation] = []
    for slug in sorted(entries):
        entry = entries[slug]
        hit = entry["hit"]
        detail = new_details.get(slug, {})
        image_path = (hit.get("images") or [None])[0]

        # Integrity guard, not a fallback: the search index and the product record are two GW
        # systems, and the whole source rests on their product codes being the same number. They
        # agreed 331/331 on 2026-08-01. If that ever stops being true the roster code is still
        # what is emitted (it is the one the roster is keyed by) and the disagreement surfaces in
        # health rather than silently picking a winner.
        if detail.get("pimKey") and str(detail["pimKey"]) != entry["pimKey"]:
            stats["pim_key_disagreements"] += 1

        hints: dict[str, object] = {"category": "paint"}
        paint_types = [str(value) for value in (hit.get("paintType") or []) if value]
        if paint_types:
            hints["line"] = paint_types[0]
            if len(paint_types) > 1:
                hints["lines"] = sorted(paint_types)
        if hit.get("paintColourRange"):
            hints["colourRange"] = str(hit["paintColourRange"])

        # features[] wins: it is GW's spec block, and it is the only place a spray states 400ml.
        volume = detail.get("volumeMl")
        volume_source = "features"
        if volume is None:
            volume = _volume_from_image(image_path)
            volume_source = "image"
        if volume is None:
            stats["volume_missing"] += 1
        else:
            hints["volumeMl"] = volume
            hints["volumeSource"] = volume_source
            stats["volume_from_features" if volume_source == "features" else "volume_from_image"] += 1

        if detail.get("launchDate"):
            hints["launchDate"] = detail["launchDate"]
        # Algolia and the product record agree on this flag; prefer the record when fetched.
        last_chance = detail.get("lastChanceToBuy")
        if last_chance is None:
            last_chance = _flag(hit.get("isLastChanceToBuy"))
        if last_chance is not None:
            hints["lastChanceToBuy"] = last_chance
            if last_chance:
                stats["last_chance_to_buy"] += 1
        while_stocks = _flag(hit.get("isAvailableWhileStocksLast"))
        if while_stocks is not None:
            hints["availableWhileStocksLast"] = while_stocks
        if hit.get("statusCode"):
            hints["statusCode"] = str(hit["statusCode"])

        price = hit.get("price")
        observations.append(
            Observation(
                key=f"{descriptor.id}:{entry['pimKey']}",
                url=f"{base_url}/en-GB/shop/{slug}",
                manufacturer=manufacturer,
                name=entry["name"],
                sku=entry["pimKey"],
                priceGbp=float(price) if isinstance(price, (int, float)) else None,
                imageUrl=f"{base_url}{image_path}" if image_path else None,
                availability=_availability(hit),
                hints=hints,
                firstSeen=context.run_date,
                lastSeen=context.run_date,
                extractor=EXTRACTOR,
            )
        )

    pending_details = sorted(set(detail_queue) - refreshed)
    full_sweep = not pending_details and not enumeration_capped and bool(entries)

    new_cursor: dict = {"details": new_details, "pending_details": pending_details}
    if build_id is not None:
        new_cursor["buildId"] = build_id

    return StrategyResult(
        observations=observations,
        full_sweep=full_sweep,
        stats=stats,
        cursor=new_cursor,
    )


STRATEGIES["gw-webstore-paints"] = gw_webstore_paints_strategy
