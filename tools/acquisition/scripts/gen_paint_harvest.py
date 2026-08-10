"""Generate data/paints/harvest/<brand>.yaml — manufacturer paint-harvest bridge files.

Projects the committed paint-source evidence (data/evidence/products/mfr-*/observations.jsonl,
produced by the shopify-paints / wp-rest-paints / woo-paints acquire strategies) onto the paint
catalog's own identities, ONCE, here — so the C# HarvestApplier only ever does exact lookups
(same architecture as gen_paint_barcodes.py). The committed YAML is the audit trail: it shows
exactly which store/catalog product matched which paint.

Per-source ROLES (owner decision, 2026-07-23 — see
docs/research/2026-07-23-paint-manufacturer-harvest-design.md):

- catalog  (mfr-vallejo): may propose NEW paints (`additions`) and enrich existing ones.
- metadata (mfr-armypainter, mfr-monument, mfr-turbodork, mfr-ak-interactive, mfr-mr-hobby):
  storefronts are never catalog-providers — matched products only fill blanks on EXISTING
  identities (`enrich`: ean/imageUrl); unmatched paint-like products land in `candidates`
  (report-only, ignored by C#) for a human to review.

Most bridges read one evidence directory. mr-hobby reads TWO inputs because no single source
holds the join: the manufacturer site knows the codes but publishes no barcode, so the bridge
unions it with data/paints/stores/mr-hobby.yaml — a committed RETAILER barcode snapshot taken
on demand by gen_paint_store_barcodes.py (that script owns the network; this one never does).

Output shape per brand file:

    <brand-slug>:
      enrich:
        "{Name}|{Set}": {ean?, imageUrl?, sku?, sourceUrl, source, price<Ccy>?}
      additions:
        - {name, set, productCode?, imageUrl?, sourceUrl, source, price<Ccy>?}
      candidates:
        - {name, sku?, url?, source, reason}

PRICE is carried in the source's OWN quoted currency and never converted -- see
SOURCE_PRICE_FIELD for the per-source evidence, observed_price() for the currency guard and
Catalog.pins() for the identity guard. GW's trade sheets carry no price at all (0 of 938 paint
observations, measured 2026-08-04), so the storefronts here are the only paint price evidence
the repo has.

Paint ranges are mostly one-off snapshots (rarely re-run) — this script reads only committed
files and is deterministic; run it after any manual acquire run:
`uv run --with pyyaml python tools/acquisition/scripts/gen_paint_harvest.py`
"""
from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
EVIDENCE_DIR = REPO / "data/evidence/products"
SOURCES_DIR = REPO / "data/catalog/sources"
BRANDS_DIR = REPO / "data/paints/brands"
STORES_DIR = REPO / "data/paints/stores"
OUT_DIR = REPO / "data/paints/harvest"

# THE INVARIANT: A SOURCE'S CROSSOVER PREDICATE IS EXACTLY WHAT ITS PAINT BRIDGE REFUSES.
#
# Boxed multi-pot sets are products, not paints (maintainer decision 2026-08-05). The product
# resolver admits them via each descriptor's `crossoverToProducts` block; this script must refuse
# precisely the same rows, or a box publishes in both catalogs or in neither. Sharing the
# evaluator rather than restating the rule is what makes that true by construction -- the three
# inline set tests this replaced were three different spellings of the same intent, and the 19
# boxes commit 6b3c930 gated out were the gap between two of them.
#
# The bootstrap keeps this a PURE-PYYAML script: resolve/crossover.py imports only `re` and
# `typing`, and the two package __init__ files this traverses import nothing third-party
# (`resolve/__init__.py` is empty; `warhub_acquisition/__init__.py` holds only `__version__`), so
# this adds no dependency and .github/workflows/paint-catalog-update.yml:75
# (`uv run --with pyyaml python ...`) still runs unchanged. The RULES are read with plain pyyaml
# below for the same reason -- loading the pydantic SourceDescriptor here would drag in pydantic.
sys.path.insert(0, str(REPO / "tools/acquisition/src"))
from warhub_acquisition.resolve.crossover import matches as crossover_matches  # noqa: E402

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
    # Owner-approved promotion 2026-07-24: Masterclass singles join as their own set.
    "john blanche masterclass": "John Blanche Masterclass",
}


# Per-source price currency. A storefront's price is NEVER assumed to be GBP (or anything
# else): each entry below is the field that source's own evidence populates, and why it is
# that currency. Measured over the committed observations, 2026-08-05:
#
#   mfr-ak-interactive   priceEur  1142/1142  Woo Store API declares currency_code per product
#   mfr-scale75          priceEur   562/562   descriptor scope.currency: eur (live-verified)
#   mfr-greenstuffworld  priceEur   477/477   recorded only when itemprop=priceCurrency is EUR
#   mfr-armypainter      priceUsd   794/794   descriptor scope.currency: usd (live /cart.js)
#   mfr-reaper           priceUsd   541/541   reapermini.com is a US store; strategy reads cents
#   mfr-turbodork        priceUsd   357/357   descriptor scope.currency: usd (live /cart.js)
#   mfr-monument         priceUsd   197/197   descriptor scope.currency: usd (live /cart.js)
#
# Deliberately absent: mfr-vallejo (0 of 1194 observations carry any price) and mfr-mr-hobby
# (0 of 134; neither the series pages nor the retailer barcode snapshot quote one). No paint
# source quotes GBP or CAD, so those two fields are never emitted by this bridge.
SOURCE_PRICE_FIELD = {
    "mfr-ak-interactive": "priceEur",
    "mfr-armypainter": "priceUsd",
    "mfr-greenstuffworld": "priceEur",
    "mfr-monument": "priceUsd",
    "mfr-reaper": "priceUsd",
    "mfr-scale75": "priceEur",
    "mfr-turbodork": "priceUsd",
}

