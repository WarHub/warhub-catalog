"""The categorize stage: what it decides, what it refuses to decide, and what it may not touch.

The tests that matter most here are the NEGATIVE ones. A stage that fills a field which already
has a fallback behind it can go wrong invisibly -- every product still has a category either way --
so the interesting assertions are that a stated category survives, that packaging is not invented,
that a rule naming an undeclared value fails loudly, and that a dry run writes nothing.
"""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
import yaml

from warhub_acquisition.categorize.decide import decide, flatten_hints
from warhub_acquisition.categorize.lexicon import Lexicon, LexiconEntry, load_lexicon
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
    # Checked when the TABLE is built, not when the clause is: `noneOf` vetoes are the same type
    # and must decide nothing, so the two lists want opposite answers from one class.
    with pytest.raises(ValueError, match="decide at least one"):
        SourceRules.model_validate({
            "source": "ret-x", "reason": "measured",
            "clauses": [{"hintEquals": {"productType": "Paints"}}],
        })


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
    """One entity per outcome: an undecided row a rule reaches, an undecided row nothing reaches,
    a stated row a rule WOULD reach (and must not), and an undecided row only its barcode
    identifies."""
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


def test_the_stage_decides_the_undecided_and_leaves_claims_alone(tmp_path: Path) -> None:
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
    # Nothing reached it, so it stays honestly undecided rather than gaining a worse answer.
    assert after["games-workshop/MYST1"]["categoryBasis"] == "unknown"
    assert after["games-workshop/MYST1"].get("category") is None


def test_the_stage_changes_only_the_four_fields_it_owns(tmp_path: Path) -> None:
    """The catalog files are rewritten wholesale, so the guard is that a rewrite is a no-op for
    every field this stage does not decide -- ids included.

    `gameSystemsBasis` is the fourth, and it is here rather than in `resolve` because it is a
    question ABOUT the category: whether a game system applies to this product at all. `resolve`
    cannot answer it, because at that point a paint pot has no category at all -- nothing had
    decided yet. Settling it upstream asked one pass
    too early and returned `unknown` for 4,189 products that are plainly hobby supplies.
    """
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
    assert changed <= {"category", "categoryBasis", "packaging", "gameSystemsBasis"}


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
        "byBasis": {"mapped": 1, "paint-barcode": 1, "stated": 1, "unknown": 1},
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


# --- the name lexicon -------------------------------------------------------------------------


def test_a_lexicon_pattern_that_does_not_compile_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not compile"):
        LexiconEntry(nameMatches="(unclosed", category="book", measured="n/a")


def test_a_lexicon_entry_must_carry_its_measurement() -> None:
    """Required here, unlike a rule table's optional `note`. A lexicon entry is the weakest signal
    the stage acts on and the easiest to write carelessly, so the number that justified it belongs
    in the file rather than in a commit message nobody will find."""
    with pytest.raises(ValueError, match="measured"):
        LexiconEntry(nameMatches="x", category="book")


def test_lexicon_order_decides() -> None:
    """First match wins, so a narrow pattern goes first. This is the real case: `INDEX CARDS: DARK
    ANGELS` is a deck of reference cards, and the `INDEX` pattern would otherwise call 146 of them
    books -- categories.yaml puts reference cards in `game-accessory`, "played with, not read"."""
    lexicon = Lexicon(
        reason="test",
        entries=[
            LexiconEntry(nameMatches=r"\bINDEX CARDS\b", category="game-accessory", measured="n/a"),
            LexiconEntry(nameMatches=r"^\s*(CODEX|INDEX)\b", category="book", measured="n/a"),
        ],
    )
    assert lexicon.match("INDEX CARDS: DARK ANGELS (ENG)").category == "game-accessory"
    assert lexicon.match("INDEX: ADEPTA SORORITAS").category == "book"
    assert lexicon.match("Some Space Marines") is None


