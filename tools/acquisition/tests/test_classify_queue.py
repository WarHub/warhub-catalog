import json
from pathlib import Path

import pytest

from warhub_acquisition.classify.queue import build_queue
from warhub_acquisition.cli import main
from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import read_yaml, write_yaml


def _line(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def seed(tmp_path: Path) -> DataPaths:
    """Two classified products (seeding real gameSystem/faction pairs into the resolved
    catalog) plus two parked ('unclassified-entity') products: one two-source entity with
    hints/url/description on different members, one bare single-source entity."""
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.taxonomy / "manufacturers.yaml",
        {"manufacturers": [{"slug": "games-workshop", "name": "Games Workshop"}]},
    )
    write_yaml(
        paths.taxonomy / "game-systems.yaml",
        {"gameSystems": [
            {"slug": "age-of-sigmar", "label": "Age of Sigmar"},
            {"slug": "warhammer-40k", "label": "Warhammer 40,000"},
        ]},
    )
    write_yaml(
        paths.taxonomy / "factions.yaml",
        {"factions": [
            {"slug": "necrons", "label": "Necrons"},
            {"slug": "stormcast-eternals", "label": "Stormcast Eternals"},
        ]},
    )
    write_yaml(paths.sources / "mfr-gw.yaml", {"id": "mfr-gw", "kind": "manufacturer", "strategy": "algolia"})
    write_yaml(paths.sources / "ret-goblin.yaml", {"id": "ret-goblin", "kind": "retailer", "strategy": "shopify"})

    mfr_gw = paths.evidence_products / "mfr-gw" / "observations.jsonl"
    mfr_gw.parent.mkdir(parents=True)
    mfr_gw.write_text(
        _line({
            "key": "mfr-gw:cp-necrons", "name": "Combat Patrol: Necrons", "manufacturer": "games-workshop",
            "hints": {"gameSystem": "warhammer-40k", "faction": "necrons"},
            "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "algolia@1",
        })
        + _line({
            "key": "mfr-gw:stormcast-libs", "name": "Stormcast Eternals Liberators",
            "manufacturer": "games-workshop",
            "hints": {"gameSystem": "age-of-sigmar", "faction": "stormcast-eternals"},
            "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "algolia@1",
        })
        + _line({
            "key": "mfr-gw:mystery-box", "name": "Combat Patrol: Necrons Mystery Box",
            "manufacturer": "games-workshop",
            "hints": {"category": "boxed-game", "packaging": "blister", "description": "A" * 400},
            "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "algolia@1",
        })
        + _line({
            "key": "mfr-gw:paint-set-mystery", "name": "Paint Set Mystery", "manufacturer": "games-workshop",
            "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "algolia@1",
        }),
        encoding="utf-8", newline="\n",
    )

    ret_goblin = paths.evidence_products / "ret-goblin" / "observations.jsonl"
    ret_goblin.parent.mkdir(parents=True)
    ret_goblin.write_text(
        _line({
            "key": "ret-goblin:mystery-box", "name": "Combat Patrol: Necrons Mystery Box",
            "manufacturer": "games-workshop", "url": "https://goblin/mystery-box",
            "imageUrl": "https://goblin/mystery-box.jpg", "hints": {"category": "miniatures"},
            "firstSeen": "2026-07-05", "lastSeen": "2026-07-12", "extractor": "shopify-handle-js@2",
        }),
        encoding="utf-8", newline="\n",
    )
    return paths


