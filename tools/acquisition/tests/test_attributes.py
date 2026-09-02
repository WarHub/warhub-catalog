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
    assert product.gameSystems == ["warhammer-40k"]
    assert product.category is None                      # nobody said, so there is none
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
    assert product.gameSystems == ["warhammer-40k"]
    assert product.faction == "aeldari"


def test_trade_category_never_overrides_a_supplied_game_system() -> None:
    # A direct gameSystem hint from ANY source wins; the trade fallback only fills genuine nulls,
    # so it must not overwrite an existing classification even when its own mapping disagrees.
    members = [
        obs("mfr-gw:necrons", hints={"gameSystem": "warhammer-40k", "faction": "necrons"}),
        obs("mfr-gw-trade:99120", hints={"tradeCategory": "AOS - Order - Stormcast Eternals"}),
    ]
    product = resolve_attributes("e", members, TRADE_KINDS, NO_EAN, None, category_maps=TRADE_MAPS)
    assert product.gameSystems == ["warhammer-40k"]
    assert product.faction == "necrons"


def test_trade_category_system_only_when_faction_unmapped() -> None:
    # "40K - Generic" maps a system but no faction: classify the system, leave faction null
    # rather than guess.
    members = [obs("mfr-gw-trade:99120", hints={"tradeCategory": "40K - Generic"})]
    product = resolve_attributes("e", members, TRADE_KINDS, NO_EAN, "99120", category_maps=TRADE_MAPS)
    assert product.gameSystems == ["warhammer-40k"]
    assert product.faction is None


def test_trade_category_unmapped_prefix_classifies_nothing() -> None:
    # A paint/accessory/opaque bucket has no gameSystem prefix in the mapping -> stays null.
    for raw in ("Paint - WH Colour - Layer", "E:B200b", "Chaos Daemons - Khorne"):
        members = [obs("mfr-gw-trade:99120", hints={"tradeCategory": raw})]
        product = resolve_attributes("e", members, TRADE_KINDS, NO_EAN, "99120", category_maps=TRADE_MAPS)
        assert product.gameSystems == [], raw
        assert product.faction is None, raw


def test_trade_fallback_is_inert_without_category_maps() -> None:
    # The default call path (category_maps=None) must behave exactly as before this feature.
    members = [obs("mfr-gw-trade:99120", hints={"tradeCategory": "40K - Xenos - Aeldari"})]
    product = resolve_attributes("e", members, TRADE_KINDS, NO_EAN, "99120")
    assert product.gameSystems == []
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


# --- gameSystems: the FOLD stays single-valued, and the reason is measured ----------------------
#
# `gameSystems` is a list because a product can belong to several games, but NOT because this fold
# ever produces several. Over all 19,904 observations that carry a `gameSystem` hint, zero carry
# more than one value: no source has ever asserted dual membership in that field. The list is
# filled to more than one element by `categorize`, from taxonomies that name games explicitly.


def test_the_fold_writes_at_most_one_system() -> None:
    product = resolve_attributes(
        "e", [obs("mfr-gw:b", hints={"gameSystem": "warhammer-40k"})], KINDS, NO_EAN, None,
    )
    assert product.gameSystems == ["warhammer-40k"]
    assert product.gameSystemsBasis == "stated"


def test_two_sources_disagreeing_is_not_merged_into_membership() -> None:
    """THE LINE BETWEEN A CLAIM AND A DISAGREEMENT. The kind ladder picks one voice; unioning
    would turn every disagreement into a membership."""
    product = resolve_attributes(
        "e",
        [obs("legacy-catalog:a", hints={"gameSystem": "bolt-action"}),
         obs("mfr-gw:b", hints={"gameSystem": "hail-caesar"})],
        KINDS, NO_EAN, None,
    )
    assert product.gameSystems == ["bolt-action"]


