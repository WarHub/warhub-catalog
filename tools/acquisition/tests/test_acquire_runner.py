"""run_source: contract enforcement gates evidence writes; missStreak sweep semantics."""
from pathlib import Path

import pytest

from warhub_acquisition.acquire.cursor import CursorStore
from warhub_acquisition.acquire.runner import (
    STRATEGIES,
    AcquireContext,
    SourceContractError,
    SourceHealth,
    StrategyResult,
    run_source,
)
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import Contract, SourceDescriptor
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy


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
    desc = descriptor(minCount=1000)  # would fail if enforced -- must be skipped on partial runs

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
