from pathlib import Path

from warhub_acquisition.models.descriptor import KIND_PRIORITY, SourceDescriptor, load_descriptors
from warhub_acquisition.yamlio import write_yaml


def test_load_descriptors(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "ret-goblin.yaml",
        {
            "id": "ret-goblin",
            "kind": "retailer",
            "strategy": "shopify",
            "baseUrl": "https://www.goblingaming.co.uk",
            "contract": {"minCount": 8000, "requiredFieldRates": {"name": 1.0, "ean": 0.6}},
        },
    )
    descriptors = load_descriptors(tmp_path)
    assert descriptors["ret-goblin"].kind == "retailer"
    assert descriptors["ret-goblin"].contract.minCount == 8000


def test_kind_priority_ordering() -> None:
    assert KIND_PRIORITY["curated"] < KIND_PRIORITY["manufacturer"] < KIND_PRIORITY["retailer"]
    assert KIND_PRIORITY["retailer"] < KIND_PRIORITY["archive"] < KIND_PRIORITY["barcode-db"]


def test_filename_must_match_id(tmp_path: Path) -> None:
    write_yaml(tmp_path / "wrong-name.yaml", {"id": "ret-goblin", "kind": "retailer", "strategy": "shopify"})
    import pytest

    with pytest.raises(ValueError, match="wrong-name"):
        load_descriptors(tmp_path)


# --- crossoverToProducts validation ----------------------------------------------------------

VALID_CROSSOVER = {
    "reason": "boxed sets are products; measured 2026-08-05",
    "category": "paint-set",
    "anyOf": [{"nameMatches": r"\bSET\b"}],
}


def test_crossover_parses_on_a_paint_source(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "mfr-gsw.yaml",
        {"id": "mfr-gsw", "kind": "manufacturer", "catalog": "paints",
         "strategy": "sitemap-sd-paints",
         "crossoverToProducts": {**VALID_CROSSOVER,
                                 "noneOf": [{"hintContainsAny": {"tags": ["brushset"]}}]}},
    )
    rule = load_descriptors(tmp_path)["mfr-gsw"].crossoverToProducts
    assert rule.category == "paint-set"
    assert rule.anyOf[0].nameMatches == r"\bSET\b"
    assert rule.noneOf[0].hintContainsAny == {"tags": ["brushset"]}


def test_crossover_on_a_products_source_raises() -> None:
    """A products source already reaches the product catalog whole, so a carve-out there is
    inert -- far more likely a typo than an intent."""
    import pytest

    with pytest.raises(ValueError, match="requires `catalog: paints`"):
        SourceDescriptor.model_validate(
            {"id": "mfr-gw", "kind": "manufacturer", "strategy": "algolia",
             "crossoverToProducts": VALID_CROSSOVER}
        )


def test_crossover_clause_must_set_exactly_one_form() -> None:
    """A clause is ONE signal; `anyOf` is where signals combine. Two forms in one clause would
    silently mean AND, which no source needs and every reader would have to guess at.

    The empty forms are rejected for a different reason: `resolve/crossover.clause_matches` reads
    these keys with `if clause.get(...)`, i.e. TRUTHINESS, so `nameMatches: ''` or
    `hintEquals: {}` would have validated cleanly and then matched nothing -- a crossover block
    that selects zero rows while the whole suite stays green. A validator and an evaluator
    disagreeing about what counts as "set" is how a dead descriptor gets written.
    """
    import pytest

    for clause in (
        {},
        {"nameMatches": r"\bSET\b", "hintEquals": {"a": "b"}},
        {"nameMatches": ""},
        {"hintEquals": {}},
        {"hintContainsAny": {}},
    ):
        with pytest.raises(ValueError, match="exactly one NON-EMPTY of"):
            SourceDescriptor.model_validate(
                {"id": "mfr-gsw", "kind": "manufacturer", "catalog": "paints",
                 "strategy": "sitemap-sd-paints",
                 "crossoverToProducts": {**VALID_CROSSOVER, "anyOf": [clause]}}
            )


def test_crossover_requires_at_least_one_any_of_clause() -> None:
    """A block that selects nothing is a block someone forgot to finish."""
    import pytest

    with pytest.raises(ValueError):
        SourceDescriptor.model_validate(
            {"id": "mfr-gsw", "kind": "manufacturer", "catalog": "paints",
             "strategy": "sitemap-sd-paints",
             "crossoverToProducts": {**VALID_CROSSOVER, "anyOf": []}}
        )


def test_crossover_rejects_unknown_keys() -> None:
    """extra="forbid" throughout: a misspelled `nameMatch` must fail CI, not silently select
    nothing (which would look exactly like a store that stopped shipping sets)."""
    import pytest

    with pytest.raises(ValueError):
        SourceDescriptor.model_validate(
            {"id": "mfr-gsw", "kind": "manufacturer", "catalog": "paints",
             "strategy": "sitemap-sd-paints",
             "crossoverToProducts": {**VALID_CROSSOVER, "anyOf": [{"nameMatch": r"\bSET\b"}]}}
        )
