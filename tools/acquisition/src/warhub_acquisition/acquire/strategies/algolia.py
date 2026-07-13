"""Algolia strategy (Games Workshop): full-sweep POST-paginated search index enumeration.

Ports `AlgoliaProductSource` from the retired .NET tool (`git show
1593ee1^:tools/WarHub.ProductCatalog.Tool/Scraping/AlgoliaProductSource.cs`) -- the app id, search
key, index name, `productType:miniatureKit` filter, `hitsPerPage`/`page`/`nbPages` pagination, and
the objectID -> GW sku parsing (`ExtractGwSku`) and hierarchy -> faction parsing (`ExtractFaction`)
logic are all ported faithfully. Two deliberate deviations from the literal .NET source, both
driven by this repo's "never guess" convention (same one shopify.py/woo.py already established for
malformed prices/vendors):

1. **No default-to-"Warhammer 40,000" gameSystem guess.** The .NET `MapToRawProduct` always
   initializes `gameSystem = "Warhammer 40,000"` before checking whether `GameSystemsRoot.lvl0`
   is even present, so a hit with no hierarchy at all silently becomes a (wrong) 40k hint. Here,
   a missing `lvl0` simply produces no gameSystem hint -- consistent with every other strategy in
   this repo never inventing a hint value.
2. **`ExtractGwSku`'s fallback-to-the-whole-objectID is NOT ported.** The .NET method returns the
   raw objectID string itself when no valid last-dash split exists (see `_extract_gw_sku`'s
   docstring for the exact condition). Using a composite id like `"P-253194-99112799002"` as
   `sku` would poison the field (it never matches the manufacturer's `codePattern`, unlike every
   real sku) purely because a rare malformed id showed up -- so this port returns `None` and
   counts `stats["malformed_object_id"]` instead, mirroring shopify.py's malformed-price handling.
3. **The faction skip-list is DATA, not code** (per the task brief): `AlgoliaProductSource.
   ExtractFaction`'s hardcoded `skipTerms` array is ported into the mapping file
   (`data/catalog/mappings/mfr-gw-algolia.yaml`'s `factionSkipTerms` list), not hardcoded here.
   `_raw_faction` below is the ported *logic* only.

No EAN: GW's Algolia payload carries no barcode/gtin field at all (probe-confirmed, per the task
brief) -- `Observation.ean` is always `None` here, never invented.

No detail fetches, no budget: every hit already carries everything this strategy extracts (name,
sku, price, url, image, hints) directly in the search response -- there is nothing to fetch a
"detail" for, and `context.budget` is ignored entirely (per the task brief). Enumeration is always
complete, so `full_sweep` is always `True` and the cursor is always `{}` (no per-product state
needs to persist between runs -- unlike shopify/woo, there is no staleness/detail-queue concept
here at all).

**Enumeration is a two-phase, per-game-system facet sweep.** Found the hard way: a live harvest of
the original single unfiltered sweep returned EXACTLY 1000 observations against nbHits 2856 --
Algolia's default `paginationLimitedTo` setting caps `page * hitsPerPage` at 1000 for plain
pagination. The .NET tool avoided the cap with per-game-system sweeps driven by a static hardcoded
list (`ManufacturerRegistry.cs`); its `GetGameSystemCountsAsync` facet query existed but was never
called. This port keeps the per-system sweep (phase 2, faithful) and replaces the static list with
live facet discovery (phase 1, deliberate improvement): self-updating, and it reads Algolia's raw
facet values directly instead of round-tripping display names through `MapGameSystem`.

1. **Facet discovery** (adapted from the unused `GetGameSystemCountsAsync`): one query with `hitsPerPage=0` and
   `facets=["GameSystemsRoot.lvl0"]` (same `filters`) returns the complete set of game-system
   facet values plus the store-wide `nbHits` (recorded as `stats["reported_nbhits"]`). A response
   with no usable facets produces an EMPTY result with `stats["missing_game_system_facets"]=1`
   rather than an exception -- the descriptor's min-count contract then fires loudly downstream,
   which is the established failure channel for "the source's data shape broke."
2. **Per-game-system paginated sweeps** (port of `BuildQuery`'s `FacetFilters`): for each facet
   value in SORTED order (determinism), paginate with
   `facetFilters=[["GameSystemsRoot.lvl0:<gs>"]]` added to the same query; each slice terminates
   on an empty hits page or `page >= nbPages`, exactly like the .NET per-system loop (that part IS
   the faithful port). Each slice stays under the 1000 cap. Hits are deduplicated across slices by objectID (first slice wins;
   `stats["cross_slice_duplicates"]` counts the rest -- a product CAN legitimately carry multiple
   lvl0 values, e.g. a starter set listed under two game lines). If any single slice's own nbHits
   exceeds 1000, `stats["slices_over_pagination_cap"]` counts it: single-level slicing is the
   faithful port, but a shortfall must be visible in health, never silent.
"""
from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

