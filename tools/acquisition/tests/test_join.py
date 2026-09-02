# tools/acquisition/tests/test_join.py
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.join import Matches, join_observations
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

TAXONOMY = Taxonomy(
    {
        "games-workshop": Manufacturer(
            slug="games-workshop", name="Games Workshop", codePattern=r"\d{11}", codeStrip=["GWS"]
        )
    }
)
KINDS = {
    "legacy": "curated",
    "mfr-gw": "manufacturer",
    "ret-goblin": "retailer",
    "ret-radaddel": "retailer",
}


def obs(key: str, **kw: object) -> Observation:
    base: dict[str, object] = {
        "key": key,
        "name": "Combat Patrol: Necrons",
        "manufacturer": "games-workshop",
        "firstSeen": "2026-07-12",
        "lastSeen": "2026-07-12",
        "extractor": "test@1",
    }
    base.update(kw)
    return Observation(**base)


def test_reassign_code_splits_a_retailer_miscode_bridge() -> None:
    # A retailer listed the single "Zodgrod" miniature under the ARMY SET's code while carrying
    # Zodgrod's EAN -- bridging the army set into the Zodgrod entity (miscode code + shared EAN).
    # reassignCodes corrects that one observation's code so the army set splits back out.
    members = [
        obs("mfr-gw:zodgrod", sku="99120103074", ean="5011921128327", name="Zodgrod Wortsnagga"),
        obs("mfr-gw:army-set", sku="60010103001", ean="5011921138395", name="Beast Snagga Army Set"),
        # the bridging retailer listing: army-set code, but Zodgrod's name + EAN
        obs("ret-goblin:zodgrod", sku="60010103001", ean="5011921128327", name="Zodgrod Wortsnagga"),
    ]
    # Without the correction, all three collapse into one entity (bad bridge).
    bridged = join_observations(members, TAXONOMY, KINDS, Matches())
    assert len(bridged.entities) == 1

    fixed = join_observations(
        members, TAXONOMY, KINDS,
        Matches(reassignCodes={"ret-goblin:zodgrod": "99120103074"}),
    )
    assert set(fixed.entities) == {"games-workshop/99120103074", "games-workshop/60010103001"}
    # the army set is now alone; Zodgrod has its own listing + the corrected retailer one
    assert len(fixed.entities["games-workshop/60010103001"]) == 1
    assert len(fixed.entities["games-workshop/99120103074"]) == 2


def test_join_by_normalized_code() -> None:
    result = join_observations(
        [obs("mfr-gw:necrons", sku="99120110077"), obs("ret-goblin:cp-necrons", sku="GWS99120110077")],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]
    assert len(result.entities["games-workshop/99120110077"]) == 2


def test_join_by_ean_without_code() -> None:
    result = join_observations(
        [
            obs("mfr-gw:necrons", sku="99120110077", ean="5011921194285"),
            obs("ret-radaddel:necrons-combat-patrol", name="Necrons Combat Patrol", ean="5011921194285"),
        ],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]


def test_name_join_when_unambiguous() -> None:
    result = join_observations(
        [obs("mfr-gw:necrons", sku="99120110077"), obs("ret-goblin:x", sku=None)],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]


def test_name_join_ambiguous_stays_separate_and_reported() -> None:
    result = join_observations(
        [
            obs("mfr-gw:a", sku="99120110077"),
            obs("mfr-gw:b", sku="99120110078"),  # two entities, same name
            obs("ret-goblin:x", sku=None),
        ],
        TAXONOMY, KINDS, Matches(),
    )
    assert "games-workshop/combat-patrol-necrons" in result.entities
    assert result.ambiguous and result.ambiguous[0]["type"] == "ambiguous-join"


def test_matches_joins_force_assignment() -> None:
    matches = Matches(joins={"ret-goblin:x": "games-workshop/99120110077"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("mfr-gw:b", sku="99120110078"), obs("ret-goblin:x", sku=None)],
        TAXONOMY, KINDS, matches,
    )
    assert len(result.entities["games-workshop/99120110077"]) == 2
    assert not result.ambiguous


def test_alias_remaps_entity_id() -> None:
    matches = Matches(aliases={"games-workshop/combat-patrol-necrons": "games-workshop/99120110077"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("ret-goblin:x", sku=None, name="Combat patrol: necrons (NEW)")],
        TAXONOMY, KINDS, matches,
    )
    # slug differs -> own entity "...-new"; alias only remaps exact ids
    assert "games-workshop/combat-patrol-necrons-new" in result.entities


def test_deterministic_ordering() -> None:
    observations = [obs("ret-goblin:b", sku="99120110078"), obs("mfr-gw:a", sku="99120110077")]
    first = join_observations(list(observations), TAXONOMY, KINDS, Matches())
    second = join_observations(list(reversed(observations)), TAXONOMY, KINDS, Matches())
    assert list(first.entities) == list(second.entities) == [
        "games-workshop/99120110077",
        "games-workshop/99120110078",
    ]


def test_degenerate_name_is_excluded_and_reported() -> None:
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("ret-goblin:x", sku=None, name="!!!")],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]
    assert {"type": "degenerate-name", "key": "ret-goblin:x", "name": "!!!"} in result.ambiguous


