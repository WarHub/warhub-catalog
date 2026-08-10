"""The committed paint archive (data/paints/brands/<slug>.yaml), indexed for joins.

Extracted from gen_paint_harvest.py so gen_set_contents.py can join against the same index
instead of restating it. That is the f181a73 rule -- a predicate spelled twice is a predicate
that will disagree with itself -- and it applies with more force here than it did there,
because the two scripts answer the SAME question ("which paint does this manufacturer code
name?") for two different consumers.

PURE-PYYAML, DELIBERATELY. Both importers run as `uv run --with pyyaml python ...` in
.github/workflows/paint-catalog-update.yml and reach this module through a sys.path bootstrap,
so this file and the two package __init__ files on the way to it may import nothing beyond the
stdlib and yaml. Asserted, not assumed -- see tests/test_crossover.py::
test_paints_catalog_imports_no_third_party_module. In particular do NOT reach for
`warhub_acquisition.yamlio.load_yaml` here just for the libyaml speed-up: it is pyyaml-only too
and would be safe, but a brand file is parsed once per script run and the import graph is the
thing being protected.

`brands_dir` is a required argument rather than a module constant on purpose: the constant would
have to encode the repo layout from inside the package (parents[5]), and the harvest tests
monkeypatch their script's BRANDS_DIR to a tmp_path. Passing it keeps both honest.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml


def norm(s: str | None) -> str:
    """Lowercase alphanumerics only -- the repo's name-join normalizer.

    Was the identical five-line body in gen_paint_harvest.py:194 AND gen_paint_barcodes.py:111.
    """
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class Catalog:
    """Existing brand catalog indexed for exact/normalized joins."""

    def __init__(self, slug: str, brands_dir: Path):
        self.slug = slug
        path = brands_dir / f"{slug}.yaml"
        self.paints: list[dict] = []
        if path.exists():
            self.paints = yaml.safe_load(path.read_text(encoding="utf-8")).get("paints") or []
        self.by_code: dict[str, str] = {}
        # Every paint carrying a given productCode, not just the first. `by_code` above is
        # first-wins (`setdefault`) and stays that way because match_code's callers depend on
        # it, but first-wins cannot answer "does this code name exactly one paint?" -- it
        # answers "yes" unconditionally. A refusal branch built on it would be decorative.
        #
        # Measured 2026-08-07 across all 21 brand files: 198 product codes are carried by more
        # than one paint (ak-real-color 175, ak-interactive 13, coat-darmes 7, army-painter 1
        # `WP1405`, mission-models 1 `MMP-096`, vallejo 1 `72.483`). reaper has 0 of its 492, so
        # for today's only set-contents brand the several-paints branch is provably dead -- but
        # it is dead by measurement, not by construction, and 15 of those duplicates sit in
        # brands bridged live today.
        self._paints_by_code: dict[str, list[dict]] = {}
        self.by_name: dict[str, list[str]] = {}
        self.keys: set[str] = set()
        # Keys more than one paint answers to. "{Name}|{Set}" is the C# applier's whole lookup,
        # so an enrich entry on such a key lands on EVERY paint sharing it -- one ean copied
        # onto two different bottles. Real in this data: mr-hobby ships Mr Color 20 and 323 both
        # named "Light Blue". A bridge must route these to candidates, not enrich.
        self.ambiguous: set[str] = set()
        self.by_key: dict[str, list[dict]] = {}
        for p in self.paints:
            s = (p.get("details") or {}).get("set") or ""
            key = f"{p['name']}|{s}"
            if key in self.keys:
                self.ambiguous.add(key)
            self.keys.add(key)
            self.by_key.setdefault(key, []).append(p)
            code = str(p.get("productCode") or "")
            if code:
                self.by_code.setdefault(code, key)
                self._paints_by_code.setdefault(code, []).append(p)
            self.by_name.setdefault(norm(p["name"]), []).append(key)

    def paints_for_code(self, code: str | None) -> list[dict]:
        """EVERY paint carrying this product code -- 0, 1 or several.

        The honest counterpart of `match_code`, for callers that must distinguish "no paint"
        from "several paints" and refuse both rather than take the first. See `_paints_by_code`
        for why `by_code` cannot be asked this.
        """
        return list(self._paints_by_code.get(code or "", ()))

    def key_of(self, paint: dict) -> str:
        """The "{Name}|{Set}" identity of a paint record from this catalog."""
        return f"{paint['name']}|{(paint.get('details') or {}).get('set') or ''}"

    def owner(self, key: str, sku: str | None) -> dict | None:
        """WHICH of the paints answering to `key` this entry's `sku` names -- None if not one.

        The lookup HarvestApplier performs (`r.ProductCode == entry.Sku`, ordinal
        case-insensitive). None for a blank sku, for a sku no paint under this key carries, and
        for a sku two of them somehow share. Identity is the dict itself: two paints are the
        same paint iff they are the same record, so callers compare with `id()` rather than
        re-deriving a key the archive may spell twice.

        `pins` asks "will the C# land this entry at all"; this asks "on WHICH pot". They differ
        exactly where the key is NOT ambiguous: `pins` is then True for any sku (there is only
        one paint, the C# needs no tie-break), while this is None unless the sku really is that
        paint's product code. `BrandHarvest.add_enrich` needs the second question -- see there.
        """
        code = (sku or "").casefold()
        if not code:
            return None
        owners = [p for p in self.by_key.get(key, [])
                  if str(p.get("productCode") or "").casefold() == code]
        return owners[0] if len(owners) == 1 else None

    def pins(self, key: str, sku: str | None) -> bool:
        """Does this enrich entry name exactly ONE catalog paint?

        True whenever the key is unique. When it is not, the entry's own `sku` has to settle
        it -- the same test HarvestApplier applies (`r.ProductCode == entry.Sku`, ordinal
        case-insensitive), so this answers the question "will the C# actually land this entry,
        and on which paint?" rather than a second, differently-shaped guess.

        Measured 2026-08-05: 66 ambiguous keys across the nine brands (57 Vallejo, 6 mr-hobby,
        1 each ak-interactive / green-stuff-world / reaper), 35 of them carrying an enrich
        entry -- every one Vallejo, which quotes no price at all. So this refuses nothing
        today; it exists so that the first time a priced storefront ships a same-name,
        same-set pair, the price is withheld instead of silently doubled onto both pots.
        """
        return key not in self.ambiguous or self.owner(key, sku) is not None

    def match_code(self, code: str | None) -> str | None:
        """FIRST paint carrying this code, as a "{Name}|{Set}" key. First-wins by file order --
        use `paints_for_code` when a duplicate must be refused rather than silently decided."""
        return self.by_code.get(code or "")

    def match_name(self, name: str | None, set_hint: str | None = None) -> str | None:
        """With a set_hint the match is IN-SET ONLY: a name that exists solely in some other
        set must not cross-set match (a Fanatic-range store product sharing a name with an old
        D&D-range paint planted the wrong SKU under the old live-enrichment flow). Without a
        hint, a brand-wide unique name is trusted."""
        keys = self.by_name.get(norm(name), [])
        if set_hint is not None:
            in_set = [k for k in keys if k.endswith(f"|{set_hint}")]
            return in_set[0] if len(in_set) == 1 else None
        return keys[0] if len(keys) == 1 else None
