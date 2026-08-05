# tools/acquisition/tests/test_crossover.py
"""The shared set predicate (resolve/crossover.py), on plain dicts and no repo data.

This module is the single point where the product resolver and the paint bridge agree on which
observations are boxed SETS. Everything here is a fixture: the repo-data half of the contract
(does each descriptor's declaration select what its reason claims?) lives in test_repo_data.py.
"""
import re
from pathlib import Path

from warhub_acquisition.resolve import crossover


def _observation(name: str = "Paint", **hints: object) -> dict:
    return {"name": name, "hints": dict(hints)}


def _rule(any_of: list[dict], none_of: list[dict] | None = None) -> dict:
    return {"reason": "x", "category": "paint-set", "anyOf": any_of, "noneOf": none_of or []}


# --- T5: each clause type in isolation ------------------------------------------------------


def test_name_matches_is_case_insensitive() -> None:
    rule = _rule([{"nameMatches": r"\bSET\b"}])
    assert crossover.matches(_observation("Warpaints Air Starter Set"), rule)
    assert crossover.matches(_observation("paint set - chrome"), rule)
    assert not crossover.matches(_observation("Wonka Violet"), rule)
    # word-boundary, not substring: "Sunset" must not read as "set"
    assert not crossover.matches(_observation("Sunset Orange"), rule)


def test_hint_equals_on_a_scalar_hint() -> None:
    rule = _rule([{"hintEquals": {"categorySlug": "paint-sets"}}])
    assert crossover.matches(_observation("Box", categorySlug="paint-sets"), rule)
    assert not crossover.matches(_observation("Box", categorySlug="chrome-paints"), rule)


def test_hint_equals_requires_every_pair() -> None:
    """Multiple pairs inside ONE hintEquals clause are an AND -- that is what `all` means."""
    rule = _rule([{"hintEquals": {"categorySlug": "paint-sets", "line": "chrome"}}])
    assert crossover.matches(_observation("Box", categorySlug="paint-sets", line="chrome"), rule)
    assert not crossover.matches(_observation("Box", categorySlug="paint-sets", line="fluor"), rule)


def test_hint_contains_any_intersects_a_list_hint() -> None:
    rule = _rule([{"hintContainsAny": {"categorySlugs": ["3rd-set", "b2b-3gen-sets"]}}])
    assert crossover.matches(_observation("Box", categorySlugs=["paints", "3rd-set"]), rule)
    assert not crossover.matches(_observation("Box", categorySlugs=["paints", "3rd-acrylics"]), rule)


def test_hint_contains_any_on_a_scalar_hint_is_membership() -> None:
    """A store that emits one value rather than a list still answers the same question."""
    rule = _rule([{"hintContainsAny": {"productType": ["Paint Sets", "Bundles"]}}])
    assert crossover.matches(_observation("Box", productType="Paint Sets"), rule)
    assert not crossover.matches(_observation("Box", productType="Paint Singles"), rule)


def test_any_of_is_an_or() -> None:
    rule = _rule([{"hintEquals": {"categorySlug": "paint-sets"}}, {"nameMatches": r"\bSET\b"}])
    assert crossover.matches(_observation("Nothing special", categorySlug="paint-sets"), rule)
    assert crossover.matches(_observation("Set x8 Fluor Paints", categorySlug="fluorescent"), rule)
    assert not crossover.matches(_observation("Wonka Violet", categorySlug="acrylic-paints"), rule)


# --- T6: the Army Painter regression --------------------------------------------------------


def test_hint_contains_any_is_exact_value_never_substring() -> None:
    """THE Army Painter regression, measured 2026-08-05.

    The 7 brush sets carry the exact tag `brushset`; the four genuine airbrush paint SETS
    (AW8001P-AW8004P) carry `Airbrush Warpaints` / `SDS Airbrush Sets`, which contain the
    substring. A substring test would veto all four real sets to exclude the 7.
    """
    veto = {"hintContainsAny": {"tags": ["brushset"]}}
    rule = _rule([{"nameMatches": r"\bSET\b"}], [veto])

    brush = _observation("Wet Palette Set", tags=["tap-shop", "brushset"])
    assert not crossover.matches(brush, rule)

    for tags in (["AIR", "Airbrush Warpaints"], ["Air Sets", "SDS Airbrush Sets"]):
        airbrush = _observation("Warpaints Air Starter Set", tags=tags)
        assert crossover.matches(airbrush, rule), tags