def test_same_slug_anchorless_groups_merge() -> None:
    result = join_observations(
        [obs("ret-goblin:x", sku=None), obs("ret-radaddel:y", sku=None)],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/combat-patrol-necrons"]
    assert [m.key for m in result.entities["games-workshop/combat-patrol-necrons"]] == ["ret-goblin:x", "ret-radaddel:y"]
    assert result.ambiguous == []


def test_alias_merge_combines_observations() -> None:
    matches = Matches(aliases={"games-workshop/99120110078": "games-workshop/99120110077"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("mfr-gw:b", sku="99120110078", name="Other Name")],
        TAXONOMY, KINDS, matches,
    )
    assert list(result.entities) == ["games-workshop/99120110077"]
    assert sorted(m.key for m in result.entities["games-workshop/99120110077"]) == ["mfr-gw:a", "mfr-gw:b"]


def test_unresolved_forced_join_reported_and_name_join_falls_back() -> None:
    matches = Matches(joins={"ret-goblin:x": "games-workshop/nonexistent"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("ret-goblin:x", sku=None)],
        TAXONOMY, KINDS, matches,
    )
    assert list(result.entities) == ["games-workshop/99120110077"]  # name-join still works
    assert {"type": "unresolved-forced-join", "key": "ret-goblin:x", "target": "games-workshop/nonexistent"} in result.ambiguous


def test_forced_join_target_resolved_through_alias() -> None:
    matches = Matches(
        joins={"ret-goblin:x": "games-workshop/old-id"},
        aliases={"games-workshop/old-id": "games-workshop/99120110077"},
    )
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("mfr-gw:b", sku="99120110078"), obs("ret-goblin:x", sku=None)],
        TAXONOMY, KINDS, matches,
    )
    assert sorted(m.key for m in result.entities["games-workshop/99120110077"]) == ["mfr-gw:a", "ret-goblin:x"]
    assert result.ambiguous == []


def test_shared_ean_across_manufacturers_does_not_merge() -> None:
    taxonomy = Taxonomy(
        {
            "games-workshop": Manufacturer(slug="games-workshop", name="Games Workshop", codePattern=r"\d{11}"),
            "wyrd-games": Manufacturer(slug="wyrd-games", name="Wyrd Games", codePattern=r"WYR\d+"),
        }
    )
    result = join_observations(
        [
            obs("mfr-gw:a", sku="99120110077", ean="5011921194285"),
            obs("ret-x:b", manufacturer="wyrd-games", name="Other Thing", sku=None, ean="5011921194285"),
        ],
        taxonomy, {**KINDS, "ret-x": "retailer"}, Matches(),
    )
    assert "games-workshop/99120110077" in result.entities
    assert "wyrd-games/other-thing" in result.entities
    assert {"type": "cross-manufacturer-ean", "ean": "5011921194285",
            "keys": ["mfr-gw:a", "ret-x:b"]} in result.ambiguous


def test_shared_ean_same_manufacturer_still_merges() -> None:
    result = join_observations(
        [
            obs("mfr-gw:a", sku="99120110077", ean="5011921194285"),
            obs("ret-goblin:x", sku=None, name="Different Listing Name", ean="5011921194285"),
        ],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]


def test_cross_manufacturer_ean_keys_include_all_owner_observations() -> None:
    # Owner manufacturer (games-workshop) asserts the EAN via TWO observations (which union
    # with each other as today, via the ean anchor); a second manufacturer (wyrd-games)
    # asserts the same EAN. The payload's "keys" must list all three asserting keys, not just
    # the owner's anchor key.
    taxonomy = Taxonomy(
        {
            "games-workshop": Manufacturer(slug="games-workshop", name="Games Workshop", codePattern=r"\d{11}"),
            "wyrd-games": Manufacturer(slug="wyrd-games", name="Wyrd Games", codePattern=r"WYR\d+"),
        }
    )
    result = join_observations(
        [
            obs("mfr-gw:a", sku="99120110077", ean="5011921194285"),
            obs("ret-goblin:x", sku=None, name="Different Listing Name", ean="5011921194285"),
            obs("ret-x:b", manufacturer="wyrd-games", name="Other Thing", sku=None, ean="5011921194285"),
        ],
        taxonomy, {**KINDS, "ret-x": "retailer"}, Matches(),
    )
    assert sorted(m.key for m in result.entities["games-workshop/99120110077"]) == ["mfr-gw:a", "ret-goblin:x"]
    assert [m.key for m in result.entities["wyrd-games/other-thing"]] == ["ret-x:b"]
    assert {
        "type": "cross-manufacturer-ean",
        "ean": "5011921194285",
        "keys": ["mfr-gw:a", "ret-goblin:x", "ret-x:b"],
    } in result.ambiguous


def test_barcode_db_joins_when_ean_matches_existing_entity() -> None:
    kinds = {**KINDS, "db-upc": "barcode-db"}
    result = join_observations(
        [
            obs("mfr-gw:a", sku="99120110077", ean="5011921194285"),
            obs("db-upc:x", sku=None, ean="5011921194285", name="DB-sourced title"),
        ],
        TAXONOMY, kinds, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]
    assert [m.key for m in result.entities["games-workshop/99120110077"]] == ["mfr-gw:a", "db-upc:x"]
    assert result.ambiguous == []