def test_build_queue_shape_for_parked_entities(tmp_path: Path) -> None:
    paths = seed(tmp_path)
    catalog = resolve_catalog(paths)
    assert list(catalog) == ["games-workshop"]  # sanity: the 2 classified products resolved

    conflicts = read_yaml(paths.conflicts)["conflicts"]
    assert len(conflicts) == 2
    assert all(c["type"] == "unclassified-entity" for c in conflicts)

    # inject an unrelated non-"unclassified-entity" conflict to verify build_queue filters by type
    conflicts.append({"type": "ean-mismatch", "entity": "games-workshop/irrelevant", "chosen": "x", "assertions": []})
    write_yaml(paths.conflicts, {"conflicts": conflicts})

    queue = build_queue(paths)

    assert queue == [
        {
            "entity": "games-workshop/combat-patrol-necrons-mystery-box",
            "name": "Combat Patrol: Necrons Mystery Box",
            "manufacturer": "games-workshop",
            "url": "https://goblin/mystery-box",
            "description": "A" * 300,
            "hints": ["category=boxed-game", "category=miniatures", "packaging=blister"],
            "candidates": {
                "gameSystems": ["age-of-sigmar", "warhammer-40k"],
                "factions": {
                    "age-of-sigmar": ["stormcast-eternals"],
                    "warhammer-40k": ["necrons"],
                },
            },
        },
        {
            "entity": "games-workshop/paint-set-mystery",
            "name": "Paint Set Mystery",
            "manufacturer": "games-workshop",
            "url": None,
            "description": None,
            "hints": [],
            "candidates": {
                "gameSystems": ["age-of-sigmar", "warhammer-40k"],
                "factions": {
                    "age-of-sigmar": ["stormcast-eternals"],
                    "warhammer-40k": ["necrons"],
                },
            },
        },
    ]

    # every item's "candidates" dict is the SAME object -- write_yaml must alias it rather than
    # duplicate the (potentially large, real-world ~47-gameSystem / ~140-faction) block per item
    assert queue[0]["candidates"] is queue[1]["candidates"]


def test_build_queue_is_deterministic_and_sorted_by_entity(tmp_path: Path) -> None:
    paths = seed(tmp_path)
    resolve_catalog(paths)
    first = build_queue(paths)
    second = build_queue(paths)
    assert first == second
    assert [item["entity"] for item in first] == sorted(item["entity"] for item in first)


def test_build_queue_no_parked_entities_is_empty(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_yaml(paths.taxonomy / "manufacturers.yaml", {"manufacturers": []})
    write_yaml(paths.taxonomy / "game-systems.yaml", {"gameSystems": []})
    write_yaml(paths.taxonomy / "factions.yaml", {"factions": []})
    assert build_queue(paths) == []


def test_build_queue_missing_evidence_for_conflict_raises(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_yaml(paths.taxonomy / "manufacturers.yaml", {"manufacturers": []})
    write_yaml(paths.taxonomy / "game-systems.yaml", {"gameSystems": []})
    write_yaml(paths.taxonomy / "factions.yaml", {"factions": []})
    write_yaml(paths.sources / "mfr-gw.yaml", {"id": "mfr-gw", "kind": "manufacturer", "strategy": "algolia"})
    write_yaml(
        paths.conflicts,
        {"conflicts": [{"type": "unclassified-entity", "entity": "games-workshop/ghost", "names": ["Ghost"]}]},
    )
    with pytest.raises(ValueError, match="games-workshop/ghost"):
        build_queue(paths)


def test_cli_emit_queue_writes_review_file(tmp_path: Path, capsys) -> None:
    paths = seed(tmp_path)
    resolve_catalog(paths)

    exit_code = main(["classify", "--emit-queue", "--data", str(tmp_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "2 queue items" in out
    written = read_yaml(tmp_path / "review" / "classification-queue.yaml")
    assert [item["entity"] for item in written["queue"]] == [
        "games-workshop/combat-patrol-necrons-mystery-box",
        "games-workshop/paint-set-mystery",
    ]


# --- real committed data ---------------------------------------------------------------------
# Uses a repo-root fixture rather than a package-relative one (see tests/test_repo_data.py):
# this package can be built/tested outside the monorepo (sdist), where ../../../../data does
# not exist -- skip cleanly in that case. Pure file reading only (no network, no LLM), so it
# stays fast.
REPO_DATA = Path(__file__).resolve().parents[3] / "data"


def test_repo_build_queue_covers_all_parked_entities() -> None:
    if not REPO_DATA.exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")
    paths = DataPaths(REPO_DATA)
    taxonomy = Taxonomy.load(paths.taxonomy)

    queue = build_queue(paths)

    # Self-consistency, not a literal: the parked count changes with every committed harvest.
    conflicts = read_yaml(paths.conflicts)["conflicts"]
    parked = sum(1 for c in conflicts if c.get("type") == "unclassified-entity")
    assert len(queue) == parked
    assert parked > 0
    for item in queue:
        assert item["name"]
        assert item["manufacturer"] in taxonomy.manufacturers
    assert [item["entity"] for item in queue] == sorted(item["entity"] for item in queue)
