r"""AppSync strategy (Corvus Belli): GraphQL `listProducts` full-sweep enumeration across the
manufacturer's own 3 game systems.

Ports `CorvusBelliProductSource` from the retired .NET tool (`git show
1593ee1^:tools/WarHub.ProductCatalog.Tool/Scraping/CorvusBelliProductSource.cs`) -- the AppSync
endpoint, the `x-api-key` header, the `listProducts` GraphQL query/payload shape, and the REF ->
sku / faction extraction logic are all ported faithfully. One scope decision and two deliberate
"never guess" deviations, all documented below and in task-10-report.md.

**Scope: all 3 Corvus Belli game systems, not just the .NET class's own convenience default.**
`CorvusBelliProductSource.FetchAllProductsAsync` (no-args) only ever calls
`FetchProductsForGameAsync("infinity", "wargames", "Infinity", ...)` -- but that is just this
*class's* default entry point. The .NET tool's real scrape driver
(`ProductCatalogApp.FetchCorvusBelliProducts`, dispatched per game system from
`ManufacturerRegistry.cs`'s `["Corvus Belli"]` entry) actually swept THREE game systems:
Infinity (wargames), Warcrow (wargames), and Aristeia! (boardgames) -- see `GAME_SYSTEMS` below,
ported directly from those two files' game/type/name tuples. This port replicates the real
scrape scope, not the narrower single-method default.

**No EAN.** The `listProducts` GraphQL response carries no barcode/gtin field anywhere in its
selection set (`availability`, `itemAvailability`, `price`, `seo`, `shortname`, `reference`,
`labels`, `outstock`, `rating`, `slug`, `preorder`, `category`, `img`, `meta` -- checked against
the ported query verbatim). `Observation.ean` is always `None`, never invented.

**REF -> sku IS parsed here, unlike the literal .NET source.** `MapToRawProduct` in the .NET file
assigns `Sku = product.Reference` verbatim, with NO parsing at all. Live evidence (single capture,
2026-07-13, Infinity/wargames page 1) shows `reference` is NOT uniformly a bare 6-digit code:
miniatures/accessories carry `"<6-digit REF>-<variant suffix>"` (e.g. `"280888-1149"`), while
non-miniature products (Winged Hussar Publishing novels, in this catalog) carry an unrelated
`"WHP-005"`-style code. `corvus-belli`'s own `taxonomy/manufacturers.yaml` entry declares
`codePattern: '\d{6}'` -- so `_extract_cb_ref` extracts exactly that leading 6-digit REF (before a
dash or end of string) and returns `None` (never the raw, non-conforming string) when it isn't
there, counting `stats["malformed_reference"]`. Same "never guess" convention as
algolia.py's `_extract_gw_sku`/woo.py's malformed-gtin handling.

**Local identifier: `slug` (falling back to raw `reference`), not a .NET `Id` field.** The .NET
`RawProduct` record has NO identity field at all (no `Id`/`ProductCode` populated for Corvus
Belli) -- this port needed to choose one for `Observation.key`. `slug` is the natural choice: it
is the same field `MapToRawProduct` itself uses to build the product's own storefront `Url`, is
unique per product, and (per live evidence) always present on every real product. A product
missing BOTH `slug` and `reference` (never observed live) has no stable identity at all and is
skipped, counted under `stats["skipped_missing_identifier"]`.

**Availability: the .NET 3-state `DetermineStatus`, ported as-is** (`"pre_order"` when `preorder`
is not null, `"out_of_stock"` when `outstock` is true, else `"current"`) -- a genuine 3-state
model from the real payload, not force-fit into algolia.py/woo.py's 2-state
`"in_stock"`/`"out_of_stock"` convention (those strategies' payloads never carried a pre-order
signal at all).

No detail fetches, no budget: every product already carries everything this strategy extracts
directly in the `listProducts` response -- `context.budget` is ignored entirely (per the task
brief), and enumeration is always complete (each of the 3 game-system sweeps paginates to its own
end), so `full_sweep` is always `True` and the cursor is always `{}`.
"""
import html
import re

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "appsync@1"