EXTRACTOR = "algolia@1"

# --- Ported constants (AlgoliaProductSource.DefaultAppId / DefaultSearchKey / DefaultIndexName /
# MaxHitsPerPage). The search key is a public, rate-limited-by-design Algolia "search-only" API
# key (not a secret) -- the .NET tool shipped it as a literal default, same as here. ---
APP_ID = "M5ZIQZNQ2H"
SEARCH_KEY = "92c6a8254f9d34362df8e6d96475e5d8"
INDEX_NAME = "prod-lazarus-product-en-gb"
HITS_PER_PAGE = 100
FILTER = "productType:miniatureKit"

SEARCH_URL = f"https://{APP_ID.lower()}-dsn.algolia.net/1/indexes/{INDEX_NAME}/query"
ALGOLIA_HEADERS = {
    "x-algolia-application-id": APP_ID,
    "x-algolia-api-key": SEARCH_KEY,
}

# The facet the .NET tool sliced sweeps by (GetGameSystemCountsAsync / BuildQuery.FacetFilters).
GAME_SYSTEM_FACET = "GameSystemsRoot.lvl0"

# Algolia's default paginationLimitedTo: plain pagination cannot see past this many results per
# query. Used only for the slices_over_pagination_cap honesty stat -- never for loop control.
PAGINATION_CAP = 1000

# Ported from AlgoliaProductSource.MapToRawProduct: `$"https://www.warhammer.com{hit.Images[0]}"`
# and `$"https://www.warhammer.com/en-GB/shop/{hit.Slug}"`.
SITE_BASE = "https://www.warhammer.com"
SHOP_PATH = "/en-GB/shop"


def _extract_gw_sku(object_id: str | None) -> str | None:
    """Port of `AlgoliaProductSource.ExtractGwSku`'s split logic (real objectIDs look like
    `"P-253194-99112799002"` or `"prod5100348-60040199167"` -- the true GW sku is the LAST
    dash-segment). See the module docstring for why the .NET fallback-to-whole-objectID branch is
    NOT ported: `None` is returned instead when no valid split exists, and the caller counts it.
    """
    if not object_id:
        return None
    last_dash = object_id.rfind("-")
    if last_dash > 0 and last_dash < len(object_id) - 1:
        return object_id[last_dash + 1 :]
    return None


def _raw_faction(hierarchy_value: str, skip_terms: set[str]) -> str:
    """Port of `AlgoliaProductSource.ExtractFaction`'s logic: split a single hierarchy value
    (e.g. `"The Old World > Armies of the Old World > Beastman Brayherds"`) on `" > "`, skip the
    game-system segment (index 0) plus any segment that case-insensitively matches a
    `factionSkipTerms` entry, and return the first surviving segment. `skip_terms` must already be
    casefolded by the caller. Falls back to `"General"` when every segment is skipped, exactly
    like the .NET source.
    """
    parts = [part.strip() for part in hierarchy_value.split(">")]
    parts = [part for part in parts if part]
    for part in parts[1:]:
        if part.casefold() not in skip_terms:
            return part
    return "General"


def _raw_game_system_and_faction(hit: dict, skip_terms: set[str]) -> tuple[str | None, str | None]:
    """Port of the hierarchy-reading half of `MapToRawProduct`: gameSystem from
    `GameSystemsRoot.lvl0[0]`, faction from the first non-empty of lvl3/lvl2/lvl1 (in that
    priority order, matching the .NET source's fallback chain), run through `_raw_faction`.
    Neither value is guessed when the hierarchy field is absent -- see module docstring deviation
    (1).
    """
    hierarchy = hit.get("GameSystemsRoot") or {}

    lvl0 = hierarchy.get("lvl0") or []
    game_system = lvl0[0] if lvl0 else None

    faction = None
    for level in ("lvl3", "lvl2", "lvl1"):
        values = hierarchy.get(level) or []
        if values:
            faction = _raw_faction(values[0], skip_terms)
            break

    return game_system, faction


