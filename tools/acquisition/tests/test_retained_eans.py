"""data/catalog/retained-eans.yaml: barcodes we published that no source attests any more.

The hole this plugs is narrow. `corroborate.py` builds `additionalEans` from barcodes some
observation currently asserts, and the ledger keeps only the latest observation per key -- so a
source that CHANGES the barcode on a handle it already had leaves no loser to retain, and a
published barcode disappears. Measured 2026-08-22 across every barcode the catalog has ever
published (14,295 at 98fa5f9): exactly two have gone that way, both `mfr-wyrd-store`.

These tests hold retention to being ADDITIVE and STATED -- it may add to `additionalEans`, never
touch a primary `ean`, and never invent an entry.
"""
from pathlib import Path

import pytest
import yaml

from warhub_acquisition.models.catalog import RetainedEans
from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import write_yaml

from test_resolver import seed

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED = REPO_ROOT / "data/catalog/retained-eans.yaml"


def _resolve(tmp_path: Path, retained: dict) -> dict:
    paths = seed(tmp_path)
    if retained is not None:
        write_yaml(paths.retained_eans, {"retained": retained})
    catalog = resolve_catalog(paths)
    return {p.id: p for products in catalog.values() for p in products}


def test_a_retained_barcode_is_re_attached_to_its_record(tmp_path: Path) -> None:
    by_id = _resolve(tmp_path, {"games-workshop/99120110077": ["5011921999999"]})
    product = by_id["games-workshop/99120110077"]
    assert "5011921999999" in product.additionalEans
    assert product.ean == "5011921194285"  # primary untouched


def test_retention_never_changes_the_primary_ean(tmp_path: Path) -> None:
    """The whole safety property. A retained value is an ALSO-ANSWERS-TO, never a claim about
    current retail packaging -- that is what `ean` is for. If retention could move a primary it
    would be a way to launder a stale barcode back over live evidence."""
    # Separate roots: `seed` creates its evidence directories with a bare mkdir, so two seeds
    # cannot share one tmp_path.
    plain = _resolve(tmp_path / "plain", None)["games-workshop/99120110077"]
    with_retention = _resolve(
        tmp_path / "retained", {"games-workshop/99120110077": ["5011921999999"]}
    )["games-workshop/99120110077"]
    assert with_retention.ean == plain.ean
    assert with_retention.eanConfidence == plain.eanConfidence


def test_a_retained_value_equal_to_the_primary_is_not_duplicated(tmp_path: Path) -> None:
    """A barcode some source starts asserting again is simply already there. Publishing it twice --
    once as `ean` and once in `additionalEans` -- would make the record contradict its own shape."""
    product = _resolve(tmp_path, {"games-workshop/99120110077": ["5011921194285"]})[
        "games-workshop/99120110077"
    ]
    assert product.ean == "5011921194285"
    assert "5011921194285" not in product.additionalEans


def test_an_absent_file_is_a_no_op(tmp_path: Path) -> None:
    product = _resolve(tmp_path, None)["games-workshop/99120110077"]
    assert product.additionalEans == []


def test_an_entry_for_an_unknown_entity_is_inert_rather_than_fatal(tmp_path: Path) -> None:
    """A retained entry outliving its record must not fail the resolve. The record it named can
    legitimately vanish (a retraction, a re-code), and a hard error there would block every nightly
    until a human edited the file -- see test_repo_data's dead-entry guard, which is where a stale
    entry is meant to surface."""
    by_id = _resolve(tmp_path, {"games-workshop/does-not-exist": ["5011921999999"]})
    assert "games-workshop/does-not-exist" not in by_id


def test_retention_is_additive_and_sorted(tmp_path: Path) -> None:
    product = _resolve(tmp_path, {"games-workshop/99120110077": ["5011921999999", "5011921888888"]})[
        "games-workshop/99120110077"
    ]
    assert product.additionalEans == ["5011921888888", "5011921999999"]


def test_the_model_refuses_an_unknown_key() -> None:
    with pytest.raises(Exception):
        RetainedEans.model_validate({"retained": {}, "somethingElse": 1})


def test_every_committed_entry_still_names_a_real_product_and_is_actually_retained() -> None:
    """The dead-entry guard. An entry whose record no longer exists, or whose barcode the catalog
    now carries as a primary anyway, is stale -- it should be removed rather than left implying a
    retention that is doing nothing. This is where such an entry surfaces, since the resolver
    deliberately ignores it rather than failing the nightly."""
    if not COMMITTED.exists():
        pytest.skip("data/catalog/retained-eans.yaml not present")
    entries = RetainedEans.model_validate(yaml.safe_load(COMMITTED.read_text(encoding="utf-8")))
    products_dir = REPO_ROOT / "data/catalog/products"
    if not products_dir.exists():
        pytest.skip("data/catalog/products/ not present")
    by_id = {}
    for path in sorted(products_dir.glob("*.yaml")):
        for product in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("products") or []:
            by_id[product["id"]] = product
    for entity, eans in entries.retained.items():
        assert entity in by_id, f"retained-eans.yaml names {entity!r}, which the catalog no longer has"
        record = by_id[entity]
        for ean in eans:
            assert ean != str(record.get("ean")), (
                f"{entity}: {ean} is the primary ean now, so retaining it is a no-op -- drop the entry"
            )
            assert ean in (record.get("additionalEans") or []), (
                f"{entity}: {ean} is declared retained but is not in the published additionalEans"
            )
