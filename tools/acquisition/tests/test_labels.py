from pathlib import Path

from warhub_acquisition.taxonomy import load_labels
from warhub_acquisition.yamlio import write_yaml

# `load_labels` used to be tested through `migrate.labels.write_label_files`, its only writer.
# That writer went with the one-time legacy migration (2026-07-13), so the files are now
# hand-maintained and this asserts the reader against the shape they are actually committed in:
# a `gameSystems`/`factions` list of {slug, label}, sorted by slug.


def _write_labels(taxonomy_dir: Path, game_systems: dict[str, str], factions: dict[str, str]) -> None:
    write_yaml(
        taxonomy_dir / "game-systems.yaml",
        {"gameSystems": [{"slug": slug, "label": game_systems[slug]} for slug in sorted(game_systems)]},
    )
    write_yaml(
        taxonomy_dir / "factions.yaml",
        {"factions": [{"slug": slug, "label": factions[slug]} for slug in sorted(factions)]},
    )


def test_round_trip_sorted(tmp_path: Path) -> None:
    _write_labels(tmp_path, {"z-sys": "Z", "a-sys": "A"}, {"orks": "Orks"})
    text = (tmp_path / "game-systems.yaml").read_text(encoding="utf-8")
    assert text.index("a-sys") < text.index("z-sys")
    game_systems, factions = load_labels(tmp_path)
    assert game_systems == {"a-sys": "A", "z-sys": "Z"}
    assert factions == {"orks": "Orks"}


def test_missing_files_empty(tmp_path: Path) -> None:
    assert load_labels(tmp_path) == ({}, {})
