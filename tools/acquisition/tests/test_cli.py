from pathlib import Path

from warhub_acquisition.cli import main
from test_resolver import seed  # reuse the fixture builder


def test_resolve_command(tmp_path: Path, capsys) -> None:
    seed(tmp_path)
    exit_code = main(["resolve", "--data", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "resolved 1 products across 1 manufacturers; 0 conflicts" in out
    assert (tmp_path / "catalog" / "products" / "games-workshop.yaml").exists()


def test_report_command(tmp_path: Path, capsys) -> None:
    seed(tmp_path)
    main(["resolve", "--data", str(tmp_path)])
    exit_code = main(["report", "--data", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "| games-workshop | 1 | 1 | 100.0% | 0.0% |" in out
    assert "- mfr-gw: 1 observations" in out


def test_missing_data_dir_is_loud(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "nope"
    assert main(["report", "--data", str(missing)]) == 1
    assert main(["resolve", "--data", str(missing)]) == 1
    err = capsys.readouterr().err
    assert "data directory not found" in err
