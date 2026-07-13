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

**sku = raw `reference`, unparsed (trim only) -- exactly like the .NET source.** `MapToRawProduct`
assigns `Sku = product.Reference` verbatim (the .NET enricher then applies `raw.Sku?.Trim()`);
this port does the same. An earlier revision of this file truncated `reference` to its leading
6-digit REF (to satisfy corvus-belli's `codePattern: '\d{6}'`) -- REVERTED as an identity-join
hazard, review fix wave 1: the dash suffix is load-bearing. Real committed evidence
(`data/catalog/products/corvus-belli.yaml`): two UNRELATED products share the 6-digit stem
`280034` -- `betrayal-characters-pack` (`sku: 280034-0837`) and `operation-kaldstrom`
(`sku: 280034-0878`). Truncation would normalize both to code `"280034"` and resolve would union
them into one corrupted entity. The repo convention (most legacy corvus-belli entries) is the raw
dash-suffixed reference as sku; `Taxonomy.normalize_code`'s `\d{6}` fullmatch naturally returns
`None` for those and identity falls back to name-slug -- safe, no corruption possible.

**Local identifier: `slug` (falling back to raw `reference`), not a .NET `Id` field.** The .NET
`RawProduct` record has NO identity field at all (no `Id`/`ProductCode` populated for Corvus
Belli) -- this port needed to choose one for `Observation.key`. `slug` is the natural choice: it
is the same field `MapToRawProduct` itself uses to build the product's own storefront `Url`, is
unique per product, and (per live evidence) always present on every real product. A product
missing BOTH `slug` and `reference` (never observed live) has no stable identity at all and is
skipped, counted under `stats["skipped_missing_identifier"]`.

**Availability: the .NET 3-state `DetermineStatus` signal, mapped onto the established 2-state
`Observation.availability` vocabulary** (final fix wave, item 6 -- see `_status`'s docstring for
the full rationale). `preorder` not null OR `outstock` true -> `"out_of_stock"`; else
`"in_stock"`. An earlier revision emitted a literal `"pre_order"` value, conflating this one
strategy's richer .NET-status axis (a genuine 3-state model from the real payload) with the
`"in_stock"`/`"out_of_stock"` vocabulary every other strategy (shopify.py/woo.py/algolia.py) and
every downstream consumer treats as binary -- fixed to map onto that established vocabulary
instead of introducing a third value nothing else in the pipeline understands.

No detail fetches, no budget: every product already carries everything this strategy extracts
directly in the `listProducts` response -- `context.budget` is ignored entirely (per the task
brief), and enumeration is always complete (each of the 3 game-system sweeps paginates to its own
end), so `full_sweep` is always `True` and the cursor is always `{}`.
"""
import html

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
    """Port of `CorvusBelliProductSource.DetermineStatus`'s 3-state RAW signal (`preorder` not
    null -> pre-order; else `outstock` -> out of stock; else current), then mapped onto
    `Observation.availability`'s established 2-state vocabulary (final fix wave, item 6):
    shopify.py/woo.py/algolia.py all only ever emit `"in_stock"`/`"out_of_stock"` -- no other
    strategy emits `"pre_order"`, so inventing a third value here would conflate this one
    strategy's richer .NET-status axis with a vocabulary every downstream consumer (resolve,
    catalog, review) treats as binary. `"current"` -> `"in_stock"` is a direct match. A pre-order
    item is deliberately mapped to `"out_of_stock"`, not `"in_stock"`: it is not yet available for
    immediate purchase/fulfilment the way an in-stock item is, and `"out_of_stock"` is the closer
    of the two established values (the alternative -- inventing `"pre_order"` as a new vocabulary
    value -- was rejected since nothing else in the pipeline consumes it)."""
    if product.get("preorder") is not None:
        return "out_of_stock"
    if product.get("outstock"):
        return "out_of_stock"
    return "in_stock"


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
    deltas = {"skipped_missing_name": 0, "unmapped_hints": 0}

    raw_name = product.get("shortname")
    if not raw_name or not str(raw_name).strip():
        deltas["skipped_missing_name"] = 1
        return None, deltas

    # Port of `WebUtility.HtmlDecode(product.Shortname)` -- deliberately NOT trimmed, matching
    # the .NET source exactly: real CB data carries trailing whitespace on some shortnames (e.g.
    # "Death Song  ", confirmed live), which this port faithfully preserves rather than "fixing".
    name = html.unescape(str(raw_name))

    # sku = raw reference, unparsed except a trim (`Sku = product.Reference` in the .NET map,
    # `raw.Sku?.Trim()` in its enricher). NEVER truncated to the 6-digit stem: the dash suffix is
    # identity-bearing -- see module docstring's fix-wave-1 note (real committed products
    # 280034-0837 and 280034-0878 are unrelated and differ only by suffix).
    reference = product.get("reference")
    sku = str(reference).strip() or None if reference is not None else None

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
