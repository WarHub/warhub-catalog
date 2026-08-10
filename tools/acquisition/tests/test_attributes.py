import pytest
from pydantic import ValidationError

from warhub_acquisition.models.catalog import CanonicalProduct, Overrides
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.attributes import apply_overrides, resolve_attributes
from warhub_acquisition.resolve.corroborate import EanResolution

KINDS = {
    "legacy-catalog": "curated",
    "mfr-gw": "manufacturer",
    "ret-a": "retailer",
    "arc-x": "archive",
    "bdb-upcitemdb": "barcode-db",
}
NO_EAN = EanResolution(None, None, [])


def obs(key: str, **kw: object) -> Observation:
    base: dict[str, object] = {
        "key": key, "name": "Combat Patrol: Necrons", "manufacturer": "games-workshop",
        "firstSeen": "2026-07-12", "lastSeen": "2026-07-12", "extractor": "t@1",
    }
    base.update(kw)
    return Observation(**base)


def members_sorted() -> list[Observation]:
    return [
        obs("mfr-gw:necrons", priceGbp=76.5, url="https://gw/necrons", hints={"gameSystem": "warhammer-40k", "faction": "necrons"}),
        obs("ret-a:necrons", name="Necrons Combat Patrol (GW)", priceGbp=65.0, imageUrl="https://ret/img.jpg"),
    ]


def test_precedence_prefers_manufacturer_then_backfills() -> None:
    product = resolve_attributes("games-workshop/99120110077", members_sorted(), KINDS, NO_EAN, "99120110077")
    assert product.name == "Combat Patrol: Necrons"     # manufacturer wins
    assert product.priceGbp == 76.5
    assert product.imageUrl == "https://ret/img.jpg"     # retailer backfills gaps
    assert product.gameSystem == "warhammer-40k"
    assert product.category == "miniatures"              # default
    assert product.evidence == ["mfr-gw:necrons", "ret-a:necrons"]


def test_lifecycle_current_when_any_live_source_sees_it() -> None:
    product = resolve_attributes("e", [obs("mfr-gw:a", missStreak=0)], KINDS, NO_EAN, None)
    assert product.status == "current"


def test_lifecycle_suspected_when_all_live_sources_miss() -> None:
    product = resolve_attributes("e", [obs("mfr-gw:a", missStreak=3), obs("ret-a:b", missStreak=4)], KINDS, NO_EAN, None)
    assert product.status == "suspected-discontinued"
    assert product.availability == "unknown"


def test_lifecycle_discontinued_when_archive_only() -> None:
    product = resolve_attributes("e", [obs("arc-x:a", archived=True)], KINDS, NO_EAN, None)
    assert product.status == "discontinued"


def test_curated_discontinued_hint_wins() -> None:
    members = [obs("legacy-catalog:a", hints={"status": "delisted"}), obs("mfr-gw:b", missStreak=0)]
    product = resolve_attributes("e", members, KINDS, NO_EAN, None)
    assert product.status == "delisted"


def test_curated_only_entity_trusts_curated_status() -> None:
    # legacy-only products (post-migration) keep their archived status; they are
    # never miss-flagged because no live scraped source covers them
    product = resolve_attributes("e", [obs("legacy-catalog:a", hints={"status": "current"})], KINDS, NO_EAN, None)
    assert product.status == "current"
    product = resolve_attributes("e", [obs("legacy-catalog:a")], KINDS, NO_EAN, None)
    assert product.status == "current"
    product = resolve_attributes("e", [obs("legacy-catalog:a", hints={"status": "suspected-discontinued"})], KINDS, NO_EAN, None)
    assert product.status == "suspected-discontinued"


def test_apply_overrides_replaces_fields() -> None:
    product = resolve_attributes("e", members_sorted(), KINDS, NO_EAN, None)
    overridden = apply_overrides(product, Overrides(products={"e": {"faction": "necrons-fixed", "quantity": 11}}))
    assert overridden.faction == "necrons-fixed"
    assert overridden.quantity == 11
    untouched = apply_overrides(product, Overrides())
    assert untouched == product


