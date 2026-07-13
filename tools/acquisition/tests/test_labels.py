from pathlib import Path

from warhub_acquisition.migrate.labels import write_label_files
from warhub_acquisition.taxonomy import load_labels


def test_round_trip_sorted(tmp_path: Path) -> None:
    write_label_files(tmp_path, {"z-sys": "Z", "a-sys": "A"}, {"orks": "Orks"})
    text = (tmp_path / "game-systems.yaml").read_text(encoding="utf-8")
    assert text.index("a-sys") < text.index("z-sys")
    game_systems, factions = load_labels(tmp_path)
    assert game_systems == {"a-sys": "A", "z-sys": "Z"}
    assert factions == {"orks": "Orks"}


def test_missing_files_empty(tmp_path: Path) -> None:
    assert load_labels(tmp_path) == ({}, {})