@lru_cache(maxsize=None)
def crossover_rule(source_id: str) -> dict | None:
    """The source's own `crossoverToProducts` block, straight out of its descriptor YAML.

    Plain pyyaml on purpose (see the bootstrap comment at the top): the pydantic
    SourceDescriptor validates the same key in CI (tests/test_repo_data.py), so this reader
    only has to FIND it, not police it. None means the source declares no carve-out -- and
    `crossover_matches` then selects nothing, which is exactly the behaviour the four
    deliberately blockless paint sources want (mfr-turbodork, mfr-mr-hobby, mfr-vallejo,
    mfr-gw-webstore-paints -- each records why in a comment on its own descriptor).
    """
    path = SOURCES_DIR / f"{source_id}.yaml"
    if not path.exists():
        # FAIL LOUD. A missing descriptor means the source id is misspelled or renamed, never
        # "this source has no carve-out" -- that case is a descriptor that EXISTS without the key,
        # handled below. Returning None here instead would silently disable the gate, and the
        # blast radius is not small: pointing SOURCES_DIR at a nonexistent directory takes
        # bridge_ak from 139 additions to 295 (156 boxed sets proposed as individual paints) and
        # puts "Sophie's Mystery Paint Set" back in reaper's -- the exact regression 6b3c930
        # fixed. Since 2026-08-05 `paint_rows` owns both reads, so the gate id and the evidence id
        # can no longer DRIFT (they are one argument) -- but a single misspelled id would silently
        # yield an empty read instead of a loud stop, which is why paint_rows calls this eagerly
        # rather than only on the first row.
        raise SystemExit(
            f"gen_paint_harvest: no descriptor at {path} -- is the source id {source_id!r} right? "
            "Refusing to run with a set gate that would silently pass everything."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("crossoverToProducts")


def is_set(observation: dict, source_id: str) -> bool:
    """Does the PRODUCT catalog claim this row? Then this bridge must not publish it as a paint.

    The one gate every bridge asks -- through `paint_rows`, which is what makes "every" true
    rather than aspirational -- so that "crosses over" and "refused here" cannot diverge.
    Measured 2026-08-05: 545 rows across the six declaring sources (285 ak, 115 reaper, 69 gsw,
    49 armypainter, 21 monument, 6 scale75), of which the resolver's
    identity floor admits 516 -- the 29 it rejects stay refused here too, which is deliberate.
    They are not paints either; they are unaddressable set rows that reach neither catalog and
    surface as `set-without-identity` in review/conflicts.yaml for a human to resolve.
    """
    return crossover_matches(observation, crossover_rule(source_id))


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def observed_price(observation: dict, source_id: str) -> dict:
    """`{'priceEur': 2.27}` when the observation quotes THIS source's currency, else `{}`.

    Reading only the pinned field is a guard, not a lookup shortcut. Both storefront price
    extractors fall back to `priceGbp` for a currency code they do not recognize
    (`_PRICE_FIELDS.get(str(currency).casefold(), "priceGbp")` in woo.py and shopify.py), so a
    store that starts answering in a currency the table lacks would land euros in `priceGbp`
    and nothing downstream would ever notice. Pinning turns that into a DROPPED price, which
    is recoverable, instead of a mislabelled one, which is not.

    A non-positive price is not a price: ak-interactive lists "QUICK GEN COLOR GUIDE [PDF]"
    (AK17000GUIDE) at 0.00 -- a free download, not a free paint. A SET's price is not a paint's
    price either, so a crossed-over row yields nothing -- and "crossed-over" means exactly what
    the SOURCE declared. For a source that declares no block this test is a no-op.

    That is the honest statement, and it is narrower than the one that stood here until
    2026-08-05 ("this guard used to be the title regex alone, which was strictly weaker").
    Priced rows suppressed by the old module-level title regex vs. by `is_set` today, measured
    2026-08-05: WIDER for reaper (19 -> 115), ak-interactive (153 -> 285) and scale75 (0 -> 6);
    identical for monument (21) and greenstuffworld (69); NARROWER for armypainter (56 -> 49)
    and turbodork (4 -> 0). SOURCE_PRICE_FIELD and `crossoverToProducts` are independent
    declarations, so turbodork keeps a price field and loses the set test entirely.

    The 11 rows the narrowing readmits are held out of the harvest by machinery that knows
    nothing about sets, which is why this function is no longer the backstop `bridge_reaper`'s
    docstring used to lean on for blockless sources: armypainter's 7 brush sets (TL5065P-TL5070P,
    BR7055P, $9.71-$97.19, deliberately vetoed from its block by
    `noneOf: hintContainsAny {tags: [brushset]}`) never arrive because TL/BR are outside
    TAP_SINGLE_SKU, and turbodork's 4 (TDK044099 plus three "_R" retailer trade packs) are
    `productType: Retail`, never promoted. 0 of the 11 reach a published price -- inert today,
    resting on a SKU regex and a productType bucket.

    Since `paint_rows` gates every bridge, no crossed row reaches this function from the
    generator at all. Kept as the second line, for direct callers and for the day a bridge
    reads a price off a row it obtained some other way.
    """
    field = SOURCE_PRICE_FIELD.get(source_id)
    if field is None:
        return {}
    if is_set(observation, source_id):
        return {}
    value = observation.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return {}
    return {field: float(value)}


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


def paint_rows(source_id: str, out: "BrandHarvest") -> list[dict]:
    """Every observation of `source_id` EXCEPT the ones its own descriptor sends to products.

    The invariant at the top of this file is universal, so the gate has to be. Until 2026-08-05
    it was not: `is_set` was called in 3 of the 9 bridges (ak, gsw, reaper) while
    bridge_armypainter, bridge_monument and bridge_scale75 declared a `crossoverToProducts`
    block and never consulted it -- 76 crossed rows (49 + 21 + 6) refused, if at all, by
    inclusion whitelists that know nothing about sets. Measured 2026-08-05, that held by
    coincidence, and for one of the three it did not hold at all:

      * armypainter -- NOT safe. Its `is_single` shape test refuses 46 of the 49; WP8017P,
        WP8042P and WP8012P ("Kings of War Ogres", "Zombicide 2nd Edition", "Zombicide Black
        Plague" paint sets) carry `WP\\d{4}P` skus and 61-112 g weights and pass it. They stayed
        out of `enrich` only because `match_code` missed and their titles have no ":" prefix --
        i.e. on a FAILED JOIN. All three carry real retail EANs (5713799801707, 5713799804203,
        5713799801202) that the resolver publishes as products right now, so one Arcturus record
        gaining code WP8017, or a store retitle to "Warpaints Fanatic: ...", would land a box's
        EAN and price on a dropper -- the exact double-publish this invariant exists to prevent.
      * monument -- safe only via the one line `productType != "Paint Singles"` (0 of its 21
        crossed rows say Paint Singles). Lift it and 3 become ADDITIONS, not candidates:
        AMP-SET-1 / AMP-SET-2 hit the `sku.startswith("AMP-")` promotion and MPA-SET-1STEP1 the
        `"1-step" in title` one -- boxed sets minted as individual paints, which is what 6b3c930
        fixed.
      * scale75 -- safe twice: all 6 crossed rows sit in collections absent from BOTH
        SCALE75_SET_BY_COLLECTION and SCALE75_NEW_SET_BY_COLLECTION, and 0 of the 6 name-match
        the catalog. Three hand-maintained lists that happen to be disjoint, with nothing
        enforcing the disjointness.

    So the gate moved into the ONE reader every bridge already called, rather than being
    copy-pasted into six more places. It therefore also runs BEFORE every enrich/ratchet branch,
    which fixes bridge_ak's own gate having sat AFTER its enrich branch (inert today -- 0 of its
    285 crossed rows code-match the catalog -- but the same ordering bridge_gsw's comment calls
    load-bearing, and it was one code match away from mattering).

    Crossed rows are REPORTED, never dropped: each becomes a candidate, so the harvest file
    still says what left and why. Measured delta of moving the gate here, 2026-08-05: `enrich`
    and `additions` byte-identical for all nine brands; candidates army-painter 73 -> 119 and
    monument-pro-acryl 1 -> 22, which is 67 rows that used to leave in silence.
    """
    crossover_rule(source_id)  # fail loud on a bad id BEFORE an empty read makes it look fine
    rows = []
    for observation in read_observations(source_id):
        if is_set(observation, source_id):
            out.candidates.append(
                {"name": observation.get("name"),
                 "sku": str(observation.get("sku") or "") or None,
                 "url": observation.get("url"),
                 "source": source_id,
                 "reason": "boxed set -- crosses to the product catalog"}
            )
            continue
        rows.append(observation)
    return rows


def read_store_barcodes(slug: str) -> list[dict]:
    """`{sku, ean, name, url, store}` rows from data/paints/stores/<slug>.yaml -- the committed
    retailer barcode snapshot produced on demand by gen_paint_store_barcodes.py. Empty when
    absent: the snapshot is optional per brand, exactly like the evidence directories above."""
    path = STORES_DIR / f"{slug}.yaml"
    if not path.exists():
        return []
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(slug) or {}
    return data.get("items") or []


def ean13_ok(value: str | None) -> bool:
    """EAN/JAN-13 check digit. A retailer barcode is third-party keyed data: one transposed
    digit would plant a barcode that resolves to a DIFFERENT product, and nothing downstream
    re-checks it (the C# fills a blank Ean verbatim). Cheap gate, kept inline so this script
    stays a pure-pyyaml script the workflow can run with `uv run --with pyyaml`."""
    digits = str(value or "")
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])


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
            self.by_name.setdefault(norm(p["name"]), []).append(key)

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
        if key not in self.ambiguous:
            return True
        code = (sku or "").casefold()
        if not code:
            return False
        owners = [p for p in self.by_key.get(key, [])
                  if str(p.get("productCode") or "").casefold() == code]
        return len(owners) == 1

    def match_code(self, code: str | None) -> str | None:
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