def test_one_sources_two_rows_are_not_a_joint_claim() -> None:
    """THE RULE THAT WAS TRIED AND MEASURED WRONG. Taking the winning source's whole claim across
    its rows looks like the honest reading of "legacy-catalog files Custodian Guard under both",
    and it produced 9 products of which 3 were false: `M24 Chaffee, US light tank` and
    `Germanic command` share EAN 5060200844311 on the Warlord store, so one entity holds both
    rows, and the WWII tank published as a Hail Caesar product. A source's rows disagreeing is a
    fact about the JOIN, not a claim about the product."""
    product = resolve_attributes(
        "e",
        [obs("mfr-warlord:tank", hints={"gameSystem": "bolt-action"}),
         obs("mfr-warlord:pikemen", hints={"gameSystem": "hail-caesar"})],
        {"mfr-warlord": "manufacturer"}, NO_EAN, None,
    )
    # ONE value, whichever the key tiebreak picks. The property is that the second row does not
    # join the first, not which of the two survives.
    assert product.gameSystems == ["hail-caesar"]


def test_the_winning_source_is_the_first_that_speaks_not_the_first_that_exists() -> None:
    """A curated member with no gameSystem at all does not veto the manufacturer's claim -- the
    ladder selects the highest-priority source that ASSERTS one."""
    product = resolve_attributes(
        "e",
        [obs("legacy-catalog:a"), obs("mfr-gw:b", hints={"gameSystem": "warhammer-40k"})],
        KINDS, NO_EAN, None,
    )
    assert product.gameSystems == ["warhammer-40k"]


def test_no_source_speaking_leaves_the_list_empty() -> None:
    product = resolve_attributes("e", [obs("ret-a:x")], KINDS, NO_EAN, None)
    assert product.gameSystems == []
    assert product.gameSystemsBasis is None    # `complete_game_systems_basis` settles it later


# --- categoryBasis: a category nothing asserted is absent ----------------------------------------
#
# `category` used to fall back to `miniatures` whenever no source spoke, so every product carried a
# value and a wrong one was invisible. It no longer does: absent is absent, and `unknown` says so.
# A source's declared FILL (`SourceDescriptor.defaultHints`) never enters the fold at all, which is
# the behaviour change these tests pin -- it used to be folded and then labelled `default`.

LEGACY_DEFAULTS = {"legacy-catalog": {"category": "miniatures"}}


def test_no_source_hint_leaves_the_category_absent() -> None:
    product = resolve_attributes("e", [obs("ret-a:x")], KINDS, NO_EAN, None)
    assert (product.category, product.categoryBasis) == (None, "unknown")


def test_a_real_source_claim_is_recorded_as_stated() -> None:
    product = resolve_attributes(
        "e", [obs("mfr-gw:x", hints={"category": "paint"})], KINDS, NO_EAN, None,
        default_hints=LEGACY_DEFAULTS,
    )
    assert (product.category, product.categoryBasis) == ("paint", "stated")


def test_a_declared_pipeline_fill_never_enters_the_fold() -> None:
    """`legacy-catalog` is `kind: curated` -- the TOP of KIND_PRIORITY -- and emits
    `category: miniatures` on 12,533 of its 12,799 observations. That is the old .NET pipeline's
    fill, not a claim about any product, so the record ends with NO category rather than with a
    plausible one nobody made."""
    product = resolve_attributes(
        "e", [obs("legacy-catalog:x", hints={"category": "miniatures"})], KINDS, NO_EAN, None,
        default_hints=LEGACY_DEFAULTS,
    )
    assert (product.category, product.categoryBasis) == (None, "unknown")