def test_barcode_db_unjoined_ean_is_dropped_not_name_joined() -> None:
    """A barcode-db observation whose ean matches no OTHER source's assertion for this
    manufacturer must never mint (or name-join into) an entity -- it is dropped and reported.
    Structurally this should never happen in production (the strategy only ever emits eans read
    straight from an existing catalog entity), but join.py enforces it defensively anyway."""
    kinds = {**KINDS, "db-upc": "barcode-db"}
    result = join_observations(
        [obs("db-upc:orphan", sku=None, ean="5011921194285", name="Combat Patrol: Necrons")],
        TAXONOMY, kinds, Matches(),
    )
    assert result.entities == {}
    assert result.ambiguous == [
        {
            "type": "barcode-db-unjoined",
            "key": "db-upc:orphan",
            "name": "Combat Patrol: Necrons",
            "ean": "5011921194285",
        }
    ]


def test_barcode_db_unjoined_no_ean_at_all_is_also_dropped() -> None:
    kinds = {**KINDS, "db-upc": "barcode-db"}
    result = join_observations(
        [obs("db-upc:orphan", sku=None, ean=None, name="Combat Patrol: Necrons")],
        TAXONOMY, kinds, Matches(),
    )
    assert result.entities == {}
    assert {"type": "barcode-db-unjoined", "key": "db-upc:orphan", "name": "Combat Patrol: Necrons", "ean": None} in result.ambiguous


def test_two_barcode_dbs_alone_never_join_or_mint_an_entity() -> None:
    """Two barcode-db observations sharing an ean, with no other (non-barcode-db) source
    asserting it, must NOT join each other into a new entity -- corroboration requires at least
    one non-barcode-db source (see resolve/corroborate.py), and join.py must not silently create
    an entity the confidence rule would then refuse to confirm."""
    kinds = {**KINDS, "db-upc": "barcode-db", "db-goupc": "barcode-db"}
    result = join_observations(
        [
            obs("db-upc:x", sku=None, ean="5011921194285", name="Combat Patrol: Necrons"),
            obs("db-goupc:y", sku=None, ean="5011921194285", name="Combat Patrol: Necrons"),
        ],
        TAXONOMY, kinds, Matches(),
    )
    assert result.entities == {}
    assert {t["key"] for t in result.ambiguous} == {"db-upc:x", "db-goupc:y"}
    assert all(t["type"] == "barcode-db-unjoined" for t in result.ambiguous)


def test_barcode_db_forced_join_bypasses_unjoined_guard() -> None:
    matches = Matches(joins={"db-upc:x": "games-workshop/99120110077"})
    kinds = {**KINDS, "db-upc": "barcode-db"}
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("db-upc:x", sku=None, name="Some DB Title")],
        TAXONOMY, kinds, matches,
    )
    assert [m.key for m in result.entities["games-workshop/99120110077"]] == ["mfr-gw:a", "db-upc:x"]
    assert result.ambiguous == []


def test_degenerate_name_forced_join_still_works() -> None:
    matches = Matches(joins={"ret-goblin:x": "games-workshop/99120110077"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("ret-goblin:x", sku=None, name="!!!")],
        TAXONOMY, KINDS, matches,
    )
    assert [m.key for m in result.entities["games-workshop/99120110077"]] == ["mfr-gw:a", "ret-goblin:x"]
    assert result.ambiguous == []


# --- declared supersessions: two product codes, one product, BOTH records kept ------------------

SUPERSESSION = {"games-workshop/99120110001": "games-workshop/99120110002"}
OLD_EAN = "5011921062164"   # the retired packaging's barcode
NEW_EAN = "5011921179398"   # the current packaging's barcode


def test_supersession_rehomes_a_stale_code_bridge_and_keeps_both_records() -> None:
    """The measured shape of every GW repackaging pair: a retailer still lists the RETIRED product
    code while carrying the CURRENT barcode. That one observation ean-unions the two codes into a
    single entity, destroying the retired record. Declaring the supersession must split them --
    and the bridge belongs to the record whose barcode it scans as, not the stale SKU it kept."""
    members = [
        obs("mfr-gw:old", sku="99120110001", ean=OLD_EAN, name="Widget", archived=True),
        obs("mfr-gw:new", sku="99120110002", ean=NEW_EAN, name="Widget"),
        obs("ret-goblin:widget", sku="99120110001", ean=NEW_EAN, name="Widget"),
    ]
    merged = join_observations(members, TAXONOMY, KINDS, Matches())
    assert list(merged.entities) == ["games-workshop/99120110002"]  # today: the retired code is gone

    split = join_observations(members, TAXONOMY, KINDS, Matches(supersessions=SUPERSESSION))
    assert set(split.entities) == {"games-workshop/99120110001", "games-workshop/99120110002"}
    assert [m.key for m in split.entities["games-workshop/99120110001"]] == ["mfr-gw:old"]
    assert [m.key for m in split.entities["games-workshop/99120110002"]] == [
        "mfr-gw:new",
        "ret-goblin:widget",
    ]
    assert [c for c in split.ambiguous if c["type"] == "supersession-stale-code"] == [
        {
            "type": "supersession-stale-code",
            "key": "ret-goblin:widget",
            "ean": NEW_EAN,
            "listed_code": "99120110001",
            "barcode_code": "99120110002",
            "manufacturer": "games-workshop",
        }
    ]