def test_apply_overrides_explicit_null_faction_clears_folded_value() -> None:
    # members_sorted() folds hints.faction == "necrons" onto the resolved product; an
    # override patch with an explicit faction=None (as apply_classifications now always
    # writes for a re-classification decision with no/null faction) must clear it rather
    # than being ignored as a no-op falsy value.
    product = resolve_attributes("e", members_sorted(), KINDS, NO_EAN, None)
    assert product.faction == "necrons"
    overridden = apply_overrides(product, Overrides(products={"e": {"faction": None}}))
    assert overridden.faction is None


def test_apply_overrides_unknown_field_raises() -> None:
    product = resolve_attributes("e", members_sorted(), KINDS, NO_EAN, None)
    with pytest.raises(ValidationError):
        apply_overrides(product, Overrides(products={"e": {"qauntity": 11}}))


def test_apply_overrides_bad_value_raises() -> None:
    product = resolve_attributes("e", members_sorted(), KINDS, NO_EAN, None)
    with pytest.raises(ValidationError):
        apply_overrides(product, Overrides(products={"e": {"quantity": "ten"}}))


def test_curated_current_does_not_resurrect_suspected() -> None:
    members = [
        obs("legacy-catalog:a", hints={"status": "current"}),
        obs("mfr-gw:b", missStreak=3),
    ]
    product = resolve_attributes("e", members, KINDS, NO_EAN, None)
    assert product.status == "suspected-discontinued"
    assert product.availability == "unknown"


def test_price_cad_folds_like_other_currencies() -> None:
    members = [
        obs("mfr-gw:necrons", priceCad=105.0, url="https://gw/necrons"),
        obs("ret-a:necrons", name="Necrons Combat Patrol (GW)", priceCad=99.0),
    ]
    product = resolve_attributes("games-workshop/99120110077", members, KINDS, NO_EAN, "99120110077")
    assert product.priceCad == 105.0  # manufacturer wins, same precedence as priceGbp


def test_barcode_db_member_never_keeps_a_decayed_entity_current() -> None:
    # bdb strategies never run a full_sweep, so their missStreak is permanently frozen at 0.
    # Before excluding barcode-db from scraped_live, this single bdb member's missStreak==0 kept
    # `any(missStreak < miss_threshold)` true forever even though the only REAL scraped source
    # (the retailer) has fully decayed -- pinning status: current indefinitely. It must decay
    # like a bdb-less entity would.
    members = [obs("ret-a:a", missStreak=3), obs("bdb-upcitemdb:a", missStreak=0)]
    product = resolve_attributes("e", members, KINDS, NO_EAN, None)
    assert product.status == "suspected-discontinued"
    assert product.availability == "unknown"


def test_barcode_db_corroboration_never_revives_an_archived_only_entity() -> None:
    # Final-review N1 repro: an archive-recovered OOP entity (archived-only -> discontinued)
    # gets its provisional EAN corroborated by a weekly bdb lookup. The bdb member is
    # archived=False with a permanently-frozen missStreak, but it says nothing about liveness --
    # it must not make `live` non-empty and flip a 2016-delisted product back to current.
    members = [obs("arc-x:a", archived=True), obs("bdb-upcitemdb:a", missStreak=0)]
    product = resolve_attributes("e", members, KINDS, NO_EAN, None)
    assert product.status == "discontinued"


def test_curated_plus_barcode_db_only_entity_still_trusts_curated_status() -> None:
    # A legacy entity corroborated ONLY by a barcode-db EAN lookup (no live scraped source at
    # all) has an empty scraped_live (bdb is excluded, same as curated) -- this is the documented
    # consequence of the fix: it falls into the curated-only branch and trusts the curated claim,
    # exactly as a curated-only entity with no bdb member would. bdb never drives lifecycle on its
    # own, so its presence alongside a curated member changes nothing here.
    members = [obs("legacy-catalog:a", hints={"status": "current"}), obs("bdb-upcitemdb:a", missStreak=0)]
    product = resolve_attributes("e", members, KINDS, NO_EAN, None)
    assert product.status == "current"

    members_delisted = [obs("legacy-catalog:a", hints={"status": "delisted"}), obs("bdb-upcitemdb:a", missStreak=0)]
    product_delisted = resolve_attributes("e", members_delisted, KINDS, NO_EAN, None)
    assert product_delisted.status == "delisted"


