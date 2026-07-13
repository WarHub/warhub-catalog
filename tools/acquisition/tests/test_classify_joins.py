import json
from pathlib import Path

import pytest

from warhub_acquisition.classify.joins import (
    DEFAULT_BUDGET,
    DEFAULT_MODEL,
    generate_candidates,
    run_join_proposals,
)
from warhub_acquisition.classify.llm import run_llm_classification
from warhub_acquisition.cli import main
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import read_yaml, write_yaml


def _line(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def _product(id_: str, name: str, manufacturer: str, sku: str | None = None, ean: str | None = None,
             url: str | None = None, evidence: list[str] | None = None) -> dict:
    return {
        "id": id_,
        "name": name,
        "manufacturer": manufacturer,
        "sku": sku,
        "ean": ean,
        "status": "current",
        "firstSeen": "2026-01-01",
        "url": url,
        "evidence": evidence or [],
    }


def write_products(paths: DataPaths, manufacturer: str, products: list[dict]) -> None:
    write_yaml(paths.catalog_products / f"{manufacturer}.yaml", {"manufacturer": manufacturer, "products": products})


def write_taxonomy(paths: DataPaths, manufacturers: list[str]) -> None:
    write_yaml(
        paths.taxonomy / "manufacturers.yaml",
        {"manufacturers": [{"slug": m, "name": m} for m in manufacturers]},
    )


# --- rule: ean --------------------------------------------------------------------------------


def test_ean_rule_pairs_same_manufacturer_entities_sharing_validated_ean(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA111", "Combat Patrol Necrons", "games-workshop", sku="AAA111",
                      ean="5011921063765", evidence=["mfr-gw:aaa111"]),
            _product("games-workshop/BBB222", "Necron Combat Patrol Box", "games-workshop", sku="BBB222",
                      ean="5011921063765", evidence=["ret-goblin:bbb222"]),
        ],
    )

    candidates = generate_candidates(paths)

    assert len(candidates) == 1
    (candidate,) = candidates
    assert candidate["entityA"]["entity"] == "games-workshop/AAA111"
    assert candidate["entityB"]["entity"] == "games-workshop/BBB222"
    assert candidate["matchedRules"] == ["ean"]
    assert candidate["manufacturer"] == "games-workshop"


def test_ean_rule_does_not_pair_across_manufacturers(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(paths, "games-workshop", [_product("games-workshop/AAA", "Widget A", "games-workshop", ean="5011921063765")])
    write_products(paths, "mantic-games", [_product("mantic-games/BBB", "Widget B", "mantic-games", ean="5011921063765")])

    assert generate_candidates(paths) == []


def test_ean_rule_invalid_ean_is_never_a_candidate_signal(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget A", "games-workshop", ean="not-a-valid-ean"),
            _product("games-workshop/BBB", "Widget B", "games-workshop", ean="not-a-valid-ean"),
        ],
    )
    assert generate_candidates(paths) == []


# --- rule: name --------------------------------------------------------------------------------


def test_name_rule_pairs_exact_normalized_name_match(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA111", "Skitarii Rangers", "games-workshop", sku="AAA111"),
            _product("games-workshop/ZZZ999", "Skitarii  Rangers!", "games-workshop", sku="ZZZ999"),
        ],
    )

    candidates = generate_candidates(paths)

    assert len(candidates) == 1
    (candidate,) = candidates
    assert candidate["matchedRules"] == ["name"]
    assert {candidate["entityA"]["entity"], candidate["entityB"]["entity"]} == {
        "games-workshop/AAA111",
        "games-workshop/ZZZ999",
    }


def test_name_rule_is_exact_not_fuzzy(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Skitarii Rangers", "games-workshop"),
            _product("games-workshop/BBB", "Skitarii Vanguard", "games-workshop"),
        ],
    )
    assert generate_candidates(paths) == []


def test_name_rule_does_not_pair_across_manufacturers(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(paths, "games-workshop", [_product("games-workshop/AAA", "Widget", "games-workshop")])
    write_products(paths, "mantic-games", [_product("mantic-games/BBB", "Widget", "mantic-games")])
    assert generate_candidates(paths) == []


def test_name_rule_three_way_group_produces_three_pairs(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/BBB", "Widget", "games-workshop"),
            _product("games-workshop/CCC", "Widget", "games-workshop"),
        ],
    )
    candidates = generate_candidates(paths)
    pairs = {(c["entityA"]["entity"], c["entityB"]["entity"]) for c in candidates}
    assert pairs == {
        ("games-workshop/AAA", "games-workshop/BBB"),
        ("games-workshop/AAA", "games-workshop/CCC"),
        ("games-workshop/BBB", "games-workshop/CCC"),
    }