def test_supersession_barrier_blocks_a_merge_it_cannot_re_home() -> None:
    """Neither side's MANUFACTURER asserts the contested barcode, so no side owns it and the
    bridging observations cannot be re-homed. The barrier itself then has to stop the ean-union --
    without it a single shared barcode silently re-merges a declared pair."""
    members = [
        obs("mfr-gw:old", sku="99120110001", name="Widget"),
        obs("mfr-gw:new", sku="99120110002", name="Widget"),
        obs("ret-goblin:old", sku="99120110001", ean=NEW_EAN, name="Widget"),
        obs("ret-radaddel:new", sku="99120110002", ean=NEW_EAN, name="Widget"),
    ]
    assert len(join_observations(members, TAXONOMY, KINDS, Matches()).entities) == 1

    split = join_observations(members, TAXONOMY, KINDS, Matches(supersessions=SUPERSESSION))
    assert set(split.entities) == {"games-workshop/99120110001", "games-workshop/99120110002"}
    assert [c for c in split.ambiguous if c["type"] == "supersession-blocked-merge"] == [
        {
            "type": "supersession-blocked-merge",
            "retired": "games-workshop/99120110001",
            "surviving": "games-workshop/99120110002",
            "keys": ["ret-goblin:old", "ret-radaddel:new"],
        }
    ]


def test_a_rehomed_bridge_cannot_name_the_group_it_was_rehomed_into() -> None:
    """The bridge here is `curated`, which OUTRANKS the manufacturer on the kind ladder that names
    a group. Its SKU is the surviving code and has just been declared stale -- so if the re-homing
    only hides that code from the UNIONS, the retired component is built correctly and then named
    after the survivor anyway. Both components then resolve to the same id and the final id-keyed
    merge folds them straight back together, which reports the pair as `unresolved-supersession`:
    the split is undone by the very step meant to publish it.

    Measured on the live data (2026-07-30) for Mortisan Boneshaper and Boingrot Bounderz, whose
    bridge is `legacy-catalog`. The pairs declared before them escaped only because their bridge
    happened to be a `retailer`, which loses that rank to the manufacturer's own retired code.
    """
    members = [
        obs("mfr-gw:old", sku="99120110001", ean=OLD_EAN, name="Widget"),
        obs("mfr-gw:new", sku="99120110002", ean=NEW_EAN, name="Widget"),
        # curated, so it wins every kind-ranked choice -- including which code names the group
        obs("legacy:widget", sku="99120110002", ean=OLD_EAN, name="Widget"),
    ]
    split = join_observations(members, TAXONOMY, KINDS, Matches(supersessions=SUPERSESSION))

    assert set(split.entities) == {"games-workshop/99120110001", "games-workshop/99120110002"}
    # the bridge scans as the OLD barcode, so it belongs to the retired record
    assert [m.key for m in split.entities["games-workshop/99120110001"]] == [
        "legacy:widget",
        "mfr-gw:old",
    ]
    assert [m.key for m in split.entities["games-workshop/99120110002"]] == ["mfr-gw:new"]
    assert [c["type"] for c in split.ambiguous] == ["supersession-stale-code"]


def test_forced_join_cannot_collapse_a_declared_supersession() -> None:
    # Contradictory hand instructions: the supersession wins and the join is reported unresolved.
    result = join_observations(
        [obs("mfr-gw:old", sku="99120110001", name="Widget"), obs("mfr-gw:new", sku="99120110002", name="Widget")],
        TAXONOMY, KINDS,
        Matches(joins={"mfr-gw:old": "games-workshop/99120110002"}, supersessions=SUPERSESSION),
    )
    assert set(result.entities) == {"games-workshop/99120110001", "games-workshop/99120110002"}
    assert {
        "type": "unresolved-forced-join",
        "key": "mfr-gw:old",
        "target": "games-workshop/99120110002",
    } in result.ambiguous


def test_supersession_naming_no_resolved_entity_is_reported() -> None:
    # Entity ids fall back to name slugs, so a typo (or a code that stopped being observed) would
    # otherwise publish a link pointing at nothing.
    result = join_observations(
        [obs("mfr-gw:new", sku="99120110002", name="Widget")],
        TAXONOMY, KINDS, Matches(supersessions=SUPERSESSION),
    )
    assert [c for c in result.ambiguous if c["type"] == "unresolved-supersession"] == [
        {
            "type": "unresolved-supersession",
            "retired": "games-workshop/99120110001",
            "surviving": "games-workshop/99120110002",
            "missing": ["games-workshop/99120110001"],
        }
    ]


