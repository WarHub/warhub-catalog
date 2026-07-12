"""Write slug->label taxonomy files consumed by the publisher."""
from pathlib import Path

from warhub_acquisition.yamlio import write_yaml


def write_label_files(
    taxonomy_dir: Path,
    game_system_labels: dict[str, str],
    faction_labels: dict[str, str],
) -> None:
    write_yaml(
        taxonomy_dir / "game-systems.yaml",
        {"gameSystems": [{"slug": slug, "label": game_system_labels[slug]} for slug in sorted(game_system_labels)]},
    )
    write_yaml(
        taxonomy_dir / "factions.yaml",
        {"factions": [{"slug": slug, "label": faction_labels[slug]} for slug in sorted(faction_labels)]},
    )