def pinned_price(catalog: Catalog, key: str, sku: str | None, observation: dict,
                 source_id: str) -> dict:
    """`observed_price`, but only for an enrich entry that names exactly one paint.

    Additions do not need this -- each one MINTS its own paint under its own
    (name, set, productCode), so its price came from precisely the product that created it.
    Enrichment is the direction that can go wrong: `{Name}|{Set}` is not unique, and a price
    landing on the wrong pot is a lie about a real product, not a missing field.
    """
    return observed_price(observation, source_id) if catalog.pins(key, sku) else {}


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


def previous_addition_codes(slug: str) -> set[str]:
    """Codes emitted as additions in the brand's committed harvest file. Additions must be a
    STABLE projection of the source: once a merge lands an addition, the catalog code-matches
    it, and a catalog-gated bridge would flip it to enrich-only — the next merge would then
    drop it from the fresh set entirely (it exists nowhere but this file). This ratchet keeps
    prior additions additions (hand-prune the file to actually retire one); the C# (Name, Set,
    Code) skip keeps re-emission idempotent against Arcturus-covered paints."""
    path = OUT_DIR / f"{slug}.yaml"
    if not path.exists():
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    additions = (data.get(slug) or {}).get("additions") or []
    return {str(a.get("productCode")) for a in additions if a.get("productCode")}


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
    prior_additions = previous_addition_codes("vallejo")
    out = BrandHarvest()
    for o in paint_rows("mfr-vallejo", out):
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
        is_prior_addition = code in prior_additions
        if key is not None and not is_prior_addition:
            out.add_enrich(key, imageUrl=o.get("imageUrl"), sku=code, **common)
        elif set_name is not None:
            # New-to-catalog singles AND prior additions (ratchet -- see
            # previous_addition_codes): additions must not flip to enrich-only just because
            # an earlier merge landed them.
            out.additions.append(
                {"name": o["name"], "set": set_name, "productCode": code,
                 "imageUrl": o.get("imageUrl"), **common}
            )
        elif key is None:
            out.candidates.append(
                {"name": o["name"], "sku": code, "url": o.get("url"), "source": "mfr-vallejo",
                 "reason": f"no set mapping for categories: {','.join(slugs) or '(none)'}"}
            )
    return out


# AK store singles suffix their names with the subseries ("PURPLE – STANDARD",
# "SPACE MAGENTA – QUICK GEN COLOR") -- far more reliable than the sprawling category tree.
# Values are the Arcturus set spellings where the subseries exists there; starred are new.
AK_SET_BY_SUFFIX = {
    "STANDARD": "Standard (3rd Gen)",
    "METALLIC": "Metallic (3rd Gen)",
    "INTENSE": "Intense (3rd Gen)",
    "PASTEL": "Pastel (3rd Gen)",
    "INK": "Ink (3rd Gen)",
    "QUICK GEN COLOR": "Quick Gen",  # *
    "COLOR PUNCH": "Color Punch (3rd Gen)",  # *
}
AK_SINGLE_SKU = re.compile(r"^AK\d{4,5}$")


def ak_prettify(name: str) -> str:
    """ALL-CAPS store name -> the Arcturus capitalization style (plain per-word capitalize:
    'APC INTERIOR LIGHT GREEN (FS24533)' -> 'Apc Interior Light Green (fs24533)'-ish)."""
    words = []
    for word in name.lower().split():
        words.append(word if word.startswith("(") and any(ch.isdigit() for ch in word)
                     else word.capitalize())
    return " ".join(words)


def ak_split(name: str) -> tuple[str, str | None]:
    """'SPACE MAGENTA – QUICK GEN COLOR' -> ('SPACE MAGENTA', 'QUICK GEN COLOR')."""
    for dash in (" – ", " - "):
        if dash in name:
            base, _, suffix = name.rpartition(dash)
            return base.strip(), suffix.strip().upper()
    return name.strip(), None


