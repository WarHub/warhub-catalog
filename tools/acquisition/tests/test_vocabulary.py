"""data/catalog/taxonomy/categories.yaml: the declared vocabularies for `category` and `packaging`.

The point of the file is that a value reaching the published catalog has been declared by a human
somewhere. These tests hold the loader to that: it must reject what is not declared, accept what
is (including the legacy values today's data still carries), and stay silent about absence -- a
missing value is honest, and forcing one would re-invent the fallback the whole effort is removing.
"""
from pathlib import Path

import pytest
import yaml

from warhub_acquisition.vocabulary import Vocabulary, load_vocabulary

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED = REPO_ROOT / "data/catalog/taxonomy/categories.yaml"


def _vocab() -> Vocabulary:
    return Vocabulary.model_validate(
        {
            "categories": [
                {"slug": "miniatures", "label": "Miniatures"},
                {"slug": "paint", "label": "Paint"},
            ],
            "packaging": [
                {"slug": "single", "label": "Single"},
                {"slug": "box", "label": "Box (legacy)", "status": "legacy", "mapsTo": "set"},
            ],
        }
    )


def test_a_declared_value_passes_on_both_axes() -> None:
    _vocab().check("paint", "single", "vallejo/x")


def test_an_undeclared_category_is_a_hard_error_naming_the_product_and_the_options() -> None:
    """Hard, not a warning. An undeclared value reaching data/catalog/products/ is a value some
    consumer will filter on that nobody has defined -- and once published it is frozen
    (docs/OBJECTIVES.md 3), so failing the resolve is the cheap end of that trade. The message
    carries the product id and the declared set because the realistic cause is a typo in
    overrides.yaml, and the fix needs both."""
    with pytest.raises(ValueError, match=r"vallejo/x: category 'minatures' is not declared"):
        _vocab().check("minatures", None, "vallejo/x")


def test_an_undeclared_packaging_is_a_hard_error_too() -> None:
    with pytest.raises(ValueError, match=r"packaging 'crate' is not declared"):
        _vocab().check("paint", "crate", "vallejo/x")


def test_absent_is_never_a_violation() -> None:
    """`packaging` is unknown for ~60% of the catalog and `category` becomes honestly nullable the
    moment a categorize stage can say "undecided". A vocabulary that rejected None would force a
    value, which is the fallback wearing a validator's clothes."""
    _vocab().check(None, None, "vallejo/x")


def test_legacy_values_still_validate() -> None:
    """`status: legacy` marks a value the catalog already holds and a later phase will migrate.
    Refusing it here would fail the resolve on today's committed data and force the vocabulary and
    the migration to land as one change -- which would hide a data change inside a declaration."""
    _vocab().check("paint", "box", "vallejo/x")


def test_a_missing_vocabulary_file_permits_everything(tmp_path: Path) -> None:
    """The package is tested outside the monorepo and every resolver fixture predates this file, so
    absence must be permissive rather than fatal -- the same posture `load_labels` takes toward a
    missing game-systems.yaml. That this REPO has the file is asserted below, not here."""
    empty = load_vocabulary(tmp_path)
    assert empty.category_slugs == frozenset()
    empty.check("anything-at-all", "whatever", "x/y")


def test_the_committed_vocabulary_declares_every_value_the_catalog_actually_uses() -> None:
    """The guard the resolver enforces, asserted directly over committed data.

    The resolver would already fail on an undeclared value, but only on a run someone performs.
    This fails in CI on the committed tree, which is where a hand-edited override or a new
    crossover stamp would otherwise sit unnoticed until the next nightly.
    """
    if not COMMITTED.exists():
        pytest.skip("data/catalog/taxonomy/categories.yaml not present")
    vocabulary = load_vocabulary(COMMITTED.parent)
    products_dir = REPO_ROOT / "data/catalog/products"
    if not products_dir.exists():
        pytest.skip("data/catalog/products/ not present")
    for path in sorted(products_dir.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for product in doc.get("products") or []:
            vocabulary.check(product.get("category"), product.get("packaging"), product["id"])


def test_every_legacy_value_names_a_current_target_and_every_entry_is_unique() -> None:
    """`mapsTo` is the migration's only authority, so it has to point somewhere real -- a legacy
    value mapping to another legacy value, or to nothing, would leave the migration undefined."""
    if not COMMITTED.exists():
        pytest.skip("data/catalog/taxonomy/categories.yaml not present")
    vocabulary = load_vocabulary(COMMITTED.parent)
    for axis, entries in (("categories", vocabulary.categories), ("packaging", vocabulary.packaging)):
        slugs = [entry.slug for entry in entries]
        assert len(slugs) == len(set(slugs)), f"{axis}: duplicate slug in {slugs}"
        current = {e.slug for e in entries if e.status != "legacy"}
        for entry in entries:
            if entry.status == "legacy":
                assert entry.mapsTo in current, (
                    f"{axis}/{entry.slug}: legacy values must name a current `mapsTo` target, "
                    f"got {entry.mapsTo!r}"
                )
            else:
                assert entry.mapsTo is None, (
                    f"{axis}/{entry.slug}: only `status: legacy` entries may carry `mapsTo`"
                )
            assert entry.definition, f"{axis}/{entry.slug}: every value needs a definition"