def test_sku_is_listing_id_reattaches_a_source_that_re_keyed_itself() -> None:
    # A source that changes strategy re-keys every listing it has -- a sitemap path becomes a
    # shopify handle -- and nothing prunes the old generation, so the store is in the ledger twice.
    # The newer copy typically has no barcode yet (the shopify budget rations the detail fetch), so
    # it is anchorless and founds an entity named after the shop's own title. The store's own
    # article number is the identity that survives the re-key.
    members = [
        obs("mfr-gw:kit", sku="99120101234", ean="5011921000012", name="A Kit"),
        obs("ret-radaddel:/a-kit", sku="119157", ean="5011921000012", name="A Kit"),
        obs("ret-radaddel:a-kit", sku="119157", name="A Kit von Games Workshop"),
    ]
    result = join_observations(members, TAXONOMY, KINDS, Matches(), {"ret-radaddel": True})
    assert list(result.entities) == ["games-workshop/99120101234"]
    assert not result.ambiguous

    # Without the declaration the anchorless row stays its own name-slug entity.
    off = join_observations(members, TAXONOMY, KINDS, Matches())
    assert sorted(off.entities) == [
        "games-workshop/99120101234",
        "games-workshop/a-kit-von-games-workshop",
    ]


def test_sku_group_disagreeing_on_the_barcode_is_reported_not_joined() -> None:
    # A store that recycles an article number across products is not one listing, and unioning it
    # would fabricate a product. The guard runs per group on every resolve rather than trusting the
    # descriptor's claim.
    members = [
        obs("ret-radaddel:/first", sku="119157", ean="5011921000012", name="First"),
        obs("ret-radaddel:second", sku="119157", ean="5011921000036", name="Second"),
    ]
    result = join_observations(members, TAXONOMY, KINDS, Matches(), {"ret-radaddel": True})
    assert sorted(result.entities) == ["games-workshop/first", "games-workshop/second"]
    assert result.ambiguous == [
        {
            "type": "sku-group-ean-conflict",
            "source": "ret-radaddel",
            "sku": "119157",
            "keys": ["ret-radaddel:/first", "ret-radaddel:second"],
            "eans": ["5011921000012", "5011921000036"],
        }
    ]


def test_sku_grouping_never_reaches_across_sources() -> None:
    # Two stores using the same house number for different things is the normal case, not a claim.
    members = [
        obs("ret-radaddel:a", sku="119157", name="A Thing"),
        obs("ret-goblin:b", sku="119157", name="Another Thing"),
    ]
    result = join_observations(
        members, TAXONOMY, KINDS, Matches(), {"ret-radaddel": True, "ret-goblin": True}
    )
    assert sorted(result.entities) == ["games-workshop/a-thing", "games-workshop/another-thing"]
    assert not result.ambiguous


def test_sku_grouping_cannot_re_merge_a_declared_supersession() -> None:
    # A declared pair is bridged by a store listing both sides under ONE article number. The two
    # sides have different barcodes by definition, so the group's own barcode guard refuses it
    # before the union barrier is ever consulted -- which is why that barrier has never fired on
    # this pass. Both are kept: the guard is what makes the claim `skuIsListingId` makes checkable,
    # and routing the union through `barred` costs nothing if a future group reaches it another way.
    matches = Matches(supersessions={"games-workshop/99120101234": "games-workshop/99120105678"})
    members = [
        obs("mfr-gw:retired", sku="99120101234", ean="5011921000012", name="Old Kit"),
        obs("mfr-gw:current", sku="99120105678", ean="5011921000036", name="Old Kit"),
        obs("ret-radaddel:/bridge", sku="119157", ean="5011921000012", name="Old Kit"),
        obs("ret-radaddel:bridge", sku="119157", ean="5011921000036", name="Old Kit"),
    ]
    result = join_observations(members, TAXONOMY, KINDS, matches, {"ret-radaddel": True})
    assert "games-workshop/99120101234" in result.entities
    assert "games-workshop/99120105678" in result.entities
    assert [c["type"] for c in result.ambiguous] == ["sku-group-ean-conflict"]


def test_reassign_manufacturer_moves_a_reseller_row_to_the_real_maker() -> None:
    # A store's catalogue filed someone else's accessory under the store's own brand. Both sides
    # already exist, each holding the same barcode, so the catalog publishes the item twice and
    # reports a cross-manufacturer-ean it cannot resolve on its own.
    kinds = {**KINDS, "legacy": "curated", "mfr-ak": "manufacturer"}
    taxonomy = Taxonomy(
        {
            "warlord-games": Manufacturer(
                slug="warlord-games", name="Warlord Games", codePattern=r"[A-Z0-9]{6,}"
            ),
            "ak-interactive": Manufacturer(
                slug="ak-interactive", name="AK Interactive", codePattern=r"AK\d{2,5}"
            ),
        }
    )
    members = [
        obs("legacy:varnish", sku="AK11237", ean="5011921000012", manufacturer="warlord-games"),
        obs("mfr-ak:varnish", sku="AK11237", ean="5011921000012", manufacturer="ak-interactive"),
    ]
    before = join_observations(members, taxonomy, kinds, Matches())
    assert sorted(before.entities) == ["ak-interactive/AK11237", "warlord-games/AK11237"]
    assert [c["type"] for c in before.ambiguous] == ["cross-manufacturer-ean"]

    after = join_observations(
        members,
        taxonomy,
        kinds,
        Matches(reassignManufacturer={"legacy:varnish": "ak-interactive"}),
    )
    assert list(after.entities) == ["ak-interactive/AK11237"]
    assert not after.ambiguous


