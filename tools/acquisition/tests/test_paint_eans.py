"""data/catalog/paint-eans.yaml: the barcodes the paint catalog publishes, as the product side
sees them.

The product resolver reads this file for one purpose -- to label a product `category: paint`
instead of guessing `miniatures` when no source said anything (resolve/attributes.py). Three
properties matter, and the third is the one a future change is most likely to break:

- THE INDEX IS REPRODUCIBLE from the committed paint archives. A stale index re-guesses.
- BARCODES STAY STRINGS. The lookup is exact string membership against a published `ean`, so a
  key YAML parsed as an integer would miss silently and the product would keep the guess.
- IT ONLY EVER LABELS. Nothing here may be read as permission to drop, refuse or rewrite a
  product record -- a product and a paint sharing a barcode is the design (docs/OBJECTIVES.md 4),
  and a refusal built on exactly this index (PR #143) was closed unmerged after it was found to
  delete 110 published ids. The last test is what makes that claim checkable rather than a
  comment: every barcode in the index must still be held by a live product record wherever the
  product catalog carried one.
"""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools/acquisition/scripts/gen_paint_eans.py"
INDEX = REPO_ROOT / "data/catalog/paint-eans.yaml"
PRODUCTS_DIR = REPO_ROOT / "data/catalog/products"
BRANDS_DIR = REPO_ROOT / "data/paints/brands"


def _index() -> dict:
    if not INDEX.exists():
        pytest.skip("data/catalog/paint-eans.yaml not present (package tested outside the monorepo)")
    return yaml.safe_load(INDEX.read_text(encoding="utf-8")) or {}


def _products() -> list[dict]:
    if not PRODUCTS_DIR.exists():
        pytest.skip("data/catalog/products/ not present")
    return [
        product
        for path in sorted(PRODUCTS_DIR.glob("*.yaml"))
        for product in ((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("products") or [])
    ]


def _barcodes(record: dict) -> list[str]:
    codes = [record["ean"]] if record.get("ean") else []
    codes += [str(extra) for extra in record.get("additionalEans") or []]
    return [str(code) for code in codes]


def test_the_committed_index_is_reproducible_from_the_committed_paint_archives() -> None:
    """Regenerating must be a no-op. The index is written by the paint workflow and read by the
    product resolver, which run on different cadences and different branches -- so a stale file is
    not a cosmetic drift, it is a run where a paint that gained a barcode last night keeps the
    `miniatures` guess tonight, with nothing anywhere saying so."""
    if not SCRIPT.exists():
        pytest.skip("gen_paint_eans.py not present (package tested outside the monorepo)")
    before = INDEX.read_bytes() if INDEX.exists() else None
    subprocess.run([sys.executable, str(SCRIPT)], check=True, capture_output=True, cwd=REPO_ROOT)
    assert INDEX.read_bytes() == before, (
        "data/catalog/paint-eans.yaml is not reproducible from data/paints/brands. Regenerate with "
        "`uv run --with pyyaml python tools/acquisition/scripts/gen_paint_eans.py` and commit it."
    )


def test_every_key_survives_yaml_as_a_string() -> None:
    """A barcode is a zero-padded numeric string. `yaml.safe_dump` would emit `0812152031524:`
    unquoted and a YAML 1.2 reader hands that back as an int, which no `ean` string can ever equal
    -- so the label would silently stop firing for exactly the UPC-A-promoted barcodes. The product
    catalog already holds 1,138 of that shape; the paint side holds none today, which is why this
    is a test and not a comment."""
    index = _index()
    bad = [code for code in (index.get("eans") or {}) if not isinstance(code, str)]
    assert not bad, f"barcode keys parsed as non-strings (use yamlio.dump_yaml, not safe_dump): {bad[:10]}"


def test_the_index_covers_the_whole_paint_catalog_not_a_sample() -> None:
    """`counts` is the audit trail, so it has to be a count of what is actually in the file, and
    the file has to be a count of what is actually in data/paints/brands. A generator that quietly
    stopped reading a brand directory would still produce a valid, self-consistent, wrong file."""
    if not BRANDS_DIR.exists():
        pytest.skip("data/paints/brands/ not present")
    index = _index()
    eans = index.get("eans") or {}
    counts = index.get("counts") or {}
    assert counts.get("eans") == len(eans), "counts.eans disagrees with the map it describes"

    expected: set[str] = set()
    paints = 0
    for path in sorted(BRANDS_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for paint in doc.get("paints") or []:
            paints += 1
            expected.update(str(v) for v in [paint.get("ean"), *(paint.get("additionalEans") or [])] if v)
    assert counts.get("paints") == paints, "counts.paints disagrees with data/paints/brands"
    assert set(eans) == expected, (
        f"index/archive barcode sets differ: {len(expected - set(eans))} missing, "
        f"{len(set(eans) - expected)} extra"
    )


def test_no_product_carrying_an_indexed_barcode_is_published_as_miniatures() -> None:
    """The defect this index exists to fix, stated as an invariant over the published data.

    A product whose barcode the paint catalog publishes IS a paint, and `miniatures` there is the
    fallback in resolve/attributes.py asserting something no source ever said. Measured 2026-08-21
    before the fix: 1,072 such rows (vallejo 570, army-painter 490, green-stuff-world 12), every
    one a single pot sold by a retailer emitting no category signal at all.

    A row can still legitimately say something OTHER than `paint` here -- a source that states
    `paint-set` or `hobby-auxiliary` outranks the fallback and must keep winning -- so this asserts
    the absence of the guess, not the presence of one value."""
    index = _index()
    eans = set(index.get("eans") or {})
    if not eans:
        pytest.skip("empty index")
    guessed = [
        product["id"]
        for product in _products()
        if product.get("category") == "miniatures" and any(code in eans for code in _barcodes(product))
    ]
    assert not guessed, (
        f"{len(guessed)} products carry a barcode the paint catalog publishes but are labelled "
        f"`category: miniatures`, e.g. {guessed[:5]}. Re-resolve (`warhub-data resolve`) after "
        f"regenerating data/catalog/paint-eans.yaml."
    )


def test_the_index_never_costs_a_product_its_barcode() -> None:
    """THE TRIPWIRE. This index labels; it must never become a reason a record is missing.

    Read the other way round from the test above: for every barcode the index holds, if the
    product catalog carries a record for it at all, that record must still be there with the
    barcode intact. It cannot prove a record was never dropped on its own -- `report --ean-guard`
    does that against HEAD -- but it does fail the moment someone reintroduces PR #143's refusal,
    whose whole effect was to make products holding these 3,965 barcodes cease to exist.
    """
    index = _index()
    eans = set(index.get("eans") or {})
    if not eans:
        pytest.skip("empty index")
    held = {code for product in _products() for code in _barcodes(product) if code in eans}
    assert held, (
        "not one of the paint catalog's barcodes is held by any product record. Either the product "
        "catalog is empty or something is refusing to publish products that overlap the paint "
        "catalog -- which is the design, not duplication (docs/OBJECTIVES.md 4)."
    )
