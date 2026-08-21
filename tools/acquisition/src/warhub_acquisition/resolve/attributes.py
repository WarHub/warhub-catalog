"""Fold an entity's observations into one canonical record; derive lifecycle."""
from warhub_acquisition.models.catalog import CanonicalProduct, Overrides
from warhub_acquisition.models.descriptor import KIND_PRIORITY
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.corroborate import EanResolution
from warhub_acquisition.resolve.set_refs import (
    content_skus_from_case_sku,
    content_skus_from_description,
)

# `weightG` is NET CONTENTS in grams for a product sold by mass (added 2026-08-06), first-wins
# across the kind-ordered members exactly like `volumeMl` beside it. It is NOT Shopify's `grams`
# hint, which is gross shipping weight and stays out of this tuple.
# `contentSkus` is LIST-valued, unlike every other member of this tuple, and folds the same way:
# `_first` takes the highest-priority source's list WHOLE. That is deliberate -- see
# CanonicalProduct.contentSkus. Unioning two sources' contents claims would assert a box neither
# of them describes.
_HINT_FIELDS = (
    "gameSystem", "faction", "category", "packaging", "quantity", "volumeMl", "weightG",
    "description", "contentSkus",
)
_DIRECT_FIELDS = ("name", "sku", "availability", "url", "imageUrl", "priceGbp", "priceUsd", "priceEur", "priceCad")


def _first(values: list[object | None]) -> object | None:
    return next((value for value in values if value is not None), None)