RESELLER_TAXONOMY = Taxonomy(
    {
        "warlord-games": Manufacturer(
            slug="warlord-games", name="Warlord Games", codePattern=r"[A-Z0-9]{6,}"
        ),
        "army-painter": Manufacturer(
            slug="army-painter", name="The Army Painter", codePattern=r"[A-Z]{2}\d{2,5}"
        ),
        "ak-interactive": Manufacturer(
            slug="ak-interactive", name="AK Interactive", codePattern=r"AK\d{2,5}"
        ),
    }
)
RESELLER_KINDS = {"legacy": "curated", "mfr-store": "manufacturer"}
SHELF = {"legacy": True}
STORE_PAGE = "https://store.warlordgames.com/products/speedpaint-grim-black"


def test_shelf_manufacturer_defers_to_the_vendor_named_on_the_same_page() -> None:
    # The curated import filed the row by the PATH it scraped it from, so a paint the reseller
    # stocks reads `warlord-games`. The store's own scrape of that same page reads Shopify's
    # `vendor`, which says who made it. Neither row carries a barcode -- nothing could ever have
    # fused them -- so the disagreement publishes one product twice.
    members = [
        obs("legacy:speedpaint", sku="WP2001", manufacturer="warlord-games", url=STORE_PAGE),
        obs("mfr-store:speedpaint", sku="WP2001", manufacturer="army-painter", url=STORE_PAGE),
    ]
    before = join_observations(members, RESELLER_TAXONOMY, RESELLER_KINDS, Matches())
    assert sorted(before.entities) == ["army-painter/WP2001", "warlord-games/WP2001"]

    after = join_observations(members, RESELLER_TAXONOMY, RESELLER_KINDS, Matches(), None, SHELF)
    assert list(after.entities) == ["army-painter/WP2001"]
    assert [c["type"] for c in after.ambiguous] == ["shelf-manufacturer-corrected"]
    assert after.ambiguous[0]["shelf"] == "warlord-games"
    assert after.ambiguous[0]["maker"] == "army-painter"


def test_shelf_manufacturer_matches_one_page_not_one_query_string() -> None:
    # A URL identifies a listing, and a tracking parameter, a fragment or a trailing slash does
    # not make it a different one. Without this the correction misses the row it is for.
    members = [
        obs("legacy:varnish", sku="AK11237", manufacturer="warlord-games", url=STORE_PAGE + "/"),
        obs(
            "mfr-store:varnish",
            sku="AK11237",
            manufacturer="ak-interactive",
            url=STORE_PAGE + "?variant=42#reviews",
        ),
    ]
    result = join_observations(members, RESELLER_TAXONOMY, RESELLER_KINDS, Matches(), None, SHELF)
    assert list(result.entities) == ["ak-interactive/AK11237"]


def test_shelf_manufacturer_leaves_a_page_only_the_shelf_source_has_seen() -> None:
    # Warlord's own products come off the same import by the same path. Nothing else names the
    # page, so there is nothing to defer to and the shelf's answer stands -- which is the answer
    # for the several thousand rows where the shelf IS the maker.
    members = [
        obs(
            "legacy:tank",
            sku="WGB123456",
            manufacturer="warlord-games",
            url="https://store.warlordgames.com/products/cromwell",
        )
    ]
    result = join_observations(members, RESELLER_TAXONOMY, RESELLER_KINDS, Matches(), None, SHELF)
    assert list(result.entities) == ["warlord-games/WGB123456"]
    assert not result.ambiguous


def test_shelf_manufacturer_refuses_a_page_two_other_sources_disagree_about() -> None:
    # Two sources reading the same page cannot both be right about who made the thing, and
    # picking one of them here would be a guess. The shelf keeps its answer and the pair stays
    # visible as the ordinary cross-source disagreement it is.
    members = [
        obs("legacy:varnish", sku="AK11237", manufacturer="warlord-games", url=STORE_PAGE),
        obs("mfr-store:varnish", sku="AK11237", manufacturer="ak-interactive", url=STORE_PAGE),
        obs("ret-goblin:varnish", sku="AK11237", manufacturer="army-painter", url=STORE_PAGE),
    ]
    kinds = {**RESELLER_KINDS, "ret-goblin": "retailer"}
    result = join_observations(members, RESELLER_TAXONOMY, kinds, Matches(), None, SHELF)
    assert "warlord-games/AK11237" in result.entities
    assert not [c for c in result.ambiguous if c["type"] == "shelf-manufacturer-corrected"]


def test_hand_reassignment_outranks_the_derived_shelf_correction() -> None:
    # A maintainer naming one observation and its reason beats a rule that read a store's vendor
    # field, because the store can be wrong about a brand it resells and matches.yaml says why.
    members = [
        obs("legacy:varnish", sku="AK11237", manufacturer="warlord-games", url=STORE_PAGE),
        obs("mfr-store:varnish", sku="AK11237", manufacturer="army-painter", url=STORE_PAGE),
    ]
    result = join_observations(
        members,
        RESELLER_TAXONOMY,
        RESELLER_KINDS,
        Matches(reassignManufacturer={"legacy:varnish": "ak-interactive"}),
        None,
        SHELF,
    )
    assert sorted(result.entities) == ["ak-interactive/AK11237", "army-painter/AK11237"]


