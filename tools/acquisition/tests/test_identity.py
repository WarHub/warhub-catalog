from warhub_acquisition.resolve.identity import entity_id, slugify


def test_slugify() -> None:
    assert slugify("Combat Patrol: Necrons") == "combat-patrol-necrons"
    assert slugify("Adrax Agatone") == "adrax-agatone"
    assert slugify("Tau'nar  Supremacy Suit!") == "tau-nar-supremacy-suit"
    assert slugify("Éléments — Terrain") == "elements-terrain"


def test_entity_id_prefers_code() -> None:
    assert entity_id("games-workshop", "99120110077", "Combat Patrol: Necrons") == "games-workshop/99120110077"


def test_entity_id_falls_back_to_name_slug() -> None:
    assert entity_id("cmon", None, "Zombicide: Black Plague") == "cmon/zombicide-black-plague"