# --- rule: legacy-code --------------------------------------------------------------------------


def seed_parked_legacy_code(tmp_path: Path) -> DataPaths:
    """A resolved entity with a numeric sku, and a PARKED entity (unclassified-entity) whose
    legacyProductCode hint digit-matches that sku (formatting differs, digits are identical)."""
    paths = DataPaths(tmp_path)
    write_taxonomy(paths, ["games-workshop", "other-mfr"])
    write_yaml(paths.taxonomy / "game-systems.yaml", {"gameSystems": []})
    write_yaml(paths.taxonomy / "factions.yaml", {"factions": []})
    write_yaml(paths.sources / "mfr-gw.yaml", {"id": "mfr-gw", "kind": "manufacturer", "strategy": "algolia"})

    write_products(
        paths,
        "games-workshop",
        [_product("games-workshop/CURRENT-CODE", "Ork Boyz", "games-workshop", sku="400 010 99")],
    )

    evidence = paths.evidence_products / "mfr-gw" / "observations.jsonl"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        _line(
            {
                "key": "mfr-gw:ork-boyz-legacy-pack",
                "name": "Ork Boyz Legacy Pack",
                "manufacturer": "games-workshop",
                "hints": {"legacyProductCode": "GW-40001099"},
                "firstSeen": "2026-01-01",
                "lastSeen": "2026-07-12",
                "extractor": "algolia@1",
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    write_yaml(
        paths.conflicts,
        {
            "conflicts": [
                {
                    "type": "unclassified-entity",
                    "entity": "games-workshop/ork-boyz-legacy-pack",
                    "names": ["Ork Boyz Legacy Pack"],
                }
            ]
        },
    )
    return paths


def test_legacy_code_rule_pairs_legacy_digits_matching_sku_digits(tmp_path: Path) -> None:
    paths = seed_parked_legacy_code(tmp_path)

    candidates = generate_candidates(paths)

    assert len(candidates) == 1
    (candidate,) = candidates
    assert candidate["matchedRules"] == ["legacy-code"]
    assert {candidate["entityA"]["entity"], candidate["entityB"]["entity"]} == {
        "games-workshop/CURRENT-CODE",
        "games-workshop/ork-boyz-legacy-pack",
    }
    parked_ctx = next(
        c for c in (candidate["entityA"], candidate["entityB"])
        if c["entity"] == "games-workshop/ork-boyz-legacy-pack"
    )
    assert parked_ctx["name"] == "Ork Boyz Legacy Pack"
    assert parked_ctx["evidence"] == ["mfr-gw:ork-boyz-legacy-pack"]


def test_legacy_code_rule_missing_parked_evidence_raises(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_taxonomy(paths, ["games-workshop"])
    write_yaml(
        paths.conflicts,
        {"conflicts": [{"type": "unclassified-entity", "entity": "games-workshop/ghost", "names": ["Ghost"]}]},
    )
    write_yaml(paths.sources / "mfr-gw.yaml", {"id": "mfr-gw", "kind": "manufacturer", "strategy": "algolia"})
    with pytest.raises(ValueError, match="games-workshop/ghost"):
        generate_candidates(paths)


# --- multi-rule + determinism + no-catalog edge cases --------------------------------------------


def test_pair_matched_by_multiple_rules_appears_once_with_all_rules(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop", ean="5011921063765"),
            _product("games-workshop/BBB", "Widget", "games-workshop", ean="5011921063765"),
        ],
    )
    candidates = generate_candidates(paths)
    assert len(candidates) == 1
    assert candidates[0]["matchedRules"] == ["ean", "name"]


def test_generate_candidates_is_deterministic_and_sorted(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/ZZZ", "Widget", "games-workshop"),
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/MMM", "Widget", "games-workshop"),
        ],
    )
    first = generate_candidates(paths)
    second = generate_candidates(paths)
    assert first == second
    pairs = [(c["entityA"]["entity"], c["entityB"]["entity"]) for c in first]
    assert pairs == sorted(pairs)


def test_no_catalog_or_conflicts_yields_no_candidates(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    assert generate_candidates(paths) == []


def test_pair_context_completeness(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop", sku="AAA", ean="5011921063765",
                      url="https://gw/aaa", evidence=["mfr-gw:aaa"]),
            _product("games-workshop/BBB", "Widget", "games-workshop", sku="BBB", ean="5011921063765",
                      url="https://gw/bbb", evidence=["mfr-gw:bbb"]),
        ],
    )
    (candidate,) = generate_candidates(paths)
    for side in ("entityA", "entityB"):
        ctx = candidate[side]
        assert set(ctx) == {"entity", "name", "sku", "ean", "url", "legacyProductCode", "evidence"}
        assert ctx["entity"]
        assert ctx["name"] == "Widget"
        assert ctx["ean"] == "5011921063765"
        assert ctx["url"]
        assert ctx["evidence"]


