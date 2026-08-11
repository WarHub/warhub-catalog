"""Generate data/paints/barcodes/citadel-colour.yaml — the Citadel paint manufacturer bridge.

The paint catalog (C#) has no product code/SKU, so it cannot join the GW trade rows directly.
This script does the fuzzy match ONCE, here, and emits a file keyed by the paint catalog's own
`{Name}|{Set}` identity so the C# BarcodeEnricher only ever does an exact lookup. The match is
auditable: the committed YAML shows exactly which paint got which barcode.

Match key: (set, normalized name), with volume as a tiebreaker. Source: the resolved
mfr-gw-trade paint observations (the SINGLE-pot barcode, not the case code).

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
- `price` — NOT carried, because there is none to carry. Measured 2026-08-04 on the committed
  snapshot: the ONLY workbook with a retail column is `Trade Direct Range Sterling` (964 rows, a
  `UKR` column), and its 964 product codes intersect the 914 distinct codes on the paint sheets in
  exactly **0** places. Consequently 0 of the 938 `hints.category: paint` observations carry
  `priceGbp`, and `priceUsd` / `priceEur` / `priceCad` exist on the Observation model but are
  populated by NO strategy at all (`gw_trade_sheets` sets only `priceGbp=_price(row, "UKR")`).
  GW's paint workbooks -- `Individual Barcodes` and `WH Colour Codes and Barcodes` -- are barcode
  registers: their columns are code, barcode, description, range, SSC, size. No price column
  exists to read. This is a SOURCE gap, not a bridge gap; the fix, if price is ever wanted, is a
  new acquisition (the webstore paint strategy, or a retailer feed), not a change here. Note also
  that the descriptions on both paint sheets are CASE descriptions (`... (6-PACK)` / `... X6`),
  so even if a paint sheet ever grew a price column it would be a case price and would need
  dividing before it could be published against a single pot.
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

TWO WORKBOOKS FEED THIS BRIDGE, and only one of them names the paint set:

- `Individual Barcodes April 2025` (`Paints`/`Sprays` sheets, 346 rows) — columns
  `Barcode (Single)`, `Unit Code`, `Range`, `SIZE`, `SSC`. Its `Range` column says
  `Paint - WH Colour - Layer`, so `tradeCategory` alone identifies the set.
- `WH Colour Codes and Barcodes` (`Paint` sheet, 592 rows, the 2026 rebrand) — columns
  `New Individual barcode`, `New SKU`, `Original SKU`, `Range`, `SSC`. Its `Range` column holds
  merchandising codes (`BS:A` 260, `E:P360` 182, `E:P210` 112, `BS:F` 38), NOT the set, so these
  rows are tagged only `hints.category: paint` and used to fall out of the gate entirely.

Those 592 rows are re-codings of paints this file ALREADY carries: each `supersedes` the very
product code sitting in the file today, under the SAME SSC and the SAME `volumeMl`. Air Abaddon
Black (SSC 28-15, 24 ml) is the worked example -- old `99189958145`/`5011921182848`, superseded by
`99189958220`/`5011921199457` (ROW) and `56189958220`/`5011921244379` (JUC). The barcode column is
literally headed `New Individual barcode`; these are single-pot barcodes, in exactly the sense the
older sheet's `Barcode (Single)` is. They are NOT case barcodes, and the `X6` in the description
does not make them so -- 349 of the 351 rows this bridge already admits ALSO say `(6-PACK)`/`X6`
in their name, because GW writes both sheets' descriptions from the trade case. The name is a
case name and the barcode column is a single barcode; that is true of both workbooks alike.

Set assignment for the rebrand rows is therefore NOT inferred from `Range`, which would be wrong:
`E:P360` alone spans SSC prefixes 21/22/27/28/29 (Base/Layer/Technical/Air/Contrast), so reading
it as "Air" would mis-set 92 of its 182 rows. Nor is it inferred from the SSC PREFIX, which is
ambiguous at 27 (21 Technical + 2 Contrast -- Hexwraith Flame 27-20 and Nighthaunt Gloom 27-19
are Contrast paints living in the Technical block). It is looked up on the FULL SSC code against
the set the OTHER workbook states for that same code -- an exact join, no inference. Measured:
335 SSC codes have a stated set, none of them contradictory, and all 592 rebrand rows land on one.

A paint can appear under more than one trade SKU. Every such case is a CONCURRENT REGIONAL pair or
a re-coding -- e.g. Chaos Black Spray is sold as `80209999077` (R/O Europe, EAN 5011921172221) and
`99209999090` (UK/ROW, EAN 5011921175291) under one shared SSC code 62-02. All of them are kept:
one takes the `ean` slot and the rest go to `additionalEans`, so a scan of any of them resolves.
Nothing here identifies an OLD vs NEW barcode -- the genuine re-barcoding record is the lineage
`supersedes` hint, not this file. The primary slot goes to a row whose own `Range` names the set,
never to an SSC-joined rebrand row; that is a stability rule, not a currency claim, and it is what
keeps a rebrand harvest from rewriting all ~300 primary barcodes in one commit.

Runs automatically in .github/workflows/paint-catalog-update.yml (before the C# tool's --barcodes
step) so new/rebranded Citadel barcodes flow in without a hand-run; also runnable directly:
`uv run --with pyyaml python tools/acquisition/scripts/gen_paint_barcodes.py`
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]

# Same pure-pyyaml bootstrap gen_paint_harvest.py uses (see its comment for why the import graph
# matters): `norm` was the identical five-line body in both scripts until 2026-08-07.
sys.path.insert(0, str(REPO / "tools/acquisition/src"))
from warhub_acquisition.paints.catalog import norm  # noqa: E402
# yamlio imports nothing but re/pathlib/yaml, so the `--with pyyaml` invocation above still works.
from warhub_acquisition.yamlio import dump_yaml  # noqa: E402

EVIDENCE = REPO / "data/evidence/products/mfr-gw-trade/observations.jsonl"
CITADEL = REPO / "data/paints/brands/citadel-colour.yaml"
OUT = REPO / "data/paints/barcodes/citadel-colour.yaml"

# tradeCategory "Paint - WH Colour - <Set>" / "Spray - Colour" -> the paint catalog `set`.
_SET_FROM_TRADE = {
    "base": "Base", "layer": "Layer", "shade": "Shade", "contrast": "Contrast",
    "dry": "Dry", "technical": "Technical", "air": "Air", "spray": "Spray",
}


def clean_paint_name(raw: str) -> str:
    n = raw.upper()
    n = re.sub(r"^\s*[A-Z][A-Z ./]*:\s*", "", n)          # leading "BASE:" / "C:" / "SPRAY -" prefix
    n = re.sub(r"\(.*?\)", " ", n)                          # (12ML), (6-PACK), (UK/ROW), ...
    n = re.sub(r"\b\d+\s*ML\b", " ", n)                     # bare "12ML"
    # ... plus the region/pack tokens GW appends. `JUC` is the rebrand sheet's spelling of the
    # Japan/US/Canada edition and appears on 295 of its 592 rows; without it here `XV-88 12ML JUC
    # X6` normalizes to `xv88juc`, which is 0.73 against `xv88` and misses. No row in the older
    # workbook contains the token, so adding it cannot move an existing match.
    n = re.sub(r"\b(6[\s-]*PACK|6[\s-]*PK|SINGLE|ROW|UK|EU|AU|JUC|GLOBAL|X6|X3)\b", " ", n)
    n = re.sub(r"\bSPRAY\b|\bPAINT\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


# GW abbreviates a few names in the trade sheet past what a 0.86 fuzzy match can bridge:
# `MECH STANDARD GREY` vs `Mechanicus Standard Grey` scores 0.842 and `MORTARION GREEN` vs
# `Mortarion Green Clear` 0.849. Both are hand-verified unambiguous -- each is the ONLY Air paint
# with that prefix -- and without them the two paints carry no barcode at all (5011921182831 and
# 5011921183500 reach nothing). Preferred over lowering the cutoff, which would loosen every match
# in the file to rescue two.
_NAME_ALIASES = {
    "mechstandardgrey": "mechanicusstandardgrey",
    "mortariongreen": "mortariongreenclear",
}


def set_from_trade_category(tc: str | None, name: str) -> str | None:
    tc = (tc or "").lower()
    if "spray" in tc or "spray" in name.lower():
        return "Spray"
    for token, label in _SET_FROM_TRADE.items():
        if f"- {token}" in tc or tc.endswith(token):
            return label
    return None


def is_paint_obs(o: dict) -> bool:
    """A paint row whose own trade `Range` NAMES the set -- the `Individual Barcodes` workbook.

    These rows are self-describing, so they seed the SSC->set table and they own the primary
    `ean`/`productCode`/`ssc` slots. `is_rebrand_paint_obs` handles the rest.
    """
    tc = str((o.get("hints") or {}).get("tradeCategory") or "").lower()
    return tc.startswith("paint") or tc.startswith("spray")


def is_rebrand_paint_obs(o: dict) -> bool:
    """A paint row the sheet TITLE calls paint but whose `Range` is a merchandising code.

    The 2026 `WH Colour Codes and Barcodes` workbook, 592 rows. It carries a real single-pot
    barcode and a real `volumeMl` but cannot say which set the paint belongs to, so it is admitted
    only where the full SSC code has a set stated by a `is_paint_obs` row -- see the module
    docstring for why `Range` and the SSC prefix are both unsafe to infer from.
    """
    return (o.get("hints") or {}).get("category") == "paint" and not is_paint_obs(o)


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
        pnorm = _NAME_ALIASES.get(pnorm, pnorm)
        exact = by_key.get((pset, pnorm))
        if exact is not None:
            return exact
        # fuzzy fallback WITHIN the same set only (never cross-set), high cutoff to avoid
        # mis-assigning a barcode; a paint name is unique within its set so this is safe.
        pool = names_by_set.get(pset, {})
        close = difflib.get_close_matches(pnorm, list(pool), n=1, cutoff=0.86)
        return pool[close[0]] if close else None

    observations = [json.loads(line) for line in EVIDENCE.read_text(encoding="utf-8").splitlines()
                    if line.strip()]

    entries: dict[str, dict] = {}

    def absorb(key: str, o: dict) -> None:
        """Fold one trade row into the entry for `key`, never displacing what is already there."""
        hints = o.get("hints") or {}
        cur = entries.get(key)
        if cur is None:
            cur = entries[key] = {"ean": o["ean"], "productCode": str(o.get("sku") or ""),
                                  "ssc": str(hints.get("sscCode") or ""),
                                  "additionalEans": [], "volumes": set()}
        elif o["ean"] != cur["ean"] and o["ean"] not in cur["additionalEans"]:
            # Same paint under a second trade SKU -- keep BOTH barcodes. Which one holds the
            # primary `ean` slot is decided by pass order (a set-stating row always wins) and then
            # by evidence order; that is acceptable precisely because the others are retained here
            # rather than dropped, so a scan of any of them resolves. Do NOT read the primary as
            # "the current/newer" barcode -- for a re-coded paint it is provably the older one.
            cur["additionalEans"].append(o["ean"])
        # GW's own SIZE column for this row, gathered from EVERY trade SKU that maps to this
        # paint (not just the first) and kept as a SET, so a disagreement between two SKUs is
        # detectable rather than silently decided by evidence order. Guessing is what this bridge
        # exists to stop.
        if isinstance(hints.get("volumeMl"), int):
            cur["volumes"].add(hints["volumeMl"])

    # PASS 1 -- rows whose own trade `Range` names the set. These build the file's primary slots,
    # and they are the ONLY source of the SSC->set table pass 2 joins against.
    set_by_ssc: dict[str, set[str]] = {}
    matched = 0
    unmatched: list[str] = []
    for o in observations:
        if not is_paint_obs(o) or not o.get("ean"):
            continue
        hints = o.get("hints") or {}
        pset = set_from_trade_category(hints.get("tradeCategory"), o.get("name") or "")
        if pset is None:
            continue
        ssc = str(hints.get("sscCode") or "")
        if ssc:
            set_by_ssc.setdefault(ssc, set()).add(pset)
        key = resolve_key(pset, norm(clean_paint_name(o.get("name") or "")))
        if key is None:
            unmatched.append(f"{pset}: {o.get('name')}")
            continue
        matched += 1
        absorb(key, o)

    # An SSC code that two rows disagree about cannot be joined against; measured there are none,
    # but a future workbook could reclassify a colour mid-flight and this must not guess.
    ambiguous_ssc = sorted(s for s, v in set_by_ssc.items() if len(v) > 1)
    stated_set: dict[str, str] = {s: next(iter(v)) for s, v in set_by_ssc.items() if len(v) == 1}

    # PASS 2 -- the rebrand workbook, joined on the FULL SSC code. Runs second so it can only ever
    # ADD to an entry pass 1 built, never take its primary barcode.
    reached = matched_rebrand = 0
    unjoinable: list[str] = []
    rebrand_unmatched: list[str] = []
    new_keys: list[str] = []
    for o in observations:
        if not is_rebrand_paint_obs(o) or not o.get("ean"):
            continue
        reached += 1
        pset = stated_set.get(str((o.get("hints") or {}).get("sscCode") or ""))
        if pset is None:
            unjoinable.append(f"{o.get('sku')} ssc={(o.get('hints') or {}).get('sscCode')}: {o.get('name')}")
            continue
        key = resolve_key(pset, norm(clean_paint_name(o.get("name") or "")))
        if key is None:
            rebrand_unmatched.append(f"{pset}: {o.get('name')}")
            continue
        matched_rebrand += 1
        if key not in entries:
            # A colour the older workbook never listed. Measured today: none -- every rebrand row
            # re-codes a paint already here. Allowed anyway, because a colour that only ever ships
            # under its new code has nowhere else to enter the bridge.
            new_keys.append(key)
        absorb(key, o)

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
        # dump_yaml (not yaml.safe_dump) because `ean`/`productCode` are the join, and safe_dump
        # decides whether to protect them by which DIGITS happen to appear. Its YAML 1.1 resolver
        # quotes '5011921193066' (that reads as an int, so it must be), but a leading-zero code is
        # only quoted when it is valid octal: '0812152031524' contains an 8, so PyYAML calls it a
        # string, emits it BARE, and reads its own output back correctly -- while a YAML 1.2
        # consumer, which has no octal rule for a bare leading zero, reads 812152031524 and the pad
        # that IS the join is gone. data/catalog/products/wyrd-games.yaml:3082 carries exactly that
        # EAN today (quoted, because the C# writer force-quotes); GW's own codes simply have not
        # handed this file a leading zero yet. Measured 2026-08-11 on the committed
        # data/paints/barcodes/citadel-colour.yaml: 0 of its scalars are bare-and-number-shaped, so
        # this closes an EXPOSURE, not a live bug -- the file is one upstream code away from it.
        #
        # sort_keys is the one thing that does not carry over: safe_dump sorted every level and
        # dump_yaml preserves insertion order, so the sort moves here explicitly. Sorting both
        # levels reproduces safe_dump's order exactly (PyYAML sorts (key, value) pairs, and the
        # keys are unique, so it is a plain key sort) and keeps the diff to what _Dumper changes.
        + dump_yaml({"citadel-colour": {
            key: {field: brand[key][field] for field in sorted(brand[key])}
            for key in sorted(brand)
        }})
    )
    # write_bytes (not write_text) so the committed file is LF on every platform -- write_text would
    # emit CRLF on Windows and churn the diff for a maintainer running this locally.
    OUT.write_bytes(content.encode("utf-8"))
    print(f"citadel paints: {len(citadel)} | matched trade barcodes: {matched} | emitted: {len(brand)}")
    print(f"entries carrying a manufacturer volumeMl: {volumes_emitted}/{len(brand)}")
    print(f"SSC->set table from range-stating rows: {len(stated_set)} codes"
          f"{f' ({len(ambiguous_ssc)} AMBIGUOUS, skipped: {ambiguous_ssc})' if ambiguous_ssc else ''}")
    print(f"rebrand rows reached: {reached} | joined on SSC + matched: {matched_rebrand} | "
          f"new paint keys they alone reach: {len(new_keys)}")
    for k in sorted(set(new_keys))[:15]:
        print("    NEW", k)
    if unjoinable:
        print(f"rebrand rows with no SSC->set join (dropped): {len(unjoinable)}")
        for u in unjoinable[:15]:
            print("   ", u)
    print(f"unmatched trade paint rows: {len(unmatched)} range-stated + "
          f"{len(rebrand_unmatched)} rebrand")
    for u in unmatched[:15]:
        print("   ", u)
    if volume_conflicts:
        print(f"VOLUME CONFLICTS (no volumeMl emitted for these): {len(volume_conflicts)}")
        for c in volume_conflicts[:15]:
            print("   ", c)


if __name__ == "__main__":
    main()
