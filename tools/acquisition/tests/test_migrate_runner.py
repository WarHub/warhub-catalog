from pathlib import Path

from test_migrate_legacy import make_faction_file
from warhub_acquisition.cli import main
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import write_yaml


def seed_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    data = tmp_path / "data"
    write_yaml(
        data / "catalog" / "taxonomy" / "manufacturers.yaml",
        {"manufacturers": [{"slug": "games-workshop", "name": "Games Workshop",
                            "codePattern": r"\d{11}", "gs1Prefixes": ["5011921"]}]},
    )
    write_yaml(data / "catalog" / "sources" / "legacy-catalog.yaml",
               {"id": "legacy-catalog", "kind": "curated", "strategy": "none"})
    write_yaml(data / "catalog" / "sources" / "seed-curated.yaml",
               {"id": "seed-curated", "kind": "curated", "strategy": "none"})
    legacy = tmp_path / "legacy"
    make_faction_file(legacy)
    seed_dir = tmp_path / "seed"
    write_yaml(
        seed_dir / "gw.yaml",
        [{"name": "Adrax Agatone", "sku": "99120101293", "manufacturer": "Games Workshop",
          "gameSystem": "Warhammer 40,000", "faction": "Space Marines", "status": "current",
          "contents": [{"unitName": "Adrax", "quantity": 1, "baseSize": "40mm"}]}],
    )
    return data, legacy, seed_dir


def run_migrate(data: Path, legacy: Path, seed_dir: Path) -> int:
    return main(["migrate", "--data", str(data), "--legacy-dir", str(legacy), "--seed-dir", str(seed_dir)])


def test_migrate_writes_evidence_and_labels(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    assert run_migrate(data, legacy, seed_dir) == 0
    out = capsys.readouterr().out
    assert "migrated 1 legacy + 1 seed observations" in out
    paths = DataPaths(data)
    assert (paths.evidence_products / "legacy-catalog" / "observations.jsonl").exists()
    assert (paths.evidence_products / "seed-curated" / "observations.jsonl").exists()
    assert (paths.taxonomy / "game-systems.yaml").exists()
    assert (paths.taxonomy / "factions.yaml").exists()


def test_migrate_is_idempotent(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    run_migrate(data, legacy, seed_dir)
    paths = DataPaths(data)
    files = [
        paths.evidence_products / "legacy-catalog" / "observations.jsonl",
        paths.evidence_products / "seed-curated" / "observations.jsonl",
        paths.taxonomy / "game-systems.yaml",
        paths.taxonomy / "factions.yaml",
    ]
    before = [f.read_bytes() for f in files]
    run_migrate(data, legacy, seed_dir)
    assert [f.read_bytes() for f in files] == before


def test_seed_faction_absent_from_legacy_mints_slug(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    write_yaml(
        seed_dir / "gw-age-of-sigmar.yaml",
        [{"name": "Lord-Celestant", "sku": "99120101999", "manufacturer": "Games Workshop",
          "gameSystem": "Warhammer 40,000", "faction": "Stormcast Eternals", "status": "current",
          "contents": [{"unitName": "Lord-Celestant", "quantity": 1, "baseSize": "40mm"}]}],
    )
    assert run_migrate(data, legacy, seed_dir) == 0
    paths = DataPaths(data)
    factions = (paths.taxonomy / "factions.yaml").read_text(encoding="utf-8")
    assert "space-marines" in factions
    assert "stormcast-eternals" in factions
