"""CLI `acquire` verb: source selection, contract-failure isolation, health report, exit codes."""
from pathlib import Path

import pytest

from warhub_acquisition.acquire.client import FetchError
from warhub_acquisition.acquire.runner import STRATEGIES, StrategyResult
from warhub_acquisition.cli import main
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import write_yaml


def obs(key: str, **kw: object) -> Observation:
    base: dict[str, object] = {
        "key": key,
        "name": f"Product {key}",
        "firstSeen": "2000-01-01",
        "lastSeen": "2000-01-01",
        "extractor": "toy@1",
    }
    base.update(kw)
    return Observation(**base)


def seed_taxonomy(paths: DataPaths) -> None:
    write_yaml(paths.taxonomy / "manufacturers.yaml", {"manufacturers": []})


def write_descriptor(paths: DataPaths, source_id: str, strategy: str, **kw: object) -> None:
    payload: dict[str, object] = {"id": source_id, "kind": "manufacturer", "strategy": strategy}
    payload.update(kw)
    write_yaml(paths.sources / f"{source_id}.yaml", payload)


def register(monkeypatch: pytest.MonkeyPatch, name: str, result: StrategyResult) -> None:
    monkeypatch.setitem(STRATEGIES, name, lambda desc, client, cursor, ctx: result)


