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
    catalog) plus two null-gameSystem products: one two-source entity with hints/url/description
    on different members, one bare single-source entity."""
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


def test_build_queue_shape_for_null_game_system_products(tmp_path: Path) -> None:
    paths = seed(tmp_path)
    catalog = resolve_catalog(paths)
    assert list(catalog) == ["games-workshop"]  # sanity: all 4 products resolved (2 classified + 2 null-gameSystem)

    # gameSystem is optional now -- the resolver publishes null-gameSystem products instead of
    # parking them, so conflicts.yaml carries no unclassified-entity rows at all.
    assert read_yaml(paths.conflicts) == {"conflicts": []}

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


def test_build_queue_no_null_game_system_products_is_empty(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_yaml(paths.taxonomy / "manufacturers.yaml", {"manufacturers": []})
    write_yaml(paths.taxonomy / "game-systems.yaml", {"gameSystems": []})
    write_yaml(paths.taxonomy / "factions.yaml", {"factions": []})
    assert build_queue(paths) == []


def test_build_queue_missing_evidence_for_null_game_system_product_raises(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    write_yaml(paths.taxonomy / "manufacturers.yaml", {"manufacturers": []})
    write_yaml(paths.taxonomy / "game-systems.yaml", {"gameSystems": []})
    write_yaml(paths.taxonomy / "factions.yaml", {"factions": []})
    write_yaml(
        paths.catalog_products / "games-workshop.yaml",
        {
            "manufacturer": "games-workshop",
            "products": [
                {
                    "id": "games-workshop/ghost",
                    "name": "Ghost",
                    "manufacturer": "games-workshop",
                    "status": "current",
                    "firstSeen": "2026-01-01",
                    # The queue's population is `gameSystemsBasis: unknown`, not "gameSystems is
                    # null" -- a record without the basis is one `resolve` never wrote, and this
                    # test is about a QUEUED product whose evidence has gone missing.
                    "gameSystemsBasis": "unknown",
                }
            ],
        },
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


def test_a_paint_row_the_product_catalog_excludes_never_reaches_the_queues_join(tmp_path: Path) -> None:
    r"""The queue must join EXACTLY what the resolver joined -- shape taken from the real bug.

    `army-painter/CP3001` (Matt Black spray primer) is published from mfr-warlord-store plus two
    retailers. mfr-armypainter is a `catalog: paints` source whose row for the same can carries the
    variant code CP3001S and the same barcode 5713799300118, and it does NOT cross into products
    (one can is not a boxed set), so the resolver never sees it. The queue used to flatten the whole
    evidence store instead: the paint row rejoined the entity by barcode, and since `_priority`
    breaks a kind tie on the observation KEY, `mfr-armypainter:...` sorted ahead of
    `mfr-warlord-store:...` and CP3001S became the entity id -- so build_queue raised "has no
    matching evidence" for a product sitting in the catalog.

    Asserting only that it no longer raises would pass for the wrong reason (any change that made
    the paint row lose the tie would also stop the raise), so this pins the two things the shared
    selection actually guarantees: the id the catalog published, and the absence of the excluded
    row's hints from the queue item.
    """
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.taxonomy / "manufacturers.yaml",
        {"manufacturers": [{
            "slug": "army-painter", "name": "The Army Painter",
            "codePattern": r"CP\d{4}[A-Z]?", "gs1Prefixes": ["5713799"],
        }]},
    )
    write_yaml(paths.taxonomy / "game-systems.yaml", {"gameSystems": []})
    write_yaml(paths.taxonomy / "factions.yaml", {"factions": []})

    write_yaml(paths.sources / "mfr-warlord-store.yaml",
               {"id": "mfr-warlord-store", "kind": "manufacturer", "strategy": "shopify"})
    write_yaml(paths.sources / "ret-tistaminis.yaml",
               {"id": "ret-tistaminis", "kind": "retailer", "strategy": "shopify"})
    # A paint source that DOES declare a crossover -- so what excludes this row is the clause not
    # matching it, not the source lacking a rule entirely.
    write_yaml(
        paths.sources / "mfr-armypainter.yaml",
        {
            "id": "mfr-armypainter", "kind": "manufacturer", "strategy": "shopify-paints",
            "catalog": "paints",
            "crossoverToProducts": {
                "category": "paint-set",
                "reason": "boxed multi-pot sets are products; single cans are not",
                "anyOf": [{"hintContainsAny": {"tags": ["paint-set"]}}],
            },
        },
    )

    store = paths.evidence_products / "mfr-warlord-store" / "observations.jsonl"
    store.parent.mkdir(parents=True)
    store.write_text(
        _line({
            "key": "mfr-warlord-store:matt-black-base-primer-spray",
            "name": "Matt Black base primer spray", "manufacturer": "army-painter",
            "sku": "CP3001", "ean": "2540101130018", "hints": {"productType": "Spray Paint"},
            "firstSeen": "2026-08-01", "lastSeen": "2026-08-22", "extractor": "shopify@1",
        }),
        encoding="utf-8", newline="\n",
    )
    retailer = paths.evidence_products / "ret-tistaminis" / "observations.jsonl"
    retailer.parent.mkdir(parents=True)
    retailer.write_text(
        _line({
            "key": "ret-tistaminis:army-painter-colour-primer-matte-black-spray",
            "name": "Army Painter Colour Primer - Matte Black Spray",
            "manufacturer": "army-painter", "sku": "CP3001", "ean": "5713799300118",
            "firstSeen": "2026-08-01", "lastSeen": "2026-08-22", "extractor": "shopify@1",
        }),
        encoding="utf-8", newline="\n",
    )
    paint = paths.evidence_products / "mfr-armypainter" / "observations.jsonl"
    paint.parent.mkdir(parents=True)
    paint.write_text(
        _line({
            "key": "mfr-armypainter:colour-primers-colour-primer-matt-black-cp3001s",
            "name": "Colour Primer: Matt Black", "manufacturer": "army-painter",
            "sku": "CP3001S", "ean": "5713799300118",
            # `tags` deliberately misses the crossover clause: one can is not a boxed set.
            "hints": {"tags": ["colour-primers"], "paintOnly": "yes"},
            "firstSeen": "2026-08-01", "lastSeen": "2026-08-22", "extractor": "shopify-paints@1",
        }),
        encoding="utf-8", newline="\n",
    )

    catalog = resolve_catalog(paths)
    assert [product.id for product in catalog["army-painter"]] == ["army-painter/CP3001"]

    queue = build_queue(paths)
    assert [item["entity"] for item in queue] == ["army-painter/CP3001"]
    # The excluded row contributed nothing -- not its hints, and not its identity.
    assert queue[0]["hints"] == ["productType=Spray Paint"]


# --- real committed data ---------------------------------------------------------------------
# Uses a repo-root fixture rather than a package-relative one (see tests/test_repo_data.py):
# this package can be built/tested outside the monorepo (sdist), where ../../../../data does
# not exist -- skip cleanly in that case. Pure file reading only (no network, no LLM), so it
# stays fast.
REPO_DATA = Path(__file__).resolve().parents[3] / "data"


def test_repo_build_queue_covers_all_null_game_system_products() -> None:
    if not REPO_DATA.exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")
    paths = DataPaths(REPO_DATA)
    taxonomy = Taxonomy.load(paths.taxonomy)

    queue = build_queue(paths)

    # Self-consistency, not a literal: the figure moves with every committed `resolve` run.
    #
    # THE QUEUE IS NO LONGER "EVERY EMPTY gameSystems", and the gap between the two numbers is the
    # point of the basis field. A null gameSystem is either a hobby product that will never have
    # one or a game product nobody has classified; only the second is a question, and only the
    # second belongs in a queue that spends money to answer questions. Measured 2026-08-31 over
    # the committed catalog: 14,265 nulls, of which 5,885 not-applicable and 8,380 unknown.
    #
    # FOUR KINDS OF NULL SINCE THE SETTINGS AXIS (2026-09-02), not two: a product placed in a
    # SETTING and deliberately in no one game -- a Black Library novel, a period terrain piece --
    # has an empty `gameSystems` and reads `setting`, and it is not a question either; and a
    # maintainer can place a product in no game by hand (`override` with an empty list), which is
    # an answer, not a question.
    counts = {"null": 0, "unknown": 0, "not-applicable": 0, "setting": 0, "override": 0}
    if paths.catalog_products.exists():
        for path in paths.catalog_products.glob("*.yaml"):
            data = read_yaml(path) or {}
            for record in data.get("products") or []:
                basis = record.get("gameSystemsBasis")
                if not record.get("gameSystems"):
                    counts["null"] += 1
                    if basis == "override":
                        counts["override"] += 1
                if basis in counts and basis != "override":
                    counts[basis] += 1
    assert len(queue) == counts["unknown"]
    # And the split is real rather than a rename: every half is populated, and together they
    # account for every null. A regression that reverted the selector would trip this.
    assert counts["not-applicable"] > 0
    assert counts["setting"] > 0
    assert counts["unknown"] + counts["not-applicable"] + counts["setting"] + counts["override"] == counts["null"]

    # NOTHING IN THE QUEUE IS A PRODUCT WHOSE QUESTION DOES NOT APPLY. Paint is the population
    # that made this worth fixing: it was 41% of the queue and the first 176 batches of any
    # partial wave.
    resolved = {}
    for path in paths.catalog_products.glob("*.yaml"):
        for record in (read_yaml(path) or {}).get("products") or []:
            resolved[record["id"]] = record
    assert not [
        item["entity"] for item in queue
        if resolved[item["entity"]].get("gameSystemsBasis") != "unknown"
    ]
    for item in queue:
        assert item["name"]
        assert item["manufacturer"] in taxonomy.manufacturers
    assert [item["entity"] for item in queue] == sorted(item["entity"] for item in queue)


def test_html_is_flattened_before_the_description_is_truncated() -> None:
    """The 300-char window is a BUDGET, and markup spends it on nothing. Measured 2026-08-07 over
    the 999 live rows of AK's `paints-acrylics` category, a raw window is 45% prose on average and
    512 rows are under half prose -- and all 256 AK boxed sets have a null gameSystem, so all 256
    reach this queue. Flattening here rather than at acquire time is deliberate: retuning a prompt
    is free, retuning what was STORED costs a re-fetch (see strategies/woo_paints.py)."""
    from warhub_acquisition.classify.queue import _DESCRIPTION_LIMIT, _prompt_description

    raw = (
        '<span class="collapseomatic " id="englang" title="ENGLISH">ENGLISH</span>'
        '<div id="target-englang" class="collapseomatic_content ">\n'
        "<p>A <strong>QUICK GEN</strong> colour set for WWII German soldiers &#8211; three "
        "tones.</p>\n</div>"
    )
    flattened = _prompt_description(raw)
    assert "<" not in flattened
    assert flattened.startswith("ENGLISH A QUICK GEN colour set")
    assert "\u2013 three tones." in flattened  # &#8211; unescaped, not left as an entity

    # Tag-free descriptions are untouched, so this is byte-identical for the 11,949 of 11,953
    # committed descriptions that carry no markup at all.
    plain = "Contains:\n\n- AK17071 GERMAN GREY\n- AK17072 FIELD GREY\n"
    assert _prompt_description(plain) == plain
    assert len(_prompt_description("x" * 500)) == _DESCRIPTION_LIMIT