def test_superseded_member_loses_within_kind_for_attributes() -> None:
    # A repackaging join folds an OLD product code's manufacturer observation (a stale price) into
    # the surviving entity alongside the CURRENT code's manufacturer observation. Within the
    # manufacturer kind the superseded old-packaging price must lose to the live price -- even
    # though the old observation's key sorts first. additionalEans flows through from the resolution.
    ean = EanResolution("5060924985581", "confirmed", [], ["5060469664330"])
    members = [
        obs("mfr-gw:0old", priceGbp=80.0, url="https://old"),   # superseded, sorts first by key
        obs("mfr-gw:1new", priceGbp=65.0, url="https://new"),   # surviving
    ]
    product = resolve_attributes("e", members, KINDS, ean, "NEW", superseded=frozenset({"mfr-gw:0old"}))
    assert product.priceGbp == 65.0
    assert product.url == "https://new"
    assert product.additionalEans == ["5060469664330"]


def test_no_supersession_keeps_within_kind_key_ordering_unchanged() -> None:
    # Without a superseded set the within-kind key order is unchanged: the key that sorts first
    # wins, exactly as before, and additionalEans is empty.
    ean = EanResolution("5060924985581", "confirmed", [])
    members = [obs("mfr-gw:0old", priceGbp=80.0), obs("mfr-gw:1new", priceGbp=65.0)]
    product = resolve_attributes("e", members, KINDS, ean, None)
    assert product.priceGbp == 80.0  # key "mfr-gw:0old" < "mfr-gw:1new"
    assert product.additionalEans == []


def test_sku_is_resolved_first_non_none() -> None:
    members = [
        obs("mfr-gw:necrons", sku=None),
        obs("ret-a:necrons", sku="GWS99120110077"),
    ]
    product = resolve_attributes("e", members, KINDS, NO_EAN, None)
    assert product.sku == "GWS99120110077"


def test_a_foreign_product_code_never_becomes_this_record_s_sku() -> None:
    """`sku` identifies the product; every other direct field only describes it. A supersession
    re-homes an observation onto the record its BARCODE scans as, having established that the SKU
    it kept is the other side's stale code -- so letting that member supply `sku` publishes
    `productCode: <retired>` beside `sku: <survivor>`, two different products in one record.

    The curated member here outranks the manufacturer, so this is not a tie-break: it must be an
    exclusion, and it must apply to `sku` alone -- the stale listing's name, price and image are
    still the best description of the retired box, which is why it was re-homed rather than dropped.
    """
    members = [
        obs("legacy-catalog:widget", sku="99120110002", priceGbp=20.5, url="https://legacy"),
        obs("mfr-gw:widget", sku="99120110001", priceGbp=18.0),
    ]
    codes = {"legacy-catalog:widget": "99120110002", "mfr-gw:widget": "99120110001"}

    product = resolve_attributes(
        "games-workshop/99120110001", members, KINDS, NO_EAN, "99120110001", member_codes=codes
    )
    assert product.sku == "99120110001"
    assert product.priceGbp == 20.5           # descriptive fields still come from the curated member
    assert product.url == "https://legacy"


def test_a_retailer_catalogue_number_is_not_a_foreign_code() -> None:
    # A retailer SKU that normalizes to NO product code makes no competing claim about the
    # manufacturer's numbering, so it stays eligible -- otherwise this rule would blank the `sku`
    # of the many records whose only SKU is a shop's own reference.
    members = [obs("ret-a:widget", sku="GWS94-22")]
    product = resolve_attributes(
        "games-workshop/99120110001", members, KINDS, NO_EAN, "99120110001",
        member_codes={"ret-a:widget": None},
    )
    assert product.sku == "GWS94-22"


