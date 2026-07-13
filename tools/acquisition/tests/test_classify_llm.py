import json
from pathlib import Path

import pytest

from warhub_acquisition.classify.llm import (
    DEFAULT_BUDGET,
    DEFAULT_MODEL,
    compute_input_hash,
    run_llm_classification,
)
from warhub_acquisition.cli import main
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import read_yaml, write_yaml

CANDIDATES = {
    "gameSystems": ["age-of-sigmar", "kings-of-war", "warhammer-40k"],
    "factions": {
        "age-of-sigmar": ["skaven", "stormcast-eternals"],
        "warhammer-40k": ["necrons"],
    },
}


def seed_taxonomy(paths: DataPaths) -> None:
    write_yaml(
        paths.taxonomy / "game-systems.yaml",
        {
            "gameSystems": [
                {"slug": "age-of-sigmar", "label": "Age of Sigmar"},
                {"slug": "kings-of-war", "label": "Kings of War"},
                {"slug": "warhammer-40k", "label": "Warhammer 40,000"},
            ]
        },
    )
    write_yaml(
        paths.taxonomy / "factions.yaml",
        {
            "factions": [
                {"slug": "necrons", "label": "Necrons"},
                {"slug": "skaven", "label": "Skaven"},
                {"slug": "stormcast-eternals", "label": "Stormcast Eternals"},
            ]
        },
    )


def make_item(i: int, candidates: dict = CANDIDATES) -> dict:
    return {
        "entity": f"mfr/item-{i:03d}",
        "name": f"Product {i}",
        "manufacturer": "mfr",
        "url": f"https://example.com/item-{i}",
        "description": None,
        "hints": [],
        "candidates": candidates,
    }


def write_queue(paths: DataPaths, items: list[dict]) -> None:
    write_yaml(paths.root / "review" / "classification-queue.yaml", {"queue": items})


# --- fake Anthropic client -----------------------------------------------------------------


class _FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]


class RecordingClient:
    """Fakes the anthropic SDK boundary: client.messages.create(**kwargs)."""

    def __init__(self, respond) -> None:
        self._respond = respond
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self._respond(kwargs, len(self.calls))
        if isinstance(result, Exception):
            raise result
        return _FakeMessage(result)


def _batch_entities(call: dict) -> list[str]:
    items = json.loads(call["messages"][0]["content"])
    return [item["entity"] for item in items]


def _accept_all(game_system: str = "age-of-sigmar", faction: str | None = None, confidence: float = 0.9):
    def respond(call: dict, call_number: int) -> str:
        return json.dumps(
            [
                {"entity": entity, "gameSystem": game_system, "faction": faction, "confidence": confidence}
                for entity in _batch_entities(call)
            ]
        )

    return respond


