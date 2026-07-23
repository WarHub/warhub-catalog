"""Generate data/paints/harvest/<brand>.yaml — manufacturer paint-harvest bridge files.

Projects the committed paint-source evidence (data/evidence/products/mfr-*/observations.jsonl,
produced by the shopify-paints / wp-rest-paints / woo-paints acquire strategies) onto the paint
catalog's own identities, ONCE, here — so the C# HarvestApplier only ever does exact lookups
(same architecture as gen_paint_barcodes.py). The committed YAML is the audit trail: it shows
exactly which store/catalog product matched which paint.

Per-source ROLES (owner decision, 2026-07-23 — see
docs/research/2026-07-23-paint-manufacturer-harvest-design.md):

- catalog  (mfr-vallejo): may propose NEW paints (`additions`) and enrich existing ones.
- metadata (mfr-armypainter, mfr-monument, mfr-turbodork, mfr-ak-interactive): storefronts
  are never catalog-providers — matched products only fill blanks on EXISTING identities
  (`enrich`: ean/imageUrl); unmatched paint-like products land in `candidates` (report-only,
  ignored by C#) for a human to review.

Output shape per brand file:

    <brand-slug>:
      enrich:
        "{Name}|{Set}": {ean?, imageUrl?, sku?, sourceUrl, source}
      additions:
        - {name, set, productCode?, imageUrl?, sourceUrl, source}
      candidates:
        - {name, sku?, url?, source, reason}

Paint ranges are mostly one-off snapshots (rarely re-run) — this script reads only committed
files and is deterministic; run it after any manual acquire run:
`uv run --with pyyaml python tools/acquisition/scripts/gen_paint_harvest.py`
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
EVIDENCE_DIR = REPO / "data/evidence/products"
BRANDS_DIR = REPO / "data/paints/brands"
OUT_DIR = REPO / "data/paints/harvest"

# SM (Speedpaint Marker) deliberately excluded: markers share paint NAMES with the Speedpaint
# range but are a different product form with their own EANs -- a marker EAN on a dropper
# paint record would be a false barcode (caught in the 2026-07-23 harvest review).
TAP_SINGLE_SKU = re.compile(r"^(WP|AW|CP|GM|QS|BF|ST)\d{4}[PS]?$")
TAP_SINGLE_MAX_GRAMS = 130  # singles are 26-31 g droppers; sprays handled by sku prefix CP
MONUMENT_NAME = re.compile(r"^PRO Acryl (?:1-Step )?(?:\d+ )?-? ?", re.IGNORECASE)

# Vallejo product_cat slug -> catalog set name. Existing sets use the Arcturus spelling so
# code-matched enrichment and additions key the same way; starred ones are NEW ranges absent
# from the Arcturus base (additions will create them).
VALLEJO_SET_BY_CATEGORY = {
    "model-color-en": "Model Color",
    "model-air-en": "Model Air",
    "game-color-en": "Game Color",
    "game-air-en": "Game Air",
    "xpress-color-en": "Xpress Color",
    "mecha-color-en": "Mecha Color",
    "metal-color-en": "Metal Color",
    "liquid-metal-en": "Liquid Gold",
    "true-metallic-metal-en": "True Metallic Metal",  # *
    "premium-color-en": "Premium Airbrush Color",
    "hobby-paint": "Hobby Paint",
    "primers-en": "Surface Primer",
    "weathering-fx-en": "Weathering FX",
    "wash-fx-en": "Wash FX",
    "pigment-fx-en": "Pigment FX",  # *
    "diorama-fx-en": "Diorama FX",  # *
    "auxiliary-products-hobby": "Auxiliaries",  # *
}

# Army Painter shop title prefix (before ":") -> catalog set. Only prefixes that resolve to an
# Arcturus set enrich; anything else stays name-matched or a candidate.
TAP_SET_BY_PREFIX = {
    "warpaints fanatic": "Warpaints Fanatic",
    "warpaints fanatic wash": "Warpaints Fanatic Wash",
    "warpaints fanatic effects": "Warpaints Fanatic",
    "warpaints fanatic metallic": "Warpaints Fanatic",
    "warpaints air": "Warpaints Air",
    "warpaints air metallics": "Warpaints Air",
    "speedpaint": "Speedpaint Set 2.0",
    "colour primer": "Warpaints Primer",
}


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def read_observations(source_id: str) -> list[dict]:
    path = EVIDENCE_DIR / source_id / "observations.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


class Catalog:
    """Existing brand catalog indexed for exact/normalized joins."""

    def __init__(self, slug: str):
        self.slug = slug
        path = BRANDS_DIR / f"{slug}.yaml"
        self.paints: list[dict] = []
        if path.exists():
            self.paints = yaml.safe_load(path.read_text(encoding="utf-8")).get("paints") or []
        self.by_code: dict[str, str] = {}
        self.by_name: dict[str, list[str]] = {}
        self.keys: set[str] = set()
        for p in self.paints:
            s = (p.get("details") or {}).get("set") or ""
            key = f"{p['name']}|{s}"
            self.keys.add(key)
            code = str(p.get("productCode") or "")
            if code:
                self.by_code.setdefault(code, key)
            self.by_name.setdefault(norm(p["name"]), []).append(key)

    def match_code(self, code: str | None) -> str | None:
        return self.by_code.get(code or "")

    def match_name(self, name: str | None, set_hint: str | None = None) -> str | None:
        keys = self.by_name.get(norm(name), [])
        if len(keys) == 1:
            return keys[0]
        if set_hint:
            in_set = [k for k in keys if k.endswith(f"|{set_hint}")]
            if len(in_set) == 1:
                return in_set[0]
        return None


class BrandHarvest:
    def __init__(self) -> None:
        self.enrich: dict[str, dict] = {}
        self.additions: list[dict] = []
        self.candidates: list[dict] = []

    def add_enrich(self, key: str, **fields: object) -> None:
        entry = self.enrich.setdefault(key, {})
        for k, v in fields.items():
            if v not in (None, "") and k not in entry:
                entry[k] = v

    def to_yaml(self) -> dict:
        out: dict[str, object] = {}
        if self.enrich:
            out["enrich"] = {k: self.enrich[k] for k in sorted(self.enrich)}
        if self.additions:
            out["additions"] = sorted(
                self.additions, key=lambda a: (a.get("set") or "", a.get("name") or "")
            )
        if self.candidates:
            out["candidates"] = sorted(
                self.candidates, key=lambda c: (c.get("reason") or "", c.get("name") or "")
            )
        return out


def vallejo_code(raw_sku: str | None) -> str | None:
    """'72001' -> '72.001' (Vallejo's display/catalog code). Non-5-digit codes pass through."""
    if not raw_sku:
        return None
    digits = str(raw_sku)
    if re.fullmatch(r"\d{5}", digits):
        return f"{digits[:2]}.{digits[2:]}"
    return digits


def bridge_vallejo() -> BrandHarvest:
    catalog = Catalog("vallejo")
    out = BrandHarvest()
    for o in read_observations("mfr-vallejo"):
        slugs = (o.get("hints") or {}).get("categorySlugs") or []
        set_name = next(
            (VALLEJO_SET_BY_CATEGORY[s] for s in slugs if s in VALLEJO_SET_BY_CATEGORY), None
        )
        code = vallejo_code(o.get("sku"))
        common = {"sourceUrl": o.get("url"), "source": "mfr-vallejo"}
        if code is None:
            out.candidates.append(
                {"name": o["name"], "url": o.get("url"), "source": "mfr-vallejo",
                 "reason": "no catalog code on product slug"}
            )
            continue
        key = catalog.match_code(code)
        if key is None and set_name is not None:
            key = catalog.match_name(o["name"], set_name)
        if key is not None:
            out.add_enrich(key, imageUrl=o.get("imageUrl"), sku=code, **common)
        elif set_name is not None:
            out.additions.append(
                {"name": o["name"], "set": set_name, "productCode": code,
                 "imageUrl": o.get("imageUrl"), **common}
            )
        else:
            out.candidates.append(
                {"name": o["name"], "sku": code, "url": o.get("url"), "source": "mfr-vallejo",
                 "reason": f"no set mapping for categories: {','.join(slugs) or '(none)'}"}
            )
    return out


def bridge_ak() -> BrandHarvest:
    catalog = Catalog("ak-interactive")
    out = BrandHarvest()
    for o in read_observations("mfr-ak-interactive"):
        sku = str(o.get("sku") or "")
        key = catalog.match_code(sku)
        if key is not None:
            out.add_enrich(key, imageUrl=o.get("imageUrl"), sku=sku,
                           sourceUrl=o.get("url"), source="mfr-ak-interactive")
        else:
            slugs = (o.get("hints") or {}).get("categorySlugs") or []
            is_set = any("set" in s for s in slugs) or "SET" in (o.get("name") or "").upper()
            out.candidates.append(
                {"name": o["name"], "sku": sku or None, "url": o.get("url"),
                 "source": "mfr-ak-interactive",
                 "reason": "set/bundle (not a single)" if is_set else "no matching product code in catalog"}
            )
    return out


def tap_split(title: str) -> tuple[str | None, str]:
    """'Warpaints Fanatic: Moldy Wine' -> ('warpaints fanatic', 'Moldy Wine')."""
    if ":" in title:
        prefix, _, name = title.partition(":")
        return prefix.strip().lower(), name.strip()
    return None, title.strip()


def bridge_armypainter() -> BrandHarvest:
    catalog = Catalog("army-painter")
    out = BrandHarvest()
    for o in read_observations("mfr-armypainter"):
        hints = o.get("hints") or {}
        sku = str(o.get("sku") or "")
        grams = hints.get("grams")
        prefix, paint_name = tap_split(o["name"])
        is_single = (
            TAP_SINGLE_SKU.fullmatch(sku) is not None
            and isinstance(grams, int)
            and grams <= (500 if sku.startswith("CP") else TAP_SINGLE_MAX_GRAMS)
        )
        if not is_single:
            continue  # sets/bundles/markers: not even candidates, the store is metadata-only
        set_hint = TAP_SET_BY_PREFIX.get(prefix or "")
        # Name-matching is only trusted under a RECOGNIZED range prefix: a title from an
        # unmapped range (a future product form sharing paint names, like the markers) must
        # never cross-set match by name alone. Code matches carry their own certainty.
        key = catalog.match_code(sku) or catalog.match_code(sku.rstrip("PS"))
        if key is None and set_hint is not None:
            key = catalog.match_name(paint_name, set_hint)
        if key is not None:
            out.add_enrich(key, ean=o.get("ean"), imageUrl=o.get("imageUrl"), sku=sku,
                           sourceUrl=o.get("url"), source="mfr-armypainter")
        else:
            out.candidates.append(
                {"name": o["name"], "sku": sku, "url": o.get("url"), "source": "mfr-armypainter",
                 "reason": "single not in catalog (new paint or renamed)"}
            )
    return out


def bridge_monument() -> BrandHarvest:
    catalog = Catalog("monument-pro-acryl")
    out = BrandHarvest()
    for o in read_observations("mfr-monument"):
        if (o.get("hints") or {}).get("productType") != "Paint Singles":
            continue
        sku = str(o.get("sku") or "")
        code = sku.removeprefix("MPA-")
        name = MONUMENT_NAME.sub("", o["name"]).strip()
        key = catalog.match_code(code) or catalog.match_code(code.zfill(3)) or catalog.match_name(name)
        if key is not None:
            out.add_enrich(key, ean=o.get("ean"), imageUrl=o.get("imageUrl"), sku=sku,
                           sourceUrl=o.get("url"), source="mfr-monument")
        else:
            out.candidates.append(
                {"name": o["name"], "sku": sku or None, "url": o.get("url"),
                 "source": "mfr-monument", "reason": "single not in catalog (new range or renamed)"}
            )
    return out


def bridge_turbodork() -> BrandHarvest:
    catalog = Catalog("turbo-dork")
    out = BrandHarvest()
    paint_types = {"TurboShift", "Metallic", "ZeniShift", "Retail"}
    for o in read_observations("mfr-turbodork"):
        if (o.get("hints") or {}).get("productType") not in paint_types:
            continue
        key = catalog.match_name(o["name"])
        if key is not None:
            out.add_enrich(key, ean=o.get("ean"), imageUrl=o.get("imageUrl"),
                           sku=o.get("sku"), sourceUrl=o.get("url"), source="mfr-turbodork")
        elif (o.get("hints") or {}).get("productType") != "Retail":
            # Retail is a legacy mixed bucket -- only the dedicated paint types report as
            # unmatched candidates, otherwise merch/bundles would flood the list.
            out.candidates.append(
                {"name": o["name"], "sku": o.get("sku"), "url": o.get("url"),
                 "source": "mfr-turbodork", "reason": "paint not in catalog (new or renamed)"}
            )
    return out


BRIDGES = {
    "vallejo": bridge_vallejo,
    "ak-interactive": bridge_ak,
    "army-painter": bridge_armypainter,
    "monument-pro-acryl": bridge_monument,
    "turbo-dork": bridge_turbodork,
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for slug, bridge in BRIDGES.items():
        harvest = bridge()
        data = harvest.to_yaml()
        out_path = OUT_DIR / f"{slug}.yaml"
        if not data:
            if out_path.exists():
                print(f"{slug}: no evidence -> leaving existing {out_path.name} untouched")
            else:
                print(f"{slug}: no evidence, nothing to emit")
            continue
        content = (
            "# GENERATED by tools/acquisition/scripts/gen_paint_harvest.py -- do not hand-edit.\n"
            "# Projection of committed manufacturer evidence onto the paint catalog's identities.\n"
            "# `enrich` keys are exact {Name}|{Set} identities (C# fills blank ean/imageUrl only);\n"
            "# `additions` are new paints from catalog-role sources; `candidates` are report-only.\n"
            + yaml.safe_dump({slug: data}, sort_keys=False, allow_unicode=True, width=200)
        )
        out_path.write_bytes(content.encode("utf-8"))
        print(
            f"{slug}: enrich={len(harvest.enrich)} additions={len(harvest.additions)} "
            f"candidates={len(harvest.candidates)}"
        )


if __name__ == "__main__":
    main()