def test_sku_eligibility_is_inert_without_member_codes() -> None:
    # The default call path (member_codes=None) must behave exactly as before this rule.
    members = [obs("legacy-catalog:widget", sku="99120110002"), obs("mfr-gw:widget", sku="99120110001")]
    product = resolve_attributes("e", members, KINDS, NO_EAN, "99120110001")
    assert product.sku == "99120110002"


# --- tradeCategory fallback classification (mfr-gw-trade China Order Form) ----------------------

TRADE_KINDS = {**KINDS, "mfr-gw-trade": "manufacturer"}
TRADE_MAPS = {
    "mfr-gw-trade": {
        "gameSystem": {"40K": "warhammer-40k", "AOS": "age-of-sigmar", "Necromunda": "other-games"},
        "faction": {
            "40K - Xenos - Aeldari": "aeldari",
            "AOS - Order - Stormcast Eternals": "grand-alliance-order",
            "Necromunda - Escher": "necromunda",
        },
    }
}


def test_trade_category_fills_null_game_system_and_faction() -> None:
    members = [obs("mfr-gw-trade:99120", hints={"tradeCategory": "40K - Xenos - Aeldari"})]
    product = resolve_attributes("e", members, TRADE_KINDS, NO_EAN, "99120", category_maps=TRADE_MAPS)
    assert product.gameSystem == "warhammer-40k"
    assert product.faction == "aeldari"


def test_trade_category_never_overrides_a_supplied_game_system() -> None:
    # A direct gameSystem hint from ANY source wins; the trade fallback only fills genuine nulls,
    # so it must not overwrite an existing classification even when its own mapping disagrees.
    members = [
        obs("mfr-gw:necrons", hints={"gameSystem": "warhammer-40k", "faction": "necrons"}),
        obs("mfr-gw-trade:99120", hints={"tradeCategory": "AOS - Order - Stormcast Eternals"}),
    ]
    product = resolve_attributes("e", members, TRADE_KINDS, NO_EAN, None, category_maps=TRADE_MAPS)
    assert product.gameSystem == "warhammer-40k"
    assert product.faction == "necrons"


def test_trade_category_system_only_when_faction_unmapped() -> None:
    # "40K - Generic" maps a system but no faction: classify the system, leave faction null
    # rather than guess.
    members = [obs("mfr-gw-trade:99120", hints={"tradeCategory": "40K - Generic"})]
    product = resolve_attributes("e", members, TRADE_KINDS, NO_EAN, "99120", category_maps=TRADE_MAPS)
    assert product.gameSystem == "warhammer-40k"
    assert product.faction is None


def test_trade_category_unmapped_prefix_classifies_nothing() -> None:
    # A paint/accessory/opaque bucket has no gameSystem prefix in the mapping -> stays null.
    for raw in ("Paint - WH Colour - Layer", "E:B200b", "Chaos Daemons - Khorne"):
        members = [obs("mfr-gw-trade:99120", hints={"tradeCategory": raw})]
        product = resolve_attributes("e", members, TRADE_KINDS, NO_EAN, "99120", category_maps=TRADE_MAPS)
        assert product.gameSystem is None, raw
        assert product.faction is None, raw


def test_trade_fallback_is_inert_without_category_maps() -> None:
    # The default call path (category_maps=None) must behave exactly as before this feature.
    members = [obs("mfr-gw-trade:99120", hints={"tradeCategory": "40K - Xenos - Aeldari"})]
    product = resolve_attributes("e", members, TRADE_KINDS, NO_EAN, "99120")
    assert product.gameSystem is None
    assert product.faction is None


