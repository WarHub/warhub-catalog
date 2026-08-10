"""Generate data/paints/barcodes/citadel-colour.yaml — the Citadel paint manufacturer bridge.

The paint catalog (C#) has no product code/SKU, so it cannot join the GW trade rows directly.
This script does the fuzzy match ONCE, here, and emits a file keyed by the paint catalog's own
`{Name}|{Set}` identity so the C# BarcodeEnricher only ever does an exact lookup. The match is
auditable: the committed YAML shows exactly which paint got which barcode.

Match key: (set, normalized name), with volume as a tiebreaker. Source: the resolved
mfr-gw-trade paint observations (the UNIT barcode, not the 6-pack case code).

WHAT CROSSES THIS BRIDGE, and what deliberately does not:

- `ean` — the manufacturer's barcode. Backfilled into a BLANK slot only; `additionalEans` are
  unioned in alongside it so no live barcode is ever displaced.
- `volumeMl` — GW's own `SIZE` column (`hints.volumeMl`), the manufacturer asserting the pot size
  of the thing it is selling. This one WINS over the C# `VolumeTable`, which is a hardcoded
  per-(brand, set) guess: the table lumps `Air` in with `Base`/`Layer` at 12 ml, while GW ships
  Air at 24 ml and says so in the SIZE column AND in the row's own name (`AIR: AVERLAND SUNSET
  (24ML)`). Technical is genuinely mixed (12 / 18 / 24 ml) and no per-set constant can be right
  for it at all. `volumeMl` is NOT part of the paint identity key (`set|name|productCode|hex`),
  so unlike `productCode` below it backfills onto the existing record instead of re-keying it.
- `productCode` / `ssc` — emitted for AUDIT ONLY; the C# side must not apply `productCode`,
  because it IS part of the identity key and writing it would re-key and duplicate every matched
  paint against its archived null-productCode record.
- `availability` — deliberately NOT carried, and it could not be even if we wanted it: every one
  of the 7,611 mfr-gw-trade observations has no availability at all (a trade price list has no
  stock signal). The product catalog's `in_stock` for these SKUs comes from retailer/webstore
  feeds (ret-goblingaming, ret-tistaminis, mfr-gw-algolia) resolved on a different cadence.
  Carrying it would mean (a) a new dependency from the paint pipeline onto the RESOLVED product
  catalog rather than evidence, (b) attributing one retailer's stock for one SKU to a paint
  identity that spans several SKUs (single pot + 6-pack, R/O-Europe + UK/ROW), and (c) baking a
  volatile value into a git-committed append-only archive, churning ~300 records a week off
  retailer stock noise. `unknown` is the honest value there; the paint tool already forces it
  back to `unknown` when a paint vanishes from its source.

A paint can appear under more than one trade SKU. Measured on the committed evidence, every such
case is a CONCURRENT REGIONAL pair -- e.g. Chaos Black Spray is sold as `80209999077`
(R/O Europe, EAN 5011921172221) and `99209999090` (UK/ROW, EAN 5011921175291) under one shared SSC
code 62-02. Both barcodes are live. All of them are kept: the first observed takes the `ean` slot
and the rest go to `additionalEans`, so a scan of either resolves. Nothing here identifies an
OLD vs NEW barcode -- the genuine re-barcoding record is the InsertDelete workbook's `Code Changes`
sheet (an `Old Barcode` column the strategy does not read yet), not this file.

Runs automatically in .github/workflows/paint-catalog-update.yml (before the C# tool's --barcodes
step) so new/rebranded Citadel barcodes flow in without a hand-run; also runnable directly:
`uv run --with pyyaml python tools/acquisition/scripts/gen_paint_barcodes.py`
"""
from __future__ import annotations

