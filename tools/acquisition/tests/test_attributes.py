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