def test_a_fill_does_not_outrank_a_lower_ranked_source_claim() -> None:
    """WHAT SUPPRESSION BUYS THAT LABELLING DID NOT -- stated as a property, because its population
    is currently zero. legacy-catalog is `kind: curated` and outranks every manufacturer and
    retailer, so while its fill still folded it would have beaten a real claim underneath it.

    MEASURED 2026-09-01, and the honest number is 0: no product carries both legacy-catalog's
    `miniatures` fill and another source's category. 12,130 products have the fill and nothing
    else; the 1,986 with a real claim have no fill. So this fixes nothing in today's data and is
    kept as a REGRESSION guard -- the two populations overlap the moment any source this catalog
    already scrapes starts stating categories on rows legacy also holds, which is one descriptor
    edit away."""
    product = resolve_attributes(
        "e",
        [obs("legacy-catalog:x", hints={"category": "miniatures"}),
         obs("ret-a:x", hints={"category": "paint"})],
        KINDS, NO_EAN, None, default_hints=LEGACY_DEFAULTS,
    )
    assert (product.category, product.categoryBasis) == ("paint", "stated")


def test_the_same_source_stating_something_else_is_still_stated() -> None:
    """`defaultHints` names an exact VALUE, not a source. legacy-catalog's terrain/book/paint hints
    are real claims (148/99/19 observations) and must keep their standing -- only the `miniatures`
    fill is a placeholder."""
    product = resolve_attributes(
        "e", [obs("legacy-catalog:x", hints={"category": "terrain"})], KINDS, NO_EAN, None,
        default_hints=LEGACY_DEFAULTS,
    )
    assert (product.category, product.categoryBasis) == ("terrain", "stated")


def test_a_higher_priority_claim_beating_the_fill_is_stated() -> None:
    """The kind ladder is unchanged where two sources both make real claims: curated still wins."""
    product = resolve_attributes(
        "e",
        [obs("legacy-catalog:x", hints={"category": "book"}),
         obs("mfr-gw:x", hints={"category": "paint"})],
        KINDS, NO_EAN, None, default_hints=LEGACY_DEFAULTS,
    )
    assert (product.category, product.categoryBasis) == ("book", "stated")


def test_suppression_is_inert_without_declared_defaults() -> None:
    """Default call path unchanged: with no `defaultHints` every stated value reads `stated`. A
    source that declares nothing is unaffected by any of this."""
    product = resolve_attributes(
        "e", [obs("legacy-catalog:x", hints={"category": "miniatures"})], KINDS, NO_EAN, None,
    )
    assert (product.category, product.categoryBasis) == ("miniatures", "stated")


def test_a_declared_fill_is_suppressed_on_every_field_not_just_category() -> None:
    """`defaultHints` is a dict of field -> value and always was; the suppression is general, so a
    curated import that ships a blanket `packaging: single` gets the same treatment the day it
    declares it. Nothing in the resolver names `category`."""
    product = resolve_attributes(
        "e", [obs("legacy-catalog:x", hints={"packaging": "single", "category": "terrain"})],
        KINDS, NO_EAN, None,
        default_hints={"legacy-catalog": {"packaging": "single"}},
    )
    assert product.packaging is None
    assert (product.category, product.categoryBasis) == ("terrain", "stated")


# --- raw captured taxonomy must stay OUT of the fold ---------------------------------------------

RAW_CAPTURE_KEYS = ("productType", "tags", "vendor", "categories", "breadcrumbs", "hierarchy")


def test_raw_source_taxonomy_never_folds_into_a_published_field() -> None:
    """Capture adds evidence and changes no record. That is the whole acceptance property of the
    raw-taxonomy capture, and it holds only because `_HINT_FIELDS` is a fixed tuple that does not
    name any of these keys. If someone adds one to that tuple, ~40,000 observations start writing
    into published records the same day, silently.

    Verified end-to-end when the capture landed: re-resolving the nightly's tree with every one of
    these keys stamped on all 40,167 product-source observations produced 30,747 products before
    and after, 0 ids moved, and not one changed field.
    """
    from warhub_acquisition.resolve.attributes import _DIRECT_FIELDS, _HINT_FIELDS

    for key in RAW_CAPTURE_KEYS:
        assert key not in _HINT_FIELDS, (
            f"{key!r} is raw source taxonomy captured verbatim by the acquire strategies. Folding "
            f"it would publish a store's own private vocabulary as a catalog value -- it is input "
            f"to the categorize stage, not a catalog field."
        )
        assert key not in _DIRECT_FIELDS


