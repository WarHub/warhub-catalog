# tools/acquisition/tests/test_paint_harvest_gate.py
"""`paint_rows` in scripts/gen_paint_harvest.py: the crossover gate every bridge reads through.

THE INVARIANT: A SOURCE'S CROSSOVER PREDICATE IS EXACTLY WHAT ITS PAINT BRIDGE REFUSES. Until
2026-08-05 that was stated universally and wired into 3 of the 9 bridges (`is_set` in ak, gsw and
reaper); bridge_armypainter, bridge_monument and bridge_scale75 declared a `crossoverToProducts`
block and never asked it, leaning on inclusion whitelists that know nothing about sets.

test_repo_data.py::test_every_bridge_reads_through_the_crossover_gate pins that STATICALLY (no
bridge may call `read_observations` directly). This module pins it BEHAVIOURALLY, and does so by
handing each of those three bridges the row its whitelist would have let through -- so a test
failure here is the actual double-publish, not a style violation.

Reads the REAL descriptors (SOURCES_DIR is left alone) against SYNTHETIC evidence: the point is
what each source's own declared predicate does to a row its bridge's other rules like.

Imported by path: the bridge scripts are not part of the installed package (they run standalone
under `uv run --with pyyaml`), same as test_paint_harvest_price.py.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools/acquisition/scripts/gen_paint_harvest.py"

CROSSED = "boxed set -- crosses to the product catalog"
AUX = "auxiliary agent, not a colour -- claimed by the product catalog"


def _load():
    if not SCRIPT.exists():
        pytest.skip("gen_paint_harvest.py not present (package tested outside the monorepo)")
    spec = importlib.util.spec_from_file_location("gen_paint_harvest_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harvest = _load()


@pytest.fixture
def evidence(monkeypatch, tmp_path: Path):
    """Point the bridge at synthetic evidence, an empty catalog and an empty prior harvest.

    SOURCES_DIR is deliberately NOT redirected -- the whole question is what the committed
    descriptors do. (`crossover_rule` is lru_cached on the source id and would leak a redirected
    read into every other test in the session anyway.)
    """
    monkeypatch.setattr(harvest, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(harvest, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(harvest, "STORES_DIR", tmp_path / "stores")
    monkeypatch.setattr(harvest, "OUT_DIR", tmp_path / "out")
    for name in ("evidence", "brands", "stores", "out"):
        (tmp_path / name).mkdir()

    def write(source_id: str, rows: list[dict]) -> None:
        directory = tmp_path / "evidence" / source_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "observations.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
        )

    def catalog(slug: str, paints: list[dict]) -> None:
        (tmp_path / "brands" / f"{slug}.yaml").write_text(
            yaml.safe_dump({"paints": paints}, sort_keys=False), encoding="utf-8"
        )

    write.catalog = catalog  # type: ignore[attr-defined]
    return write


def _reasons(out) -> list[str]:
    return [c["reason"] for c in out.candidates]


# --- the reader itself -----------------------------------------------------------------------


def test_a_crossed_row_is_reported_not_dropped(evidence) -> None:
    """Refusing a row and losing a row are different things. The harvest file is the audit
    trail, so a gated row leaves as a candidate saying why -- verbatim the `reason` string the
    gsw and reaper bridges have emitted since af01ca5 (6b3c930 shipped the gates themselves under
    the narrower wordings "set title filed under a range category" / "...labelled
    category=paint"), so the six bridges joining them relabel nothing and invent nothing."""
    evidence("mfr-monument", [
        {"name": "AdeptiCon Paint Set", "sku": "MPA-SET-ACON", "url": "u",
         "hints": {"productType": "Paint Sets"}},
    ])
    out = harvest.BrandHarvest()
    assert harvest.paint_rows("mfr-monument", out) == []
    assert out.candidates == [
        {"name": "AdeptiCon Paint Set", "sku": "MPA-SET-ACON", "url": "u",
         "source": "mfr-monument", "reason": CROSSED}
    ]


def test_the_receipt_names_the_kind_the_clause_declared_not_always_a_set(evidence) -> None:
    """A refusal is RECORDED, never guessed -- including the kind of thing being refused.

    ak-interactive.com crosses two kinds out of the same paint categories (a per-clause `category`,
    crossover.py::category_for): boxed sets and auxiliary agents. The receipt was the fixed word
    "boxed set" for both, and this file is the ONLY place the paint side says why AK712 Acrylic
    Thinner is not a paint. Measured 2026-08-11 over data/paints/harvest/: 562 candidate rows carry
    a crossover reason and 16 of them -- all AK -- are `hobby-auxiliary`.

    Both rows below are real AK titles, and they run against the REAL descriptor (SOURCES_DIR is
    not redirected), so this pins the actual clause order too: "ODOURLESS THINNER" reaches the
    narrow clause first, "FLESH COLORS SET" falls through to the title clause.
    """
    evidence("mfr-ak-interactive", [
        {"name": "ODOURLESS THINNER", "sku": "AKABT111", "url": "u"},
        {"name": "FLESH COLORS SET", "sku": "AKABT301", "url": "u"},
    ])
    out = harvest.BrandHarvest()
    assert harvest.paint_rows("mfr-ak-interactive", out) == []
    assert _reasons(out) == [AUX, CROSSED]


def test_a_crossover_category_with_no_receipt_stops_the_run(monkeypatch, evidence) -> None:
    """The next `category` someone adds must not inherit the previous one's word by default.

    `CROSSOVER_REASON.get(stamp)` with a fallback would file a new kind under an old label -- the
    exact defect this pair of tests exists to close -- so an unmapped stamp is a hard stop. Pinned
    because the failure mode is silent: the harvest would still be written, still be valid YAML,
    and still be wrong.
    """
    monkeypatch.setattr(harvest, "CROSSOVER_REASON", {})
    evidence("mfr-ak-interactive", [{"name": "FLESH COLORS SET", "sku": "AKABT301", "url": "u"}])
    with pytest.raises(SystemExit, match="CROSSOVER_REASON"):
        harvest.paint_rows("mfr-ak-interactive", harvest.BrandHarvest())


def test_a_blockless_source_loses_nothing(evidence) -> None:
    """Four paint sources deliberately declare no block (see SOURCES_WITHOUT_A_CROSSOVER_BLOCK
    in test_repo_data.py). Routing them through the gate must be a pure no-op -- including for a
    row whose title is full of set words, since `crossover.matches` returns False on no rule."""
    rows = [{"name": "Turbo Dork Full Range Collection Set", "sku": "TDK1", "url": "u"},
            {"name": "Box Wine", "sku": "TDK2", "url": "u"}]
    evidence("mfr-turbodork", rows)
    out = harvest.BrandHarvest()
    assert harvest.paint_rows("mfr-turbodork", out) == rows
    assert out.candidates == []


def test_a_misspelled_source_id_fails_loud(evidence) -> None:
    """The gate reads the descriptor by id; a typo must not read as "no carve-out".

    `paint_rows` now owns BOTH reads, so the gate id and the evidence id can no longer drift
    apart -- but they can be misspelled together, and then the evidence read returns [] and the
    bridge quietly emits nothing. That is why the rule is fetched EAGERLY, before the loop:
    without it this raises nothing at all (verified while writing this test)."""
    with pytest.raises(SystemExit):
        harvest.paint_rows("mfr-monumnet", harvest.BrandHarvest())


# --- the three bridges that declared a block and never asked it -------------------------------


def test_armypainter_set_rows_do_not_pass_its_singles_shape_test(evidence) -> None:
    """The one declaring-but-unwired bridge whose whitelist was NOT a substitute for the gate.

    Measured 2026-08-05: `is_single` refuses 46 of the 49 crossed rows, but WP8017P, WP8042P and
    WP8012P have `WP\\d{4}P` skus and 61-112 g dropper weights and pass it. They stayed out of
    `enrich` only because `match_code` missed and their titles carry no ":" prefix -- a FAILED
    JOIN, not a refusal -- while carrying real retail EANs the resolver publishes as products.
    Give the catalog the code (`WP8017`, exactly what `sku.rstrip("PS")` looks up) and the old
    bridge would have put a box's EAN and $34.12 onto a dropper. The control row below is the
    same product with the set words removed: it still enriches, so this test fails only for
    boxes."""
    evidence.catalog("army-painter", [
        {"name": "Ogre Skin", "productCode": "WP8017",
         "details": {"set": "Warpaints Fanatic", "hex": "#6B7A4A"}},
        {"name": "Ogre Hide", "productCode": "WP8019",
         "details": {"set": "Warpaints Fanatic", "hex": "#6B7A4B"}},
    ])
    evidence("mfr-armypainter", [
        {"name": "Kings of War Ogres Paint Set", "sku": "WP8017P", "ean": "5713799801707",
         "url": "u", "priceUsd": 34.12, "hints": {"grams": 63}},
        {"name": "Ogre Hide", "sku": "WP8019P", "ean": "5713799801905",
         "url": "u", "priceUsd": 3.99, "hints": {"grams": 30}},
    ])
    out = harvest.bridge_armypainter()
    assert out.enrich == {
        "Ogre Hide|Warpaints Fanatic": {
            "ean": "5713799801905", "sku": "WP8019P", "sourceUrl": "u",
            "source": "mfr-armypainter", "priceUsd": 3.99,
        }
    }
    assert out.additions == []
    assert _reasons(out) == [CROSSED]


def test_monument_set_rows_are_gated_even_when_the_producttype_lies(evidence) -> None:
    """monument's refusal is ONE line -- `productType != "Paint Singles"` -- and it was doing the
    job by coincidence (measured 2026-08-05: 0 of its 21 crossed rows say Paint Singles). The
    counterfactual is not academic: with that line widened, AMP-SET-1/AMP-SET-2 hit the
    `sku.startswith("AMP-")` promotion and MPA-SET-1STEP1 the `"1-step" in title` one, and all
    three publish as individual paints -- the failure 6b3c930 fixed. So the rows below wear the
    productType that WOULD get them through, and must still leave on the title clause."""
    evidence("mfr-monument", [
        {"name": "AMP Colors Cosmic Paint Set #1", "sku": "AMP-SET-1", "url": "u",
         "ean": "0850038993108", "hints": {"productType": "Paint Singles"}},
        {"name": "PRO Acryl 1-Step Set #1", "sku": "MPA-SET-1STEP1", "url": "u",
         "hints": {"productType": "Paint Singles"}},
        {"name": "PRO Acryl 1-Step 001 - Bold Titanium White", "sku": "MPA-5001", "url": "u",
         "hints": {"productType": "Paint Singles"}},
    ])
    out = harvest.bridge_monument()
    assert out.enrich == {}
    # The real 1-Step single still lands -- the gate reads the SET word, not the "1-step" one.
    assert [a["productCode"] for a in out.additions] == ["MPA-5001"]
    assert _reasons(out) == [CROSSED, CROSSED]


def test_scale75_set_rows_are_gated_even_from_a_mapped_collection(evidence) -> None:
    """scale75's safety was doubly coincidental: all 6 crossed rows sit in collections absent
    from BOTH mapping dicts, and 0 of the 6 name-match the catalog. Two hand-maintained lists
    that happen to be disjoint from a third, with nothing enforcing it. Below, one product is in
    a MAPPED collection as well as a crossed one -- the pre-gate bridge would have minted it as
    a "Scale Color Range" addition."""
    evidence("mfr-scale75", [
        {"name": "SSE-080 PRISM SET", "sku": "SSE-080", "url": "u", "priceEur": 59.95,
         "hints": {"collections": ["scalecolor-individual", "prism"]}},
        {"name": "BLACK", "sku": "SC-01", "url": "u", "priceEur": 2.95,
         "hints": {"collections": ["scalecolor-individual"]}},
    ])
    out = harvest.bridge_scale75()
    assert [a["productCode"] for a in out.additions] == ["SC-01"]
    assert _reasons(out) == [CROSSED]


# --- the ordering the move fixed --------------------------------------------------------------


def test_a_crossed_row_cannot_enrich_even_when_it_code_matches(evidence) -> None:
    """bridge_ak's own `is_set` sat AFTER its enrich/ratchet branch, unlike gsw's and reaper's,
    whose comments argue explicitly for pre-branch placement. Inert on today's data (0 of the 285
    crossed ak rows code-match the catalog) and one code match away from not being: a set that
    matched would have enriched a paint with the box's image and EUR price before the gate ever
    ran. Gating in the READER makes the ordering unrepresentable rather than merely correct."""
    evidence.catalog("ak-interactive", [
        {"name": "Ak 3G Range Afv", "productCode": "AK11500",
         "details": {"set": "Standard (3rd Gen)", "hex": ""}},
    ])
    evidence("mfr-ak-interactive", [
        {"name": "AK 3G RANGE AFV SET", "sku": "AK11500", "url": "u", "priceEur": 289.0,
         "hints": {"categorySlugs": ["3rd-acrylics"]}},
    ])
    out = harvest.bridge_ak()
    assert out.enrich == {}
    assert out.additions == []
    assert _reasons(out) == [CROSSED]
