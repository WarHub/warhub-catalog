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


def test_degenerate_name_forced_join_still_works() -> None:
    matches = Matches(joins={"ret-goblin:x": "games-workshop/99120110077"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("ret-goblin:x", sku=None, name="!!!")],
        TAXONOMY, KINDS, matches,
    )
    assert [m.key for m in result.entities["games-workshop/99120110077"]] == ["mfr-gw:a", "ret-goblin:x"]
    assert result.ambiguous == []
