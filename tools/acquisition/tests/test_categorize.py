"""The categorize stage: what it decides, what it refuses to decide, and what it may not touch.

The tests that matter most here are the NEGATIVE ones. A stage that fills a field which already
has a fallback behind it can go wrong invisibly -- every product still has a category either way --
so the interesting assertions are that a stated category survives, that packaging is not invented,
that a rule naming an undeclared value fails loudly, and that a dry run writes nothing.
"""
import json
from pathlib import Path

import pytest
import yaml

from warhub_acquisition.categorize.decide import decide, flatten_hints
from warhub_acquisition.categorize.paints import load_paint_barcodes
from warhub_acquisition.categorize.rules import (
    CategoryClause,
    SourceRules,
    load_category_rules,
)
from warhub_acquisition.categorize.stage import categorize
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import read_yaml, write_yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

VOCABULARY = {
    "categories": [
        {"slug": "miniatures", "label": "Miniatures"},
        {"slug": "paint", "label": "Paint"},
        {"slug": "paint-set", "label": "Paint set"},
        {"slug": "book", "label": "Book"},
        {"slug": "hobby-auxiliary", "label": "Hobby auxiliary"},
    ],
    "packaging": [
        {"slug": "single", "label": "Single"},
        {"slug": "set", "label": "Set"},
        {"slug": "digital", "label": "Digital"},
    ],
}


