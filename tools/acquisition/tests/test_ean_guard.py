"""report --ean-guard: confirmed-EAN change detection against `git show HEAD:<path>`.

Uses a THROWAWAY git repo built under tmp_path (git init + config + commit) -- never touches
the real repo. The data dir is repo_root/"data" so DataPaths(data).root.parent == repo_root,
matching how the guard derives the repo root in production.
"""
import subprocess
from pathlib import Path

from warhub_acquisition.cli import main
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import write_yaml


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(repo_root: Path) -> DataPaths:
    repo_root.mkdir(parents=True, exist_ok=True)
    _git("init", cwd=repo_root)
    _git("config", "user.email", "test@example.com", cwd=repo_root)
    _git("config", "user.name", "Test", cwd=repo_root)
    return DataPaths(repo_root / "data")


def _commit(repo_root: Path, message: str) -> None:
    _git("add", "-A", cwd=repo_root)
    _git("commit", "-m", message, cwd=repo_root)


def _write_catalog(paths: DataPaths, products: list[dict]) -> None:
    write_yaml(
        paths.catalog_products / "games-workshop.yaml",
        {"manufacturer": "games-workshop", "products": products},
    )


def test_confirmed_ean_change_exits_5_and_lists_the_entity(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5060393709671", "eanConfidence": "confirmed"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Confirmed-EAN changes" in out
    assert "games-workshop/a" in out
    assert "5011921194285" in out
    assert "5060393709671" in out


def test_no_change_exits_0_and_no_guard_section(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out


def test_provisional_ean_change_is_not_a_hit(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "provisional"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5060393709671", "eanConfidence": "provisional"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out


def test_new_entity_is_not_a_hit(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [
            {"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"},
            {"id": "games-workshop/b", "name": "Thing B", "ean": "5011921194286", "eanConfidence": "provisional"},
        ],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out


def test_removed_entity_is_not_a_hit(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(paths, [])

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out


def test_new_manufacturer_file_absent_from_head_is_not_a_hit(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    (repo_root / "README.md").write_text("hello\n", encoding="utf-8", newline="\n")
    _commit(repo_root, "seed repo")

    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out


def test_repackaging_retained_in_additional_passes_and_reports(tmp_path: Path, capsys) -> None:
    # HEAD confirmed ean X; the working record's primary flips to Y but X is retained in
    # additionalEans -- a tracked repackaging (multi-EAN join). Reported distinctly, NOT a
    # regression: exit 0, and the regression section is absent.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{
            "id": "games-workshop/a", "name": "Thing A", "ean": "5060393709671",
            "eanConfidence": "confirmed", "additionalEans": ["5011921194285"],
        }],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out
    assert "repackaging" in out.lower()
    assert "games-workshop/a" in out


def test_lost_confirmed_ean_not_in_additional_fails_loudly(tmp_path: Path, capsys) -> None:
    # HEAD confirmed ean X; the working primary is Y and X is NOWHERE (not primary, not in
    # additionalEans) -- a genuine regression that must fail loudly: exit 5.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{
            "id": "games-workshop/a", "name": "Thing A", "ean": "5060393709671",
            "eanConfidence": "confirmed", "additionalEans": ["5011921063765"],
        }],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Confirmed-EAN changes" in out
    assert "5011921194285" in out


def test_report_without_ean_guard_flag_ignores_git_state(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5060393709671", "eanConfidence": "confirmed"}],
    )

    exit_code = main(["report", "--data", str(paths.root)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out
