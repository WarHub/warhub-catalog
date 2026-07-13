"""run_source: contract enforcement gates evidence writes; missStreak sweep semantics."""
from pathlib import Path

import httpx
import pytest

from warhub_acquisition.acquire.cursor import CursorStore
from warhub_acquisition.acquire.runner import (
    STRATEGIES,
    AcquireContext,
    SourceContractError,
    SourceHealth,
    StrategyResult,
    load_mappings,
    run_source,
)
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import Contract, SourceDescriptor
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy
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


def descriptor(source_id: str = "toy-src", **contract_kw: object) -> SourceDescriptor:
    contract = Contract(**contract_kw) if contract_kw else None
    return SourceDescriptor(id=source_id, kind="manufacturer", strategy=source_id, contract=contract)


def context(tmp_path: Path, budget: int | None = None) -> AcquireContext:
    return AcquireContext(taxonomy=Taxonomy({}), mappings={}, run_date="2026-07-13", budget=budget)


def register(name: str, result: StrategyResult, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(STRATEGIES, name, lambda desc, client, cursor, ctx: result)


def test_contract_min_count_violation_raises_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = StrategyResult(
        observations=[obs("toy-src:a"), obs("toy-src:b")],
        full_sweep=True,
        stats={"fetched": 2},
        cursor={},
    )
    register("toy-src", result, monkeypatch)
    desc = descriptor(minCount=100)
    paths = DataPaths(tmp_path)

    with pytest.raises(SourceContractError) as excinfo:
        run_source(desc, paths, context(tmp_path))

    assert excinfo.value.details["type"] == "min-count"
    assert excinfo.value.details["expected"] == 100
    assert excinfo.value.details["actual"] == 2
    assert not (paths.evidence_products / "toy-src" / "observations.jsonl").exists()
    assert not (paths.evidence_products / "toy-src" / "cursor.yaml").exists()


def test_unconditional_min_count_applies_on_budgeted_partial_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (final fix wave, item 3): minCount must be checked on EVERY run, not only
    full-sweep ones -- shopify.py/woo.py sources can never reach full_sweep at all (barcode-less
    products requeue forever), so a minCount gated on full_sweep was permanently inert for them
    and a partial enumeration collapse (e.g. the bulk listing itself shrinking) would be silent."""
    result = StrategyResult(
        observations=[obs("toy-src:a")],
        full_sweep=False,
        stats={"fetched": 1},
        cursor={"pending": ["b", "c"]},
    )
    register("toy-src", result, monkeypatch)
    desc = descriptor(minCount=10)
    paths = DataPaths(tmp_path)

    with pytest.raises(SourceContractError) as excinfo:
        run_source(desc, paths, context(tmp_path, budget=1))

    assert excinfo.value.details["type"] == "min-count"
    assert excinfo.value.details["expected"] == 10
    assert excinfo.value.details["actual"] == 1
    assert not (paths.evidence_products / "toy-src" / "observations.jsonl").exists()
    assert not (paths.evidence_products / "toy-src" / "cursor.yaml").exists()


def test_unconditional_min_count_zero_is_a_noop_on_partial_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A minCount of 0 (sitemap_sd.py's descriptors, by design: partial-by-design coverage) must
    stay a no-op on a budgeted/partial run -- this is the sitemap-source escape hatch the
    unconditional minCount check relies on."""
    result = StrategyResult(
        observations=[],
        full_sweep=False,
        stats={"fetched": 0},
        cursor={"fetched": {}},
    )
    register("toy-src", result, monkeypatch)
    desc = descriptor(minCount=0)
    paths = DataPaths(tmp_path)

    health = run_source(desc, paths, context(tmp_path, budget=1))

    assert health.contract_ok is True
    assert health.observation_count == 0


def test_healthy_full_sweep_writes_evidence_and_updates_miss_streaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = DataPaths(tmp_path)
    store = EvidenceStore(paths.evidence_products)
    store.upsert("toy-src", obs("toy-src:seen", missStreak=3, firstSeen="1999-01-01", lastSeen="1999-01-01"))
    store.upsert("toy-src", obs("toy-src:unseen", missStreak=1, firstSeen="1999-01-01", lastSeen="1999-01-01"))
    store.save("toy-src")

    result = StrategyResult(
        observations=[obs("toy-src:seen", ean="123"), obs("toy-src:new")],
        full_sweep=True,
        stats={"fetched": 2, "skipped_unknown_vendor": 0},
        cursor={"page": 3},
    )
    register("toy-src", result, monkeypatch)
    desc = descriptor(minCount=1)

    health = run_source(desc, paths, context(tmp_path))

    assert isinstance(health, SourceHealth)
    assert health.source_id == "toy-src"
    assert health.full_sweep is True
    assert health.contract_ok is True
    assert health.observation_count == 2
    assert health.stats == {"fetched": 2, "skipped_unknown_vendor": 0}
    assert health.marked_missed == 1  # only toy-src:unseen was not observed this sweep

    reloaded = EvidenceStore(paths.evidence_products).load("toy-src")
    assert reloaded["toy-src:seen"].missStreak == 0
    assert reloaded["toy-src:seen"].ean == "123"
    assert reloaded["toy-src:seen"].firstSeen == "1999-01-01"  # older firstSeen preserved
    assert reloaded["toy-src:seen"].lastSeen == "2026-07-13"
    assert reloaded["toy-src:unseen"].missStreak == 2  # incremented: not observed this sweep
    assert reloaded["toy-src:new"].missStreak == 0
    assert reloaded["toy-src:new"].firstSeen == "2026-07-13"

    cursor = CursorStore(paths.evidence_products).load("toy-src")
    assert cursor["page"] == 3
    assert cursor["last_good_count"] == 2
    assert cursor["last_run_date"] == "2026-07-13"


def test_budgeted_partial_run_never_increments_miss_streak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = DataPaths(tmp_path)
    store = EvidenceStore(paths.evidence_products)
    store.upsert("toy-src", obs("toy-src:unseen", missStreak=0, firstSeen="1999-01-01", lastSeen="1999-01-01"))
    store.save("toy-src")
    CursorStore(paths.evidence_products).save("toy-src", {"last_good_count": 999, "last_run_date": "2020-01-01"})

    result = StrategyResult(
        observations=[obs("toy-src:new")],
        full_sweep=False,
        stats={"fetched": 1},
        cursor={"pending": ["x"]},
    )
    register("toy-src", result, monkeypatch)
    # minCount=0: this test is about mark_missed/missStreak gating on full_sweep, not minCount
    # (which is now checked unconditionally, final fix wave item 3 -- see the dedicated
    # test_unconditional_min_count_* tests below for that behavior).
    desc = descriptor(minCount=0)

    health = run_source(desc, paths, context(tmp_path, budget=1))

    assert health.full_sweep is False
    assert health.marked_missed == 0  # mark_missed is never invoked on a partial run
    reloaded = EvidenceStore(paths.evidence_products).load("toy-src")
    assert reloaded["toy-src:unseen"].missStreak == 0  # untouched by a partial sweep

    cursor = CursorStore(paths.evidence_products).load("toy-src")
    assert cursor["pending"] == ["x"]
    assert cursor["last_good_count"] == 999  # preserved -- not a full-sweep baseline
    assert cursor["last_run_date"] == "2026-07-13"


def test_drop_exceeding_max_drop_pct_on_full_sweep_raises_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = DataPaths(tmp_path)
    store = EvidenceStore(paths.evidence_products)
    store.upsert("toy-src", obs("toy-src:existing"))
    store.save("toy-src")
    before = (paths.evidence_products / "toy-src" / "observations.jsonl").read_bytes()
    CursorStore(paths.evidence_products).save("toy-src", {"last_good_count": 100, "last_run_date": "2020-01-01"})

    result = StrategyResult(
        observations=[obs(f"toy-src:{i}") for i in range(40)],  # 60% drop vs last_good_count=100
        full_sweep=True,
        stats={"fetched": 40},
        cursor={},
    )
    register("toy-src", result, monkeypatch)
    desc = descriptor(minCount=0, maxDropPct=50.0)

    with pytest.raises(SourceContractError) as excinfo:
        run_source(desc, paths, context(tmp_path))

    assert excinfo.value.details["type"] == "drop"
    assert excinfo.value.details["last_good_count"] == 100
    assert excinfo.value.details["actual"] == 40

    assert (paths.evidence_products / "toy-src" / "observations.jsonl").read_bytes() == before
    cursor = CursorStore(paths.evidence_products).load("toy-src")
    assert cursor["last_good_count"] == 100  # untouched


def test_required_field_rate_violation_applies_regardless_of_full_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = DataPaths(tmp_path)
    result = StrategyResult(
        observations=[obs("toy-src:a", ean="123"), obs("toy-src:b"), obs("toy-src:c")],
        full_sweep=False,
        stats={"fetched": 3},
        cursor={},
    )
    register("toy-src", result, monkeypatch)
    desc = descriptor(requiredFieldRates={"ean": 0.5})  # only 1/3 have ean

    with pytest.raises(SourceContractError) as excinfo:
        run_source(desc, paths, context(tmp_path))

    assert excinfo.value.details["type"] == "field-fill-rate"
    assert excinfo.value.details["field"] == "ean"
    assert not (paths.evidence_products / "toy-src" / "observations.jsonl").exists()


def test_empty_fetched_set_skips_field_rate_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = DataPaths(tmp_path)
    result = StrategyResult(observations=[], full_sweep=False, stats={"fetched": 0}, cursor={})
    register("toy-src", result, monkeypatch)
    desc = descriptor(requiredFieldRates={"ean": 0.5})

    health = run_source(desc, paths, context(tmp_path))
    assert health.observation_count == 0


def test_load_mappings_reads_every_file_keyed_by_source_id(tmp_path: Path) -> None:
    write_yaml(tmp_path / "mfr-warlord-store.yaml", {"gameSystem": {"Bolt Action": "bolt-action"}, "faction": {}})
    write_yaml(tmp_path / "ret-goblingaming.yaml", {"gameSystem": {}, "faction": {}})

    mappings = load_mappings(tmp_path)

    assert set(mappings) == {"mfr-warlord-store", "ret-goblingaming"}
    assert mappings["mfr-warlord-store"]["gameSystem"] == {"Bolt Action": "bolt-action"}
    assert mappings["ret-goblingaming"] == {"gameSystem": {}, "faction": {}}


def test_load_mappings_missing_directory_returns_empty_dict(tmp_path: Path) -> None:
    assert load_mappings(tmp_path / "does-not-exist") == {}


def _capture_client_strategy(captured: dict) -> object:
    def strategy(desc, client, cursor, ctx):
        captured["client"] = client
        return StrategyResult(observations=[], full_sweep=False, stats={}, cursor={})

    return strategy


def test_runner_passes_politeness_timeout_seconds_to_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix wave 2 (live-run defect, 2026-07-13): descriptors can raise the HTTP timeout for slow
    bulk endpoints (Wayback CDX pages: 200KB+, 3-7s+ live) via `politeness.timeoutSeconds` --
    run_source must wire it into the PoliteClient it constructs."""
    captured: dict = {}
    monkeypatch.setitem(STRATEGIES, "toy-timeout", _capture_client_strategy(captured))
    desc = SourceDescriptor(
        id="toy-timeout",
        kind="archive",
        strategy="toy-timeout",
        baseUrl="https://example.test",
        politeness={"rps": 1.0, "timeoutSeconds": 60},
    )

    run_source(desc, DataPaths(tmp_path), context(tmp_path))

    assert captured["client"]._client.timeout == httpx.Timeout(60.0)


def test_runner_default_timeout_is_30_seconds_when_unspecified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}
    monkeypatch.setitem(STRATEGIES, "toy-timeout", _capture_client_strategy(captured))
    desc = SourceDescriptor(
        id="toy-timeout", kind="manufacturer", strategy="toy-timeout", baseUrl="https://example.test"
    )

    run_source(desc, DataPaths(tmp_path), context(tmp_path))

    assert captured["client"]._client.timeout == httpx.Timeout(30.0)