import difflib
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
    # Cross-pipeline dependency: the GW trade evidence is produced by the acquire pipeline, a
    # separate workflow. If it hasn't been harvested yet (fresh clone, or run before the first
    # mfr-gw-trade acquisition), skip cleanly and leave the existing committed barcode file as-is
    # rather than crash the paint-catalog workflow.
    if not EVIDENCE.exists():
        print(f"SKIP: no GW trade evidence at {EVIDENCE.relative_to(REPO)}; "
              "leaving data/paints/barcodes/citadel-colour.yaml untouched.")
        return

    # index the paint catalog: (set, normalized name) -> canonical "{Name}|{Set}" key,
    # plus per-set normalized-name lists for a fuzzy fallback (apostrophe-s, "Flesh"->"Fleshtone",
    # "Casandora"/"Cassandora" spelling, etc. -- all real GW paints already in the catalog with
    # colour, just under a name variant).
    citadel = yaml.safe_load(CITADEL.read_text(encoding="utf-8"))["paints"]
    by_key: dict[tuple[str, str], str] = {}
    names_by_set: dict[str, dict[str, str]] = {}
    for p in citadel:
        s = (p.get("details") or {}).get("set") or ""
        by_key[(s, norm(p["name"]))] = f"{p['name']}|{s}"
        names_by_set.setdefault(s, {})[norm(p["name"])] = f"{p['name']}|{s}"

    def resolve_key(pset: str, pnorm: str) -> str | None:
        exact = by_key.get((pset, pnorm))
        if exact is not None:
            return exact
        # fuzzy fallback WITHIN the same set only (never cross-set), high cutoff to avoid
        # mis-assigning a barcode; a paint name is unique within its set so this is safe.
        pool = names_by_set.get(pset, {})
        close = difflib.get_close_matches(pnorm, list(pool), n=1, cutoff=0.86)
        return pool[close[0]] if close else None

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
        key = resolve_key(pset, norm(pname))
        if key is None:
            unmatched.append(f"{pset}: {o.get('name')}")
            continue
        matched += 1
        hints = o.get("hints") or {}
        ssc = str(hints.get("sscCode") or "")
        cur = entries.get(key)
        if cur is None:
            cur = entries[key] = {"ean": o["ean"], "productCode": str(o.get("sku") or ""),
                                  "ssc": ssc, "additionalEans": [], "volumes": set()}
        elif o["ean"] != cur["ean"] and o["ean"] not in cur["additionalEans"]:
            # Same paint under a second trade SKU -- keep BOTH barcodes. Which one holds the
            # primary `ean` slot is decided purely by evidence order (first seen wins); that is
            # acceptable precisely because the other is retained here rather than dropped, so a
            # scan of either resolves. Do NOT read the primary as "the current/newer" barcode.
            cur["additionalEans"].append(o["ean"])
        # GW's own SIZE column for this row, gathered from EVERY trade SKU that maps to this
        # paint (not just the first) and kept as a SET, so a disagreement between two SKUs is
        # detectable rather than silently decided by evidence order. Measured on the committed
        # evidence there are zero such disagreements -- all 297 matched paints carry exactly one
        # volume -- but a future workbook could introduce one, and guessing is what this bridge
        # exists to stop.
        if isinstance(hints.get("volumeMl"), int):
            cur["volumes"].add(hints["volumeMl"])

    # emit: {brand-slug}: {"{Name}|{Set}": {ean, productCode, ssc, volumeMl?, additionalEans?}}
    brand: dict[str, dict] = {}
    volumes_emitted = 0
    volume_conflicts: list[str] = []
    for key, v in sorted(entries.items()):
        rec = {"ean": v["ean"]}
        if v["productCode"]:
            rec["productCode"] = v["productCode"]
        if v["ssc"]:
            rec["ssc"] = v["ssc"]
        if len(v["volumes"]) == 1:
            rec["volumeMl"] = next(iter(v["volumes"]))
            volumes_emitted += 1
        elif len(v["volumes"]) > 1:
            # Two trade SKUs for one paint identity claiming different pot sizes. Emit NOTHING:
            # the C# side then keeps its per-set table value rather than this bridge picking a
            # winner by evidence order. Loud, because it means either the match is wrong or GW
            # really does ship this paint in two sizes and the catalog needs two records.
            volume_conflicts.append(f"{key}: {sorted(v['volumes'])}")
        if v["additionalEans"]:
            rec["additionalEans"] = sorted(set(v["additionalEans"]))
        brand[key] = rec

    OUT.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "# GENERATED by tools/acquisition/scripts/gen_paint_barcodes.py -- do not hand-edit.\n"
        "# Maps the paint catalog's {Name}|{Set} identity to the manufacturer's own assertions from\n"
        "# the GW trade sheets: barcodes, and `volumeMl` from GW's SIZE column. The C# BarcodeEnricher\n"
        "# does an exact lookup; the fuzzy trade->catalog match happened at generation time.\n"
        "# `volumeMl` OVERRIDES the tool's hardcoded per-set VolumeTable (a hand override still wins);\n"
        "# `productCode`/`ssc` are audit-only -- applying productCode would re-key the paint.\n"
        + yaml.safe_dump({"citadel-colour": brand}, sort_keys=True, allow_unicode=True, width=200)
    )
    # write_bytes (not write_text) so the committed file is LF on every platform -- write_text would
    # emit CRLF on Windows and churn the diff for a maintainer running this locally.
    OUT.write_bytes(content.encode("utf-8"))
    print(f"citadel paints: {len(citadel)} | matched trade barcodes: {matched} | emitted: {len(brand)}")
    print(f"entries carrying a manufacturer volumeMl: {volumes_emitted}/{len(brand)}")
    print(f"unmatched trade paint rows: {len(unmatched)}")
    for u in unmatched[:15]:
        print("   ", u)
    if volume_conflicts:
        print(f"VOLUME CONFLICTS (no volumeMl emitted for these): {len(volume_conflicts)}")
        for c in volume_conflicts[:15]:
            print("   ", c)


if __name__ == "__main__":
    main()
