from pathlib import Path

from test_migrate_runner import seed_repo
from warhub_acquisition.cli import main


def test_migrate_verifies_and_writes_report(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    exit_code = main(["migrate", "--data", str(data), "--legacy-dir", str(legacy), "--seed-dir", str(seed_dir)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "verification: OK" in out
    report = (data / "review" / "migration-report.md").read_text(encoding="utf-8")
    assert "games-workshop" in report
    assert "| manufacturer |" in report
    # the legacy Adrax and the seed Adrax share sku 99120101293 -> one entity
    catalog = (data / "catalog" / "products" / "games-workshop.yaml").read_text(encoding="utf-8")
    assert catalog.count("- id:") == 1
    assert "quantity: 1" in catalog          # from seed contents
    assert "ean: '5011921140862'" in catalog
    assert "eanConfidence: confirmed" in catalog  # curated-kind assertion


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