def resolve_attributes(
    entity: str,
    members: list[Observation],
    kinds: dict[str, str],
    ean: EanResolution,
    code: str | None,
    miss_threshold: int = 3,
    superseded: frozenset[str] = frozenset(),
    category_maps: dict[str, dict] | None = None,
    member_codes: dict[str, str | None] | None = None,
    paint_eans: frozenset[str] = frozenset(),
) -> CanonicalProduct:
    # A repackaging join folds an OLD product code's observations (superseded) into the surviving
    # entity. Their attributes describe the retired box (a stale price, an old image), so within a
    # source kind they must lose to the surviving code's observations -- otherwise a still-live
    # old-packaging manufacturer page could pin a stale price over the current one. This does NOT
    # touch the curated>manufacturer>retailer>archive kind ladder: it only breaks ties WITHIN a
    # kind, and is a no-op for the single-code majority (no member is superseded there).
    ordered = sorted(
        members,
        key=lambda m: (KIND_PRIORITY.get(kinds.get(m.source_id, "barcode-db"), 9), m.key in superseded, m.key),
    )
    # `sku` is the only direct field that IDENTIFIES this product rather than describing it, so it
    # is the only one a member may be disqualified from supplying. An observation re-homed onto the
    # record its barcode scans as still carries the OTHER side's product code as its SKU -- that is
    # exactly what join.py's `supersession-stale-code` re-homing establishes about it -- and
    # publishing that would state a falsehood: `productCode: 99070207021` beside
    # `sku: 99120207208`, the code of a different product. A member whose SKU normalizes to a
    # DIFFERENT product code than this entity's is therefore skipped here. A retailer's own
    # catalogue number (`GWS94-22`, `120563` -- no normalized code at all) is NOT a competing
    # claim about GW's numbering and still qualifies, which is why this tests the NORMALIZED code
    # rather than string-comparing raw SKUs.
    foreign = {
        member.key
        for member in members
        if code is not None
        and member_codes is not None
        and member_codes.get(member.key) not in (None, code)
    }
    fields: dict[str, object] = {}
    for name in _DIRECT_FIELDS:
        eligible = [m for m in ordered if name != "sku" or m.key not in foreign]
        fields[name] = _first([getattr(member, name) for member in eligible])
    for name in _HINT_FIELDS:
        fields[name] = _first([member.hints.get(name) for member in ordered])

    # Fallback classification from a source's raw category taxonomy (today only mfr-gw-trade's
    # `tradeCategory`, mapped in data/catalog/mappings/<source>.yaml). Applied ONLY when no source
    # supplied a gameSystem directly, and it never overrides one -- it fills the products (chiefly
    # the GW trade ingest's China Order Form rows) that would otherwise publish gameSystem: null.
    # `ordered` already puts higher-priority/surviving sources first, so the first member whose
    # source maps its tradeCategory to a system wins; faction is taken from that same mapping.
    if fields["gameSystem"] is None and category_maps:
        for member in ordered:
            trade_category = member.hints.get("tradeCategory")
            mapping = category_maps.get(member.source_id) if trade_category else None
            if not mapping:
                continue
            prefix = str(trade_category).split(" - ", 1)[0]
            system = (mapping.get("gameSystem") or {}).get(prefix)
            if system:
                fields["gameSystem"] = system
                if fields["faction"] is None:
                    fields["faction"] = (mapping.get("faction") or {}).get(str(trade_category))
                break

    # WHAT IS IN THE BOX, when the source states it in prose instead of in a field. Only
    # `mfr-reaper` hands us a machine-readable contents array; every other brand writes the codes
    # into its `description`, which by this point has already been folded above and so is one
    # string regardless of which source supplied it. Never overrides a stated list -- a structured
    # array is the stronger claim and prose must not be allowed to contradict it.
    #
    # HERE rather than in the strategy (acquire-time parsing would make a better regex cost a
    # re-fetch) and rather than in gen_set_contents.py (which cannot reach `contentSkus` at all,
    # since it is written only from hints, and whose coverage test cross-checks the relation
    # against exactly this field). See resolve/set_refs.py, which argues all four candidate homes.
    #
    # Both `warlord-games` and `ak-interactive` derive contents from descriptions, with
    # `ak-interactive` by far the dominant population. When this path was first measured
    # (2026-08-07) Warlord was the ONLY population, which is why older notes describe it that way;
    # AK's own boxed sets arrived later and now outnumber it heavily. The Warlord entries are AK
    # "Quick Gen" boxes Warlord resells; their descriptions come from `legacy-catalog` -- a frozen
    # curated import with `strategy: none`, so no strategy change could ever have produced them.
    # Re-derive with `content_skus_from_description` over the committed product descriptions, or
    # count `contentSkusFrom: description` in data/catalog/products/.
    if fields["contentSkus"] is None and fields["description"]:
        derived = content_skus_from_description(str(fields["description"]))
        if derived:
            fields["contentSkus"] = derived
            fields["contentSkusFrom"] = "description"
    # A case pack of ONE colour states its membership in its own sku rather than in prose, so it
    # is tried after the description and only when that found nothing. See
    # `content_skus_from_case_sku` for why the rule is narrow and why it claims the colour but
    # not the count.
    if fields["contentSkus"] is None:
        derived = content_skus_from_case_sku(
            fields.get("sku") and str(fields["sku"]), fields.get("name") and str(fields["name"]))
        if derived:
            fields["contentSkus"] = derived
            fields["contentSkusFrom"] = "sku"
    if fields["contentSkus"] is not None:
        fields.setdefault("contentSkusFrom", "stated")

    # `category` is the one hint with a FALLBACK, and that fallback is the last thing in this
    # function that is not evidence. So before asserting it, ask the one source of truth that is
    # not a source: our own paint catalog. A barcode it publishes belongs to a paint -- the pot
    # and the product are the same physical thing, joined on exactly this key at publish time
    # (tools/WarHub.Catalog.Publish/CrossCatalogLinks.cs, docs/OBJECTIVES.md 4) -- so `paint` here
    # is a DERIVED FACT, not a better guess. data/catalog/paint-eans.yaml is that index; see
    # scripts/gen_paint_eans.py for why it is committed rather than read live.
    #
    # THIS ADDS A LABEL AND REMOVES NOTHING. It cannot fire where a source stated a category
    # (`fields["category"]` is already set by the fold above), it runs after the crossover stamp,
    # and `apply_overrides` still overrides it. Measured 2026-08-21 on catalog/acquisition: 1,072
    # products move miniatures->paint, 0 move the other way, 0 records appear or disappear. The
    # 948 that already said `paint` (games-workshop 838 off mfr-gw-trade's `Range` column,
    # steamforged-games 110 off mfr-warmachine's product_type map) never reach this branch. A
    # REFUSAL built on this same index -- PR #143 -- would have deleted 110 published ids and was
    # closed unmerged. The index labels; it must never be used to drop or reject a record.
    #
    # `miniatures` STAYS the fallback for everything else, and that is a measurement rather than
    # timidity: 16,711 of 30,747 products (54.4%) carry it with no source hint behind them at all,
    # because the biggest product sources emit no category signal whatsoever -- ret-goblingaming,
    # mfr-warlord-store, ret-radaddel, ret-tistaminis, ret-gamenerdz, mfr-gw-algolia,
    # mfr-manticgames and every arc-* store `hints: {}` on every row. Publishing null there would
    # empty the field across more than half the catalog for consumers who filter on it. Narrowing
    # the guess FURTHER is a curation job on data/catalog/mappings/, not a code change: the
    # `category:` table acquire/strategies/shopify.py::_apply_hints reads already answers this
    # question at the source, and mfr-warmachine uses it for 222 rows. It is the better lever for
    # the general case and a worse one for paints -- hints are baked into evidence at acquire
    # time, so a curated map changes nothing until each store is re-harvested.
    fields.setdefault("category", None)
    if fields["category"] is None:
        # No empty-index short-circuit: an empty `paint_eans` already makes every membership test
        # False, so the no-index path is the old behaviour by construction rather than by a branch
        # someone could later get wrong.
        published_as_paint = any(code in paint_eans for code in (ean.ean, *ean.additional) if code)
        fields["category"] = "paint" if published_as_paint else "miniatures"

    curated_status = _first(
        [member.hints.get("status") for member in members if kinds.get(member.source_id) == "curated"]
    )
    # barcode-db members never run a full_sweep -- their strategy only ever corroborates EAN, so
    # their missStreak is permanently frozen at 0 and their presence says NOTHING about liveness
    # in either direction. They are excluded from BOTH lifecycle collections: from scraped_live
    # (a frozen missStreak would keep `any(missStreak < miss_threshold)` true forever, pinning
    # status: current after every real source decayed) AND from live (a weekly bdb corroboration
    # of a recovered archived-only entity's provisional EAN must not flip discontinued->current).
    live = [
        member
        for member in members
        if not member.archived and kinds.get(member.source_id) != "barcode-db"
    ]
    scraped_live = [member for member in live if kinds.get(member.source_id) != "curated"]
    if not live:
        status = "discontinued"
    elif not scraped_live:
        # curated-only OR curated+bdb-only entity (e.g. legacy import not yet re-observed live,
        # or a legacy entity corroborated only by a barcode-db EAN lookup): trust the curated
        # claim if one exists; curated sources are never miss-flagged. Note a bdb-only entity
        # with NO curated member also lands here (scraped_live empty, curated_status None) and
        # falls through to "current" -- consistent with bdb never driving lifecycle on its own.
        status = str(curated_status) if curated_status else "current"
    elif any(member.missStreak < miss_threshold for member in scraped_live):
        status = "current"
    else:
        status = "suspected-discontinued"
        fields["availability"] = "unknown"
    if curated_status in ("discontinued", "delisted"):
        status = str(curated_status)  # explicit curated lifecycle always wins

    return CanonicalProduct(
        id=entity,
        manufacturer=members[0].manufacturer,
        productCode=code,
        ean=ean.ean,
        eanConfidence=ean.confidence,
        additionalEans=ean.additional,
        status=status,
        firstSeen=min(member.firstSeen for member in members),
        evidence=sorted(member.key for member in members),
        **fields,
    )


def apply_overrides(product: CanonicalProduct, overrides: Overrides) -> CanonicalProduct:
    patch = overrides.products.get(product.id)
    if not patch:
        return product
    # revalidate the merged record so an unknown key or wrong-typed value in
    # human-edited overrides.yaml fails loudly instead of being dropped
    return CanonicalProduct.model_validate({**product.model_dump(), **patch})