# --- T7: noneOf ------------------------------------------------------------------------------


def test_none_of_vetoes_a_row_any_of_selects() -> None:
    rule = _rule(
        [{"hintContainsAny": {"collections": ["floww-oleos"]}}],
        [{"nameMatches": r"\bCASE\b"}],
    )
    assert crossover.matches(_observation("PRIMARY", collections=["floww-oleos"]), rule)
    # SFLOW-000, an empty carrying case in the same collection
    assert not crossover.matches(_observation("DR FLOWS PAINT CASE", collections=["floww-oleos"]), rule)


def test_none_of_wins_over_every_any_of_clause() -> None:
    """The veto is evaluated FIRST and is unconditional -- satisfying more anyOf clauses
    cannot rescue a vetoed row."""
    rule = _rule(
        [{"nameMatches": r"\bSET\b"}, {"hintEquals": {"categorySlug": "paint-sets"}}],
        [{"hintContainsAny": {"tags": ["brushset"]}}],
    )
    row = _observation("Brush Set", categorySlug="paint-sets", tags=["brushset"])
    assert not crossover.matches(row, rule)


# --- T8: absent inputs -----------------------------------------------------------------------


def test_missing_hint_key_is_false_not_an_error() -> None:
    for clause in (
        {"hintEquals": {"categorySlug": "paint-sets"}},
        {"hintContainsAny": {"tags": ["brushset"]}},
    ):
        assert crossover.matches(_observation("Box"), _rule([clause])) is False
    # ...and an empty/absent hints mapping entirely
    assert crossover.matches({"name": "Box"}, _rule([{"hintEquals": {"a": "b"}}])) is False


def test_no_rule_selects_nothing() -> None:
    """A `catalog: paints` source that declares no carve-out crosses nothing -- today's
    behaviour for mfr-turbodork, mfr-mr-hobby, mfr-vallejo and mfr-gw-webstore-paints."""
    for empty in (None, {}, {"anyOf": []}):
        assert crossover.matches(_observation("Warpaints Air Starter Set"), empty) is False


def test_missing_name_does_not_raise() -> None:
    assert crossover.matches({"hints": {}}, _rule([{"nameMatches": r"\bSET\b"}])) is False
    assert crossover.matches({"name": None}, _rule([{"nameMatches": r"\bSET\b"}])) is False


# --- T9: import hygiene ----------------------------------------------------------------------


def test_crossover_imports_no_third_party_module() -> None:
    """Guards the pure-pyyaml property of .github/workflows/paint-catalog-update.yml:75.

    gen_paint_harvest.py runs as `uv run --with pyyaml python ...` and imports this module via a
    sys.path bootstrap. If anything here (or in the packages it traverses) grew a pydantic or
    yaml import, that workflow line would start failing at import time -- in CI, on a paint
    harvest, far from whoever added the import. Asserted on the SOURCE rather than on
    sys.modules, because pytest has already imported the whole package by now.
    """
    import warhub_acquisition
    import warhub_acquisition.resolve

    def top_level_imports(path: Path) -> set[str]:
        found = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^(?:from|import)\s+([\w.]+)", line)
            if match:
                found.add(match.group(1).split(".")[0])
        return found

    # The bootstrap traverses two package __init__ files to reach this module, so neither may
    # import anything. Note `warhub_acquisition/__init__.py` is NOT empty -- it carries
    # `__version__ = "0.1.0"` -- so the property asserted is import-freedom, not emptiness.
    for package in (warhub_acquisition, warhub_acquisition.resolve):
        imports = top_level_imports(Path(package.__file__))
        assert imports == set(), f"{package.__name__}/__init__.py now imports {sorted(imports)}"

    imported = top_level_imports(Path(crossover.__file__))
    assert imported == {"re", "typing"}, f"crossover.py imports {sorted(imported)}"