def _line(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def _observation(key: str, source: str, **kwargs) -> Observation:
    payload = {
        "key": key, "name": kwargs.pop("name", "Thing"), "manufacturer": "games-workshop",
        "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "test@1",
    }
    payload.update(kwargs)
    return Observation.model_validate(payload)


# --- rule files -------------------------------------------------------------------------------


def test_a_clause_must_carry_exactly_one_signal() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        CategoryClause(category="paint")
    with pytest.raises(ValueError, match="exactly one"):
        CategoryClause(category="paint", hintEquals={"productType": "Paints"}, nameMatches="paint")


def test_a_clause_that_decides_nothing_is_rejected() -> None:
    """A clause with a signal and no outcome matches rows and then does nothing to them -- which
    reads, in a table of 40 lines, exactly like a store that stopped using that value."""
    with pytest.raises(ValueError, match="category.*packaging"):
        CategoryClause(hintEquals={"productType": "Paints"})


def test_a_packaging_only_clause_is_allowed() -> None:
    """`Digital` on a store's shelf establishes the FORM and nothing about the contents; forcing
    such a clause to invent a category would be the guess this stage exists to remove."""
    clause = CategoryClause(packaging="digital", hintEquals={"productType": "Digital"})
    assert clause.category is None


def test_an_empty_table_is_rejected() -> None:
    with pytest.raises(ValueError, match="decides nothing"):
        SourceRules(source="ret-x", reason="because", clauses=[])


def test_the_filename_must_name_the_source(tmp_path: Path) -> None:
    """Two ways to say which source a table applies to is how one ends up applying to a source it
    does not name -- invisibly, because a table that matches nothing looks like a store with no
    taxonomy."""
    write_yaml(
        tmp_path / "ret-goblingaming.yaml",
        {"source": "ret-tistaminis", "reason": "typo", "clauses": [
            {"category": "paint", "hintEquals": {"productType": "Paints"}}]},
    )
    with pytest.raises(ValueError, match="the filename must match"):
        load_category_rules(tmp_path)


def test_a_missing_rules_directory_is_not_an_error(tmp_path: Path) -> None:
    assert load_category_rules(tmp_path / "nope") == {}


# --- the decision -----------------------------------------------------------------------------


def test_flatten_hints_addresses_a_nested_level() -> None:
    flat = flatten_hints({"hierarchy": {"lvl1": ["A > Unit Type"]}, "tags": ["x"], "productType": "P"})
    assert flat == {"hierarchy.lvl1": ["A > Unit Type"], "tags": ["x"], "productType": "P"}


def _rules(**by_source) -> dict:
    return {
        source: SourceRules(source=source, reason="test", clauses=[CategoryClause(**c) for c in clauses])
        for source, clauses in by_source.items()
    }


def test_the_higher_kind_decides_when_two_sources_both_match() -> None:
    members = [
        _observation("ret-a:1", "ret-a", hints={"productType": "Bits"}),
        _observation("mfr-b:1", "mfr-b", hints={"productType": "Paint Pot"}),
    ]
    rules = _rules(
        **{
            "ret-a": [{"category": "hobby-auxiliary", "hintEquals": {"productType": "Bits"}}],
            "mfr-b": [{"category": "paint", "hintEquals": {"productType": "Paint Pot"}}],
        }
    )
    decision, conflicts = decide(
        "e", members, {"ret-a": "retailer", "mfr-b": "manufacturer"}, rules, [], frozenset()
    )
    assert (decision.category, decision.basis) == ("paint", "mapped")
    assert decision.why == "mfr-b productType=Paint Pot"
    # Cross-kind disagreement is what the ladder is FOR and must not be reported, or the real
    # same-kind splits would be buried under thousands of these.
    assert conflicts == []


def test_two_sources_of_the_same_kind_disagreeing_is_reported() -> None:
    members = [
        _observation("ret-a:1", "ret-a", hints={"productType": "Bits"}),
        _observation("ret-b:1", "ret-b", hints={"productType": "Paints"}),
    ]
    rules = _rules(
        **{
            "ret-a": [{"category": "hobby-auxiliary", "hintEquals": {"productType": "Bits"}}],
            "ret-b": [{"category": "paint", "hintEquals": {"productType": "Paints"}}],
        }
    )
    decision, conflicts = decide(
        "e", members, {"ret-a": "retailer", "ret-b": "retailer"}, rules, [], frozenset()
    )
    assert decision.category == "hobby-auxiliary"  # deterministic: kind tie broken on the key
    assert [c.kind for c in conflicts] == ["category-disagreement"]
    assert "ret-a=hobby-auxiliary" in conflicts[0].detail
    assert "ret-b=paint" in conflicts[0].detail


def test_a_paint_barcode_decides_a_product_no_table_reached() -> None:
    members = [_observation("ret-a:1", "ret-a", hints={"productType": "Unmapped"})]
    decision, conflicts = decide(
        "e", members, {"ret-a": "retailer"}, {}, ["5011921194506"], frozenset({"5011921194506"})
    )
    assert (decision.category, decision.basis) == ("paint", "paint-barcode")
    assert conflicts == []


def test_a_paint_barcode_never_overrules_a_stores_own_filing() -> None:
    """THE PRECEDENCE, and the reason it is that way round. Vallejo's Diorama Effects pastes are
    carried by the paint catalog and filed by Goblin Gaming as Basing Materials; the vocabulary's
    own boundary says a colourless texture paste is `hobby-auxiliary`, so the store is right and a
    cross-catalog inference must not overrule it. It is reported instead -- measured 2026-08-25 on
    the committed data, this fires on exactly 7 products, all of them that Vallejo range."""
    members = [_observation("ret-a:1", "ret-a", hints={"productType": "Basing Materials"})]
    rules = _rules(
        **{"ret-a": [{"category": "hobby-auxiliary", "hintEquals": {"productType": "Basing Materials"}}]}
    )
    decision, conflicts = decide(
        "e", members, {"ret-a": "retailer"}, rules, ["4"], frozenset({"4"})
    )
    assert decision.category == "hobby-auxiliary"
    assert [c.kind for c in conflicts] == ["paint-barcode-vs-taxonomy"]


def test_a_packaging_only_match_still_lets_the_barcode_decide_the_category() -> None:
    members = [_observation("ret-a:1", "ret-a", hints={"productType": "Digital"})]
    rules = _rules(**{"ret-a": [{"packaging": "digital", "hintEquals": {"productType": "Digital"}}]})
    decision, _ = decide("e", members, {"ret-a": "retailer"}, rules, ["9"], frozenset({"9"}))
    assert (decision.category, decision.packaging, decision.basis) == ("paint", "digital", "paint-barcode")


def test_nothing_matches_means_no_decision() -> None:
    members = [_observation("ret-a:1", "ret-a", hints={"productType": "Whatever"})]
    decision, conflicts = decide("e", members, {"ret-a": "retailer"}, {}, ["1"], frozenset({"2"}))
    assert decision is None and conflicts == []


# --- the stage --------------------------------------------------------------------------------


def _seed(tmp_path: Path) -> DataPaths:
    """One entity per outcome: a guessed row a rule reaches, a guessed row nothing reaches, a
    stated row a rule WOULD reach (and must not), and a guessed row only its barcode identifies."""
    paths = DataPaths(tmp_path)
    # A codePattern, so the fixture's entity ids are CODE-based like the real catalog's rather
    # than name slugs -- the stage looks records up by id, and a slug id would exercise a
    # different lookup than production uses.
    write_yaml(
        paths.taxonomy / "manufacturers.yaml",
        {"manufacturers": [
            {"slug": "games-workshop", "name": "Games Workshop", "codePattern": r"[A-Z]+\d+"}
        ]},
    )
    write_yaml(paths.taxonomy / "game-systems.yaml", {"gameSystems": []})
    write_yaml(paths.taxonomy / "factions.yaml", {"factions": []})
    write_yaml(paths.taxonomy / "categories.yaml", VOCABULARY)
    write_yaml(paths.sources / "ret-shop.yaml",
               {"id": "ret-shop", "kind": "retailer", "strategy": "shopify"})

    evidence = paths.evidence_products / "ret-shop" / "observations.jsonl"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        _line({"key": "ret-shop:brush", "name": "Big Brush", "manufacturer": "games-workshop",
               "sku": "BRUSH1", "hints": {"productType": "Brushes"},
               "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "shopify@1"})
        + _line({"key": "ret-shop:mystery", "name": "Mystery Thing", "manufacturer": "games-workshop",
                 "sku": "MYST1", "hints": {"productType": "Unlabelled"},
                 "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "shopify@1"})
        + _line({"key": "ret-shop:tome", "name": "Some Codex", "manufacturer": "games-workshop",
                 "sku": "TOME1", "hints": {"productType": "Brushes", "category": "book"},
                 "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "shopify@1"})
        + _line({"key": "ret-shop:pot", "name": "A Pot", "manufacturer": "games-workshop",
                 "sku": "POT1", "ean": "5011921194506", "hints": {"productType": "Unlabelled"},
                 "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "shopify@1"}),
        encoding="utf-8", newline="\n",
    )

    brands = paths.paints / "brands"
    brands.mkdir(parents=True)
    write_yaml(brands / "citadel.yaml", {"paints": [{"name": "A Pot", "ean": "5011921194506"}]})

    write_yaml(
        paths.category_rules / "ret-shop.yaml",
        {
            "source": "ret-shop",
            "reason": "the shop's product_type is a format axis",
            "clauses": [{"category": "hobby-auxiliary", "packaging": "single",
                         "hintEquals": {"productType": "Brushes"}}],
        },
    )
    resolve_catalog(paths)
    return paths


def _catalog(paths: DataPaths) -> dict[str, dict]:
    return {
        record["id"]: record
        for path in sorted(paths.catalog_products.glob("*.yaml"))
        for record in (read_yaml(path) or {}).get("products") or []
    }


def test_the_stage_decides_guesses_and_leaves_claims_alone(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    before = _catalog(paths)
    assert before["games-workshop/TOME1"]["categoryBasis"] == "stated"

    outcome = categorize(paths)
    after = _catalog(paths)

    assert (outcome.considered, outcome.decided) == (3, 2)
    assert (after["games-workshop/BRUSH1"]["category"], after["games-workshop/BRUSH1"]["categoryBasis"]) == (
        "hobby-auxiliary", "mapped",
    )
    assert (after["games-workshop/POT1"]["category"], after["games-workshop/POT1"]["categoryBasis"]) == (
        "paint", "paint-barcode",
    )
    # A source's claim about ONE product outranks a table about a shelf -- even though this row's
    # productType matches the Brushes clause, which is why the fixture gives it that value.
    assert after["games-workshop/TOME1"]["category"] == "book"
    assert after["games-workshop/TOME1"]["categoryBasis"] == "stated"
    # Nothing reached it, so it keeps the honest guess rather than gaining a worse answer.
    assert after["games-workshop/MYST1"]["categoryBasis"] == "guessed"


def test_the_stage_changes_only_the_three_fields_it_owns(tmp_path: Path) -> None:
    """The catalog files are rewritten wholesale, so the guard is that a rewrite is a no-op for
    every field this stage does not decide -- ids included."""
    paths = _seed(tmp_path)
    before = _catalog(paths)
    categorize(paths)
    after = _catalog(paths)

    assert set(before) == set(after)
    changed = {
        key
        for pid in before
        for key in set(before[pid]) | set(after[pid])
        if before[pid].get(key) != after[pid].get(key)
    }
    assert changed <= {"category", "categoryBasis", "packaging"}


def test_packaging_is_filled_only_where_the_record_had_none(tmp_path: Path) -> None:
    """A clause infers packaging from a shelf label; a source states it about the product. The
    inference must never overwrite the statement."""
    paths = _seed(tmp_path)
    path = paths.catalog_products / "games-workshop.yaml"
    document = read_yaml(path)
    for record in document["products"]:
        if record["id"] == "games-workshop/BRUSH1":
            record["packaging"] = "set"
    write_yaml(path, document)

    categorize(paths)
    assert _catalog(paths)["games-workshop/BRUSH1"]["packaging"] == "set"


def test_a_dry_run_writes_nothing(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    before = {p: p.read_bytes() for p in sorted(paths.catalog_products.glob("*.yaml"))}

    outcome = categorize(paths, apply=False)

    assert outcome.decided == 2
    assert {p: p.read_bytes() for p in sorted(paths.catalog_products.glob("*.yaml"))} == before
    assert not paths.categorize_review.exists()


def test_a_rule_naming_an_undeclared_category_fails_the_run(tmp_path: Path) -> None:
    """Validated against the TABLE, not just its output: a clause naming an undeclared value that
    happens to match nothing today would sit undetected until the day the store adds that value."""
    paths = _seed(tmp_path)
    write_yaml(
        paths.category_rules / "ret-shop.yaml",
        {
            "source": "ret-shop", "reason": "typo",
            "clauses": [{"category": "miniature", "hintEquals": {"productType": "Never Seen"}}],
        },
    )
    with pytest.raises(ValueError, match="not declared"):
        categorize(paths)


def test_the_worklist_counts_only_products_that_are_still_undecided(tmp_path: Path) -> None:
    """What makes `unmapped` a worklist rather than a census. A raw value appearing on 900
    already-decided products is not work; one appearing on 900 undecided ones is the next table
    entry worth writing."""
    paths = _seed(tmp_path)
    categorize(paths)
    review = read_yaml(paths.categorize_review)

    assert review["summary"] == {
        "products": 4, "undecided": 1, "decidedThisRun": 2,
        "byBasis": {"guessed": 1, "mapped": 1, "paint-barcode": 1, "stated": 1},
    }
    values = {row["value"] for row in review["unmapped"]["ret-shop"]}
    assert values == {"productType=Unlabelled"}  # the decided rows' values are absent
    assert review["deadClauses"] == []


def test_the_summary_survives_a_second_run(tmp_path: Path) -> None:
    """Running twice is a no-op the second time -- the first left nothing replaceable -- so a
    report phrased as "decided N this run" would read 0 for a perfectly healthy catalog. The
    catalog figures have to be the ones that mean something, or the section trains a reader to
    ignore it."""
    paths = _seed(tmp_path)
    categorize(paths)
    first = read_yaml(paths.categorize_review)["summary"]
    outcome = categorize(paths)
    second = read_yaml(paths.categorize_review)["summary"]

    assert outcome.decided == 0 and second["decidedThisRun"] == 0
    assert {k: v for k, v in first.items() if k != "decidedThisRun"} == {
        k: v for k, v in second.items() if k != "decidedThisRun"
    }


def test_a_dead_clause_is_reported(tmp_path: Path) -> None:
    """A clause matching NO observation is nearly always a typo -- `hintEquals` is exact and a
    store's value can differ by a case or a stray space ("Paint set" beside "Paint Set" at
    Warlord, both real). Nothing announces it: a table with a broken line and a store with no
    taxonomy produce identical output. Counted over ALL evidence, not over what this run decided,
    because otherwise every clause looks dead once the catalog is already categorized -- which is
    exactly when someone reads the file."""
    paths = _seed(tmp_path)
    write_yaml(
        paths.category_rules / "ret-shop.yaml",
        {
            "source": "ret-shop", "reason": "one live clause and one typo",
            "clauses": [
                {"category": "hobby-auxiliary", "hintEquals": {"productType": "Brushes"}},
                {"category": "paint", "hintEquals": {"productType": "brushes"}},
            ],
        },
    )
    categorize(paths)
    assert read_yaml(paths.categorize_review)["deadClauses"] == ["ret-shop productType=brushes"]


def test_a_table_for_a_paint_source_is_refused(tmp_path: Path) -> None:
    """DEAD BY CONSTRUCTION, and it took two committed tables to notice.
    `select_product_observations` admits a `catalog: paints` source's rows only where
    `crossoverToProducts` selects them, and every selected row arrives with a category already
    stamped -- so it is `stated` and this stage never reaches it. Tables for mfr-monument and
    mfr-turbodork were written and committed before the dead-clause report showed all fourteen of
    their clauses matching nothing."""
    paths = _seed(tmp_path)
    write_yaml(
        paths.sources / "mfr-pots.yaml",
        {"id": "mfr-pots", "kind": "manufacturer", "strategy": "shopify-paints", "catalog": "paints"},
    )
    write_yaml(
        paths.category_rules / "mfr-pots.yaml",
        {"source": "mfr-pots", "reason": "looks useful, cannot fire",
         "clauses": [{"category": "paint", "hintEquals": {"productType": "Paint"}}]},
    )
    with pytest.raises(ValueError, match="can never fire"):
        categorize(paths)


# --- the committed tables ---------------------------------------------------------------------


def test_every_committed_rule_file_names_a_real_source_and_declared_values() -> None:
    """A table for a source that does not exist, or naming a category the vocabulary does not
    declare, decides nothing and says nothing about it -- so it is checked here rather than being
    discovered on the night a store starts emitting the value."""
    rules_dir = REPO_ROOT / "data/catalog/taxonomy/category-rules"
    if not rules_dir.exists():
        pytest.skip("no committed rule tables")
    sources_dir = REPO_ROOT / "data/catalog/sources"
    vocabulary = yaml.safe_load(
        (REPO_ROOT / "data/catalog/taxonomy/categories.yaml").read_text(encoding="utf-8")
    )
    categories = {entry["slug"] for entry in vocabulary["categories"]}
    packagings = {entry["slug"] for entry in vocabulary["packaging"]}

    tables = load_category_rules(rules_dir)
    assert tables, "the rules directory exists but holds no table"
    for source, table in tables.items():
        assert (sources_dir / f"{source}.yaml").exists(), f"{source} has no source descriptor"
        for clause in table.clauses:
            assert clause.category is None or clause.category in categories, (
                f"{source}: category {clause.category!r} is not declared in categories.yaml"
            )
            assert clause.packaging is None or clause.packaging in packagings, (
                f"{source}: packaging {clause.packaging!r} is not declared in categories.yaml"
            )
