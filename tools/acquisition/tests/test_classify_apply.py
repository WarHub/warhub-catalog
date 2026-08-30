from pathlib import Path

import pytest
from pydantic import ValidationError

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
            "games-workshop/paint-set-mystery": {"gameSystem": "age-of-sigmar", "faction": None},
            "games-workshop/unrelated": {"category": "terrain"},
        },
    }


def test_apply_never_touches_the_hand_authored_set_refs_file(tmp_path: Path) -> None:
    """apply_classifications rebuilds overrides.yaml from a literal of the two keys it owns, and
    write_yaml is plain PyYAML -- so any hand-authored key it does not know about is deleted, with
    its comments, and the command still exits 0. That is exactly what happened to `setRefs` on
    2026-08-11: one `classify --apply` dropped 22 lines, 19 of them the evidence for a maintainer's
    typo correction, and nothing went red (the classification run committed all of `data/`; ci.yml
    ran pytest on `tools/**` only). The fix was to move the key to its own file, so this test asserts the
    property that fix bought: set-refs.yaml is BYTE-IDENTICAL across a run. If it fails, apply.py
    has learned to write a file it must never write.
    """
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(paths.overrides, {"retract": [], "products": {}})
    # byte-compared, not dict-compared: the comments are the point -- a model round-trip would
    # preserve the data and still destroy the evidence a reviewer needs.
    paths.set_refs.write_text(
        "# hand-authored; written by nobody\nsetRefs:\n  ak-interactive/AK11781:\n"
        "    # six-point evidence lives here\n    AK111424: AK11424\n",
        encoding="utf-8",
        newline="",
    )
    before = paths.set_refs.read_text(encoding="utf-8")
    write_yaml(
        paths.classifications,
        {"games-workshop/a": {"gameSystem": "warhammer-40k", "decidedBy": "llm", "date": "2026-07-12"}},
    )

    assert apply_classifications(paths) == 1

    assert paths.set_refs.read_text(encoding="utf-8") == before
    assert read_yaml(paths.overrides) == {
        "retract": [],
        "products": {"games-workshop/a": {"gameSystem": "warhammer-40k", "faction": None}},
    }


def test_a_hand_authored_key_in_overrides_is_rejected_rather_than_deleted(tmp_path: Path) -> None:
    """The other half of the 2026-08-11 split, and the half that stops it recurring.

    Moving `setRefs` out only helps if putting a hand-authored key BACK is caught. It is:
    apply_classifications loads through `Overrides`, which is extra="forbid", so a third top-level
    key fails at LOAD time and overrides.yaml is never written -- instead of being read, ignored,
    and silently dropped by the two-key literal at write time. The error names the offending key,
    so the author is told what to do with it. Without this the model comment's promise is unbacked
    and the same class of loss returns under a different key name.
    """
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(paths.overrides, {"retract": [], "products": {}, "setRefs": {"a/b": {"X": "Y"}}})
    write_yaml(
        paths.classifications,
        {"games-workshop/a": {"gameSystem": "warhammer-40k", "decidedBy": "llm", "date": "2026-07-12"}},
    )

    with pytest.raises(ValidationError) as excinfo:
        apply_classifications(paths)
    assert "setRefs" in str(excinfo.value)

    # And nothing was written: the file still carries the key it was refused for, so a maintainer
    # who mis-filed a correction still has it rather than having to recover it from git.
    assert read_yaml(paths.overrides)["setRefs"] == {"a/b": {"X": "Y"}}


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
        "products": {"games-workshop/a": {"gameSystem": "warhammer-40k", "faction": None}},
    }


def test_reclassification_with_null_faction_clears_stale_override(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(
        paths.overrides,
        {
            "retract": [],
            "products": {
                "games-workshop/combat-patrol-necrons-mystery-box": {
                    "gameSystem": "warhammer-40k", "faction": "necrons",
                },
            },
        },
    )
    write_yaml(
        paths.classifications,
        {
            "games-workshop/combat-patrol-necrons-mystery-box": {
                "gameSystem": "warhammer-40k", "faction": None, "decidedBy": "human", "date": "2026-07-12",
            },
        },
    )

    count = apply_classifications(paths)

    assert count == 1
    overrides = read_yaml(paths.overrides)
    assert overrides == {
        "retract": [],
        "products": {
            "games-workshop/combat-patrol-necrons-mystery-box": {
                "gameSystem": "warhammer-40k", "faction": None,
            },
        },
    }
    # explicit null survives the yaml round-trip (not dropped, not left stale)
    assert "faction" in overrides["products"]["games-workshop/combat-patrol-necrons-mystery-box"]


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