def test_stamping_every_raw_key_on_a_member_changes_nothing_about_the_record() -> None:
    """The same property as a behaviour, not just a name check -- a future refactor could read
    hints somewhere other than `_HINT_FIELDS` and this would catch it."""
    plain = resolve_attributes("e", [obs("ret-a:x", hints={"category": "paint"})], KINDS, NO_EAN, None)
    noisy = resolve_attributes(
        "e",
        [obs("ret-a:x", hints={
            "category": "paint",
            "productType": "Paints & Hobby", "tags": ["citadel", "base"], "vendor": "Games Workshop",
            "categories": ["paints"], "breadcrumbs": ["Home", "Paints"],
            "hierarchy": {"lvl0": ["Warhammer 40,000"]},
        })],
        KINDS, NO_EAN, None,
    )
    assert noisy.model_dump() == plain.model_dump()


def test_crossover_reads_hints_so_capture_stays_off_the_paint_strategies() -> None:
    """A trap found while verifying the capture, recorded so the next person does not re-find it.

    `resolve/crossover.py::clause_matches` matches on `hints` -- `hintContainsAny` over `tags` and
    `hintEquals` over `productType` are exactly what the paint sources' `crossoverToProducts`
    blocks are written against. So adding a captured key to a `catalog: paints` strategy can change
    WHICH ROWS CROSS into the product catalog, i.e. can add or remove published products. Stamping
    fake `tags`/`productType` on every source (paint sources included) during verification moved
    the catalog by 3 added and 2 removed ids; restricting the stamp to `catalog: products` sources,
    which is what the changed strategies actually serve, moved nothing.

    The four strategies carrying raw capture today (shopify, woo-store-api, algolia,
    sitemap-structured-data) serve product sources ONLY -- the paint pipeline has its own
    `*_paints.py` variants. This test pins that separation.
    """
    from pathlib import Path

    import yaml

    sources_dir = Path(__file__).resolve().parents[3] / "data/catalog/sources"
    if not sources_dir.exists():
        pytest.skip("data/catalog/sources/ not present")
    capturing = {"shopify", "woo-store-api", "algolia", "sitemap-structured-data"}
    for path in sorted(sources_dir.glob("*.yaml")):
        descriptor = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if descriptor.get("strategy") in capturing:
            assert descriptor.get("catalog", "products") == "products", (
                f"{descriptor['id']} is a paint source on a raw-capturing strategy. Its captured "
                f"hints can be read by its own crossoverToProducts clauses, so the crossover set "
                f"must be re-measured before this is allowed."
            )


# --- staleFields: a source can be authoritative AND frozen ---------------------------------------
#
# `legacy-catalog` is kind: curated (KIND_PRIORITY 0, above manufacturer and retailer) and
# strategy: none -- never re-observed, so its stock and price values are whatever they were on
# import day. Measured 2026-08-21 over the 10,245 products where it meets a live source, that rank
# is right for some fields and wrong for others:
#
#   availability  1,205 overridden, 1,175 a stale in_stock beating a live out_of_stock -- WRONG
#   prices          386 overridden, a frozen RRP beating a live retail price          -- WRONG
#   name            981 overridden, legacy SHORTER in 733 (no store chrome)           -- BETTER
#   url             470 overridden, manufacturer page vs a retailer listing in 354    -- BETTER
#
# Hence per-field, not per-source. Demoting the whole source was measured too: it fixes
# availability and collaterally rewrites 981 names, 526 imageUrls and 470 urls.

STALE = {"legacy-catalog": ["availability", "priceGbp"]}


def test_a_stale_field_loses_to_a_live_source_whatever_the_kind_ladder_says() -> None:
    product = resolve_attributes(
        "e",
        [obs("legacy-catalog:x", availability="in_stock", priceGbp=108.0),
         obs("ret-a:x", availability="out_of_stock", priceGbp=91.8)],
        KINDS, NO_EAN, None, stale_fields=STALE,
    )
    assert product.availability == "out_of_stock"
    assert product.priceGbp == 91.8