def bridge_ak() -> BrandHarvest:
    """CATALOG role for the store's paint singles since 2026-07-24 (owner-approved promotion):
    the Trello-tracked gaps (Quick Gen range, 3rd-gen review) come exactly from here. Sets,
    bundles, guides and everything without a clean AK-number SKU stay out; washes ride along
    as their own set. Additions are born colour-less; chart swatches heal them later."""
    catalog = Catalog("ak-interactive")
    prior_additions = previous_addition_codes("ak-interactive")
    out = BrandHarvest()
    for o in paint_rows("mfr-ak-interactive", out):
        sku = str(o.get("sku") or "")
        key = catalog.match_code(sku)
        common = {"sourceUrl": o.get("url"), "source": "mfr-ak-interactive"}
        if key is not None and sku not in prior_additions:
            out.add_enrich(key, imageUrl=o.get("imageUrl"), sku=sku, **common,
                           **pinned_price(catalog, key, sku, o, "mfr-ak-interactive"))
            continue

        slugs = set((o.get("hints") or {}).get("categorySlugs") or [])
        name_raw = o["name"]
        # Sets no longer reach here at all: `paint_rows` removed all 285 of them (of 1,142)
        # before the loop, under their own reason. What is left is the SHAPE test -- bundles,
        # guides and anything without a clean AK-number sku -- which the descriptor's predicate
        # never claimed to cover. Note this line used to also carry the set test, AFTER the
        # enrich branch above; moving it into the reader closed that ordering hole.
        if not AK_SINGLE_SKU.fullmatch(sku):
            out.candidates.append(
                {"name": name_raw, "sku": sku or None, "url": o.get("url"),
                 "source": "mfr-ak-interactive",
                 "reason": "set/bundle/guide (not a promotable single)"}
            )
            continue

        base, suffix = ak_split(name_raw)
        set_name = AK_SET_BY_SUFFIX.get(suffix or "")
        if suffix == "INK" and not sku.startswith("AK112"):
            # Two distinct ink lines share the "– INK" suffix: 3rd-gen inks are AK112xx
            # (Arcturus "Ink (3rd Gen)"); the standalone The-Inks range is AK16xxx.
            set_name = "Inks"
        if set_name is None:
            if "acrylic-wash" in slugs:
                set_name = "Acrylic Wash"  # new set: Arcturus has no AK wash range
            elif "3rd-acrylics" in slugs and suffix is None:
                # Un-suffixed 3rd-gen singles (effects etc.) join the dominant set.
                set_name = "Standard (3rd Gen)"
        if set_name is None:
            out.candidates.append(
                {"name": name_raw, "sku": sku, "url": o.get("url"),
                 "source": "mfr-ak-interactive",
                 "reason": f"single outside promoted ranges (suffix: {suffix or '(none)'})"}
            )
            continue

        out.additions.append(
            {"name": ak_prettify(base), "set": set_name, "productCode": sku,
             "imageUrl": o.get("imageUrl"), **common,
             **observed_price(o, "mfr-ak-interactive")}
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
    prior_additions = previous_addition_codes("army-painter")
    out = BrandHarvest()
    for o in paint_rows("mfr-armypainter", out):
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
        # Code-match against ARCTURUS-shaped codes only (store SKUs carry a P/S packaging
        # suffix the base set doesn't). A VERBATIM store-SKU hit is deliberately not trusted:
        # the retired live-Shopify flow planted name-matched store SKUs into the archive
        # (including cross-set false attributions), so a verbatim match can be an echo of a
        # historical mistake, not a join. Name-matching only under a recognized range prefix,
        # in-set only.
        key = catalog.match_code(sku.rstrip("PS"))
        if key is None and set_hint is not None:
            key = catalog.match_name(paint_name, set_hint)
        if key is not None and sku not in prior_additions:
            out.add_enrich(key, ean=o.get("ean"), imageUrl=o.get("imageUrl"), sku=sku,
                           sourceUrl=o.get("url"), source="mfr-armypainter",
                           **pinned_price(catalog, key, sku, o, "mfr-armypainter"))
        elif set_hint is not None and "triad" not in o["name"].lower():
            # Owner-approved promotion 2026-07-24: unmatched singles under a recognized range
            # prefix are NEW paints (Fanatic waves, Masterclass) -- born with their store EAN
            # and image. Triads are 3-packs, never singles.
            out.additions.append(
                {"name": paint_name, "set": set_hint, "productCode": sku,
                 "ean": o.get("ean"), "imageUrl": o.get("imageUrl"),
                 "sourceUrl": o.get("url"), "source": "mfr-armypainter",
                 **observed_price(o, "mfr-armypainter")}
            )
        else:
            out.candidates.append(
                {"name": o["name"], "sku": sku, "url": o.get("url"), "source": "mfr-armypainter",
                 "reason": "single outside promoted ranges"}
            )
    return out


def bridge_monument() -> BrandHarvest:
    catalog = Catalog("monument-pro-acryl")
    prior_additions = previous_addition_codes("monument-pro-acryl")
    out = BrandHarvest()
    for o in paint_rows("mfr-monument", out):
        if (o.get("hints") or {}).get("productType") != "Paint Singles":
            continue
        sku = str(o.get("sku") or "")
        code = sku.removeprefix("MPA-")
        name = MONUMENT_NAME.sub("", o["name"]).strip()
        common = {"ean": o.get("ean"), "imageUrl": o.get("imageUrl"),
                  "sourceUrl": o.get("url"), "source": "mfr-monument"}
        key = catalog.match_code(code) or catalog.match_code(code.zfill(3)) or catalog.match_name(name)
        if key is not None and sku not in prior_additions:
            out.add_enrich(key, sku=sku, **common,
                           **pinned_price(catalog, key, sku, o, "mfr-monument"))
            continue
        # Owner-approved promotion 2026-07-24: the two post-Arcturus ranges join as their own
        # sets; anything else unmatched stays a candidate.
        title = o["name"]
        price = observed_price(o, "mfr-monument")
        if sku.startswith("MPA-5") or "1-step" in title.lower():
            paint = title.split(" - ", 1)[-1].strip()
            out.additions.append(
                {"name": paint, "set": "Pro Acryl 1-Step", "productCode": sku, **common, **price})
        elif sku.startswith("AMP-"):
            paint = title.split(" - ", 1)[-1].strip()
            out.additions.append(
                {"name": paint, "set": "AMP Colors", "productCode": sku, **common, **price})
        else:
            out.candidates.append(
                {"name": title, "sku": sku or None, "url": o.get("url"),
                 "source": "mfr-monument", "reason": "single outside promoted ranges (renamed?)"}
            )
    return out


def bridge_turbodork() -> BrandHarvest:
    catalog = Catalog("turbo-dork")
    prior_additions = previous_addition_codes("turbo-dork")
    out = BrandHarvest()
    paint_types = {"TurboShift", "Metallic", "ZeniShift", "Retail"}
    for o in paint_rows("mfr-turbodork", out):
        hints = o.get("hints") or {}
        if hints.get("productType") not in paint_types:
            continue
        sku = str(o.get("sku") or "")
        key = catalog.match_name(o["name"])
        common = {"ean": o.get("ean"), "imageUrl": o.get("imageUrl"),
                  "sourceUrl": o.get("url"), "source": "mfr-turbodork"}
        if key is not None and sku not in prior_additions:
            out.add_enrich(key, sku=sku, **common,
                           **pinned_price(catalog, key, sku, o, "mfr-turbodork"))
        elif hints.get("productType") != "Retail":
            # Owner-approved promotion 2026-07-24: the dedicated paint types
            # (TurboShift/Metallic/ZeniShift) join the base's single flat set, born with
            # their store EAN + image. Retail stays a legacy mixed bucket -- never promoted.
            out.additions.append(
                {"name": o["name"], "set": "Turbo Dork", "productCode": sku or None, **common,
                 **observed_price(o, "mfr-turbodork")}
            )
    return out


# scale75.com collection handle -> Arcturus set spelling ("Warfront  Range" really has two
# spaces in the base data). Handles absent here (drop-paint, flow/floww, scalecolor-games,
# prism sets) are ranges the catalog does not know yet -> candidates for a later promotion.
SCALE75_SET_BY_COLLECTION = {
    "scalecolor-individual": "Scale Color Range",
    "artist-individuales": "Artist Range",
    "warfront-individuales": "Warfront  Range",
    "fantasy-games-individuales": "Fantasy & Games Range",
    "instant-individuales": "Instant Colors Range",
    "metal-n-alchemy-individuales": "Metal N Alchemy Range",
    "inktensity-individuales": "Inktensity Range",
    "fx-fluor-individuales": "FX Range",
}


# Post-Arcturus scale75 ranges, owner-approved promotion 2026-07-24. floww-oleos (oil sets +
# a case) and the prism handles (sets) are deliberately absent -- sets never promote.
SCALE75_NEW_SET_BY_COLLECTION = {
    "drop-paint-individuales": "Drop & Paint",
    "flow-individuales": "Scalecolor Floww",
    "scalecolor-games-individuales": "Scalecolor Games",
}


def bridge_scale75() -> BrandHarvest:
    """CATALOG role since 2026-07-24 (owner-approved): Arcturus scale75 has no product codes,
    so joins are name-based with collection membership as the set hint (the store publishes no
    other range signal). Matched singles get image enrichment (no EANs exist -- variant
    barcodes unpopulated store-wide); unmatched singles in KNOWN sets and the three
    post-Arcturus ranges join as additions with the store SKU as the code."""
    catalog = Catalog("scale75")
    prior_additions = previous_addition_codes("scale75")
    out = BrandHarvest()
    for o in paint_rows("mfr-scale75", out):
        collections = (o.get("hints") or {}).get("collections") or []
        sku = str(o.get("sku") or "")
        common = {"imageUrl": o.get("imageUrl"), "sourceUrl": o.get("url"), "source": "mfr-scale75"}
        known_set = next(
            (SCALE75_SET_BY_COLLECTION[c] for c in collections if c in SCALE75_SET_BY_COLLECTION),
            None,
        )
        new_set = next(
            (SCALE75_NEW_SET_BY_COLLECTION[c] for c in collections if c in SCALE75_NEW_SET_BY_COLLECTION),
            None,
        )
        price = observed_price(o, "mfr-scale75")
        if known_set is not None:
            key = catalog.match_name(o["name"], known_set) or catalog.match_name(o["name"])
            if key is not None and sku not in prior_additions:
                out.add_enrich(key, sku=sku, **common,
                               **pinned_price(catalog, key, sku, o, "mfr-scale75"))
                continue
            out.additions.append(
                {"name": ak_prettify(o["name"]), "set": known_set,
                 "productCode": sku or None, **common, **price}
            )
        elif new_set is not None:
            out.additions.append(
                {"name": ak_prettify(o["name"]), "set": new_set,
                 "productCode": sku or None, **common, **price}
            )
        else:
            out.candidates.append(
                {"name": o["name"], "sku": sku or None, "url": o.get("url"),
                 "source": "mfr-scale75",
                 "reason": "sets/unmapped collections: " + ",".join(collections[:4])}
            )
    return out


# greenstuffworld.com category slug -> catalog set. First four use the Arcturus spellings;
# the rest are post-Arcturus ranges (owner-approved promotion 2026-07-24). The store's
# acrylic-inks category spans three Arcturus ink sets -- unmatched inks join the store's own
# umbrella naming rather than guessing a subset.
GSW_SET_BY_CATEGORY = {
    "acrylic-paints": "Acrylic Colors",
    "dipping-inks": "Dipping Inks",
    "metallic-acrylic-paints": "Metallic Colors",
    "chameleon-acrylic-paints": "Chameleon Colorshift Metallic",
    "acrylic-inks": "Acrylic Inks",
    "fluorescent-acrylic-paints": "Fluorescent",
    "dry-brush-paints": "Dry Brush",
    "flexible-paints": "Flexible",
    "liquid-pigments": "Liquid Pigments",
    "chrome-paints": "Chrome",
    "effect-paints": "Effects",
    "varnishes": "Varnish",
    "acrylic-primers": "Primer",
    "colour-primers-spray": "Spray Primer",
    "colorshift-chameleon-spray": "Chameleon Spray",
    "chrome-spray-paint": "Chrome Spray",
    "blackest-black-paint": "Blackest Black",
}

# Leading marketing descriptors on store titles ("Acrylic Color WONKA VIOLET", "Dipping ink
# 60 ml - Papyrus DIP"). Stripped iteratively; a trailing ALL-CAPS run is title-cased.
#
# TWO things this regex must NOT do, both measured against the 477 committed greenstuffworld
# observations on 2026-08-05:
#
# 1. IT MUST NOT ERASE THE VOLUME. Until today `\d+ ?ml` sat in the alternation below as a peer
#    of the marketing words and was thrown away, which collapsed the store's 17 ml and 60 ml
#    dipping inks -- different skus, different gtin13s, 3.7375 vs 2.125 EUR -- onto one name:
#    32 (set, cleanedName) collisions that do not exist on the raw titles (0). The volume is
#    now CAPTURED and re-emitted as a suffix, which takes that to 0. Naming a pot after its
#    volume is not a convention invented here: 86 GSW archive records ALREADY end in one
#    ("Alpha Turquoise 30 ml", "Antique Gold 17ml") purely because the store writes it last in
#    those titles, where this ^-anchored regex could never reach it. Keeping it in one position
#    and erasing it in the other was the actual defect.
#    Deleting the alternative outright is NOT the fix, and that was measured too: `[-–]` is
#    ^-anchored, so the volume is precisely what unblocks it. Drop it and the loop stalls with
#    the dash unreached -- 69 dipping-ink names become "60 ml - Grey Mist Dip".
#    What this does NOT fix: `suffix_match` below still joins BOTH volume listings onto the one
#    bare catalog name, so 31 of those 32 pairs never reach this function at all. See its own
#    comment.
#
# 2. IT MUST NOT EAT A PREFIX OUT OF THE MIDDLE OF A WORD. The word alternatives carry no
#    trailing \b before today, so `metallic paint` matched 14 characters of "Metallic Paints
#    Set - Colours" and the `\s*` then matched ZERO (the next character is "s"), yielding
#    "s Set - Colours" -- skus 9910/9911/9912, whose mangled names are still in the archive.
#    Those three are boxed sets `paint_rows` now routes to candidates, so this boundary repairs
#    nothing on disk today (3 of 477 cleaned names change, 474 byte-identical, 0 of them
#    reaching `additions`); it is prevention against the next plural the store ships.
#    `[-–]` stays OUTSIDE the boundary in its own ^-anchored branch, because a hyphen followed
#    by a space has no word boundary between them -- `(-)\b` would never fire and every
#    "... - Colour" title would stop being stripped at all.
_GSW_PREFIX = re.compile(
    r"^(acrylic (color|colors|white paint|black paint|paint)|dipping ink|metallic paint|"
    r"chameleon( paint)?|fluor(escent)? (acrylic )?paint|dry ?brush( paint)?|flexible paint|"
    r"liquid pigments?|chrome paint|effect paint|varnish|primer|colorshift|maxx darth)\b\s*"
    r"|^[-–]\s*",
    re.IGNORECASE,
)
# Peeled by the same loop, but REMEMBERED rather than discarded -- see (1) above. Re-emitted in
# one canonical spelling ("60 ml"), so a store retitle from "60ml" to "60 ml" is not a rename --
# but ONLY for a volume in the LEADING position, which is all this `^`-anchored regex can reach.
# A title carrying its volume at the END passes through with the store's own spelling, and the
# brand already holds both forms side by side: measured 2026-08-06 over the 161 committed GSW
# additions, 89 names end in a volume -- 62 in the no-space store spelling ("Satin Varnish 17ml",
# "Chrome Spray Paint 400ml") and 27 with a space, of which only these 3 dipping inks come from
# the capture below. So a TRAILING "17ml" -> "17 ml" respacing is still an unaliased rename that
# would mint and strand. That predates this rule (the `^` anchor always had it) and is not fixed
# here; it is written down so the sentence above is not read as a general guarantee.
_GSW_VOLUME = re.compile(r"^(\d+) ?ml\b\s*", re.IGNORECASE)


def gsw_clean_name(raw: str) -> str:
    name = raw.strip()
    volume: str | None = None
    while True:
        matched = _GSW_VOLUME.match(name)
        if matched:
            volume = matched.group(1)
            name = name[matched.end():].strip()
            continue
        stripped = _GSW_PREFIX.sub("", name, count=1).strip()
        if stripped == name or not stripped:
            break
        name = stripped
    # Title-case fully-uppercase words (WONKA VIOLET -> Wonka Violet), leave mixed-case alone.
    words = [w.capitalize() if w.isupper() and len(w) > 2 else w for w in name.split()]
    cleaned = " ".join(words)
    # .strip() covers a title that is nothing BUT a volume ("Dipping ink 60 ml"), which today
    # also cleans to "60 ml" -- the volume capture must not turn that into " 60 ml".
    return f"{cleaned} {volume} ml".strip() if volume else cleaned


def bridge_gsw() -> BrandHarvest:
    """CATALOG role since 2026-07-24 (owner-approved). greenstuffworld.com titles wrap the
    paint name in marketing prefixes ("Acrylic Color WONKA VIOLET") while the base data keeps
    bare names -- so the join is LONGEST-UNIQUE-SUFFIX on normalized names (>=5 chars, longest
    catalog name that the store title ends with, unique at that length). Enrichment carries
    the store's REAL gtin13 EANs (100% fill) + images; unmatched paints in mapped categories
    join as additions (cleaned name, mpn as productCode, EAN at birth)."""
    catalog = Catalog("green-stuff-world")
    prior_additions = previous_addition_codes("green-stuff-world")
    out = BrandHarvest()
    # normed catalog name -> keys, for suffix lookup
    by_norm: dict[str, list[str]] = catalog.by_name
    norms = sorted(by_norm, key=len, reverse=True)

    def suffix_match(store_name: str) -> str | None:
        # KNOWN DEFECT, deliberately not fixed here (2026-08-05). This matches on the RAW title,
        # so it is blind to a volume the title carries and the catalog record does not:
        # norm("Dipping ink 60 ml - PAPYRUS DIP") and norm("Dipping ink 17 ml - Papyrus Dip")
        # both END with `papyrusdip` and both claim `Papyrus Dip|Dipping Inks`. `add_enrich` is
        # first-wins and the 60 ml rows sit earlier in observations.jsonl, so the 17 ml row is
        # discarded every time. Measured 2026-08-05: 34 enrich keys are claimed by more than one
        # store row and 39 rows are dropped in silence -- 31 of them these ml pairs, the other 8
        # a different collapse entirely (`Orange|Fluor Metallic` is claimed by 4 rows spanning
        # Transparent Ink / Opaque Ink / Fluor Ink / Fluor Paint, `Yellow` likewise, `White` by
        # 3). It has landed: 33 of the 41 committed `Dipping Inks` records carry a 60 ml sku's
        # ean, price and image while declaring volumeMl 17, and all 31 genuine 17 ml barcodes
        # appear NOWHERE in the repo outside this source's evidence file (git grep, all 31).
        # `gsw_clean_name`'s volume fix does NOT reach these -- they never reach it. Repairing
        # them needs a volume-aware join here AND an explicit correction pass over the archive,
        # not a regeneration.
        n = norm(store_name)
        best: str | None = None
        for cand in norms:
            if len(cand) < 5:
                break  # sorted by length desc; everything after is shorter
            if n == cand or n.endswith(cand):
                keys = by_norm[cand]
                if len(keys) == 1:
                    return keys[0]
                return None  # ambiguous at the longest match -- refuse
        return best

    for o in paint_rows("mfr-greenstuffworld", out):
        slug = (o.get("hints") or {}).get("categorySlug") or ""
        # The set gate that stood here is now `paint_rows`, which every bridge shares. It covers
        # both signals this descriptor declares: the `paint-sets` category AND the set word list.
        # The category check alone is necessary but NOT sufficient -- greenstuffworld.com files
        # its RANGE sets under the range's own category, so "Paint Set - Chrome" arrives as
        # chrome-paints and "Set x8 Fluor Paints" as fluorescent-acrylic-paints, both mapped in
        # GSW_SET_BY_CATEGORY and both promoted. Measured 2026-08-05: 50 rows leave on the
        # category, 19 more on the title (69 total), and those 19 are exactly the boxes that
        # reached `additions` and published as single 17 ml droppers before commit 6b3c930.
        #
        # Gating in the READER is what keeps this BEFORE the enrich/ratchet branch, which is
        # load-bearing here: `catalog` reads the archive, so all 17 already-published sets
        # self-match by name. A gate after the ratchet would demote them to candidates in
        # generation N, find their codes gone from `previous_addition_codes` in N+1 and re-promote
        # them -- a two-generation oscillation. The cost of that placement is stated plainly: if
        # the store ever retitles an EXISTING single to contain a set word, that real paint drops
        # out of `fresh` too.
        sku = str(o.get("sku") or "")
        common = {"ean": o.get("ean"), "imageUrl": o.get("imageUrl"),
                  "sourceUrl": o.get("url"), "source": "mfr-greenstuffworld"}
        key = suffix_match(o["name"])
        if key is not None and sku not in prior_additions:
            out.add_enrich(key, sku=sku, **common,
                           **pinned_price(catalog, key, sku, o, "mfr-greenstuffworld"))
            continue
        set_name = GSW_SET_BY_CATEGORY.get(slug)
        if set_name is not None:
            out.additions.append(
                {"name": gsw_clean_name(o["name"]), "set": set_name,
                 "productCode": sku or None, **common,
                 **observed_price(o, "mfr-greenstuffworld")}
            )
        else:
            out.candidates.append(
                {"name": o["name"], "sku": sku or None, "url": o.get("url"),
                 "source": "mfr-greenstuffworld",
                 "reason": f"unmapped category ({slug})"}
            )
    return out


# reapermini.com line label -> Arcturus set spelling (they match the site's own page names).
REAPER_SET_BY_LINE = {
    "Master Series Paints Core Colors": "Master Series Paints Core Colors",
    "Master Series Paints Bones": "Master Series Paints Bones",
    "Master Series Paints Pathfinder Colors": "Master Series Paints Pathfinder",
}


def bridge_reaper() -> BrandHarvest:
    """CATALOG role (owner-activated + promotion 2026-07-24). Site skus are zero-padded
    ("09412") while the Arcturus base stores bare digits ('9412') -- codes normalize by
    stripping leading zeros, and additions adopt the base convention. Singles only; the
    set-kind observations (triads/sets/LTPK, hints.category paint-set) carry contentSkus as
    committed set-membership evidence but never promote. No EANs exist in the site data.

    The set filter is also what keeps SET prices out: 114 of the 541 observations are
    paint-set kind and all 114 quote a priceUsd (a $47.99 Learn To Paint Kit, a $659.99 full
    range). A set's price is not a paint's price, and `paint_rows` now removes all 115 before
    this loop sees them, so no ordering inside this bridge can expose one. `observed_price`
    asks the same predicate as a second line -- but only for a source that DECLARES one, so it
    is not the backstop an earlier version of this docstring implied it was for every source."""
    catalog = Catalog("reaper")
    prior_additions = previous_addition_codes("reaper")
    out = BrandHarvest()
    for o in paint_rows("mfr-reaper", out):
        hints = o.get("hints") or {}
        # ONE gate for both routes out, and it now lives in `paint_rows` above. The old
        # `hints.get("category") != "paint"` continue is subsumed by the descriptor's
        # `hintEquals: {category: paint-set}` clause, so all 114 category-marked sets leave in the
        # reader -- and the 1 the category misses (09985 "Sophie's Mystery Paint Set", which
        # reapermini.com labels category=paint) leaves on the title clause. 115 rows, measured
        # 2026-08-05. Reading through the gate is also what keeps it before the enrich/ratchet
        # branch, so a gated row can never oscillate back in (see bridge_gsw).
        if hints.get("category") != "paint":
            # Unreachable today and kept as a floor, not as live logic: reapermini.com emits
            # exactly two categories across all 541 observations (paint 427, paint-set 114,
            # measured 2026-08-05) and `paint_rows` already removed every paint-set. If the
            # site ever adds a third kind, it must not be mistaken for a paint.
            continue
        code = str(o.get("sku") or "").lstrip("0")
        line = str(hints.get("line") or "")
        set_name = REAPER_SET_BY_LINE.get(line)
        common = {"imageUrl": o.get("imageUrl"), "sourceUrl": o.get("url"), "source": "mfr-reaper"}
        key = catalog.match_code(code)
        if key is not None and code not in prior_additions:
            out.add_enrich(key, sku=code, **common,
                           **pinned_price(catalog, key, code, o, "mfr-reaper"))
        elif set_name is not None:
            out.additions.append(
                {"name": o["name"], "set": set_name, "productCode": code or None, **common,
                 **observed_price(o, "mfr-reaper")}
            )
        else:
            out.candidates.append(
                {"name": o["name"], "sku": code or None, "url": o.get("url"),
                 "source": "mfr-reaper", "reason": f"unmapped line ({line or 'none'})"}
            )
    return out


# --- Mr Hobby (GSI Creos) ------------------------------------------------------------------
# The manufacturer source is SERIES-level: mr-hobby.com has no per-colour page anywhere, so one
# observation covers a whole range and its `sku` is the range STRING the site prints under
# "Product Number" -- "C1~C189", "H1~110,151,301~340,511~515", "WC01-08,14-18". Expanding that
# is deliberately the bridge's job (see the strategy docstring: evidence stays faithful to the
# site, re-tuning the parse must never require a re-fetch). Separators are whatever the CMS
# typed that day, including the fullwidth/Japanese forms.
MRHOBBY_SEPARATORS = str.maketrans({"～": "~", "、": ",", "・": ",", "/": ","})
MRHOBBY_TOKEN = re.compile(r"^([A-Z]*)(\d+)(?:\s*[~-]\s*([A-Z]*)(\d+))?$", re.IGNORECASE)
# Widest real range is Mr.COLOR C1~C189; the cap only fires if a malformed string parses into a
# nonsense span, which must fail loudly as "unparseable" rather than mint thousands of codes.
MRHOBBY_MAX_SPAN = 400

# Site code prefix -> the Arcturus base's own spelling. The base stores Mr Color and Mr Metal
# Color codes as BARE digits ('74', '218') with the C/MC prefix implied, and spells the spray
# range SP1 where the site prints S1 (both verified against data/paints/brands/mr-hobby.yaml).
#
# An alias is only applied to a code the MANUFACTURER's own ranges confirm (see bridge_mrhobby):
# dropping a prefix is a claim about which range a number belongs to, and a retailer sku alone
# cannot support it. aztoyhobby lists MC124/127/129/131/132 alongside the real MC211~219 metal
# colours; mr-hobby.com publishes only MC211~219, so the stray MC1xx stay verbatim (-> no match
# -> candidate) instead of aliasing onto Mr Color 124/127/131, three unrelated paints.
MRHOBBY_CODE_ALIAS = {"C": "", "MC": "", "S": "SP"}

# GS1 Japan prefix GSI Creos ships every Mr Hobby JAN under. data/catalog/taxonomy/
# manufacturers.yaml deliberately pins NO gs1Prefixes for this brand (nothing was verifiable
# from the manufacturer), so the gate lives here, next to the retailer data it guards: a
# multi-vendor hobby store mis-keying a Tamiya or Gaia barcode onto a Mr Hobby listing is the
# exact failure this catches, and a rejected row is reported as a candidate, never dropped.
MRHOBBY_GS1_PREFIX = "4973028"


def mrhobby_expand(raw: str | None) -> list[str] | None:
    """'C1~C189' -> ['C1'...'C189']; 'WC01-08,14-18' -> ['WC01'...'WC08','WC14'...'WC18'].

    The prefix carries across comma groups (the site drops it after the first: 'XAC01,02',
    'SVC01~11,101'), and zero-padding follows the range's own lower bound ('WC01-08' pads to
    two, 'H1~110' does not). None means "not a code string at all" -- the letter-only product
    numbers ('LG', 'GGX') and anything the CMS typed freehand.
    """
    if not raw:
        return None
    codes: list[str] = []
    prefix = ""
    for token in str(raw).translate(MRHOBBY_SEPARATORS).split(","):
        token = token.strip()
        if not token:
            continue
        match = MRHOBBY_TOKEN.match(token)
        if match is None:
            return None
        lo_prefix, lo, hi_prefix, hi = match.groups()
        prefix = (lo_prefix or prefix).upper()
        if hi is None:
            codes.append(f"{prefix}{lo}")
            continue
        if hi_prefix and hi_prefix.upper() != prefix:
            return None  # 'S1~151・SJ01・02'-style mixed spans: refuse rather than guess
        start, end = int(lo), int(hi)
        if end < start or end - start > MRHOBBY_MAX_SPAN:
            return None
        codes.extend(f"{prefix}{n:0{len(lo)}d}" for n in range(start, end + 1))
    return codes or None


def mrhobby_canonical(code: str) -> str:
    """'NGA01' / 'NGA1' -> 'NGA1'. One spelling per code so the site's padding (which varies
    range by range: 'WC01-08' but 'H1~110') never decides whether two codes are the same."""
    match = re.fullmatch(r"([A-Z]*)(\d+)", code.upper())
    return f"{match.group(1)}{int(match.group(2))}" if match else code.upper()


def mrhobby_code_forms(code: str, *, alias_ok: bool = True) -> list[str]:
    """Every spelling of one site code the base might store it under -- zero-stripped,
    zero-padded-to-two and verbatim digits, under the aliased prefix FIRST and the site's own
    prefix second.

    Alias-first is load-bearing, not cosmetic. The Arcturus base duplicates three Mr.COLOR
    singles into its "Mr Color Modulation Set" under their PREFIXED codes -- C38/C39/C40 are
    the same bottles as bare 38/39/40 (Olive Drab 2, Dark Yellow, German Gray). Verbatim-first
    would put the barcode on the set copy; alias-first puts it on the canonical single, which
    is what the site's C<n> means everywhere.
    """
    match = re.fullmatch(r"([A-Z]*)(\d+)", code.upper())
    forms: list[str] = []
    if match is None:
        return [code.upper()]
    prefix, digits = match.groups()
    number = int(digits)
    alias = MRHOBBY_CODE_ALIAS.get(prefix) if alias_ok else None
    prefixes = [prefix] if alias is None else [alias, prefix]
    for candidate_prefix in prefixes:
        for tail in (str(number), f"{number:02d}", digits):
            form = f"{candidate_prefix}{tail}"
            if form and form not in forms:
                forms.append(form)
    return forms


def bridge_mrhobby() -> BrandHarvest:
    """METADATA-ONLY, and a UNION of two sources that each hold half the join.

    mr-hobby.com knows which codes exist (as ranges) but publishes no JAN/EAN, no per-colour
    page and no hex, EN or JA -- so the manufacturer can never fill a field, and all 668
    catalog paints sat EAN-less. A hobby retailer stocking the range publishes the JAN per
    single, keyed by GSI's own item code (data/paints/stores/mr-hobby.yaml, snapshotted on
    demand by gen_paint_store_barcodes.py). So: the manufacturer's expanded ranges CONFIRM the
    identity and supply the canonical site code + series page for the audit trail, the store
    supplies the barcode, and the join is EXACT on the code at both ends -- no fuzzy matching,
    no name matching, nowhere.

    No `additions`: neither source can name a new colour (the manufacturer publishes series
    pages only, and a storefront is not a catalog-provider). Everything unmatched -- a whole
    manufacturer range the catalog lacks, a store single, a barcode that fails its check digit
    -- lands in `candidates` for a human, never in the catalog.
    """
    catalog = Catalog("mr-hobby")
    out = BrandHarvest()

    # Pass 1 -- manufacturer: expand every series range onto catalog identities.
    confirmed: dict[str, tuple[str, str | None]] = {}  # identity key -> (site code, series url)
    site_codes: set[str] = set()  # every code the manufacturer lists, in or out of the catalog
    for o in paint_rows("mfr-mr-hobby", out):
        codes = mrhobby_expand(o.get("sku"))
        common = {"name": o["name"], "sku": o.get("sku") or None, "url": o.get("url"),
                  "source": "mfr-mr-hobby"}
        if codes is None:
            out.candidates.append({**common, "reason": "product number is not a code range"})
            continue
        site_codes.update(mrhobby_canonical(code) for code in codes)
        hits = 0
        for code in codes:
            form = next((f for f in mrhobby_code_forms(code) if f in catalog.by_code), None)
            if form is None:
                continue
            hits += 1
            confirmed.setdefault(catalog.by_code[form], (code, o.get("url")))
        if hits == 0:
            plural = "" if len(codes) == 1 else "s"
            out.candidates.append(
                {**common,
                 "reason": f"manufacturer range absent from catalog ({len(codes)} code{plural})"}
            )

    # Pass 2 -- retailer: the barcode, onto identities the catalog already has.
    for item in read_store_barcodes("mr-hobby"):
        sku = str(item.get("sku") or "")
        ean = str(item.get("ean") or "")
        store = str(item.get("store") or "store")
        common = {"name": item.get("name"), "sku": sku or None, "url": item.get("url"),
                  "source": store}
        # Manufacturer-corroborated codes may use the prefix alias; store-only ones may not.
        corroborated = mrhobby_canonical(sku) in site_codes
        form = next(
            (f for f in mrhobby_code_forms(sku, alias_ok=corroborated) if f in catalog.by_code),
            None,
        )
        if form is None:
            out.candidates.append(
                {**common,
                 "reason": "manufacturer range not in catalog" if corroborated
                 else "store-only code (marker/tool/finish, or a range the catalog lacks)"}
            )
            continue
        if not ean13_ok(ean) or not ean.startswith(MRHOBBY_GS1_PREFIX):
            out.candidates.append({**common, "reason": f"rejected barcode {ean or '(none)'}"})
            continue
        key = catalog.by_code[form]
        if key in catalog.ambiguous:
            # Two paints answer to this "{Name}|{Set}" (Mr Color 20 and 323 are both "Light
            # Blue"). The C# fills BOTH from one entry, so enriching would plant this barcode
            # on a bottle it does not belong to. Report the collision instead.
            out.candidates.append(
                {**common, "reason": f"ambiguous catalog identity ({key}) -- barcode {ean}"}
            )
            continue
        site_code, series_url = confirmed.get(key, (None, None))
        out.add_enrich(
            key,
            ean=ean,
            # Prefer the MANUFACTURER's own spelling and page when its ranges cover this code:
            # the store is the barcode's source, but the site is the authority on the identity.
            sku=site_code or sku,
            sourceUrl=series_url or item.get("url"),
            source=f"mfr-mr-hobby+{store}" if site_code else store,
        )
    return out


BRIDGES = {
    "vallejo": bridge_vallejo,
    "ak-interactive": bridge_ak,
    "army-painter": bridge_armypainter,
    "monument-pro-acryl": bridge_monument,
    "turbo-dork": bridge_turbodork,
    "scale75": bridge_scale75,
    "green-stuff-world": bridge_gsw,
    "reaper": bridge_reaper,
    "mr-hobby": bridge_mrhobby,
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
            "# priceEur/priceUsd are the storefront's OWN quoted currency, never converted --\n"
            "# inert until HarvestApplier reads them (it fills blank ean/imageUrl today).\n"
            + yaml.safe_dump({slug: data}, sort_keys=False, allow_unicode=True, width=200)
        )
        out_path.write_bytes(content.encode("utf-8"))
        print(
            f"{slug}: enrich={len(harvest.enrich)} additions={len(harvest.additions)} "
            f"candidates={len(harvest.candidates)}"
        )


if __name__ == "__main__":
    main()