def test_the_lexicon_runs_only_when_nothing_stronger_did(tmp_path: Path) -> None:
    """LAST, and only on products still resting on a fallback. A store's filing and the paint
    catalog's barcode are statements about the product; a name pattern is an inference from how it
    is written, so it may not overrule either."""
    members = [_observation("ret-a:1", "ret-a", name="Big Brush 30ml", hints={"productType": "Bits"})]
    rules = _rules(**{"ret-a": [{"category": "hobby-auxiliary", "hintEquals": {"productType": "Bits"}}]})
    lexicon = Lexicon(
        reason="test",
        entries=[LexiconEntry(nameMatches=r"\b\d+\s?ML\b", category="paint", measured="n/a")],
    )
    kinds = {"ret-a": "retailer"}

    mapped, _ = decide("e", members, kinds, rules, [], frozenset(), "Big Brush 30ml", lexicon)
    assert (mapped.category, mapped.basis) == ("hobby-auxiliary", "mapped")

    by_barcode, _ = decide("e", members, kinds, {}, ["7"], frozenset({"7"}), "Big Brush 30ml", lexicon)
    assert (by_barcode.category, by_barcode.basis) == ("paint", "paint-barcode")

    by_name, _ = decide("e", members, kinds, {}, [], frozenset(), "Big Brush 30ml", lexicon)
    assert (by_name.category, by_name.basis) == ("paint", "lexicon")
    assert by_name.why == r"name matches /\b\d+\s?ML\b/"