def test_acquire_named_source_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-src", "toy")
    register(
        monkeypatch,
        "toy",
        StrategyResult(observations=[obs("toy-src:a")], full_sweep=True, stats={"fetched": 1, "new": 1}, cursor={}),
    )

    exit_code = main(["acquire", "--data", str(tmp_path), "--source", "toy-src", "--run-date", "2026-07-13"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "toy-src: ok fetched=1 new=1" in out
    assert (paths.evidence_products / "toy-src" / "observations.jsonl").exists()
    health = (tmp_path / "review" / "acquisition-health.md").read_text(encoding="utf-8")
    assert "toy-src" in health
    assert "ok" in health


def test_acquire_loads_real_mapping_file_into_context_mappings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-src", "toy")
    write_yaml(
        paths.mappings / "toy-src.yaml",
        {"gameSystem": {"Bolt Action": "bolt-action"}, "faction": {}},
    )

    seen_mappings: dict = {}

    def capture(desc, client, cursor, ctx):
        seen_mappings.update(ctx.mappings)
        return StrategyResult(observations=[obs("toy-src:a")], full_sweep=True, stats={"fetched": 1}, cursor={})

    monkeypatch.setitem(STRATEGIES, "toy", capture)

    exit_code = main(["acquire", "--data", str(tmp_path), "--source", "toy-src", "--run-date", "2026-07-13"])

    assert exit_code == 0
    assert seen_mappings == {"toy-src": {"gameSystem": {"Bolt Action": "bolt-action"}, "faction": {}}}


def test_acquire_missing_mappings_directory_yields_empty_mappings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-src", "toy")

    seen_mappings: dict = {"sentinel": "unset"}

    def capture(desc, client, cursor, ctx):
        seen_mappings.clear()
        seen_mappings.update(ctx.mappings)
        return StrategyResult(observations=[obs("toy-src:a")], full_sweep=True, stats={"fetched": 1}, cursor={})

    monkeypatch.setitem(STRATEGIES, "toy", capture)

    exit_code = main(["acquire", "--data", str(tmp_path), "--source", "toy-src", "--run-date", "2026-07-13"])

    assert exit_code == 0
    assert seen_mappings == {}


def test_acquire_contract_violation_exits_4_and_other_sources_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-fail", "toy-fail", contract={"minCount": 100})
    write_descriptor(paths, "toy-ok", "toy-ok")
    register(
        monkeypatch,
        "toy-fail",
        StrategyResult(observations=[obs("toy-fail:a")], full_sweep=True, stats={"fetched": 1}, cursor={}),
    )
    register(
        monkeypatch,
        "toy-ok",
        StrategyResult(observations=[obs("toy-ok:a")], full_sweep=True, stats={"fetched": 1}, cursor={}),
    )

    exit_code = main(["acquire", "--data", str(tmp_path), "--run-date", "2026-07-13"])
    out = capsys.readouterr().out

    assert exit_code == 4
    assert "CONTRACT VIOLATION toy-fail" in out
    assert "toy-ok: ok fetched=1" in out
    assert not (paths.evidence_products / "toy-fail" / "observations.jsonl").exists()
    assert (paths.evidence_products / "toy-ok" / "observations.jsonl").exists()

    health = (tmp_path / "review" / "acquisition-health.md").read_text(encoding="utf-8")
    assert "toy-fail" in health
    assert "toy-ok" in health


def test_acquire_source_error_isolated_other_sources_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-broken", "toy-broken")
    write_descriptor(paths, "toy-ok", "toy-ok")

    def raise_value_error(desc, client, cursor, ctx):
        raise ValueError("boom")

    monkeypatch.setitem(STRATEGIES, "toy-broken", raise_value_error)
    register(
        monkeypatch,
        "toy-ok",
        StrategyResult(observations=[obs("toy-ok:a")], full_sweep=True, stats={"fetched": 1}, cursor={}),
    )

    exit_code = main(["acquire", "--data", str(tmp_path), "--run-date", "2026-07-13"])
    out = capsys.readouterr().out

    assert exit_code == 4
    assert "SOURCE ERROR toy-broken: ValueError: boom" in out
    assert "toy-ok: ok fetched=1" in out
    assert not (paths.evidence_products / "toy-broken" / "observations.jsonl").exists()
    assert (paths.evidence_products / "toy-ok" / "observations.jsonl").exists()

    health = (tmp_path / "review" / "acquisition-health.md").read_text(encoding="utf-8")
    assert "toy-broken" in health
    assert "ERROR" in health
    assert "toy-ok" in health
    assert "ok" in health


def test_acquire_fetch_error_isolated_and_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-broken", "toy-broken")
    write_descriptor(paths, "toy-ok", "toy-ok")

    def raise_fetch_error(desc, client, cursor, ctx):
        raise FetchError("https://example.test/list", 503)

    monkeypatch.setitem(STRATEGIES, "toy-broken", raise_fetch_error)
    register(
        monkeypatch,
        "toy-ok",
        StrategyResult(observations=[obs("toy-ok:a")], full_sweep=True, stats={"fetched": 1}, cursor={}),
    )

    exit_code = main(["acquire", "--data", str(tmp_path), "--run-date", "2026-07-13"])
    out = capsys.readouterr().out

    assert exit_code == 4
    assert "SOURCE ERROR toy-broken: FetchError" in out
    assert "toy-ok: ok fetched=1" in out
    assert not (paths.evidence_products / "toy-broken" / "observations.jsonl").exists()
    assert (paths.evidence_products / "toy-ok" / "observations.jsonl").exists()

    health = (tmp_path / "review" / "acquisition-health.md").read_text(encoding="utf-8")
    assert "toy-broken" in health
    assert "ERROR" in health
    assert "toy-ok" in health


def test_acquire_auto_select_skips_sources_without_registered_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-ok", "toy-ok")
    write_descriptor(paths, "legacy-catalog", "none", kind="curated")
    register(
        monkeypatch,
        "toy-ok",
        StrategyResult(observations=[obs("toy-ok:a")], full_sweep=True, stats={"fetched": 1}, cursor={}),
    )

    exit_code = main(["acquire", "--data", str(tmp_path), "--run-date", "2026-07-13"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "toy-ok: ok" in out
    assert "legacy-catalog" not in out
    assert not (paths.evidence_products / "legacy-catalog").exists()

    health = (tmp_path / "review" / "acquisition-health.md").read_text(encoding="utf-8")
    assert "## Skipped (no registered strategy)" in health
    assert "legacy-catalog" in health


def test_acquire_naming_unregistered_source_is_error(tmp_path: Path, capsys) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "legacy-catalog", "none", kind="curated")

    exit_code = main(
        ["acquire", "--data", str(tmp_path), "--source", "legacy-catalog", "--run-date", "2026-07-13"]
    )
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "legacy-catalog" in err


def test_acquire_naming_unknown_source_is_error(tmp_path: Path, capsys) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)

    exit_code = main(
        ["acquire", "--data", str(tmp_path), "--source", "does-not-exist", "--run-date", "2026-07-13"]
    )
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "does-not-exist" in err


def test_acquire_invalid_run_date_format_exits_1(tmp_path: Path, capsys) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)

    exit_code = main(["acquire", "--data", str(tmp_path), "--run-date", "13-07-2026"])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "run-date" in err


def test_acquire_missing_run_date_is_argparse_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["acquire", "--data", str(tmp_path)])


def test_acquire_missing_data_dir_exits_1(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "nope"
    exit_code = main(["acquire", "--data", str(missing), "--run-date", "2026-07-13"])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "data directory not found" in err