def cache_lines(paths: DataPaths) -> list[dict]:
    cache_path = paths.root / "review" / "classification-cache.jsonl"
    if not cache_path.exists():
        return []
    return [json.loads(line) for line in cache_path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --- hash recipe -----------------------------------------------------------------------------


def test_compute_input_hash_is_sha256_of_canonical_sorted_compact_json() -> None:
    import hashlib

    item = make_item(1)
    expected = hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert compute_input_hash(item) == expected


def test_compute_input_hash_changes_when_candidates_change() -> None:
    item_a = make_item(1, candidates=CANDIDATES)
    other_candidates = {"gameSystems": [*CANDIDATES["gameSystems"], "necromunda"], "factions": CANDIDATES["factions"]}
    item_b = make_item(1, candidates=other_candidates)
    assert compute_input_hash(item_a) != compute_input_hash(item_b)


# --- batching / budget -------------------------------------------------------------------------


def test_batching_43_items_makes_3_requests_of_20_20_3(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_queue(paths, [make_item(i) for i in range(43)])
    client = RecordingClient(_accept_all())

    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert [len(_batch_entities(call)) for call in client.calls] == [20, 20, 3]
    assert summary.requests == 3
    assert summary.queried == 43
    assert summary.cached_skips == 0
    assert summary.accepted == 43
    assert summary.unknown == 0
    assert summary.low_confidence == 0


def test_budget_caps_requests_not_items(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_queue(paths, [make_item(i) for i in range(43)])
    client = RecordingClient(_accept_all())

    summary = run_llm_classification(paths, run_date="2026-07-12", client=client, budget=2)

    assert len(client.calls) == 2
    assert summary.requests == 2
    assert summary.queried == 40
    assert len(cache_lines(paths)) == 40


def test_default_budget_and_model_constants() -> None:
    assert DEFAULT_BUDGET == 500
    assert DEFAULT_MODEL == "claude-haiku-4-5-20251001"


# --- candidates homogeneity guard -------------------------------------------------------------
# queue.py currently guarantees one shared `candidates` object for the whole queue, and the system
# prompt is built once from the first pending item's candidates. These tests cover what happens if
# that invariant is ever violated (queue.py bug or a hand-edited queue file).


def test_mismatched_candidates_across_queue_items_raises_value_error_naming_entity(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    other_candidates = {"gameSystems": [*CANDIDATES["gameSystems"], "necromunda"], "factions": CANDIDATES["factions"]}
    item0 = make_item(0, candidates=CANDIDATES)
    item1 = make_item(1, candidates=other_candidates)
    write_queue(paths, [item0, item1])

    client = RecordingClient(_accept_all())
    with pytest.raises(ValueError, match=item1["entity"]):
        run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert client.calls == []  # must fail before ever sending a request with a wrong-for-item1 prompt


def test_equal_but_distinct_candidates_dicts_do_not_trigger_guard_and_validate_per_item(tmp_path: Path) -> None:
    """Distinct dict objects with equal content must NOT trip the homogeneity guard (it compares
    by equality, not identity), and each item's decision must validate against its OWN candidates
    dict rather than a shared/batch-level reference.
    """
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    candidates_copy = json.loads(json.dumps(CANDIDATES))  # equal by value, distinct object
    assert candidates_copy == CANDIDATES
    assert candidates_copy is not CANDIDATES
    item0 = make_item(0, candidates=CANDIDATES)
    item1 = make_item(1, candidates=candidates_copy)
    write_queue(paths, [item0, item1])

    client = RecordingClient(_accept_all())
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.accepted == 2
    assert summary.unknown == 0


# --- cache hit skip ------------------------------------------------------------------------


def test_cache_hit_skips_item_without_querying(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    cached_item = make_item(0)
    fresh_item = make_item(1)
    write_queue(paths, [cached_item, fresh_item])

    cache_path = paths.root / "review" / "classification-cache.jsonl"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    pre_entry = {
        "confidence": 0.95,
        "date": "2026-07-01",
        "decision": "classified",
        "entity": cached_item["entity"],
        "faction": None,
        "gameSystem": "age-of-sigmar",
        "inputHash": compute_input_hash(cached_item),
        "model": DEFAULT_MODEL,
    }
    cache_path.write_text(json.dumps(pre_entry, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    client = RecordingClient(_accept_all())
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.cached_skips == 1
    assert summary.queried == 1
    assert len(client.calls) == 1
    assert _batch_entities(client.calls[0]) == [fresh_item["entity"]]


# --- malformed / defensive parsing ----------------------------------------------------------


def test_malformed_json_response_marks_whole_batch_unknown(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(i) for i in range(3)]
    write_queue(paths, items)

    def respond(call, n):
        return "Sorry, I can't help classify these products."

    client = RecordingClient(respond)
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.unknown == 3
    assert summary.accepted == 0
    entries = cache_lines(paths)
    assert len(entries) == 3
    assert all(e["decision"] == "unknown" for e in entries)
    assert not paths.classifications.exists()


def test_per_item_salvage_on_partial_batch_response(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(i) for i in range(3)]
    write_queue(paths, items)

    def respond(call, n):
        entities = _batch_entities(call)
        # item 0: valid; item 1: missing from response entirely; item 2: bad confidence type
        return json.dumps(
            [
                {"entity": entities[0], "gameSystem": "age-of-sigmar", "faction": None, "confidence": 0.9},
                {"entity": entities[2], "gameSystem": "age-of-sigmar", "faction": None, "confidence": "high"},
            ]
        )

    client = RecordingClient(respond)
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.accepted == 1
    assert summary.unknown == 2
    entries = {e["entity"]: e for e in cache_lines(paths)}
    assert entries[items[0]["entity"]]["decision"] == "classified"
    assert entries[items[1]["entity"]]["decision"] == "unknown"
    assert entries[items[2]["entity"]]["decision"] == "unknown"


def test_duplicate_entity_in_response_last_occurrence_wins(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(0)]
    write_queue(paths, items)

    def respond(call, n):
        entities = _batch_entities(call)
        return json.dumps(
            [
                {"entity": entities[0], "gameSystem": "kings-of-war", "faction": None, "confidence": 0.6},
                {"entity": entities[0], "gameSystem": "age-of-sigmar", "faction": None, "confidence": 0.9},
            ]
        )

    client = RecordingClient(respond)
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.accepted == 1
    entries = cache_lines(paths)
    assert entries[0]["gameSystem"] == "age-of-sigmar"
    assert entries[0]["confidence"] == 0.9


def test_response_wrapped_in_markdown_fence_is_parsed(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(0)]
    write_queue(paths, items)

    def respond(call, n):
        entities = _batch_entities(call)
        payload = json.dumps(
            [{"entity": entities[0], "gameSystem": "age-of-sigmar", "faction": None, "confidence": 0.91}]
        )
        return f"```json\n{payload}\n```"

    client = RecordingClient(respond)
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.accepted == 1


# --- unknown-slug rejection ------------------------------------------------------------------


def test_unknown_game_system_slug_rejected_and_cached(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(0)]
    write_queue(paths, items)

    def respond(call, n):
        entities = _batch_entities(call)
        return json.dumps(
            [{"entity": entities[0], "gameSystem": "warhammer-30k", "faction": None, "confidence": 0.9}]
        )

    client = RecordingClient(respond)
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.unknown == 1
    assert summary.accepted == 0
    entries = cache_lines(paths)
    assert entries[0]["decision"] == "unknown"
    assert entries[0]["gameSystem"] is None
    assert not paths.classifications.exists()


def test_unknown_faction_slug_rejects_whole_item(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(0)]
    write_queue(paths, items)

    def respond(call, n):
        entities = _batch_entities(call)
        return json.dumps(
            [{"entity": entities[0], "gameSystem": "age-of-sigmar", "faction": "necrons", "confidence": 0.9}]
        )

    client = RecordingClient(respond)
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    # necrons is not a candidate faction for age-of-sigmar -- never guessed, whole item unknown
    assert summary.unknown == 1
    assert summary.accepted == 0


def test_boolean_confidence_rejected_as_non_numeric(tmp_path: Path) -> None:
    # isinstance(True, int) is True in Python -- confidence=True must not be silently coerced into
    # a "valid" numeric confidence.
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(0)]
    write_queue(paths, items)

    def respond(call, n):
        entities = _batch_entities(call)
        return json.dumps([{"entity": entities[0], "gameSystem": "age-of-sigmar", "faction": None, "confidence": True}])

    client = RecordingClient(respond)
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.unknown == 1
    assert summary.accepted == 0
    entries = cache_lines(paths)
    assert entries[0]["decision"] == "unknown"


def test_literal_unknown_game_system_string_is_unknown_decision(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(0)]
    write_queue(paths, items)

    def respond(call, n):
        entities = _batch_entities(call)
        return json.dumps([{"entity": entities[0], "gameSystem": "unknown", "faction": None, "confidence": 0.95}])

    client = RecordingClient(respond)
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.unknown == 1


# --- confidence threshold ---------------------------------------------------------------------


def test_below_threshold_confidence_not_written_to_products_but_cached(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(0)]
    write_queue(paths, items)

    def respond(call, n):
        entities = _batch_entities(call)
        return json.dumps([{"entity": entities[0], "gameSystem": "age-of-sigmar", "faction": None, "confidence": 0.5}])

    client = RecordingClient(respond)
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.low_confidence == 1
    assert summary.accepted == 0
    assert not paths.classifications.exists()
    entries = cache_lines(paths)
    assert entries[0]["decision"] == "classified"
    assert entries[0]["confidence"] == 0.5
    assert entries[0]["gameSystem"] == "age-of-sigmar"


def test_exactly_threshold_confidence_is_accepted(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(0)]
    write_queue(paths, items)

    def respond(call, n):
        entities = _batch_entities(call)
        return json.dumps([{"entity": entities[0], "gameSystem": "age-of-sigmar", "faction": None, "confidence": 0.8}])

    client = RecordingClient(respond)
    summary = run_llm_classification(paths, run_date="2026-07-12", client=client)

    assert summary.accepted == 1
    assert summary.low_confidence == 0


# --- provenance --------------------------------------------------------------------------------


def test_accepted_decision_has_exact_provenance_fields(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(0)]
    write_queue(paths, items)
    input_hash = compute_input_hash(items[0])

    def respond(call, n):
        entities = _batch_entities(call)
        return json.dumps(
            [{"entity": entities[0], "gameSystem": "age-of-sigmar", "faction": "skaven", "confidence": 0.92}]
        )

    client = RecordingClient(respond)
    run_llm_classification(paths, run_date="2026-07-12", client=client, model="claude-haiku-4-5-20251001")

    written = read_yaml(paths.classifications)
    assert written == {
        items[0]["entity"]: {
            "gameSystem": "age-of-sigmar",
            "faction": "skaven",
            "decidedBy": "llm",
            "model": "claude-haiku-4-5-20251001",
            "inputHash": input_hash,
            "date": "2026-07-12",
        }
    }


def test_products_yaml_merges_replacing_same_entity_and_stays_sorted(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_yaml(
        paths.classifications,
        {"mfr/zzz-existing": {"gameSystem": "kings-of-war", "faction": None, "decidedBy": "human", "date": "2026-01-01"}},
    )
    items = [make_item(2), make_item(1), make_item(0)]  # deliberately unsorted
    write_queue(paths, items)

    client = RecordingClient(_accept_all())
    run_llm_classification(paths, run_date="2026-07-12", client=client)

    written = read_yaml(paths.classifications)
    assert list(written) == sorted(written)
    assert "mfr/zzz-existing" in written  # pre-existing untouched entity preserved


# --- crash / incremental flush -----------------------------------------------------------------


def test_cache_flushed_incrementally_survives_crash_after_first_batch(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_queue(paths, [make_item(i) for i in range(25)])  # 2 batches: 20 + 5

    def respond(call, n):
        if n == 1:
            return _accept_all()(call, n)
        raise RuntimeError("simulated crash mid-run")

    client = RecordingClient(respond)

    with pytest.raises(RuntimeError):
        run_llm_classification(paths, run_date="2026-07-12", client=client)

    entries = cache_lines(paths)
    assert len(entries) == 20  # only the first, successfully-flushed batch survived


def test_second_run_after_crash_still_writes_cached_accepted_decisions_to_products_yaml(
    tmp_path: Path,
) -> None:
    """The other half of the crash-survival invariant: a run that crashes AFTER the cache is
    incrementally flushed but BEFORE `_write_classifications` runs (e.g. the process is killed
    between the last batch's `append_cache_lines` and the final write, or a later run's own
    process dies before writing) leaves accepted decisions sitting in the cache but never
    materialized to products.yaml. A SECOND run must not treat those cache hits as already
    handled -- it must fold them into products.yaml just like a first-time acceptance would.
    """
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(i) for i in range(20)]
    write_queue(paths, items)

    # First run: succeeds and flushes the cache, but simulate a crash that happens AFTER the
    # incremental cache flush and BEFORE products.yaml is written -- i.e. products.yaml never
    # gets the accepted decisions from this run, exactly like a process killed between the two.
    client = RecordingClient(_accept_all())
    run_llm_classification(paths, run_date="2026-07-12", client=client)
    assert paths.classifications.exists()
    paths.classifications.unlink()  # simulate: cache flushed, but the write never landed

    assert len(cache_lines(paths)) == 20
    assert not paths.classifications.exists()

    # Second run: every item is now a cache hit (same queue, same input hashes) -- no new
    # queries should be made, but the previously-accepted, still-stranded decisions must land
    # in products.yaml this time.
    client2 = RecordingClient(_accept_all())
    summary = run_llm_classification(paths, run_date="2026-07-13", client=client2)

    assert summary.cached_skips == 20
    assert summary.queried == 0
    assert client2.calls == []

    written = read_yaml(paths.classifications)
    assert set(written) == {item["entity"] for item in items}
    for item in items:
        entry = written[item["entity"]]
        assert entry["gameSystem"] == "age-of-sigmar"
        assert entry["decidedBy"] == "llm"
        # provenance keeps the ORIGINAL cache entry's date/model, not the second run's -- the
        # cache entry is the source of truth being re-materialized, unmodified.
        assert entry["date"] == "2026-07-12"


# --- CLI: missing key / missing queue -----------------------------------------------------------


def test_cli_llm_missing_api_key_exits_1(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    exit_code = main(["classify", "--llm", "--data", str(tmp_path), "--run-date", "2026-07-12"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err


def test_cli_llm_missing_queue_file_exits_1(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    exit_code = main(["classify", "--llm", "--data", str(tmp_path), "--run-date", "2026-07-12"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "emit-queue" in err


def test_cli_llm_missing_run_date_exits_1(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    exit_code = main(["classify", "--llm", "--data", str(tmp_path)])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "--run-date" in err


def test_cli_llm_success_wires_budget_and_model(tmp_path: Path, monkeypatch, capsys) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    write_queue(paths, [make_item(0)])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")

    client = RecordingClient(_accept_all())

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: client)

    exit_code = main(
        [
            "classify",
            "--llm",
            "--data",
            str(tmp_path),
            "--run-date",
            "2026-07-12",
            "--budget",
            "7",
            "--model",
            "claude-haiku-4-5-20251001",
        ]
    )

    assert exit_code == 0
    assert client.calls[0]["model"] == "claude-haiku-4-5-20251001"
    out = capsys.readouterr().out
    assert "queried=1" in out
    assert "accepted=1" in out


# --- determinism -------------------------------------------------------------------------------


def test_run_is_deterministic_given_identical_responses(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_taxonomy(paths)
    items = [make_item(i) for i in [2, 0, 1]]
    write_queue(paths, items)

    client1 = RecordingClient(_accept_all())
    run_llm_classification(paths, run_date="2026-07-12", client=client1)
    first = read_yaml(paths.classifications)

    # reset for a second independent run against a fresh dir with the same inputs
    paths2 = DataPaths(tmp_path.parent / (tmp_path.name + "-2"))
    seed_taxonomy(paths2)
    write_queue(paths2, items)
    client2 = RecordingClient(_accept_all())
    run_llm_classification(paths2, run_date="2026-07-12", client=client2)
    second = read_yaml(paths2.classifications)

    assert first == second
    assert list(first) == sorted(first)
