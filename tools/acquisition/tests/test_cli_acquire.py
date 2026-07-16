"""CLI `acquire` verb: source selection, contract-failure isolation, health report, exit codes."""
from pathlib import Path

import httpx
import pytest

from warhub_acquisition.acquire import runner as runner_module
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


def test_acquire_rate_limited_source_exits_degraded_3_and_other_sources_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A source whose only failure is an upstream rate-limit (429, flagged rate_limited on the
    FetchError) must NOT fail the run: it's recorded `rate-limited` in the health report and the
    command exits 3 (DEGRADED), while every other source still runs and commits normally."""
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-throttled", "toy-throttled")
    write_descriptor(paths, "toy-ok", "toy-ok")

    def raise_rate_limit(desc, client, cursor, ctx):
        raise FetchError("https://example.test/products.json", 429)  # 429 -> rate_limited by default

    monkeypatch.setitem(STRATEGIES, "toy-throttled", raise_rate_limit)
    register(
        monkeypatch,
        "toy-ok",
        StrategyResult(observations=[obs("toy-ok:a")], full_sweep=True, stats={"fetched": 1}, cursor={}),
    )

    exit_code = main(["acquire", "--data", str(tmp_path), "--run-date", "2026-07-13"])
    out = capsys.readouterr().out

    assert exit_code == 3
    assert "RATE LIMITED toy-throttled" in out
    assert "toy-ok: ok fetched=1" in out
    assert not (paths.evidence_products / "toy-throttled" / "observations.jsonl").exists()
    assert (paths.evidence_products / "toy-ok" / "observations.jsonl").exists()

    health = (tmp_path / "review" / "acquisition-health.md").read_text(encoding="utf-8")
    assert "toy-throttled" in health
    assert "rate-limited" in health
    assert "toy-ok" in health


def test_acquire_cloudflare_403_flagged_rate_limited_exits_degraded_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A Cloudflare-style 403 that PoliteClient flagged rate_limited is treated exactly like a 429:
    DEGRADED (exit 3), status `rate-limited` in the report."""
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-cf", "toy-cf")

    def raise_cf_403(desc, client, cursor, ctx):
        raise FetchError("https://example.test/products.json", 403, rate_limited=True)

    monkeypatch.setitem(STRATEGIES, "toy-cf", raise_cf_403)

    exit_code = main(["acquire", "--data", str(tmp_path), "--source", "toy-cf", "--run-date", "2026-07-13"])
    out = capsys.readouterr().out

    assert exit_code == 3
    assert "RATE LIMITED toy-cf" in out
    health = (tmp_path / "review" / "acquisition-health.md").read_text(encoding="utf-8")
    assert "rate-limited" in health


def test_acquire_plain_403_not_flagged_is_genuine_error_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A 403 the client did NOT flag rate_limited (no edge signature) is a genuine error -- the CLI
    must not blanket-treat every 403 as a throttle. Exit 4, status ERROR."""
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-403", "toy-403")

    def raise_plain_403(desc, client, cursor, ctx):
        raise FetchError("https://example.test/private", 403)  # rate_limited defaults False

    monkeypatch.setitem(STRATEGIES, "toy-403", raise_plain_403)

    exit_code = main(["acquire", "--data", str(tmp_path), "--source", "toy-403", "--run-date", "2026-07-13"])
    out = capsys.readouterr().out

    assert exit_code == 4
    assert "SOURCE ERROR toy-403: FetchError" in out
    health = (tmp_path / "review" / "acquisition-health.md").read_text(encoding="utf-8")
    assert "ERROR" in health


def test_acquire_genuine_error_beats_rate_limit_and_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A real failure always wins over a rate-limit: a run with BOTH a rate-limited source and a
    genuine error exits 4 (broken), never 3 (degraded) -- so a real fault is never masked by a
    coincident throttle. Both are still distinguishable in the health report."""
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-throttled", "toy-throttled")
    write_descriptor(paths, "toy-broken", "toy-broken")

    def raise_rate_limit(desc, client, cursor, ctx):
        raise FetchError("https://example.test/products.json", 429)

    def raise_value_error(desc, client, cursor, ctx):
        raise ValueError("boom")

    monkeypatch.setitem(STRATEGIES, "toy-throttled", raise_rate_limit)
    monkeypatch.setitem(STRATEGIES, "toy-broken", raise_value_error)

    exit_code = main(["acquire", "--data", str(tmp_path), "--run-date", "2026-07-13"])
    out = capsys.readouterr().out

    assert exit_code == 4
    assert "RATE LIMITED toy-throttled" in out
    assert "SOURCE ERROR toy-broken: ValueError: boom" in out

    health = (tmp_path / "review" / "acquisition-health.md").read_text(encoding="utf-8")
    assert "rate-limited" in health
    assert "ERROR" in health


def test_acquire_robots_disallowed_isolated_and_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """End-to-end via `cli.main()` (the real production call path, `_run_acquire` -> `run_source`
    with no injected transport): `RobotsDisallowedError` is a plain `Exception` subclass raised
    from inside `run_source`, BEFORE the strategy runs -- it must hit the exact same per-source
    isolation as any other source-level failure (SOURCE ERROR printed, exit code 4, other sources
    unaffected, no evidence written for the blocked source). `cli.py`'s `except Exception` clause
    is exception-type-agnostic, so this is largely already proven by the ValueError/FetchError
    siblings above -- this test closes the loop for the robots preflight specifically, real
    descriptor `baseUrl` and all (the CLI has no transport-injection flag, so `PoliteClient` itself
    is monkeypatched to route through a `MockTransport` instead of real network)."""
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_descriptor(paths, "toy-robots-broken", "toy-robots-broken", baseUrl="https://example.test")
    write_descriptor(paths, "toy-ok", "toy-ok")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        raise AssertionError(f"unexpected request: {request.url}")

    real_polite_client = runner_module.PoliteClient

    def fake_polite_client(base_url, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_polite_client(base_url, **kwargs)

    monkeypatch.setattr(runner_module, "PoliteClient", fake_polite_client)

    def never_called(desc, client, cursor, ctx):
        raise AssertionError("strategy must not run when robots.txt disallows the source")

    monkeypatch.setitem(STRATEGIES, "toy-robots-broken", never_called)
    register(
        monkeypatch,
        "toy-ok",
        StrategyResult(observations=[obs("toy-ok:a")], full_sweep=True, stats={"fetched": 1}, cursor={}),
    )

    exit_code = main(["acquire", "--data", str(tmp_path), "--run-date", "2026-07-13"])
    out = capsys.readouterr().out

    assert exit_code == 4
    assert "SOURCE ERROR toy-robots-broken: RobotsDisallowedError" in out
    assert "toy-ok: ok fetched=1" in out
    assert not (paths.evidence_products / "toy-robots-broken" / "observations.jsonl").exists()
    assert (paths.evidence_products / "toy-ok" / "observations.jsonl").exists()

    health = (tmp_path / "review" / "acquisition-health.md").read_text(encoding="utf-8")
    assert "toy-robots-broken" in health
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