# --- Ported constants (CorvusBelliProductSource.GraphQlEndpoint / ApiKey). The key is the .NET
# tool's own literal default (an AppSync "API key" auth mode key, not a user secret) -- probe-
# confirmed still live, 2026-07-13. ---
GRAPHQL_ENDPOINT = "https://aiscbwsb6vb3xbysk57tnk3miy.appsync-api.eu-west-1.amazonaws.com/graphql"
API_KEY = "da2-xxsxwilwsvhuhauw4d7e3qhocy"
API_HEADERS = {"x-api-key": API_KEY}

SITE_BASE = "https://store.corvusbelli.com"
IMAGE_BASE = "https://store.corvusbelli.com/media/catalog/product"

# --- (apiGame, apiType, gameSystemName) tuples -- ported from ManufacturerRegistry.cs's
# ["Corvus Belli"] GameSystems dict + ProductCatalogApp.cs's FetchCorvusBelliProducts switch. This
# is enumeration SCOPE (which game systems get swept), kept as code -- the taxonomy-slug hint
# mapping for these same 3 names lives in data/catalog/mappings/mfr-corvus-belli.yaml. ---
GAME_SYSTEMS: list[tuple[str, str, str]] = [
    ("infinity", "wargames", "Infinity"),
    ("warcrow", "wargames", "Warcrow"),
    ("aristeia", "boardgames", "Aristeia!"),
]

# Ported verbatim from CorvusBelliProductSource.ProductsQuery.
PRODUCTS_QUERY = """query products($category: ICategory!, $lang: LANG!, $filters: [INameValue], $page: Int, $sort: PRODUCT_SORT, $rating: Int) {
    products: listProducts(category: $category, lang: $lang, filters: $filters, page: $page, sort: $sort, rating: $rating) {
        products {
            availability { from, to }
            itemAvailability
            price
            seo
            shortname
            reference
            labels
            outstock
            rating { value, votes }
            slug
            preorder
            category { cat, game, type }
            img {
                nextgen
                front { title, img, description }
            }
            meta {
                groups { group, name }
                options { group, option, outstock, reference, type }
            }
        }
        pages
        currentPage
        total
    }
}"""

# Matches a leading 6-digit REF followed by a dash (variant suffix) or end of string -- corvus-
# belli's own taxonomy/manufacturers.yaml codePattern is exactly `\d{6}`.
_REF_RE = re.compile(r"^(\d{6})(?:-|$)")


def _extract_cb_ref(reference: str | None) -> str | None:
    """Port+parse of the .NET `reference` field (see module docstring for why this port DOES
    parse, unlike the literal .NET `Sku = product.Reference` assignment). Real examples:
    `"280888-1149"` -> `"280888"`; a bare 6-digit code with no suffix -> itself unchanged;
    `"WHP-005"` (a non-miniature catalog code) -> `None`, never the raw string."""
    if not reference:
        return None
    match = _REF_RE.match(reference.strip())
    return match.group(1) if match else None