def test_a_lexicon_entry_naming_an_undeclared_category_fails_the_run(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    write_yaml(
        paths.taxonomy / "category-lexicon.yaml",
        {"reason": "typo", "entries": [
            {"nameMatches": "Mystery", "category": "mystery-box", "measured": "n/a"}]},
    )
    with pytest.raises(ValueError, match="not declared"):
        categorize(paths)


def test_a_missing_lexicon_is_not_an_error(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    assert load_lexicon(paths.taxonomy) is None
    assert categorize(paths).decided == 2


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

    lexicon_path = REPO_ROOT / "data/catalog/taxonomy/category-lexicon.yaml"
    if lexicon_path.exists():
        lexicon = load_lexicon(REPO_ROOT / "data/catalog/taxonomy")
        assert lexicon.entries, "the lexicon exists but holds no entry"
        for entry in lexicon.entries:
            assert entry.category in categories, (
                f"lexicon: category {entry.category!r} is not declared in categories.yaml"
            )

    tables = load_category_rules(rules_dir)
    assert tables, "the rules directory exists but holds no table"
    systems = {
        entry["slug"] for entry in yaml.safe_load(
            (REPO_ROOT / "data/catalog/taxonomy/game-systems.yaml").read_text(encoding="utf-8")
        )["gameSystems"]
    }
    factions = {
        entry["slug"] for entry in yaml.safe_load(
            (REPO_ROOT / "data/catalog/taxonomy/factions.yaml").read_text(encoding="utf-8")
        )["factions"]
    }
    manufacturers = {
        entry["slug"] for entry in yaml.safe_load(
            (REPO_ROOT / "data/catalog/taxonomy/manufacturers.yaml").read_text(encoding="utf-8")
        )["manufacturers"]
    }
    for scope, table in tables.items():
        # A table is scoped to a FEED or to a MAKER, and each is held to its own register: a
        # source must have a descriptor, a manufacturer must be in the taxonomy. Either way a
        # table naming something that does not exist can never fire, and a dead table is
        # indistinguishable from a store that publishes no taxonomy.
        if table.manufacturer is not None:
            assert scope in manufacturers, f"{scope} is not a declared manufacturer"
        else:
            assert (sources_dir / f"{scope}.yaml").exists(), f"{scope} has no source descriptor"
        for clause in [*table.clauses, *table.noneOf]:
            assert clause.category is None or clause.category in categories, (
                f"{scope}: category {clause.category!r} is not declared in categories.yaml"
            )
            assert clause.packaging is None or clause.packaging in packagings, (
                f"{scope}: packaging {clause.packaging!r} is not declared in categories.yaml"
            )
            # A rule may not mint a game system or faction the taxonomy has never heard of --
            # the same guard the category vocabulary has always had, extended to the dimensions
            # a clause can now decide.
            unknown = [s for s in clause.gameSystems if s not in systems]
            assert not unknown, (
                f"{scope}: gameSystems {unknown!r} are not declared in game-systems.yaml"
            )
            assert clause.faction is None or clause.faction in factions, (
                f"{scope}: faction {clause.faction!r} is not declared in factions.yaml"
            )


# --- manufacturer tables: a maker's own product code as a signal ------------------------------

from warhub_acquisition.categorize.rules import SourceRules  # noqa: E402


def _table(**kwargs) -> dict:
    return {"reason": "measured", **kwargs}


def test_a_clause_must_decide_something_and_a_veto_must_decide_nothing() -> None:
    with pytest.raises(ValidationError, match="decide at least one"):
        SourceRules.model_validate(_table(
            manufacturer="m", clauses=[{"codeMatches": "^X", "note": "nothing"}]))
    with pytest.raises(ValidationError, match="must decide nothing"):
        SourceRules.model_validate(_table(
            manufacturer="m",
            clauses=[{"codeMatches": "^X", "gameSystems": ["g"]}],
            noneOf=[{"codeMatches": "^Y", "gameSystems": ["g"]}]))


def test_a_table_names_exactly_one_scope() -> None:
    with pytest.raises(ValidationError, match="exactly one of source/manufacturer"):
        SourceRules.model_validate(_table(clauses=[{"codeMatches": "^X", "gameSystems": ["g"]}]))
    with pytest.raises(ValidationError, match="exactly one of source/manufacturer"):
        SourceRules.model_validate(_table(
            source="s", manufacturer="m", clauses=[{"nameMatches": "x", "gameSystems": ["g"]}]))


def test_a_source_table_may_not_read_the_products_code() -> None:
    """A code belongs to the product; a source table only ever speaks for one store's own words."""
    with pytest.raises(ValidationError, match="does not own"):
        SourceRules.model_validate(_table(
            source="ret-x", clauses=[{"codeMatches": "^X", "gameSystems": ["g"]}]))


def test_code_clauses_match_the_product_code_not_the_name() -> None:
    from warhub_acquisition.resolve.crossover import clause_matches

    clause = {"codeMatches": r"^\d{4}02"}
    # GW digits 5-6 == 02 is Age of Sigmar.
    assert clause_matches("", {}, clause, "99120299039")
    assert not clause_matches("", {}, clause, "99120199039")
    # The name is not consulted, so a product merely *called* something cannot spoof a code rule.
    assert not clause_matches("99120299039", {}, clause, "")


def test_a_clause_answering_another_question_no_longer_swallows_the_category() -> None:
    """ONE SCAN PER AXIS. `mfr-b` files this product's GAME and says nothing about what it is;
    `ret-a` says what it is. Under the old single scan the higher-kind source matched first and
    the product came out with no category at all -- measured on the committed data, that was
    happening to 83 products, 80 of them ret-goblingaming rows blocked by mfr-manticgames."""
    members = [
        _observation("ret-a:1", "ret-a", hints={"productType": "Paints"}),
        _observation("mfr-b:1", "mfr-b", hints={"productType": "Kings of War"}),
    ]
    rules = _rules(
        **{
            "ret-a": [{"category": "paint", "hintEquals": {"productType": "Paints"}}],
            "mfr-b": [{"gameSystems": ["kings-of-war"], "hintEquals": {"productType": "Kings of War"}}],
        }
    )
    decision, _ = decide(
        "e", members, {"ret-a": "retailer", "mfr-b": "manufacturer"}, rules, [], frozenset()
    )
    assert (decision.category, decision.basis) == ("paint", "mapped")
    assert decision.gameSystems == ("kings-of-war",)


def test_a_packaging_only_clause_writes_its_packaging() -> None:
    """A table that settled only `packaging` used to write nothing at all, because the stage
    gated the write on the category. Five committed clauses did exactly that."""
    members = [_observation("ret-a:1", "ret-a", hints={"productType": "Digital"})]
    rules = _rules(**{"ret-a": [{"packaging": "digital", "hintEquals": {"productType": "Digital"}}]})
    decision, _ = decide("e", members, {"ret-a": "retailer"}, rules, [], frozenset())
    assert decision is not None
    assert (decision.category, decision.packaging) == (None, "digital")


def test_a_veto_silences_only_the_axes_it_names() -> None:
    """GW's Forge World veto is about the GAME -- the code names a production line that supplies
    six systems. It was also suppressing a `miniatures` answer that is 99.8% pure on the same
    products, because a veto used to stop the whole table."""
    rules = {
        "gw": SourceRules(
            manufacturer="gw",
            reason="test",
            noneOf=[CategoryClause(codeMatches=r"^\d{2}8[56]", blocks=["gameSystems"])],
            clauses=[
                CategoryClause(codeMatches=r"^\d{2}8[56]", category="miniatures"),
                CategoryClause(codeMatches=r"^\d{4}30", gameSystems=["horus-heresy"]),
            ],
        )
    }
    decision, _ = decide(
        "e", [], {}, rules, [], frozenset(), name="Astraeus", manufacturer="gw", code="99860112345",
    )
    assert (decision.category, decision.basis) == ("miniatures", "code")
    assert decision.gameSystems == ()


def test_a_veto_with_no_blocks_still_silences_everything() -> None:
    rules = {
        "gw": SourceRules(
            manufacturer="gw",
            reason="test",
            noneOf=[CategoryClause(codeMatches=r"^\d{2}8[56]")],
            clauses=[CategoryClause(codeMatches=r"^\d{2}8[56]", category="miniatures")],
        )
    }
    decision, _ = decide(
        "e", [], {}, rules, [], frozenset(), name="Astraeus", manufacturer="gw", code="99860112345",
    )
    assert decision is None


def test_a_veto_may_only_name_real_axes() -> None:
    with pytest.raises(ValidationError, match="not axes"):
        SourceRules.model_validate(_table(source="ret-x",
            clauses=[{"nameMatches": "x", "category": "paint"}],
            noneOf=[{"nameMatches": "y", "blocks": ["gameSystem"]}]))


def test_a_deciding_clause_may_not_block() -> None:
    with pytest.raises(ValidationError, match="for `noneOf` vetoes"):
        SourceRules.model_validate(_table(source="ret-x",
            clauses=[{"nameMatches": "x", "category": "paint", "blocks": ["faction"]}]))


# --- a rule may EXTEND a claim on a set-valued field, never contradict one ----------------------


def _record(**kw):
    from warhub_acquisition.models.catalog import CanonicalProduct
    base = dict(id="m/1", name="Forge Father Squad", manufacturer="m", status="current",
                firstSeen="2026-07-01")
    return CanonicalProduct(**{**base, **kw})


def _decision(*systems):
    from warhub_acquisition.categorize.decide import Decision
    return Decision(category=None, packaging=None, basis="", why="",
                    gameSystems=tuple(systems), game_systems_basis="mapped",
                    game_systems_why="mfr-m categories~firefight-forge-fathers")


def _outcome():
    from warhub_acquisition.categorize.stage import Outcome
    return Outcome()


def test_a_rule_adds_a_membership_the_source_could_not_state() -> None:
    """MANTIC SELLS ONE BOX INTO TWO GAMES. legacy-catalog had to pick one and picked `deadzone`;
    the store's own shelves say Deadzone AND Firefight. Adding the second contradicts nothing --
    the rule's set contains everything the catalog already claims."""
    from warhub_acquisition.categorize.stage import _apply_game_systems
    record = _record(gameSystems=["deadzone"], gameSystemsBasis="stated")
    outcome = _outcome()
    assert _apply_game_systems(record, _decision("deadzone", "firefight"), outcome, frozenset())
    assert record.gameSystems == ["deadzone", "firefight"]
    assert outcome.conflicts == []


def test_a_rule_that_would_drop_a_stated_system_is_reported_instead() -> None:
    from warhub_acquisition.categorize.stage import _apply_game_systems
    record = _record(gameSystems=["deadzone"], gameSystemsBasis="stated")
    outcome = _outcome()
    assert not _apply_game_systems(record, _decision("firefight"), outcome, frozenset())
    assert record.gameSystems == ["deadzone"]
    assert [c.kind for c in outcome.conflicts] == ["gameSystem-disagreement"]


def test_an_empty_list_is_filled_by_the_same_containment_test() -> None:
    from warhub_acquisition.categorize.stage import _apply_game_systems
    record = _record(gameSystemsBasis="unknown")
    outcome = _outcome()
    assert _apply_game_systems(record, _decision("firefight"), outcome, frozenset())
    assert (record.gameSystems, record.gameSystemsBasis) == (["firefight"], "mapped")


def test_a_maintainers_decision_is_never_extended() -> None:
    """The 78 Kill Team entries in overrides.yaml are a decision that those products are
    `kill-team` AND NOT `warhammer-40k`. Extending the set would quietly undo it."""
    from warhub_acquisition.categorize.stage import _apply_game_systems
    record = _record(gameSystems=["kill-team"], gameSystemsBasis="override")
    outcome = _outcome()
    assert not _apply_game_systems(
        record, _decision("kill-team", "warhammer-40k"), outcome, frozenset())
    assert record.gameSystems == ["kill-team"]
    # ...AND IT IS NOT REPORTED EITHER. An override is the record that someone weighed this exact
    # product, so a source contradicting it is the thing they decided against, not an open
    # question. GW's own store shelves those Kill Team boxes under `Warhammer 40,000 > Unit Type`
    # -- which is WHY the overrides exist -- and reporting that every night would be the review
    # file arguing with a decision instead of surfacing one.
    assert outcome.conflicts == []


def test_a_catch_all_is_replaced_rather_than_extended() -> None:
    from warhub_acquisition.categorize.stage import _apply_game_systems
    record = _record(gameSystems=["other-games"], gameSystemsBasis="stated")
    outcome = _outcome()
    assert _apply_game_systems(record, _decision("necromunda"), outcome, frozenset({"other-games"}))
    assert record.gameSystems == ["necromunda"]


def test_a_catch_all_beside_a_real_claim_is_not_replaced() -> None:
    """Refining `[other-games]` is informative; replacing `[warhammer-40k, other-games]` would drop
    a real claim to gain a guess."""
    from warhub_acquisition.categorize.stage import _apply_game_systems
    record = _record(gameSystems=["other-games", "warhammer-40k"], gameSystemsBasis="stated")
    outcome = _outcome()
    assert not _apply_game_systems(
        record, _decision("necromunda"), outcome, frozenset({"other-games"}))
    assert record.gameSystems == ["other-games", "warhammer-40k"]


def test_a_rule_that_merely_agrees_does_not_demote_the_basis() -> None:
    """AGREEMENT IS NOT AN EXTENSION. A table naming exactly what a source already stated must
    leave the record alone -- rewriting it would set `gameSystemsBasis: mapped` and lose the fact
    that a source said it. Measured when the test read `<=` instead of `<`: 4,242 products
    silently traded `stated` provenance for a rule that agreed with them."""
    from warhub_acquisition.categorize.stage import _apply_game_systems
    record = _record(gameSystems=["firefight"], gameSystemsBasis="stated")
    outcome = _outcome()
    assert not _apply_game_systems(record, _decision("firefight"), outcome, frozenset())
    assert (record.gameSystems, record.gameSystemsBasis) == (["firefight"], "stated")
    assert outcome.conflicts == []