def test_a_stale_field_still_fills_when_nothing_live_supplies_it() -> None:
    """DEMOTION, NOT EXCLUSION -- the distinction that keeps 231 availability and 1,714 priceUsd
    values the frozen import is the only source of. Verified on the real tree: 0 records lost
    either field."""
    product = resolve_attributes(
        "e",
        [obs("legacy-catalog:x", availability="in_stock", priceGbp=108.0), obs("ret-a:x")],
        KINDS, NO_EAN, None, stale_fields=STALE,
    )
    assert product.availability == "in_stock"
    assert product.priceGbp == 108.0


def test_fields_not_named_stale_keep_the_sources_curated_rank() -> None:
    """The whole point of doing this per field. `name` and `url` are BETTER off the curated import
    and must not move -- a blanket demotion would have taken 981 names and 470 urls with it."""
    product = resolve_attributes(
        "e",
        [obs("legacy-catalog:x", name="Black Panther and Killmonger",
             url="https://atomicmassgames.com/p", availability="in_stock"),
         obs("ret-a:x", name="Black Panther and Killmonger - Marvel Crisis Protocol",
             url="https://shop.example/listing", availability="out_of_stock")],
        KINDS, NO_EAN, None, stale_fields=STALE,
    )
    assert product.name == "Black Panther and Killmonger"       # curated rank intact
    assert product.url == "https://atomicmassgames.com/p"       # curated rank intact
    assert product.availability == "out_of_stock"               # only the stale field moved


def test_stale_fields_are_inert_when_nothing_declares_any() -> None:
    """Every other source declares none, so the fold they get is byte-identical to before."""
    members = [obs("legacy-catalog:x", availability="in_stock"), obs("ret-a:x", availability="out_of_stock")]
    assert resolve_attributes("e", members, KINDS, NO_EAN, None).availability == "in_stock"
    assert resolve_attributes("e", members, KINDS, NO_EAN, None, stale_fields={}).availability == "in_stock"


def test_a_stale_field_also_demotes_below_a_lower_ranked_kind() -> None:
    """Stale means LAST, not "one rung down" -- an archive observation is a better answer about
    current stock than a frozen import that predates it, even though archive ranks below curated."""
    product = resolve_attributes(
        "e",
        [obs("legacy-catalog:x", availability="in_stock"), obs("arc-x:x", availability="out_of_stock")],
        KINDS, NO_EAN, None, stale_fields=STALE,
    )
    assert product.availability == "out_of_stock"


def test_hint_fields_can_be_declared_stale_too() -> None:
    """The mechanism is field-name based and spans both `_DIRECT_FIELDS` and `_HINT_FIELDS`, so a
    future frozen source that ships a stale `description` can say so without new machinery."""
    product = resolve_attributes(
        "e",
        [obs("legacy-catalog:x", hints={"description": "old blurb"}),
         obs("ret-a:x", hints={"description": "current blurb"})],
        KINDS, NO_EAN, None, stale_fields={"legacy-catalog": ["description"]},
    )
    assert product.description == "current blurb"


# --- gameSystemsBasis -------------------------------------------------------------------------
#
# A null gameSystem was carrying two facts that need opposite responses: a hobby product that will
# never have one, and a game product nobody has classified. Only the second is a question.

from warhub_acquisition.resolve.attributes import (  # noqa: E402
    apply_classification,
    complete_membership_bases,
)
from warhub_acquisition.taxonomy import Settings  # noqa: E402

_LABELS = {"warhammer-40k": "Warhammer 40,000", "infinity": "Infinity", "bolt-action": "Bolt Action"}
_SETTINGS = Settings(
    {"warhammer-40k": "Warhammer 40,000", "world-war-two": "Second World War"},
    {"warhammer-40k": "warhammer-40k", "bolt-action": "world-war-two", "konflikt-47": "world-war-two"},
    settingless=frozenset({"epic-encounters"}),
)


