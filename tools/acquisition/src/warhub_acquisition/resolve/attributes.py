"""Fold an entity's observations into one canonical record; derive lifecycle."""
import re

from warhub_acquisition.models.catalog import CanonicalProduct, Overrides
from warhub_acquisition.taxonomy import Settings
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
# `gameSystem` is NOT here. Every other field in this tuple folds first-wins to a single value;
# game systems fold to a LIST -- of at most one element here; see below -- and the two rules
# cannot share a loop.
_HINT_FIELDS = (
    "faction", "category", "packaging", "quantity", "volumeMl", "weightG",
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
    default_hints: dict[str, dict[str, str]] | None = None,
    stale_fields: dict[str, list[str]] | None = None,
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
    # A source can be authoritative AND stale at the same time, so the winner is decided per FIELD
    # rather than once per member. `SourceDescriptor.staleFields` names the fields a source carries
    # as a frozen snapshot; for those, and only those, it sorts behind every other member whatever
    # its kind. `sorted` is stable, so the kind ladder above still decides everything else and this
    # is a no-op for every source that declares nothing.
    #
    # It DEMOTES, it does not exclude: a stale member still supplies a field nothing live has, which
    # is what keeps the 1,714 priceUsd and 231 availability values legacy-catalog is the only source
    # of. See SourceDescriptor.staleFields for the four-way measurement that made this per-field.
    stale = {sid: frozenset(names) for sid, names in (stale_fields or {}).items() if names}

    def _for(name: str) -> list[Observation]:
        if not stale:
            return ordered
        return sorted(ordered, key=lambda m: name in stale.get(m.source_id, frozenset()))

    # A HINT A SOURCE DECLARES AS ITS OWN FILL IS NOT A CLAIM ABOUT THIS PRODUCT, so it never
    # enters the fold. `SourceDescriptor.defaultHints` names those values; until now it only
    # LABELLED them after the fact, which left the fill winning the fold and a lower-ranked
    # source's real assertion discarded behind it.
    defaults = default_hints or {}

    def _claimed(member: Observation, name: str) -> object | None:
        value = member.hints.get(name)
        if value is not None and defaults.get(member.source_id, {}).get(name) == value:
            return None
        return value

    fields: dict[str, object] = {}
    for name in _DIRECT_FIELDS:
        eligible = [m for m in _for(name) if name != "sku" or m.key not in foreign]
        fields[name] = _first([getattr(member, name) for member in eligible])
    for name in _HINT_FIELDS:
        fields[name] = _first([_claimed(member, name) for member in _for(name)])

    # A SOURCE ROW NAMES ONE GAME, AND SO DOES THIS FOLD. Measured 2026-09-01 over all 19,904
    # observations carrying a `gameSystem` hint -- legacy-catalog, mfr-gw-algolia,
    # mfr-warlord-store, mfr-corvus-belli, mfr-para-bellum, seed-curated -- exactly ZERO carry more
    # than one value. No source has ever asserted dual membership in this field, so there is
    # nothing here to widen, and the list this writes is empty or a single element.
    #
    # TAKING ONE SOURCE'S SEVERAL ROWS AS A JOINT CLAIM IS WRONG, which is worth recording because
    # it looks right and was briefly implemented here. 19 products have one source whose rows
    # disagree, and not one of them is a listing that names two games. They are two other things:
    #
    #   * ONE PRODUCT CODE COVERING SEVERAL LISTINGS -- `Custodian Guard`, `Shield-Captain` and
    #     `Vexilus Praetor` share a code and the entity holds all three rows. The dual membership
    #     is real there, but it is the JOIN saying so, not the source.
    #   * A BAD JOIN. `M24 Chaffee, US light tank` and `Germanic command` both carry EAN
    #     5060200844311 on the Warlord store, so one entity holds both rows -- and folding them
    #     jointly published a WWII tank as a Hail Caesar product. 3 of the 9 products that rule
    #     produced were false in exactly that way, and its own description names Achtung Panzer!
    #     as the second game, which is not what it published.
    #
    # THE HONEST SIGNAL IS THE TAXONOMY, and `categorize` is where it is read: GW's Algolia rows
    # carry a `hierarchy` whose `lvl0` is a LIST (94 products name two systems once the
    # `Other Games` catch-all is discounted) and Mantic shelves 114 products under both Deadzone
    # and Firefight. Those are claims about a product; this is a fold over rows that may not
    # describe the same one.
    stated_system = _first([_claimed(member, "gameSystem") for member in _for("gameSystem")])
    fields["gameSystems"] = [str(stated_system)] if stated_system is not None else []

    # A source asserted it for this product. Recorded rather than inferred later, because by the
    # time anything downstream sees the record, a value folded from a hint and one written by a
    # rule table are indistinguishable -- which is how 1,819 LLM guesses came to sit in the same
    # field as 12,802 source claims with nothing to tell them apart.
    if fields["gameSystems"]:
        fields["gameSystemsBasis"] = "stated"

    # Fallback classification from a source's raw category taxonomy (today only mfr-gw-trade's
    # `tradeCategory`, mapped in data/catalog/mappings/<source>.yaml). Applied ONLY when no source
    # supplied a gameSystem directly, and it never overrides one -- it fills the products (chiefly
    # the GW trade ingest's China Order Form rows) that would otherwise publish gameSystem: null.
    # `ordered` already puts higher-priority/surviving sources first, so the first member whose
    # source maps its tradeCategory to a system wins; faction is taken from that same mapping.
    if not fields["gameSystems"] and category_maps:
        for member in ordered:
            trade_category = member.hints.get("tradeCategory")
            mapping = category_maps.get(member.source_id) if trade_category else None
            if not mapping:
                continue
            prefix = str(trade_category).split(" - ", 1)[0]
            system = (mapping.get("gameSystem") or {}).get(prefix)
            if system:
                fields["gameSystems"] = [system]
                fields["gameSystemsBasis"] = "mapped"
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

    # NOTHING IS GUESSED HERE ANY MORE. `category` used to fall back to `miniatures` whenever no
    # source spoke, which put a value on every product and so made a wrong one invisible -- the
    # exact defect `gameSystem` was cured of one change earlier. A category nothing asserted is
    # now absent, and `unknown` says so. `categorize` is what fills it from a rule table.
    fields.setdefault("category", None)
    fields["categoryBasis"] = "unknown" if fields["category"] is None else "stated"

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
    merged = CanonicalProduct.model_validate({**product.model_dump(), **patch})
    if patch.get("gameSystems") is not None:
        merged.gameSystemsBasis = "override"
    if patch.get("settings") is not None:
        merged.settingsBasis = "override"
    return merged


def apply_classification(
    product: CanonicalProduct, decisions: dict[str, dict], accepted: str = "classified"
) -> CanonicalProduct:
    """Apply an LLM classification, and ONLY where the evidence said nothing.

    THIS USED TO BE AN OVERRIDE, and that was the defect. `classify --apply` merged its decisions
    into data/catalog/overrides.yaml -- the file whose whole purpose is a human's judgement
    outranking every source -- and `apply_overrides` runs last, so a Haiku label beat the
    manufacturer that contradicted it. Measured 2026-08-31: 3,182 decisions, all `decidedBy: llm`,
    1,819 of them deciding a published record. Among them `SQUIG ORANGE (6-PACK) 12ML` ->
    the-old-world and `CONTRAST: BLACK LEGION` -> warhammer-40k: a colour is not a game product,
    and no source ever said it was.

    A guess is now what it always was, ranked accordingly: it fills a hole and can never fill
    anything else. A human override still outranks it, because `apply_overrides` still runs after.
    """
    decision = decisions.get(product.id)
    if not decision or product.gameSystems or not decision.get("gameSystem"):
        return product
    # THE DECISION FILE STAYS SCALAR and is not migrated, because its scalar shape is its contract:
    # the prompt tells the model to "pick EXACTLY ONE slug", so a record there is one answer to one
    # question. Wrapping it here says that plainly; rewriting 3,182 cached decisions into
    # single-element lists would only make a guess look like a measurement of membership.
    return product.model_copy(
        update={
            "gameSystems": [str(decision["gameSystem"])],
            "faction": product.faction or decision.get("faction"),
            "gameSystemsBasis": accepted,
        }
    )


#: Categories for which a game system is a category error rather than a missing value. A pot of
#: paint belongs to no game system and never will; saying `unknown` about it invites a classifier
#: to keep asking. `terrain` and `book` are deliberately NOT here -- a Necromunda bulkhead and a
#: Space Marines codex both belong to a system.
_NO_GAME_SYSTEM_CATEGORIES = frozenset({"paint", "paint-set", "hobby-auxiliary"})


#: The `gameSystemsBasis` / `settingsBasis` values this module is allowed to rewrite. Everything
#: else -- `stated`, `mapped`, `code`, `classified`, `override` -- traces to something and is left
#: exactly as it was. `setting` is here because it is derived from the settings axis and must
#: follow it; `derived` because it follows the game axis.
DERIVED_BASES = frozenset({"unknown", "not-applicable", "setting", "derived", None})


def complete_membership_bases(
    product: CanonicalProduct, system_labels: dict[str, str], settings: "Settings"
) -> CanonicalProduct:
    """Settle the two membership axes against each other, and name what an empty one means.

    THREE POSITIVE STATES AND ONE HOLE, and a product ends in exactly one of them:

      by game      `gameSystems` is non-empty. `settings` DERIVES from it -- each game names its
                   setting in game-systems.yaml -- and `settingsBasis` says `derived`. A hand
                   override of `settings` is the one thing that is not re-derived.
      by setting   `gameSystems` is empty and `settings` is not: a novel, a building sold for a
                   whole period. `gameSystemsBasis` says `setting` -- this product belongs to a
                   setting and deliberately to no one game in it.
      by nothing   both empty, and the category says why: a pot of paint belongs to no game and
                   no universe. Both bases say `not-applicable`.
      unknown      both empty and nothing said why. Both bases say `unknown`.

    THE PREDICATE FOR THE LAST TWO IS SAFE BY CONSTRUCTION, not by accuracy: it is only consulted
    when both lists are ALREADY empty, so it cannot erase a value anything else established. That
    matters, because the obvious formulation -- "category is paint, therefore no game system" --
    is measurably wrong: 411 products carry both, and they are real. `Infinity: JSA Paint Set` is
    a paint set AND an Infinity product; a faction transfer sheet is hobby-auxiliary AND belongs
    to its army.

    A NAMED COLOUR IS STILL A COLOUR, which is the one judgement encoded here. `CONTRAST: BLACK
    LEGION (18ML)` names a 40k faction and is a pot of paint; `Warhammer 40,000: Paints + Tools`
    is a boxed product for a game. The separator is whether the record is a single colour, and
    the test for that is the source's own words -- a volume, a multipack count, or `spray`.

    ONLY DERIVED BASES ARE EVER REWRITTEN (`DERIVED_BASES`). A `stated` game, a `mapped` setting
    or an `override` on either axis is a fact someone established and this function has nothing
    to add to it.
    """
    update: dict[str, object] = {}
    if product.gameSystems:
        if product.settingsBasis != "override":
            derived = settings.for_games(product.gameSystems)
            update["settings"] = derived
            if derived:
                update["settingsBasis"] = "derived"
            elif settings.all_settingless(product.gameSystems):
                update["settingsBasis"] = "not-applicable"
            else:
                update["settingsBasis"] = "unknown"
        return product.model_copy(update=update) if update else product
    if product.settings:
        if product.gameSystemsBasis in DERIVED_BASES:
            update["gameSystemsBasis"] = "setting"
        return product.model_copy(update=update) if update else product
    if product.category not in _NO_GAME_SYSTEM_CATEGORIES or _names_a_game_system(
        product.name, system_labels
    ):
        basis = "unknown"
    else:
        basis = "not-applicable"
    if product.gameSystemsBasis in DERIVED_BASES:
        update["gameSystemsBasis"] = basis
    if product.settingsBasis in DERIVED_BASES:
        update["settingsBasis"] = basis
    return product.model_copy(update=update) if update else product


_COLOUR_RECORD = re.compile(r"\d+\s*ml\b|\(\s*\d+\s*[- ]?pack\s*\)|\bx\s?\d+\b|\bspray\b", re.IGNORECASE)


def _names_a_game_system(name: str, system_labels: dict[str, str]) -> bool:
    """True when the product's own name names a game system AND the record is not a single colour.

    Driven by the taxonomy's labels rather than a hand-listed set of game names, so a system added
    to `game-systems.yaml` is recognised here the same day.
    """
    text = (name or "").lower()
    if not any(label.lower() in text for label in system_labels.values() if len(label) > 3):
        return False
    return _COLOUR_RECORD.search(text) is None
