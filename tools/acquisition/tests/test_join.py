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
KINDS = {"mfr-gw": "manufacturer", "ret-goblin": "retailer", "ret-radaddel": "retailer"}


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