def complete_game_systems_basis(product, labels):
    return complete_membership_bases(product, labels, _SETTINGS)


def _product(**kwargs) -> CanonicalProduct:
    base = dict(
        id="mfr/x", name="A Thing", manufacturer="mfr", status="current", firstSeen="2026-01-01"
    )
    return CanonicalProduct.model_validate({**base, **kwargs})


def test_a_hobby_product_with_no_game_system_is_not_applicable_rather_than_unknown() -> None:
    settled = complete_game_systems_basis(_product(name="Abaddon Black 12ml", category="paint"), _LABELS)
    assert settled.gameSystemsBasis == "not-applicable"


def test_a_game_product_with_no_game_system_stays_unknown() -> None:
    settled = complete_game_systems_basis(_product(name="Some Squad", category="miniatures"), _LABELS)
    assert settled.gameSystemsBasis == "unknown"


def test_the_predicate_can_never_erase_a_game_system_anything_established() -> None:
    """It is only ever consulted where gameSystem is ALREADY null, which is what makes it safe.

    The obvious formulation -- "category is paint, therefore no game system" -- is measurably
    wrong: 411 products carry both, and they are real.
    """
    themed = _product(name="Infinity: JSA Paint Set", category="paint-set", gameSystems=["infinity"],
                      gameSystemsBasis="stated")
    settled = complete_game_systems_basis(themed, _LABELS)
    assert (settled.gameSystems, settled.gameSystemsBasis) == (["infinity"], "stated")


def test_a_hobby_product_named_for_a_game_is_a_question_not_a_dismissal() -> None:
    # `Infinity: JSA Paint Set` with no stated system must not be written off as not-applicable --
    # it is a themed boxed product and somebody should decide.
    settled = complete_game_systems_basis(_product(name="Infinity: JSA Paint Set", category="paint-set"), _LABELS)
    assert settled.gameSystemsBasis == "unknown"


def test_a_colour_named_after_a_faction_is_still_a_colour() -> None:
    """The one judgement in the predicate. `CONTRAST: BLACK LEGION (18ML)` names a 40k faction and
    is a pot of paint; a prior classification wave called 34 near-identical records 40k products."""
    for name in (
        "Warhammer 40,000 Contrast Paint 18ml",
        "SQUIG ORANGE (6-PACK) 12ML Warhammer 40,000",
        "Warhammer 40,000 Spray",
    ):
        settled = complete_game_systems_basis(_product(name=name, category="paint"), _LABELS)
        assert settled.gameSystemsBasis == "not-applicable", name


def test_a_classification_fills_a_hole_and_can_never_overrule_a_source() -> None:
    decisions = {"mfr/x": {"gameSystem": "warhammer-40k", "faction": None}}

    stated = _product(gameSystems=["bolt-action"], gameSystemsBasis="stated")
    assert apply_classification(stated, decisions).gameSystems == ["bolt-action"]

    empty = _product()
    filled = apply_classification(empty, decisions)
    assert (filled.gameSystems, filled.gameSystemsBasis) == (["warhammer-40k"], "classified")


# --- settings: the layer above the game --------------------------------------------------------


def test_a_products_settings_derive_from_its_games() -> None:
    """Two WWII games, one setting: the union of what each game names, without duplicates."""
    product = _product(gameSystems=["bolt-action", "konflikt-47"], gameSystemsBasis="stated")
    settled = complete_membership_bases(product, _LABELS, _SETTINGS)
    assert (settled.settings, settled.settingsBasis) == (["world-war-two"], "derived")
    assert settled.gameSystemsBasis == "stated"


def test_a_game_the_taxonomy_places_in_no_setting_leaves_the_settings_unknown() -> None:
    product = _product(gameSystems=["infinity"], gameSystemsBasis="stated")
    settled = complete_membership_bases(product, _LABELS, _SETTINGS)
    assert (settled.settings, settled.settingsBasis) == ([], "unknown")