def test_a_list_valued_hint_folds_first_wins_and_is_never_unioned() -> None:
    """`contentSkus` is the first LIST-valued member of `_HINT_FIELDS`, and the fold must take one
    source's list WHOLE rather than merging them.

    Two sources disagreeing about what is in a box is a conflict to surface, not an input to
    average: a union would assert a set neither source describes, and nothing downstream could
    tell afterwards which refs came from where. `_first` already does the right thing -- this pins
    it, so a well-meaning "merge the lists" change fails instead of silently fabricating contents.
    """
    from warhub_acquisition.resolve.attributes import _HINT_FIELDS

    assert "contentSkus" in _HINT_FIELDS

    manufacturer = obs("mfr-gw:box", hints={"contentSkus": ["A1", "A2"]})
    retailer = obs("ret-a:box", hints={"contentSkus": ["B1", "B2", "B3"]})

    product = resolve_attributes("e", [manufacturer, retailer], KINDS, NO_EAN, None)
    assert product.contentSkus == ["A1", "A2"], "the manufacturer's list must win WHOLE"

    # Sorting is by kind priority, so the same answer regardless of arrival order -- and in
    # particular the retailer's three refs never appear alongside the manufacturer's two.
    product = resolve_attributes("e", [retailer, manufacturer], KINDS, NO_EAN, None)
    assert product.contentSkus == ["A1", "A2"]


def test_a_product_with_no_contents_hint_states_nothing_rather_than_empty() -> None:
    """None, not `[]`. "The source said nothing about the contents" and "the source says this box
    is empty" are different claims, and every other hint field in `_HINT_FIELDS` is nullable for
    the same reason."""
    product = resolve_attributes("e", [obs("mfr-gw:a")], KINDS, NO_EAN, None)
    assert product.contentSkus is None


# --- contentSkus derived from the source's own prose (resolve/set_refs.py) ----------------------

QUICK_GEN = (
    "QUICK GEN colour set for painting WWII German soldiers.\n\nContains:\n\n"
    "- AK17071 GERMAN GREY\n- AK17072 FIELD GREY\n- AK17049 BLACK\n"
)


def test_contents_are_derived_from_a_description_when_no_source_states_them() -> None:
    """Only mfr-reaper hands us a contents array; every other brand writes the codes into its
    description. Deriving HERE -- not in the strategy, not in gen_set_contents.py -- is what puts
    the refs on the product record, which is the field
    test_set_contents.py::test_the_relation_covers_exactly_the_products_that_state_contents
    cross-checks the whole relation against.

    The 24 real cases come from `legacy-catalog` (kind: curated, strategy: none), a frozen import.
    No strategy change could ever have produced them, which is why the parse cannot live upstream.
    """
    product = resolve_attributes(
        "warlord-games/AK17501",
        [obs("legacy-catalog:a", hints={"description": QUICK_GEN})],
        KINDS, NO_EAN, "AK17501",
    )
    assert product.contentSkus == ["AK17071", "AK17072", "AK17049"]
    assert product.contentSkusFrom == "description"


def test_a_stated_contents_array_is_never_overridden_by_prose() -> None:
    """A machine-readable array is the stronger claim and is exhaustive by construction; a prose
    list is editorial and may be a lower bound. Prose must not be allowed to contradict it, and
    `contentSkusFrom` must keep saying which one a consumer is looking at."""
    product = resolve_attributes(
        "reaper/09901",
        [obs("mfr-gw:a", hints={"contentSkus": ["09030", "09031"], "description": QUICK_GEN})],
        KINDS, NO_EAN, None,
    )
    assert product.contentSkus == ["09030", "09031"]
    assert product.contentSkusFrom == "stated"


def test_a_description_stating_no_membership_leaves_contents_unset() -> None:
    """`None` reads as "no source said what is in this box", which is a different claim from "this
    box is empty". Measured 2026-08-07, 11,479 of the 11,503 committed descriptions land here."""
    product = resolve_attributes(
        "games-workshop/x",
        [obs("mfr-gw:a", hints={"description": "A single 18ml bottle of intense white."})],
        KINDS, NO_EAN, None,
    )
    assert product.contentSkus is None
    assert product.contentSkusFrom is None
