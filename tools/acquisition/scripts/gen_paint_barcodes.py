"""Generate data/paints/barcodes/citadel-colour.yaml — the Citadel paint EAN bridge.

The paint catalog (C#) has no product code/SKU, so it cannot join the GW trade barcodes directly.
This script does the fuzzy match ONCE, here, and emits a file keyed by the paint catalog's own
`{Name}|{Set}` identity so the C# BarcodeEnricher only ever does an exact lookup. The match is
auditable: the committed YAML shows exactly which paint got which barcode.

Match key: (set, normalized name), with volume as a tiebreaker. Source of barcodes: the resolved
mfr-gw-trade paint observations (the UNIT barcode, not the 6-pack case code). When both the
pre-rebrand (Individual Barcodes) and post-rebrand (WH Colour Codes) barcodes exist for a paint,
the newer WH-Colour one wins as `ean` and the older is kept as `additionalEans`.

Run: `uv run --with pyyaml python tools/acquisition/scripts/gen_paint_barcodes.py`
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
EVIDENCE = REPO / "data/evidence/products/mfr-gw-trade/observations.jsonl"
CITADEL = REPO / "data/paints/brands/citadel-colour.yaml"
OUT = REPO / "data/paints/barcodes/citadel-colour.yaml"

# tradeCategory "Paint - WH Colour - <Set>" / "Spray - Colour" -> the paint catalog `set`.
_SET_FROM_TRADE = {
    "base": "Base", "layer": "Layer", "shade": "Shade", "contrast": "Contrast",
    "dry": "Dry", "technical": "Technical", "air": "Air", "spray": "Spray",
}


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clean_paint_name(raw: str) -> str:
    n = raw.upper()
    n = re.sub(r"^\s*[A-Z][A-Z ./]*:\s*", "", n)          # leading "BASE:" / "C:" / "SPRAY -" prefix
    n = re.sub(r"\(.*?\)", " ", n)                          # (12ML), (6-PACK), (UK/ROW), ...
    n = re.sub(r"\b\d+\s*ML\b", " ", n)                     # bare "12ML"
    n = re.sub(r"\b(6[\s-]*PACK|6[\s-]*PK|SINGLE|ROW|UK|EU|AU|GLOBAL|X6|X3)\b", " ", n)
    n = re.sub(r"\bSPRAY\b|\bPAINT\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def set_from_trade_category(tc: str | None, name: str) -> str | None:
    tc = (tc or "").lower()
    if "spray" in tc or "spray" in name.lower():
        return "Spray"
    for token, label in _SET_FROM_TRADE.items():
        if f"- {token}" in tc or tc.endswith(token):
            return label
    return None


def is_paint_obs(o: dict) -> bool:
    tc = str((o.get("hints") or {}).get("tradeCategory") or "").lower()
    return tc.startswith("paint") or tc.startswith("spray")


def main() -> None:
    # index the paint catalog: (set, normalized name) -> canonical "{Name}|{Set}" key
    citadel = yaml.safe_load(CITADEL.read_text(encoding="utf-8"))["paints"]
    by_key: dict[tuple[str, str], str] = {}
    for p in citadel:
        s = (p.get("details") or {}).get("set") or ""
        by_key[(s, norm(p["name"]))] = f"{p['name']}|{s}"

    # collect trade paint barcodes, newest (WH Colour) preferred as primary
    entries: dict[str, dict] = {}
    matched = 0
    unmatched: list[str] = []
    for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        if not is_paint_obs(o) or not o.get("ean"):
            continue
        tc = (o.get("hints") or {}).get("tradeCategory")
        pset = set_from_trade_category(tc, o.get("name") or "")
        if pset is None:
            continue
        pname = clean_paint_name(o.get("name") or "")
        key = by_key.get((pset, norm(pname)))
        if key is None:
            unmatched.append(f"{pset}: {o.get('name')}")
            continue
        matched += 1
        ssc = str((o.get("hints") or {}).get("sscCode") or "")
        # WH Colour rows carry a rebrand SKU (9918996...) and are the current barcode; prefer them.
        is_new = str(o.get("sku") or "").startswith("9918996")
        cur = entries.get(key)
        if cur is None:
            entries[key] = {"ean": o["ean"], "productCode": str(o.get("sku") or ""), "ssc": ssc,
                            "_new": is_new, "additionalEans": []}
        else:
            if is_new and not cur["_new"]:
                cur["additionalEans"].append(cur["ean"])
                cur.update(ean=o["ean"], productCode=str(o.get("sku") or ""), ssc=ssc, _new=True)
            elif o["ean"] != cur["ean"] and o["ean"] not in cur["additionalEans"]:
                cur["additionalEans"].append(o["ean"])

    # emit: {brand-slug}: {"{Name}|{Set}": {ean, productCode, ssc, additionalEans?}}
    brand: dict[str, dict] = {}
    for key, v in sorted(entries.items()):
        rec = {"ean": v["ean"]}
        if v["productCode"]:
            rec["productCode"] = v["productCode"]
        if v["ssc"]:
            rec["ssc"] = v["ssc"]
        if v["additionalEans"]:
            rec["additionalEans"] = sorted(set(v["additionalEans"]))
        brand[key] = rec

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# GENERATED by tools/acquisition/scripts/gen_paint_barcodes.py -- do not hand-edit.\n"
        "# Maps the paint catalog's {Name}|{Set} identity to GW trade barcodes. The C# BarcodeEnricher\n"
        "# does an exact lookup; the fuzzy trade->catalog match happened at generation time.\n"
        + yaml.safe_dump({"citadel-colour": brand}, sort_keys=True, allow_unicode=True, width=200),
        encoding="utf-8",
    )
    print(f"citadel paints: {len(citadel)} | matched trade barcodes: {matched} | emitted: {len(brand)}")
    print(f"unmatched trade paint rows: {len(unmatched)}")
    for u in unmatched[:15]:
        print("   ", u)


if __name__ == "__main__":
    main()