def test_a_game_declared_settingless_is_not_applicable_rather_than_unknown() -> None:
    """A 5e-compatible encounter box is played in whatever campaign the buyer runs: no universe,
    and nothing missing."""
    product = _product(gameSystems=["epic-encounters"], gameSystemsBasis="stated")
    settled = complete_membership_bases(product, _LABELS, _SETTINGS)
    assert (settled.settings, settled.settingsBasis) == ([], "not-applicable")


def test_a_product_placed_in_a_setting_but_no_game_says_so_on_the_game_axis() -> None:
    """A Black Library novel: a rule placed it in Warhammer 40,000, nothing placed it in a game,
    and that is not a hole -- `setting` on the game axis is the positive statement."""
    product = _product(name="Horus Rising", category="book",
                       settings=["warhammer-40k"], settingsBasis="code")
    settled = complete_membership_bases(product, _LABELS, _SETTINGS)
    assert settled.gameSystemsBasis == "setting"
    assert (settled.settings, settled.settingsBasis) == (["warhammer-40k"], "code")


def test_a_hand_override_of_the_settings_is_never_re_derived() -> None:
    product = _product(gameSystems=["bolt-action"], gameSystemsBasis="stated",
                       settings=["warhammer-40k"], settingsBasis="override")
    settled = complete_membership_bases(product, _LABELS, _SETTINGS)
    assert settled.settings == ["warhammer-40k"]


def test_a_hobby_product_is_not_applicable_on_both_axes() -> None:
    settled = complete_membership_bases(_product(name="Abaddon Black 12ml", category="paint"), _LABELS, _SETTINGS)
    assert (settled.gameSystemsBasis, settled.settingsBasis) == ("not-applicable", "not-applicable")


def test_overriding_the_settings_marks_the_basis() -> None:
    overrides = Overrides.model_validate({"products": {"mfr/x": {"settings": ["warhammer-40k"]}}})
    after = apply_overrides(_product(), overrides)
    assert (after.settings, after.settingsBasis) == (["warhammer-40k"], "override")


def test_a_generic_verdict_survives_the_membership_completion() -> None:
    """The categorize stage marks a TerrainCrate kit `not-applicable` because Mantic's own shelf
    says it belongs to no game; the completion predicate, which only guesses from the category,
    must keep that verdict rather than downgrade it to `unknown` -- while still saying `unknown`
    where nothing spoke."""
    from warhub_acquisition.models.catalog import CanonicalProduct
    from warhub_acquisition.resolve.attributes import complete_membership_bases
    from warhub_acquisition.taxonomy import Settings

    settings = Settings({}, {}, frozenset())
    verdict = CanonicalProduct(
        id="mantic-games/MGSS304", name="Sci-Fi Terrain: Furniture", manufacturer="mantic-games",
        status="current", firstSeen="2026-07-01",
        category="terrain", gameSystemsBasis="not-applicable", settingsBasis="not-applicable",
    )
    kept = complete_membership_bases(verdict, {}, settings)
    assert (kept.gameSystemsBasis, kept.settingsBasis) == ("not-applicable", "not-applicable")
    silent = complete_membership_bases(verdict.model_copy(update={"gameSystemsBasis": "unknown", "settingsBasis": "unknown"}), {}, settings)
    assert (silent.gameSystemsBasis, silent.settingsBasis) == ("unknown", "unknown")


def test_an_override_of_the_category_stamps_its_basis() -> None:
    from warhub_acquisition.models.catalog import CanonicalProduct, Overrides
    from warhub_acquisition.resolve.attributes import apply_overrides

    product = CanonicalProduct(id="vallejo/28890", name="Brush Restorer", manufacturer="vallejo",
                               status="current", firstSeen="2026-07-01", category="paint", categoryBasis="mapped")
    patched = apply_overrides(product, Overrides(products={"vallejo/28890": {"category": "hobby-auxiliary"}}))
    assert (patched.category, patched.categoryBasis) == ("hobby-auxiliary", "override")
