# tools/acquisition/tests/test_paint_harvest_p3.py
"""`bridge_p3` in scripts/gen_paint_harvest.py: the relaunched Formula P3 range, minted.

TWO THINGS ARE BEING PROTECTED HERE, and they pull in opposite directions.

The first is that the range mints AT ALL. warmachine.gg is a storefront, and the harvest doctrine
(docs/research/2026-07-23-paint-manufacturer-harvest-design.md) is that storefronts never propose
paints; this bridge is a documented, maintainer-authorised exception for one range that exists on
no other source. So a change that quietly turned it back into an enrich-only bridge would look
like doctrine being restored and would in fact delete 110 paints nobody else publishes.

The second is that it mints WITHOUT TOUCHING the original Privateer Press records. PR #128 landed
a version of this work that name-matched them and backfilled 97 EANs onto pots that are a
different physical product, then reverted it. 98 of the 110 relaunched colours name-match a legacy
record, so the join that did that is one `match_name` call away at all times. The tests below hand
the bridge a catalog containing exactly the legacy records the reverted change hit.

Reads the REAL descriptor (SOURCES_DIR untouched) against SYNTHETIC evidence, like
test_paint_harvest_gate.py, and imports the script by path for the same reason.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools/acquisition/scripts/gen_paint_harvest.py"


def _load():
    if not SCRIPT.exists():
        pytest.skip("gen_paint_harvest.py not present (package tested outside the monorepo)")
    spec = importlib.util.spec_from_file_location("gen_paint_harvest_p3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harvest = _load()

# Real rows, trimmed: a plain colour, the Mixing Medium, that colour's trade case, and the
# starter set. EANs are the committed ones (all check-digit valid).
SINGLE = {"name": "P3 Paints: Cygnar Blue", "sku": "SFP3-N158-S", "ean": "5061060701783",
          "url": "https://warmachine.gg/products/p3-paints-cygnar-blue",
          "imageUrl": "https://cdn.example/CygnarBlue.png", "priceUsd": 4.1,
          "hints": {"category": "paint"}}
MEDIUM = {"name": "P3 Paints: Mixing Medium", "sku": "SFP3-N235-S", "ean": "5061060702551",
          "url": "https://warmachine.gg/products/p3-paints-mixing-medium",
          "imageUrl": "https://cdn.example/MixingMedium.png", "priceUsd": 4.65,
          "hints": {"category": "paint"}}
CASE = {"name": "P3 Paints: Cygnar Blue (Pack of 6)", "sku": "SFP3-N158", "ean": None,
        "url": "https://warmachine.gg/products/p3-paints-cygnar-blue-pack-of-6",
        "priceUsd": 24.6, "hints": {"category": "paint"}}
STARTER = {"name": "P3 Paints: Starter Set Dropper Bottle (10 paints)", "sku": "SFP3-N128",
           "ean": "5061060701486", "url": "https://warmachine.gg/products/p3-starter",
           "priceUsd": 39.99, "hints": {"category": "paint"}}
MINIATURE = {"name": "Warcaster Kara Sloan", "sku": "PIP31091", "url": "https://warmachine.gg/x",
             "priceUsd": 24.99, "hints": {}}

# The two legacy records the reverted backfill landed on, verbatim from data/paints/brands/p3.yaml.
LEGACY = [
    {"name": "Cygnar Blue Base", "details": {"set": "Privateer Press Formula P3",
                                             "hex": "#1F4E79", "container": "pot"}},
    {"name": "Cygnar Blue Highlight", "details": {"set": "Privateer Press Formula P3",
                                                  "hex": "#4A7EBB", "container": "pot"}},
]


@pytest.fixture
def evidence(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(harvest, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(harvest, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(harvest, "OUT_DIR", tmp_path / "out")
    for name in ("evidence", "brands", "out"):
        (tmp_path / name).mkdir()

    def write(rows: list[dict], paints: list[dict] | None = None) -> None:
        directory = tmp_path / "evidence" / "mfr-warmachine"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "observations.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
        )
        (tmp_path / "brands" / "p3.yaml").write_text(
            yaml.safe_dump({"paints": paints or []}, sort_keys=False), encoding="utf-8"
        )

    return write


def test_a_single_mints_and_takes_its_barcode_the_same_run(evidence) -> None:
    """The addition and the enrich entry are one mechanism, not two: `AppendAdditions` births the
    paint colour-less and barcode-less, `ApplyEnrichment` runs after it and fills the blank Ean.
    So the enrich key MUST be the identity the addition just minted, or the barcode lands
    nowhere."""
    evidence([SINGLE])
    out = harvest.bridge_p3()

    assert out.additions == [{
        "name": "Cygnar Blue", "set": "P3 Paints", "productCode": "SFP3-N158-S",
        "imageUrl": "https://cdn.example/CygnarBlue.png",
        "sourceUrl": SINGLE["url"], "source": "mfr-warmachine", "priceUsd": 4.1,
    }]
    assert out.enrich == {"Cygnar Blue|P3 Paints": {
        "ean": "5061060701783", "imageUrl": "https://cdn.example/CygnarBlue.png",
        "sku": "SFP3-N158-S", "sourceUrl": SINGLE["url"], "source": "mfr-warmachine",
        "priceUsd": 4.1,
    }}
    assert out.candidates == []


def test_the_product_code_keeps_the_single_suffix(evidence) -> None:
    """`-S` is the store's own, and dropping it would hand the paint the TRADE CASE's part
    number -- SFP3-N158 is a real, different product that publishes under that code."""
    evidence([SINGLE, CASE])
    out = harvest.bridge_p3()
    assert [a["productCode"] for a in out.additions] == ["SFP3-N158-S"]
    assert out.enrich["Cygnar Blue|P3 Paints"]["sku"] == "SFP3-N158-S"


def test_multi_bottle_rows_are_refused_and_say_so(evidence) -> None:
    """The trade case and the starter set are products, not paints. Refused by SKU SHAPE, because
    mfr-warmachine declares no `crossoverToProducts` block and correctly should not -- it is not a
    `catalog: paints` source, so all its rows already publish as products and there is nothing to
    carve out. Reported rather than dropped: the harvest is the record of what left and why."""
    evidence([SINGLE, CASE, STARTER])
    out = harvest.bridge_p3()

    assert [a["name"] for a in out.additions] == ["Cygnar Blue"]
    assert sorted((c["sku"], c["reason"]) for c in out.candidates) == [
        ("SFP3-N128", "multi-bottle pack -- crosses to the product catalog"),
        ("SFP3-N158", "multi-bottle pack -- crosses to the product catalog"),
    ]


def test_the_mixing_medium_is_part_of_the_range(evidence) -> None:
    """Colourless utility, and a paint the range ships -- maintainer decision 2026-08-13. It mints
    like any other single; what it does NOT get is a colour, and that is the swatch pass's job
    (data/paints/swatch-sources.yaml pins it in `skipCodes`), not a shape test here."""
    evidence([MEDIUM])
    out = harvest.bridge_p3()
    assert [(a["name"], a["productCode"]) for a in out.additions] == [
        ("Mixing Medium", "SFP3-N235-S")
    ]


def test_nothing_but_p3_reaches_the_paint_catalog(evidence) -> None:
    """mfr-warmachine is a whole storefront -- miniatures, books, digital downloads. Only the
    SFP3 block is paint, and the rest must not even become candidates (they are not refused
    paints; they were never paints)."""
    evidence([SINGLE, MINIATURE])
    out = harvest.bridge_p3()
    assert [a["name"] for a in out.additions] == ["Cygnar Blue"]
    assert out.candidates == []


def test_the_legacy_privateer_press_records_are_never_touched(evidence) -> None:
    """THE PR #128 REGRESSION, pinned. `Cygnar Blue` name-matches two committed legacy records;
    a bridge that reached for `match_name` (or keyed enrichment on the legacy set) would put a
    Steamforged dropper bottle's barcode, photo and price on a Privateer Press pot. Every enrich
    key this bridge emits must name the NEW set, and no addition may claim a legacy identity."""
    evidence([SINGLE], paints=LEGACY)
    out = harvest.bridge_p3()

    legacy_keys = {"Cygnar Blue Base|Privateer Press Formula P3",
                   "Cygnar Blue Highlight|Privateer Press Formula P3"}
    assert set(out.enrich) & legacy_keys == set()
    assert all(key.endswith("|P3 Paints") for key in out.enrich)
    assert all(a["set"] == "P3 Paints" for a in out.additions)
    # And the presence of a catalog changes nothing: the bridge is catalog-blind by construction,
    # so its output is identical to the empty-catalog run above.
    assert out.additions[0]["productCode"] == "SFP3-N158-S"


def test_a_malformed_barcode_is_dropped_not_published(evidence) -> None:
    """`ean13_ok` is the gate. A store barcode is third-party keyed data and nothing downstream
    re-checks it -- the C# fills a blank Ean verbatim -- so a bad check digit must not become a
    barcode that resolves to some other product. The paint still mints; only the ean is withheld."""
    evidence([{**SINGLE, "ean": "5061060701782"}])  # last digit wrong
    out = harvest.bridge_p3()
    assert len(out.additions) == 1
    assert "ean" not in out.enrich["Cygnar Blue|P3 Paints"]