# --- fake Anthropic client (mirrors test_classify_llm.py's RecordingClient) ----------------------


class _FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]


class RecordingClient:
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


def _batch_pair_ids(call: dict) -> list[str]:
    items = json.loads(call["messages"][0]["content"])
    return [item["pairId"] for item in items]


def _accept_all_same_product(confidence: float = 0.9):
    def respond(call: dict, call_number: int) -> str:
        return json.dumps(
            [{"pairId": pair_id, "sameProduct": True, "confidence": confidence} for pair_id in _batch_pair_ids(call)]
        )

    return respond


def join_cache_lines(paths: DataPaths) -> list[dict]:
    cache_path = paths.root / "review" / "join-cache.jsonl"
    if not cache_path.exists():
        return []
    return [json.loads(line) for line in cache_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def seed_many_name_dupe_pairs(paths: DataPaths, n: int) -> None:
    products = []
    for i in range(n):
        products.append(_product(f"games-workshop/A{i:03d}", f"Widget {i}", "games-workshop", sku=f"A{i:03d}"))
        products.append(_product(f"games-workshop/B{i:03d}", f"Widget {i}", "games-workshop", sku=f"B{i:03d}"))
    write_products(paths, "games-workshop", products)


# --- LLM flow: batching / cache / threshold / provenance ------------------------------------------


def test_batching_25_pairs_makes_2_requests_of_20_5(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_many_name_dupe_pairs(paths, 25)
    client = RecordingClient(_accept_all_same_product())

    summary = run_join_proposals(paths, run_date="2026-07-12", client=client)

    assert summary.candidates == 25
    assert [len(_batch_pair_ids(call)) for call in client.calls] == [20, 5]
    assert summary.requests == 2
    assert summary.queried == 25
    assert summary.cached_skips == 0
    assert summary.accepted == 25


def test_budget_caps_requests_not_pairs(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_many_name_dupe_pairs(paths, 25)
    client = RecordingClient(_accept_all_same_product())

    summary = run_join_proposals(paths, run_date="2026-07-12", client=client, budget=1)

    assert summary.requests == 1
    assert summary.queried == 20
    assert len(join_cache_lines(paths)) == 20


def test_default_budget_and_model_constants() -> None:
    assert DEFAULT_BUDGET == 500
    assert DEFAULT_MODEL == "claude-haiku-4-5-20251001"


def test_cache_hit_skips_pair_without_querying(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/BBB", "Widget", "games-workshop"),
        ],
    )
    client = RecordingClient(_accept_all_same_product())
    run_join_proposals(paths, run_date="2026-07-12", client=client)
    assert len(client.calls) == 1

    client2 = RecordingClient(_accept_all_same_product())
    summary = run_join_proposals(paths, run_date="2026-07-13", client=client2)

    assert summary.cached_skips == 1
    assert summary.queried == 0
    assert client2.calls == []


def test_verdict_same_product_below_threshold_is_low_confidence_not_accepted(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/BBB", "Widget", "games-workshop"),
        ],
    )

    def respond(call, n):
        return json.dumps(
            [{"pairId": pid, "sameProduct": True, "confidence": 0.5} for pid in _batch_pair_ids(call)]
        )

    client = RecordingClient(respond)
    summary = run_join_proposals(paths, run_date="2026-07-12", client=client)

    assert summary.low_confidence == 1
    assert summary.accepted == 0
    written = read_yaml(paths.root / "review" / "join-proposals.yaml")
    (proposal,) = written["proposals"]
    assert proposal["acceptedCandidate"] is False
    assert proposal["verdict"] == "same-product"
    assert proposal["confidence"] == 0.5


def test_verdict_exactly_threshold_is_accepted(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/BBB", "Widget", "games-workshop"),
        ],
    )

    def respond(call, n):
        return json.dumps(
            [{"pairId": pid, "sameProduct": True, "confidence": 0.8} for pid in _batch_pair_ids(call)]
        )

    client = RecordingClient(respond)
    summary = run_join_proposals(paths, run_date="2026-07-12", client=client)

    assert summary.accepted == 1
    written = read_yaml(paths.root / "review" / "join-proposals.yaml")
    (proposal,) = written["proposals"]
    assert proposal["acceptedCandidate"] is True