def _apply_hints(hit: dict, mapping: dict) -> tuple[dict[str, object], int]:
    """Map raw GameSystemsRoot.lvl0 / hierarchy-derived faction -> taxonomy slugs via the source's
    mapping file. Never guesses: a present-but-unmapped raw gameSystem or faction each counts
    (not hinted) -- same convention as shopify.py's product_type/tags and woo.py's categories.
    """
    hints: dict[str, object] = {}
    unmapped = 0
    gs_map = mapping.get("gameSystem") or {}
    faction_map = mapping.get("faction") or {}
    skip_terms = {str(term).casefold() for term in (mapping.get("factionSkipTerms") or [])}

    raw_game_system, raw_faction = _raw_game_system_and_faction(hit, skip_terms)

    if raw_game_system:
        slug = gs_map.get(raw_game_system)
        if slug:
            hints["gameSystem"] = slug
        else:
            unmapped += 1

    if raw_faction:
        slug = faction_map.get(raw_faction)
        if slug:
            hints["faction"] = slug
        else:
            unmapped += 1

    return hints, unmapped


def _image_url(hit: dict) -> str | None:
    images = hit.get("images") or []
    if not images:
        return None
    first = images[0]
    return f"{SITE_BASE}{first}" if isinstance(first, str) and first else None


def _availability(hit: dict) -> str | None:
    if "isInStock" not in hit:
        return None
    return "in_stock" if hit["isInStock"] else "out_of_stock"


def _build_candidate(
    descriptor: SourceDescriptor,
    hit: dict,
    manufacturer: str,
    mapping: dict,
    run_date: str,
) -> tuple[Observation | None, dict[str, int]]:
    """Returns `(observation_or_None, stat_deltas)`. `observation` is `None` only when the hit has
    no name at all (ported from `MapToRawProduct`'s `IsNullOrWhiteSpace(hit.Name)` guard -- the
    whole hit is skipped, not just a field left blank)."""
    deltas = {"skipped_missing_name": 0, "malformed_object_id": 0, "unmapped_hints": 0}

    name = hit.get("name")
    if not name or not str(name).strip():
        deltas["skipped_missing_name"] = 1
        return None, deltas

    object_id = hit.get("objectID")
    sku = _extract_gw_sku(hit.get("sku") or object_id)
    if sku is None:
        deltas["malformed_object_id"] = 1

    slug = hit.get("slug")
    url = f"{SITE_BASE}{SHOP_PATH}/{slug}" if slug else None

    price = hit.get("price")
    price_kwargs: dict[str, object] = {}
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        price_kwargs["priceGbp"] = float(price)

    hints, unmapped = _apply_hints(hit, mapping)
    deltas["unmapped_hints"] = unmapped

    observation = Observation(
        key=f"{descriptor.id}:{object_id}",
        url=url,
        manufacturer=manufacturer,
        name=name,
        sku=sku,
        ean=None,  # no EAN in GW's Algolia payload -- probe-confirmed, never invented.
        imageUrl=_image_url(hit),
        availability=_availability(hit),
        hints=hints,
        firstSeen=run_date,
        lastSeen=run_date,
        extractor=EXTRACTOR,
        **price_kwargs,
    )
    return observation, deltas