HOUSE_KINDS = {**KINDS, "ret-shop": "retailer", "mfr-gw": "manufacturer"}
HINT_CODES = {"ret-shop": "tags"}


def test_a_shop_house_number_takes_the_makers_code_from_its_own_tags() -> None:
    # The shop numbers its listings itself, so the row has no product code and founds a second
    # record under a slug of its own title -- next to the record the manufacturer's code already
    # names. The real number is in the shop's tag list, beside the brand.
    members = [
        obs("mfr-gw:patrol", sku="99120101234", name="Combat Patrol: Necrons"),
        obs(
            "ret-shop:patrol",
            sku="129011",
            name="Combat Patrol: Necrons (deutsch) von Games Workshop",
            hints={"tags": ["Warhammer 40.000", "99120101234", "Necrons"]},
        ),
    ]
    before = join_observations(members, TAXONOMY, HOUSE_KINDS, Matches())
    assert len(before.entities) == 2

    after = join_observations(
        members, TAXONOMY, HOUSE_KINDS, Matches(), None, None, HINT_CODES
    )
    assert list(after.entities) == ["games-workshop/99120101234"]


def test_two_tag_codes_are_no_code_at_all() -> None:
    # A tag list is prose. Where more than one value normalizes, the row keeps no code -- a wrong
    # code MERGES two products, so silence is the cheaper failure.
    members = [
        obs("mfr-gw:patrol", sku="99120101234", name="Combat Patrol: Necrons"),
        obs(
            "ret-shop:bundle",
            sku="129012",
            name="Necron Bundle",
            hints={"tags": ["99120101234", "99120105678"]},
        ),
    ]
    result = join_observations(
        members, TAXONOMY, HOUSE_KINDS, Matches(), None, None, HINT_CODES
    )
    assert sorted(result.entities) == ["games-workshop/99120101234", "games-workshop/necron-bundle"]


def test_the_sources_own_sku_still_wins_where_it_normalizes() -> None:
    # This supplies a code the source did not have; it never overrides one the source did.
    members = [
        obs(
            "ret-shop:patrol",
            sku="99120105678",
            name="Combat Patrol: Necrons",
            hints={"tags": ["99120101234"]},
        )
    ]
    result = join_observations(
        members, TAXONOMY, HOUSE_KINDS, Matches(), None, None, HINT_CODES
    )
    assert list(result.entities) == ["games-workshop/99120105678"]


def test_a_source_that_declares_no_hint_reads_no_tags() -> None:
    # Every shop's tag list is full of words; only a source that says where its codes live is read.
    members = [
        obs("mfr-gw:patrol", sku="99120101234", name="Combat Patrol: Necrons"),
        obs("ret-shop:patrol", sku="129011", name="Kampfpatrouille",
            hints={"tags": ["99120101234"]}),
    ]
    result = join_observations(members, TAXONOMY, HOUSE_KINDS, Matches(), None, None, {})
    assert len(result.entities) == 2


def test_reject_eans_unfuses_two_products_a_wrong_barcode_merged() -> None:
    # One source put product A's barcode on product B, and the (manufacturer, ean) union fused
    # them: B's product code stopped existing. Rejecting that one assertion splits them back apart
    # and leaves everything else the source said intact.
    members = [
        obs("mfr-gw:pot", sku="99120100001", ean="5011921000012", name="Desert Sand"),
        obs("legacy:terrain", sku="99120100002", ean="5011921000012", name="Normandy Wall"),
        obs("ret-goblin:terrain", sku="99120100002", ean="5011921000036", name="Normandy Wall"),
    ]
    before = join_observations(members, TAXONOMY, KINDS, Matches())
    # One record, and the pot's own code has stopped existing -- the curated row names the fusion.
    assert list(before.entities) == ["games-workshop/99120100002"]

    after = join_observations(
        members,
        TAXONOMY,
        KINDS,
        Matches(rejectEans={"legacy:terrain": ["5011921000012"]}),
    )
    assert sorted(after.entities) == ["games-workshop/99120100001", "games-workshop/99120100002"]
    # The rejection is scoped to the barcode named: the row keeps its code, name and everything else.
    terrain = after.entities["games-workshop/99120100002"]
    assert sorted(m.key for m in terrain) == ["legacy:terrain", "ret-goblin:terrain"]
    assert next(m for m in terrain if m.key == "legacy:terrain").sku == "99120100002"


def test_reject_eans_ignores_a_barcode_the_observation_does_not_assert() -> None:
    # A stale entry must not blank a barcode the source has since corrected to something else.
    members = [obs("legacy:thing", sku="99120100002", ean="5011921000036", name="Thing")]
    result = join_observations(
        members, TAXONOMY, KINDS, Matches(rejectEans={"legacy:thing": ["5011921000012"]})
    )
    assert list(result.entities) == ["games-workshop/99120100002"]
    assert result.entities["games-workshop/99120100002"][0].ean == "5011921000036"


# --- one code, two spellings ---------------------------------------------------------------------