def test_verdict_different_product_never_accepted_regardless_of_confidence(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/BBB", "Widget", "games-workshop"),
        ],
    )

    def respond(call, n):
        return json.dumps(
            [{"pairId": pid, "sameProduct": False, "confidence": 0.99} for pid in _batch_pair_ids(call)]
        )

    client = RecordingClient(respond)
    summary = run_join_proposals(paths, run_date="2026-07-12", client=client)

    assert summary.rejected == 1
    assert summary.accepted == 0
    written = read_yaml(paths.root / "review" / "join-proposals.yaml")
    (proposal,) = written["proposals"]
    assert proposal["verdict"] == "different-product"
    assert proposal["acceptedCandidate"] is False


def test_malformed_response_marks_pair_unknown(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/BBB", "Widget", "games-workshop"),
        ],
    )

    def respond(call, n):
        return "not json"

    client = RecordingClient(respond)
    summary = run_join_proposals(paths, run_date="2026-07-12", client=client)

    assert summary.unknown == 1
    entries = join_cache_lines(paths)
    assert entries[0]["verdict"] == "unknown"


def test_boolean_same_product_and_numeric_confidence_required(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/BBB", "Widget", "games-workshop"),
        ],
    )

    def respond(call, n):
        return json.dumps(
            [{"pairId": pid, "sameProduct": "yes", "confidence": 0.9} for pid in _batch_pair_ids(call)]
        )

    client = RecordingClient(respond)
    summary = run_join_proposals(paths, run_date="2026-07-12", client=client)

    assert summary.unknown == 1  # "yes" is not a bool -- never guessed


def test_cache_flushed_incrementally_survives_crash_after_first_batch(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    seed_many_name_dupe_pairs(paths, 25)  # 2 batches: 20 + 5

    def respond(call, n):
        if n == 1:
            return _accept_all_same_product()(call, n)
        raise RuntimeError("simulated crash mid-run")

    client = RecordingClient(respond)
    with pytest.raises(RuntimeError):
        run_join_proposals(paths, run_date="2026-07-12", client=client)

    assert len(join_cache_lines(paths)) == 20


# --- proposals file shape ------------------------------------------------------------------------


def test_proposals_file_has_header_comment_and_sorted_provenance(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/ZZZ", "Widget", "games-workshop"),
            _product("games-workshop/AAA", "Widget", "games-workshop"),
        ],
    )
    client = RecordingClient(_accept_all_same_product(confidence=0.92))
    run_join_proposals(paths, run_date="2026-07-12", client=client, model="claude-haiku-4-5-20251001")

    proposals_path = paths.root / "review" / "join-proposals.yaml"
    text = proposals_path.read_text(encoding="utf-8")
    assert text.startswith("#")
    assert "matches.yaml" in text
    assert "classify --propose-joins" in text

    written = read_yaml(proposals_path)
    (proposal,) = written["proposals"]
    assert proposal == {
        "entityA": {"entity": "games-workshop/AAA", "name": "Widget", "sku": None, "ean": None,
                     "url": None, "legacyProductCode": None, "evidence": []},
        "entityB": {"entity": "games-workshop/ZZZ", "name": "Widget", "sku": None, "ean": None,
                     "url": None, "legacyProductCode": None, "evidence": []},
        "manufacturer": "games-workshop",
        "matchedRules": ["name"],
        "verdict": "same-product",
        "confidence": 0.92,
        "acceptedCandidate": True,
        "model": "claude-haiku-4-5-20251001",
        "date": "2026-07-12",
        "inputHash": proposal["inputHash"],
    }


def test_proposals_file_never_touches_matches_yaml(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/BBB", "Widget", "games-workshop"),
        ],
    )
    client = RecordingClient(_accept_all_same_product(confidence=0.95))
    run_join_proposals(paths, run_date="2026-07-12", client=client)
    assert not paths.matches.exists()


