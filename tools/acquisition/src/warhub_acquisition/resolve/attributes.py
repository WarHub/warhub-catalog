"""Fold an entity's observations into one canonical record; derive lifecycle."""
from warhub_acquisition.models.catalog import CanonicalProduct, Overrides
from warhub_acquisition.models.descriptor import KIND_PRIORITY
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.corroborate import EanResolution

_HINT_FIELDS = ("gameSystem", "faction", "category", "packaging", "quantity", "volumeMl", "description")
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
    fields: dict[str, object] = {}
    for name in _DIRECT_FIELDS:
        fields[name] = _first([getattr(member, name) for member in ordered])
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

    fields.setdefault("category", None)
    if fields["category"] is None:
        fields["category"] = "miniatures"

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