def algolia_strategy(
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
        "malformed_object_id": 0,
        "unmapped_hints": 0,
        "cross_slice_duplicates": 0,
        "slices_over_pagination_cap": 0,
        "missing_game_system_facets": 0,
    }

    # --- Manufacturer: pinned per-source, same mechanism as woo.py (Algolia's hit payload has no
    # per-product vendor/brand field -- this whole index IS Games Workshop's own catalog). ---
    manufacturer_name = str(descriptor.scope.get("manufacturer") or "")
    manufacturer = context.taxonomy.manufacturer_for_vendor(manufacturer_name) if manufacturer_name else None

    # --- Phase 1: facet discovery (port of GetGameSystemCountsAsync). hitsPerPage=0 returns no
    # hits, just the facet value counts and the store-wide nbHits (the honesty baseline
    # products_seen is compared against in health reports). ---
    facet_body = {
        "query": "",
        "hitsPerPage": 0,
        "page": 0,
        "filters": FILTER,
        "facets": [GAME_SYSTEM_FACET],
    }
    facet_payload = client.post_json(SEARCH_URL, facet_body, headers=ALGOLIA_HEADERS)
    stats["fetched_pages"] += 1

    reported_nbhits = facet_payload.get("nbHits") if isinstance(facet_payload, dict) else None
    if isinstance(reported_nbhits, int):
        stats["reported_nbhits"] = reported_nbhits

    facets = facet_payload.get("facets") if isinstance(facet_payload, dict) else None
    game_system_counts = facets.get(GAME_SYSTEM_FACET) if isinstance(facets, dict) else None
    # Sorted for determinism: the facet dict's own order is relevance/count-based and can shift
    # between runs, which would make cross-slice dedupe ("first slice wins") nondeterministic.
    game_systems = sorted(game_system_counts) if isinstance(game_system_counts, dict) else []

    if not game_systems:
        # No usable facets -- the index's shape changed out from under us. Return an EMPTY result
        # (with the stat below) instead of raising: the descriptor's minCount contract fires
        # loudly downstream, the established failure channel for source-shape drift, and a failed
        # contract never decays existing evidence (run_source checks before any write).
        stats["missing_game_system_facets"] = 1

    # --- Phase 2: per-game-system paginated sweeps (port of BuildQuery's FacetFilters). Each
    # slice paginates via page/nbPages, terminating on an empty hits page OR page >= nbPages,
    # exactly like the .NET per-system loop; each stays under Algolia's ~1000
    # paginationLimitedTo cap, which a single unfiltered sweep does NOT (live harvest proved it:
    # exactly 1000 observations against nbHits 2856). context.budget is never consulted (per the
    # task brief). ---
    hits_by_id: dict[str, dict] = {}
    for game_system in game_systems:
        page = 0
        while True:
            body = {
                "query": "",
                "hitsPerPage": HITS_PER_PAGE,
                "page": page,
                "filters": FILTER,
                "facetFilters": [[f"{GAME_SYSTEM_FACET}:{game_system}"]],
            }
            payload = client.post_json(SEARCH_URL, body, headers=ALGOLIA_HEADERS)
            stats["fetched_pages"] += 1

            if page == 0:
                # Cap-detection honesty: single-level slicing is the faithful port, but if a
                # slice itself outgrows the pagination cap the shortfall must show up in health
                # stats, never silently truncate.
                slice_nbhits = payload.get("nbHits") if isinstance(payload, dict) else None
                if isinstance(slice_nbhits, int) and slice_nbhits > PAGINATION_CAP:
                    stats["slices_over_pagination_cap"] += 1

            hits = payload.get("hits") if isinstance(payload, dict) else None
            hits = hits or []
            if not hits:
                break

            for hit in hits:
                object_id = hit.get("objectID")
                if not object_id:
                    continue
                if object_id in hits_by_id:
                    # First slice wins (slices visited in sorted game-system order, so this is
                    # deterministic). Legitimate: one product can carry multiple lvl0 values.
                    stats["cross_slice_duplicates"] += 1
                else:
                    hits_by_id[object_id] = hit

            nb_pages = payload.get("nbPages") if isinstance(payload, dict) else None
            page += 1
            if not isinstance(nb_pages, int) or page >= nb_pages:
                break

    stats["products_seen"] = len(hits_by_id)

    observations: list[Observation] = []
    if manufacturer is None:
        stats["skipped_unknown_vendor"] = len(hits_by_id)
    else:
        for object_id in sorted(hits_by_id):
            observation, deltas = _build_candidate(
                descriptor, hits_by_id[object_id], manufacturer, mapping, context.run_date
            )
            for key, value in deltas.items():
                stats[key] += value
            if observation is not None:
                observations.append(observation)

    return StrategyResult(
        observations=observations,
        full_sweep=True,
        stats=stats,
        cursor={},
    )


STRATEGIES["algolia"] = algolia_strategy
