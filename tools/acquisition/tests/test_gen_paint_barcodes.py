# tools/acquisition/tests/test_gen_paint_barcodes.py
"""The Citadel barcode bridge, and specifically the SSC join that admits the rebrand workbook.

GW ships paint barcodes in two workbooks. Only `Individual Barcodes` names the paint set in its
`Range` column; `WH Colour Codes and Barcodes` (the 2026 rebrand) puts a merchandising code there
instead, so its rows have to borrow a set from somewhere. These tests pin WHERE from -- the full
SSC code, joined against what the other workbook states for that same code -- and pin the two
things that go wrong if you take a shortcut: reading the `Range` code as a set, or reading only
the SSC prefix.
"""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
BRIDGE = REPO_ROOT / "tools/acquisition/scripts/gen_paint_barcodes.py"


def _bridge():
    if not BRIDGE.exists():
        pytest.skip("gen_paint_barcodes.py not present (package tested outside the monorepo)")
    spec = importlib.util.spec_from_file_location("gen_paint_barcodes", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stated(sku, ean, ssc, trade_category, name, volume_ml=12):
    """A row from `Individual Barcodes`: its own `Range` names the set. The harvester records the
    range and the tab verbatim and stamps no category (since 2026-09-03; the judgement lives in
    category-rules/mfr-gw-trade.yaml)."""
    return {"sku": sku, "ean": ean, "name": name,
            "hints": {"sscCode": ssc, "tradeCategory": trade_category,
                      "sheets": ["Paints"], "volumeMl": volume_ml}}


def _rebrand(sku, ean, ssc, range_code, name, volume_ml=12):
    """A row from `WH Colour Codes and Barcodes`: `Range` is a merchandising code, not a set, and
    the `Paint` tab it sits on is the only thing that says it is a paint."""
    return {"sku": sku, "ean": ean, "name": name,
            "hints": {"sscCode": ssc, "tradeCategory": range_code,
                      "sheets": ["Paint"], "volumeMl": volume_ml}}


def _run(tmp_path, observations, paint_names):
    """Drive the real main() over a synthetic evidence file and paint catalog."""
    module = _bridge()
    evidence = tmp_path / "observations.jsonl"
    evidence.write_text("\n".join(json.dumps(o) for o in observations), encoding="utf-8")
    brand = tmp_path / "citadel-colour.yaml"
    brand.write_text(yaml.safe_dump(
        {"paints": [{"name": n, "details": {"set": s}} for n, s in paint_names]}), encoding="utf-8")
    out = tmp_path / "out.yaml"
    module.EVIDENCE, module.CITADEL, module.OUT = evidence, brand, out
    module.main()
    return yaml.safe_load(out.read_text(encoding="utf-8"))["citadel-colour"]


def test_rebrand_row_takes_its_set_from_the_ssc_code_not_its_range_code(tmp_path) -> None:
    """`E:P360` is not "Air". It spans SSC 21/22/27/28/29, so reading it as a set mis-sets rows."""
    result = _run(tmp_path, [
        _stated("99189951255", "5011921186624", "22-50", "Paint - WH Colour - Layer",
                "ADMINISTRATUM GREY 12ML (6-PACK)"),
        _stated("99189958174", "5011921183340", "28-44", "Paint - WH Colour - Air",
                "AIR: ADMINISTRATUM GREY (24ML) (6-PACK)", volume_ml=24),
        # Both rebrand rows carry the SAME `Range` code; only the SSC tells them apart.
        _rebrand("99189951399", "5011921197583", "22-50", "E:P360",
                 "L:ADMINISTRATUM GREY 12ML ROW X6"),
        _rebrand("99189958301", "5011921199815", "28-44", "E:P360",
                 "A:ADMINISTRATUM GREY 24ML ROW X6", volume_ml=24),
    ], [("Administratum Grey", "Layer"), ("Administratum Grey", "Air")])

    assert result["Administratum Grey|Layer"]["additionalEans"] == ["5011921197583"]
    assert result["Administratum Grey|Air"]["additionalEans"] == ["5011921199815"]


def test_rebrand_row_never_displaces_the_primary_barcode(tmp_path) -> None:
    """The rebrand row is NEWER, and still does not take the slot -- see the module docstring.

    Its barcode is kept alongside, so a scan of either resolves; letting it win would rewrite
    every primary barcode in the committed file the first time a rebrand workbook lands.
    """
    result = _run(tmp_path, [
        _stated("99189958145", "5011921182848", "28-15", "Paint - WH Colour - Air",
                "AIR: ABADDON BLACK (24ML) (6-PACK)", volume_ml=24),
        _rebrand("99189958220", "5011921199457", "28-15", "E:P360",
                 "A:ABADDON BLACK 24ML ROW X6", volume_ml=24),
        _rebrand("56189958220", "5011921244379", "28-15", "E:P360",
                 "A:ABADDON BLACK 24ML JUC X6", volume_ml=24),
    ], [("Abaddon Black", "Air")])

    entry = result["Abaddon Black|Air"]
    assert entry["ean"] == "5011921182848"
    assert entry["productCode"] == "99189958145"
    assert entry["ssc"] == "28-15"
    assert entry["additionalEans"] == ["5011921199457", "5011921244379"]
    assert entry["volumeMl"] == 24


def test_ssc_prefix_27_is_ambiguous_so_the_join_uses_the_full_code(tmp_path) -> None:
    """27 holds Technical AND two Contrast paints (Hexwraith Flame, Nighthaunt Gloom)."""
    result = _run(tmp_path, [
        _stated("99189956080", "5011921193066", "27-03", "Paint - WH Colour - Technical",
                "TECHNICAL: 'ARDCOAT (24ML) (6-PACK)", volume_ml=24),
        _stated("99189960060", "5011921176335", "27-20", "Paint - WH Colour - Contrast",
                "CONTRAST: HEXWRAITH FLAME (18ML) 6 PACK", volume_ml=18),
        _rebrand("99189956199", "5011921260001", "27-03", "BS:A",
                 "T:'ARDCOAT 24ML ROW X6", volume_ml=24),
        _rebrand("99189960261", "5011921262502", "27-20", "BS:A",
                 "C:HEXWRAITH FLAME 18ML ROW X6", volume_ml=18),
    ], [("'Ardcoat", "Technical"), ("Hexwraith Flame", "Contrast")])

    assert result["'Ardcoat|Technical"]["additionalEans"] == ["5011921260001"]
    assert result["Hexwraith Flame|Contrast"]["additionalEans"] == ["5011921262502"]


def test_rebrand_row_whose_ssc_no_workbook_states_is_dropped(tmp_path) -> None:
    """No stated set means no defensible set. Drop it rather than infer one from the prefix."""
    result = _run(tmp_path, [
        _stated("99189950232", "5011921187720", "21-25", "Paint - WH Colour - Base",
                "ABADDON BLACK 12ML (6-PACK)"),
        _rebrand("56189950999", "5011921299999", "21-99", "BS:A", "B:NEW COLOUR 12ML JUC X6"),
    ], [("Abaddon Black", "Base"), ("New Colour", "Base")])

    assert "New Colour|Base" not in result
    assert result["Abaddon Black|Base"].get("additionalEans") is None


def test_contradictory_ssc_set_is_not_guessed(tmp_path) -> None:
    """Two stating rows disagreeing about one SSC makes it unusable for the join, not a coin flip."""
    result = _run(tmp_path, [
        _stated("99189950232", "5011921187720", "21-25", "Paint - WH Colour - Base",
                "ABADDON BLACK 12ML (6-PACK)"),
        _stated("99189951232", "5011921187721", "21-25", "Paint - WH Colour - Layer",
                "ABADDON BLACK 12ML (6-PACK)"),
        _rebrand("99189950999", "5011921196371", "21-25", "BS:A", "B:ABADDON BLACK 12ML ROW X6"),
    ], [("Abaddon Black", "Base"), ("Abaddon Black", "Layer")])

    assert result["Abaddon Black|Base"].get("additionalEans") is None
    assert result["Abaddon Black|Layer"].get("additionalEans") is None


def test_juc_region_token_is_stripped_from_the_name(tmp_path) -> None:
    """`XV-88 12ML JUC X6` normalizes to `xv88juc`, only 0.73 against `xv88` -- a silent miss."""
    module = _bridge()
    assert module.clean_paint_name("B: XV-88 12ML JUC X6") == "XV-88"

    result = _run(tmp_path, [
        _stated("99189950229", "5011921187157", "21-21", "Paint - WH Colour - Base",
                "XV-88 12ML (6-PACK)"),
        _rebrand("56189950999", "5011921234444", "21-21", "BS:A", "B: XV-88 12ML JUC X6"),
    ], [("XV-88", "Base")])

    assert result["XV-88|Base"]["additionalEans"] == ["5011921234444"]


def test_two_skus_disagreeing_on_volume_emit_no_volume(tmp_path) -> None:
    result = _run(tmp_path, [
        _stated("99189950232", "5011921187720", "21-25", "Paint - WH Colour - Base",
                "ABADDON BLACK 12ML (6-PACK)", volume_ml=12),
        _rebrand("99189950999", "5011921196371", "21-25", "BS:A",
                 "B:ABADDON BLACK 12ML ROW X6", volume_ml=18),
    ], [("Abaddon Black", "Base")])

    assert "volumeMl" not in result["Abaddon Black|Base"]


def test_no_paint_row_in_the_committed_evidence_carries_a_price() -> None:
    """A tripwire for the reason the bridge carries no price: the source has none to carry.

    GW's paint workbooks are barcode registers with no price column, and the one workbook that
    does price things (`Trade Direct Range Sterling`, a `UKR` column) shares zero product codes
    with them. If this ever fails, a harvest has started carrying paint prices and the bridge
    should be widened to gather them -- as a SET per currency, and only after checking whether the
    priced row is a single pot or a case, because every paint description here is a case name.
    """
    evidence = REPO_ROOT / "data/evidence/products/mfr-gw-trade/observations.jsonl"
    if not evidence.exists():
        pytest.skip("no committed mfr-gw-trade evidence")
    module = _bridge()
    priced = []
    for line in evidence.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        observation = json.loads(line)
        if not (module.is_paint_obs(observation) or module.is_rebrand_paint_obs(observation)):
            continue
        for currency in ("priceGbp", "priceUsd", "priceEur", "priceCad"):
            if observation.get(currency) is not None:
                priced.append((observation.get("sku"), currency, observation[currency]))
    assert not priced, f"paint observations now carry prices: {priced[:5]}"


def test_committed_bridge_gives_every_barcode_to_exactly_one_paint() -> None:
    """A barcode on two paints means the SSC join or the fuzzy name match put one in the wrong place."""
    committed = REPO_ROOT / "data/paints/barcodes/citadel-colour.yaml"
    if not committed.exists():
        pytest.skip("no committed citadel barcode bridge")
    brand = yaml.safe_load(committed.read_text(encoding="utf-8"))["citadel-colour"]
    owners: dict[str, list[str]] = {}
    for key, record in brand.items():
        for barcode in [record["ean"], *(record.get("additionalEans") or [])]:
            owners.setdefault(barcode, []).append(key)
    shared = {barcode: keys for barcode, keys in owners.items() if len(keys) > 1}
    assert not shared, f"barcodes claimed by more than one paint: {shared}"
