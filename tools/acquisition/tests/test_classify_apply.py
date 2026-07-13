from pathlib import Path

import pytest

from warhub_acquisition.classify.apply import apply_classifications
from warhub_acquisition.cli import main
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import read_yaml, write_yaml


def seed_taxonomy(paths: DataPaths) -> None:
    write_yaml(
        paths.taxonomy / "game-systems.yaml",
        {"gameSystems": [
            {"slug": "age-of-sigmar", "label": "Age of Sigmar"},
            {"slug": "warhammer-40k", "label": "Warhammer 40,000"},
        ]},
    )
    write_yaml(
        paths.taxonomy / "factions.yaml",
        {"factions": [
            {"slug": "necrons", "label": "Necrons"},
            {"slug": "stormcast-eternals", "label": "Stormcast Eternals"},
        ]},
    )


def test_valid_classifications_merge_into_overrides_preserving_existing_keys(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(
        paths.overrides,
        {
            "retract": ["games-workshop/retracted-item"],
            "products": {
                "games-workshop/combat-patrol-necrons-mystery-box": {"quantity": 5},
                "games-workshop/unrelated": {"category": "terrain"},
            },
        },
    )
    write_yaml(
        paths.classifications,
        {
            "games-workshop/combat-patrol-necrons-mystery-box": {
                "gameSystem": "warhammer-40k", "faction": "necrons", "decidedBy": "llm",
                "model": "test-model", "inputHash": "abc123", "date": "2026-07-12",
            },
            "games-workshop/paint-set-mystery": {
                "gameSystem": "age-of-sigmar", "decidedBy": "human", "date": "2026-07-12",
            },
        },
    )

    count = apply_classifications(paths)

    assert count == 2
    overrides = read_yaml(paths.overrides)
    assert overrides == {
        "retract": ["games-workshop/retracted-item"],
        "products": {
            "games-workshop/combat-patrol-necrons-mystery-box": {
                "quantity": 5, "gameSystem": "warhammer-40k", "faction": "necrons",
            },
            "games-workshop/paint-set-mystery": {"gameSystem": "age-of-sigmar"},
            "games-workshop/unrelated": {"category": "terrain"},
        },
    }


def test_unknown_game_system_slug_raises_naming_entity_and_slug(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(
        paths.classifications,
        {
            "games-workshop/combat-patrol-necrons-mystery-box": {
                "gameSystem": "bogus-system", "decidedBy": "llm", "date": "2026-07-12",
            },
        },
    )
    with pytest.raises(ValueError) as excinfo:
        apply_classifications(paths)
    assert "games-workshop/combat-patrol-necrons-mystery-box" in str(excinfo.value)
    assert "bogus-system" in str(excinfo.value)


def test_unknown_faction_slug_raises_naming_entity_and_slug(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(
        paths.classifications,
        {
            "games-workshop/paint-set-mystery": {
                "gameSystem": "warhammer-40k", "faction": "bogus-faction",
                "decidedBy": "llm", "date": "2026-07-12",
            },
        },
    )
    with pytest.raises(ValueError) as excinfo:
        apply_classifications(paths)
    assert "games-workshop/paint-set-mystery" in str(excinfo.value)
    assert "bogus-faction" in str(excinfo.value)


def test_invalid_slug_raises_before_writing_overrides(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(paths.overrides, {"retract": [], "products": {}})
    write_yaml(
        paths.classifications,
        {
            "games-workshop/a": {"gameSystem": "warhammer-40k", "decidedBy": "llm", "date": "2026-07-12"},
            "games-workshop/b": {"gameSystem": "bogus-system", "decidedBy": "llm", "date": "2026-07-12"},
        },
    )
    with pytest.raises(ValueError):
        apply_classifications(paths)
    # all-or-nothing: no partial merge from the classifications that *were* valid
    assert read_yaml(paths.overrides) == {"retract": [], "products": {}}


def test_missing_classifications_file_is_noop(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    assert apply_classifications(paths) == 0
    assert not paths.overrides.exists()


def test_no_overrides_file_yet_creates_it(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(
        paths.classifications,
        {"games-workshop/a": {"gameSystem": "warhammer-40k", "decidedBy": "llm", "date": "2026-07-12"}},
    )
    count = apply_classifications(paths)
    assert count == 1
    assert read_yaml(paths.overrides) == {
        "retract": [],
        "products": {"games-workshop/a": {"gameSystem": "warhammer-40k"}},
    }


def test_cli_apply_success(tmp_path: Path, capsys) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(
        paths.classifications,
        {"games-workshop/a": {"gameSystem": "warhammer-40k", "decidedBy": "llm", "date": "2026-07-12"}},
    )
    exit_code = main(["classify", "--apply", "--data", str(tmp_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "applied 1 classification" in out
    assert "resolve" in out  # documents that the operator must re-run resolve after


def test_cli_apply_unknown_slug_is_exit_1(tmp_path: Path, capsys) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(
        paths.classifications,
        {"games-workshop/a": {"gameSystem": "bogus-system", "decidedBy": "llm", "date": "2026-07-12"}},
    )
    exit_code = main(["classify", "--apply", "--data", str(tmp_path)])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "bogus-system" in err
    assert "games-workshop/a" in err
