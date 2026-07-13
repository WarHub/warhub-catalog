import json
from pathlib import Path

from test_migrate_runner import seed_repo
from warhub_acquisition.cli import main
from warhub_acquisition.migrate.runner import MigrationSummary
from warhub_acquisition.migrate.verify import verify_migration
from warhub_acquisition.models.catalog import CanonicalProduct
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import write_yaml
import warhub_acquisition.migrate.verify as verify_module


def test_migrate_verifies_and_writes_report(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    exit_code = main(["migrate", "--data", str(data), "--legacy-dir", str(legacy), "--seed-dir", str(seed_dir)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "verification: OK" in out
    report = (data / "review" / "migration-report.md").read_text(encoding="utf-8")
    assert "games-workshop" in report
    assert "| manufacturer |" in report
    assert "- minted factions: 0" in report
    assert "## Invalid EAN values" not in report
    # the legacy Adrax and the seed Adrax share sku 99120101293 -> one entity
    catalog = (data / "catalog" / "products" / "games-workshop.yaml").read_text(encoding="utf-8")
    assert catalog.count("- id:") == 1
    assert "quantity: 1" in catalog          # from seed contents
    assert "ean: '5011921140862'" in catalog
    assert "eanConfidence: confirmed" in catalog  # curated-kind assertion


def test_report_lists_invalid_checksum_eans(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    write_yaml(
        seed_dir / "gw-bad-ean.yaml",
        [{"name": "Miscast Miniature", "sku": "99120101994", "ean": "5011921194286",
          "manufacturer": "Games Workshop", "gameSystem": "Warhammer 40,000",
          "faction": "Space Marines", "status": "current",
          "contents": [{"unitName": "Miscast", "quantity": 1, "baseSize": "40mm"}]}],
    )
    main(["migrate", "--data", str(data), "--legacy-dir", str(legacy), "--seed-dir", str(seed_dir)])
    report = (data / "review" / "migration-report.md").read_text(encoding="utf-8")
    assert "## Invalid EAN values" in report
    assert "- 5011921194286" in report


def test_report_table_includes_record_counts(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    main(["migrate", "--data", str(data), "--legacy-dir", str(legacy), "--seed-dir", str(seed_dir)])
    report = (data / "review" / "migration-report.md").read_text(encoding="utf-8")
    assert "| manufacturer | records | entities | with EAN | confirmed |" in report
    assert "| games-workshop | 2 | 1 | 1 | 1 |" in report  # 1 legacy + 1 seed obs -> 1 entity


def test_violation_exits_3(tmp_path: Path, capsys, monkeypatch) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    import warhub_acquisition.migrate.verify as verify_module

    real = verify_module.verify_migration

    def broken(paths, summary):  # force a violation to pin the exit path
        violations, report = real(paths, summary)
        return (["forced violation"], report)

    monkeypatch.setattr("warhub_acquisition.cli.verify_migration", broken, raising=False)
    monkeypatch.setattr(verify_module, "verify_migration", broken)
    exit_code = main(["migrate", "--data", str(data), "--legacy-dir", str(legacy), "--seed-dir", str(seed_dir)])
    assert exit_code == 3
    assert "forced violation" in capsys.readouterr().out


def test_ean_mismatch_chosen_and_assertions_exempt_losing_ean_from_lost_check(
    tmp_path: Path, monkeypatch
) -> None:
    # unit test of the "not-lost" exemption in verify_migration: build a hand-written
    # conflicts.yaml with a real ean-mismatch payload shape (chosen + assertions), plus
    # evidence asserting both EANs, and prove the losing (non-chosen) EAN does NOT get
    # reported as "lost" because it is recovered from the assertions list.
    data = tmp_path / "data"
    paths = DataPaths(data)

    def line(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    mfr = paths.evidence_products / "mfr-gw" / "observations.jsonl"
    mfr.parent.mkdir(parents=True)
    mfr.write_text(
        line({"key": "mfr-gw:a", "name": "Combat Patrol: Necrons", "manufacturer": "games-workshop",
              "sku": "99120110077", "ean": "5011921194285",
              "firstSeen": "2026-07-12", "lastSeen": "2026-07-12", "extractor": "t@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    goblin = paths.evidence_products / "ret-goblin" / "observations.jsonl"
    goblin.parent.mkdir(parents=True)
    goblin.write_text(
        line({"key": "ret-goblin:a", "name": "Combat Patrol: Necrons", "manufacturer": "games-workshop",
              "sku": "GWS99120110077", "ean": "5060393709671",
              "firstSeen": "2026-07-12", "lastSeen": "2026-07-12", "extractor": "t@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )

    product = CanonicalProduct(
        id="games-workshop/99120110077", name="Combat Patrol: Necrons", manufacturer="games-workshop",
        status="current", firstSeen="2026-07-12", ean="5011921194285", eanConfidence="conflicted",
        evidence=["mfr-gw:a", "ret-goblin:a"],
    )
    monkeypatch.setattr(verify_module, "resolve_catalog", lambda p: {"games-workshop": [product]})

    write_yaml(
        paths.conflicts,
        {
            "conflicts": [
                {
                    "type": "ean-mismatch",
                    "entity": "games-workshop/99120110077",
                    "chosen": "5011921194285",
                    "assertions": [
                        {"ean": "5011921194285", "sources": ["mfr-gw"]},
                        {"ean": "5060393709671", "sources": ["ret-goblin"]},
                    ],
                },
            ]
        },
    )

    summary = MigrationSummary(legacy_count=2, seed_count=0)
    violations, _report = verify_migration(paths, summary)
    assert not any("lost" in v for v in violations)