def _parse_int_field(value: object) -> int | None:
    """Port of `CbProductList.ParseJsonInt`: `pages`/`total` can arrive as a JSON number (live
    evidence: `pages` was `24.0`, a float) or a numeric string. Anything else (missing, null,
    non-numeric) is `None` -- the caller decides the safe fallback, this helper never guesses 0."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _extract_product_list(payload: object) -> dict | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    products = data.get("products")
    return products if isinstance(products, dict) else None


def _extract_faction(seo: list | None, name: str, candidates: list[str]) -> str | None:
    """Port of `CorvusBelliProductSource.ExtractFaction`'s logic EXACTLY, including its traversal
    order: for each `seo` entry (in order), check every candidate (in list order) as a case-
    insensitive substring -- the first (seoText, candidate) pair that matches wins, so an earlier
    seo entry always wins over a later one regardless of candidate order within it. Only when NO
    seo entry matches anything does it fall back to checking `name` against every candidate (in
    list order). Returns `None` (never guessed) when nothing matches at all -- for `Aristeia!`,
    `candidates` is always empty (see module docstring), so this always returns `None` for it.
    """
    if seo:
        for seo_text in seo:
            folded = str(seo_text).casefold()
            for candidate in candidates:
                if candidate.casefold() in folded:
                    return candidate
    folded_name = name.casefold()
    for candidate in candidates:
        if candidate.casefold() in folded_name:
            return candidate
    return None


def _status(product: dict) -> str:
    """Port of `CorvusBelliProductSource.DetermineStatus`: a genuine 3-state model from the real
    payload (`preorder` not null -> pre-order; else `outstock` -> out of stock; else current)."""
    if product.get("preorder") is not None:
        return "pre_order"
    if product.get("outstock"):
        return "out_of_stock"
    return "current"


def _image_url(product: dict) -> str | None:
    img = product.get("img") or {}
    front = img.get("front") or {}
    img_file = front.get("img")
    if not img_file or not str(img_file).strip():
        return None
    return f"{IMAGE_BASE}/{img_file}"


def _apply_hints(
    product: dict, name: str, game_system_name: str, mapping: dict
) -> tuple[dict[str, object], int]:
    """Map the fixed gameSystemName + extracted raw faction -> taxonomy slugs via the source's
    mapping file. Never guesses: an unmapped gameSystem name, or a raw faction that WAS extracted
    but has no matching taxonomy slug, each count (not hinted) -- same convention as
    algolia.py/woo.py. A raw faction that could not be extracted AT ALL (no candidate matched
    anywhere, or `game_system_name == "Aristeia!"` with no candidates) is NOT counted as unmapped
    -- there was nothing to map in the first place.
    """
    hints: dict[str, object] = {}
    unmapped = 0

    gs_map = mapping.get("gameSystem") or {}
    gs_slug = gs_map.get(game_system_name)
    if gs_slug:
        hints["gameSystem"] = gs_slug
    else:
        unmapped += 1

    candidates_map = mapping.get("factionCandidatesByGameSystem") or {}
    candidates = candidates_map.get(game_system_name) or []
    raw_faction = _extract_faction(product.get("seo"), name, candidates)
    if raw_faction:
        faction_map = mapping.get("faction") or {}
        faction_slug = faction_map.get(raw_faction)
        if faction_slug:
            hints["faction"] = faction_slug
        else:
            unmapped += 1

    return hints, unmapped


def _build_candidate(
    key: str,
    product: dict,
    api_game: str,
    game_system_name: str,
    category_type: str,
    manufacturer: str,
    mapping: dict,
    run_date: str,
) -> tuple[Observation | None, dict[str, int]]:
    """Returns `(observation_or_None, stat_deltas)`. `observation` is `None` only when the
    product has no name at all (ported from `MapToRawProduct`'s implicit
    `WebUtility.HtmlDecode(product.Shortname)` call, which the .NET map path never actually
    guards -- see `test_hit_with_no_name_is_skipped_and_counted`'s equivalent test for why this
    port DOES guard it: an unnamed product is unusable downstream, mirrors algolia.py/woo.py)."""
    deltas = {"skipped_missing_name": 0, "malformed_reference": 0, "unmapped_hints": 0}

    raw_name = product.get("shortname")
    if not raw_name or not str(raw_name).strip():
        deltas["skipped_missing_name"] = 1
        return None, deltas

    # Port of `WebUtility.HtmlDecode(product.Shortname)` -- deliberately NOT trimmed, matching
    # the .NET source exactly: real CB data carries trailing whitespace on some shortnames (e.g.
    # "Death Song  ", confirmed live), which this port faithfully preserves rather than "fixing".
    name = html.unescape(str(raw_name))

    sku = _extract_cb_ref(product.get("reference"))
    if sku is None:
        deltas["malformed_reference"] = 1

    slug = product.get("slug")
    url = f"{SITE_BASE}/en/{category_type}/{api_game}/{slug}" if slug else None

    price = product.get("price")
    price_kwargs: dict[str, object] = {}
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        price_kwargs["priceEur"] = float(price)

    hints, unmapped = _apply_hints(product, name, game_system_name, mapping)
    deltas["unmapped_hints"] = unmapped

    observation = Observation(
        key=key,
        url=url,
        manufacturer=manufacturer,
        name=name,
        sku=sku,
        ean=None,  # listProducts carries no barcode/gtin field at all -- never invented.
        imageUrl=_image_url(product),
        availability=_status(product),
        hints=hints,
        firstSeen=run_date,
        lastSeen=run_date,
        extractor=EXTRACTOR,
        **price_kwargs,
    )
    return observation, deltas


def _fetch_game_system(
    client: PoliteClient, api_game: str, category_type: str, stats: dict[str, int]
) -> list[dict]:
    """Port of `FetchProductsForGameAsync`'s page loop: 1-indexed `page`, re-reads `totalPages`
    from EVERY response's `pages` field, terminates once `page > totalPages` OR an empty
    `products` page is returned -- whichever comes first, exactly like the .NET source."""
    products: list[dict] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        body = {
            "query": PRODUCTS_QUERY,
            "variables": {
                "category": {"type": category_type, "game": api_game},
                "lang": "en",
                "filters": [],
                "page": page,
            },
        }
        payload = client.post_json(GRAPHQL_ENDPOINT, body, headers=API_HEADERS)
        stats["fetched_pages"] += 1

        product_list = _extract_product_list(payload)
        page_products = product_list.get("products") if product_list else None
        if not isinstance(page_products, list) or not page_products:
            break

        products.extend(page_products)

        if page == 1:
            reported_total = _parse_int_field(product_list.get("total")) if product_list else None
            if reported_total is not None:
                stats["reported_total"] = stats.get("reported_total", 0) + reported_total

        total_pages = (_parse_int_field(product_list.get("pages")) if product_list else None) or 0
        page += 1

    return products


def appsync_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    mapping = context.mappings.get(descriptor.id, {}) if context.mappings else {}

    stats = {
        "fetched_pages": 0,
        "products_seen": 0,
        "skipped_unknown_vendor": 0,
        "skipped_missing_name": 0,
        "skipped_missing_identifier": 0,
        "malformed_reference": 0,
        "unmapped_hints": 0,
    }

    # --- Manufacturer: pinned per-source, same mechanism as algolia.py/woo.py. ---
    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None

    # --- Enumerate: always full, across all 3 game systems (see module docstring). context.budget
    # is never consulted (per the task brief). ---
    # local key -> (product, api_game, game_system_name, category_type)
    products_by_key: dict[str, tuple[dict, str, str, str]] = {}
    for api_game, category_type, game_system_name in GAME_SYSTEMS:
        for product in _fetch_game_system(client, api_game, category_type, stats):
            local_id = product.get("slug") or product.get("reference")
            if not local_id:
                stats["skipped_missing_identifier"] += 1
                continue
            key = f"{descriptor.id}:{api_game}:{local_id}"
            products_by_key[key] = (product, api_game, game_system_name, category_type)

    stats["products_seen"] = len(products_by_key)

    observations: list[Observation] = []
    if manufacturer is None:
        stats["skipped_unknown_vendor"] = len(products_by_key)
    else:
        for key in sorted(products_by_key):
            product, api_game, game_system_name, category_type = products_by_key[key]
            observation, deltas = _build_candidate(
                key, product, api_game, game_system_name, category_type, manufacturer, mapping, context.run_date
            )
            for stat_key, value in deltas.items():
                stats[stat_key] += value
            if observation is not None:
                observations.append(observation)

    return StrategyResult(
        observations=observations,
        full_sweep=True,
        stats=stats,
        cursor={},
    )


STRATEGIES["appsync"] = appsync_strategy