# --- cache separation from classification cache ----------------------------------------------


def test_join_cache_is_a_separate_file_from_classification_cache(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_yaml(paths.taxonomy / "game-systems.yaml", {"gameSystems": [{"slug": "age-of-sigmar", "label": "AoS"}]})
    write_yaml(paths.taxonomy / "factions.yaml", {"factions": []})
    write_yaml(
        paths.root / "review" / "classification-queue.yaml",
        {
            "queue": [
                {
                    "entity": "mfr/item-1",
                    "name": "Item",
                    "manufacturer": "mfr",
                    "url": None,
                    "description": None,
                    "hints": [],
                    "candidates": {"gameSystems": ["age-of-sigmar"], "factions": {}},
                }
            ]
        },
    )
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/BBB", "Widget", "games-workshop"),
        ],
    )

    classify_client = RecordingClient(
        lambda call, n: json.dumps(
            [{"entity": "mfr/item-1", "gameSystem": "age-of-sigmar", "faction": None, "confidence": 0.9}]
        )
    )
    run_llm_classification(paths, run_date="2026-07-12", client=classify_client)

    join_client = RecordingClient(_accept_all_same_product())
    run_join_proposals(paths, run_date="2026-07-12", client=join_client)

    classification_cache = paths.root / "review" / "classification-cache.jsonl"
    join_cache = paths.root / "review" / "join-cache.jsonl"
    assert classification_cache.exists()
    assert join_cache.exists()
    assert classification_cache != join_cache

    classify_entries = [json.loads(line) for line in classification_cache.read_text(encoding="utf-8").splitlines()]
    join_entries = join_cache_lines(paths)
    assert len(classify_entries) == 1
    assert len(join_entries) == 1
    assert "decision" in classify_entries[0] and "verdict" not in classify_entries[0]
    assert "verdict" in join_entries[0] and "decision" not in join_entries[0]


# --- CLI -------------------------------------------------------------------------------------


def test_cli_propose_joins_missing_api_key_exits_1(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    paths = DataPaths(tmp_path)
    write_yaml(paths.taxonomy / "manufacturers.yaml", {"manufacturers": []})
    exit_code = main(["classify", "--propose-joins", "--data", str(tmp_path), "--run-date", "2026-07-12"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err


def test_cli_propose_joins_missing_run_date_exits_1(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    paths = DataPaths(tmp_path)
    write_yaml(paths.taxonomy / "manufacturers.yaml", {"manufacturers": []})
    exit_code = main(["classify", "--propose-joins", "--data", str(tmp_path)])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "--run-date" in err


def test_cli_propose_joins_success_wires_budget_and_model(tmp_path: Path, monkeypatch, capsys) -> None:
    paths = DataPaths(tmp_path)
    write_products(
        paths,
        "games-workshop",
        [
            _product("games-workshop/AAA", "Widget", "games-workshop"),
            _product("games-workshop/BBB", "Widget", "games-workshop"),
        ],
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")

    client = RecordingClient(_accept_all_same_product())

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: client)

    exit_code = main(
        [
            "classify",
            "--propose-joins",
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
    assert "candidates=1" in out
    assert "accepted=1" in out


def test_cli_classify_mode_group_rejects_llm_and_propose_joins_together(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["classify", "--llm", "--propose-joins", "--data", str(tmp_path), "--run-date", "2026-07-12"])


# --- real committed data (read-only; generation only, no LLM) -------------------------------------
# Mirrors test_classify_queue.py's REPO_DATA pattern: skip cleanly when this package is built/tested
# outside the monorepo, where ../../../../data does not exist. Pure file reading only.
REPO_DATA = Path(__file__).resolve().parents[3] / "data"


def test_repo_generate_candidates_no_cross_manufacturer_and_sorted() -> None:
    if not REPO_DATA.exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")
    paths = DataPaths(REPO_DATA)

    candidates = generate_candidates(paths)

    pairs = [(c["entityA"]["entity"], c["entityB"]["entity"]) for c in candidates]
    assert pairs == sorted(pairs)
    for candidate in candidates:
        mfr_a = candidate["entityA"]["entity"].split("/", 1)[0]
        mfr_b = candidate["entityB"]["entity"].split("/", 1)[0]
        assert mfr_a == mfr_b == candidate["manufacturer"]
        assert candidate["matchedRules"]