def test_a_code_rewrite_turns_a_retailers_spelling_into_the_makers() -> None:
    """gamenerdz swaps Mantic's `MG` prefix for `MAN` and Steamforged's `SF<line>-` for
    `SFG<line>`; both rows must land in the record the maker's own code names."""
    taxonomy = Taxonomy(
        {
            "mantic-games": Manufacturer(
                slug="mantic-games", name="Mantic", codePattern=r"[A-Z]{2,10}\d{2,6}[A-Z]*",
                codeRewrite=[{"match": r"MAN([A-Z]+\d.*)", "replace": r"MG\1", "reason": "t"}],
            ),
            "steamforged-games": Manufacturer(
                slug="steamforged-games", name="Steamforged", codePattern=r"SF[A-Z0-9-]+",
                codeRewrite=[{"match": r"SFG([A-Z]{2})([A-Z]*)(\d.*)", "replace": r"SF\1-\2\3", "reason": "t"}],
            ),
        }
    )
    assert taxonomy.normalize_code("mantic-games", "MANKWR407") == "MGKWR407"
    assert taxonomy.normalize_code("mantic-games", "MGKWR407") == "MGKWR407"
    assert taxonomy.normalize_code("steamforged-games", "SFGGT023") == "SFGT-023"
    assert taxonomy.normalize_code("steamforged-games", "SFGIKMER320") == "SFIK-MER320"
    # the maker's own spelling is untouched, and a hyphen-less SF+line form is not mistaken for it
    assert taxonomy.normalize_code("steamforged-games", "SFGT-023") == "SFGT-023"
    assert taxonomy.normalize_code("steamforged-games", "SFGT023") == "SFGT023"


def test_a_rewrite_must_say_why() -> None:
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Manufacturer(slug="m", name="M", codeRewrite=[{"match": "X", "replace": "Y"}])


def test_a_named_group_leaves_a_spelling_suffix_out_of_the_code() -> None:
    """Army Painter's trailing `P` and Warlord's trailing `K` are the makers' own store spellings;
    every other trailing letter on an Army Painter code is a different product."""
    taxonomy = Taxonomy(
        {
            "army-painter": Manufacturer(
                slug="army-painter", name="AP",
                codePattern=r"(?P<paint>(WP|GM)\d{4}[A-OQ-Z]?)P?",
            ),
            "warlord-games": Manufacturer(
                slug="warlord-games", name="WG",
                codePattern=r"(?P<num>[0-9]{9,12})K?(-[0-9]{1,2})?|(?P<alpha>(?=[A-Z0-9-]*[A-Z])[A-Z0-9-]{5,}?)K?",
            ),
        }
    )
    assert taxonomy.normalize_code("army-painter", "WP8057P") == "WP8057"
    assert taxonomy.normalize_code("army-painter", "WP8057") == "WP8057"
    assert taxonomy.normalize_code("army-painter", "GM1010C") == "GM1010C"
    assert taxonomy.normalize_code("warlord-games", "403011012K") == "403011012"
    assert taxonomy.normalize_code("warlord-games", "WGB-BI-35K") == "WGB-BI-35"
    assert taxonomy.normalize_code("warlord-games", "WGB-AK-21K") == "WGB-AK-21"


def test_two_spellings_of_one_code_now_join_and_two_real_codes_are_reported() -> None:
    """The record that used to hold `MANKWR407` beside `MGKWR407` is one record with one code;
    a record holding two of the maker's OWN codes is reported, because that is a question --
    a renumbering nobody declared, or two products on one barcode -- and it was invisible."""
    taxonomy = Taxonomy(
        {
            "mantic-games": Manufacturer(
                slug="mantic-games", name="Mantic", codePattern=r"[A-Z]{2,10}\d{2,6}[A-Z]*",
                codeRewrite=[{"match": r"MAN([A-Z]+\d.*)", "replace": r"MG\1", "reason": "t"}],
            )
        }
    )
    kinds = {"mfr-m": "manufacturer", "ret-g": "retailer"}
    spellings = [
        obs("mfr-m:giant", sku="MGKWR407", ean="5060924982481", manufacturer="mantic-games"),
        obs("ret-g:giant", sku="MANKWR407", ean="5060924982481", manufacturer="mantic-games"),
    ]
    result = join_observations(spellings, taxonomy, kinds, Matches())
    assert list(result.entities) == ["mantic-games/MGKWR407"]
    assert not [c for c in result.ambiguous if c["type"] == "multi-code-entity"]

    two_codes = [
        obs("mfr-m:druid-v", sku="MGVAF201", ean="5060924988148", manufacturer="mantic-games"),
        obs("mfr-m:druid-k", sku="MGKWN206", ean="5060924988148", manufacturer="mantic-games"),
    ]
    result = join_observations(two_codes, taxonomy, kinds, Matches())
    reports = [c for c in result.ambiguous if c["type"] == "multi-code-entity"]
    assert len(reports) == 1
    assert reports[0]["codes"] == ["MGKWN206", "MGVAF201"]
    assert reports[0]["keys"] == ["mfr-m:druid-k", "mfr-m:druid-v"]


def test_a_contained_spelling_is_a_variant_not_a_second_code() -> None:
    from warhub_acquisition.resolve.join import _code_variants
    assert _code_variants("WGB-BI-35", "WGB-BI-35K")
    assert _code_variants("280873", "280873-0990")
    assert not _code_variants("MGVAF201", "MGKWN206")
