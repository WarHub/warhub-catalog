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
- ONE DOCUMENTED EXCEPTION to "storefronts are never catalog-providers": `bridge_p3` mints
  from warmachine.gg, which is a storefront. Maintainer-authorised 2026-08-13; the three
  grounds and their limits are stated on the bridge, not here, so the exception cannot drift
  away from the code it licenses.

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
# `typing`, paints/catalog.py only `re`/`pathlib`/`yaml`, and the three package __init__ files
# this traverses import nothing third-party (`resolve/__init__.py` and `paints/__init__.py` are
# empty; `warhub_acquisition/__init__.py` holds only `__version__`), so this adds no dependency
# and .github/workflows/paint-catalog-update.yml:75 (`uv run --with pyyaml python ...`) still
# runs unchanged. The RULES are read with plain pyyaml below for the same reason -- loading the
# pydantic SourceDescriptor here would drag in pydantic.
#
# `Catalog`/`norm` moved OUT of this file (2026-08-07) so gen_set_contents.py joins manufacturer
# codes to paints through the same index rather than a second spelling of it -- f181a73's rule.
sys.path.insert(0, str(REPO / "tools/acquisition/src"))
from warhub_acquisition.paints.catalog import Catalog, norm  # noqa: E402
from warhub_acquisition.resolve.crossover import (  # noqa: E402
    category_for as crossover_category,
    matches as crossover_matches,
)
from warhub_acquisition.yamlio import dump_yaml  # noqa: E402

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
#   mfr-reaper           priceUsd   541/576   reapermini.com is a US store; strategy reads cents
#                                             (the 35 set-only paints quote no price -- an
#                                             associatedProducts entry has no price field)
#   mfr-turbodork        priceUsd   357/357   descriptor scope.currency: usd (live /cart.js)
#   mfr-monument         priceUsd   197/197   descriptor scope.currency: usd (live /cart.js)
#
# Deliberately absent: mfr-vallejo (0 of 1194 observations carry any price) and mfr-mr-hobby
# (0 of 134; neither the series pages nor the retailer barcode snapshot quote one). No paint
# source quotes GBP or CAD, so those two fields are never emitted by this bridge.
#   mfr-warmachine       priceUsd   110/110   descriptor scope.currency: usd; every P3 single
#                                             quotes $4.10 (91) or $4.65 (19)
SOURCE_PRICE_FIELD = {
    "mfr-ak-interactive": "priceEur",
    "mfr-armypainter": "priceUsd",
    "mfr-greenstuffworld": "priceEur",
    "mfr-monument": "priceUsd",
    "mfr-reaper": "priceUsd",
    "mfr-scale75": "priceEur",
    "mfr-turbodork": "priceUsd",
    "mfr-warmachine": "priceUsd",
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
    Measured 2026-08-11: 562 rows across the six declaring sources (302 ak, 115 reaper, 69 gsw,
    49 armypainter, 21 monument, 6 scale75), of which the resolver's
    identity floor admits 530 -- the 32 it rejects stay refused here too, which is deliberate.
    They are not paints either; they are unaddressable crossed rows that reach neither catalog and
    surface in review/conflicts.yaml as `paint-set-without-identity` (29) or
    `hobby-auxiliary-without-identity` (3) for a human to resolve.

    BOOLEAN ON PURPOSE, and it stays that way. `category_for` would answer the same question for
    every committed descriptor, but only because `Crossover.category` is a required field -- a
    clause that matched under a block with no category would make it answer None, i.e. silently
    UNGATE the row. The gate asks `matches`; `crossed_reason` below does the labelling, and fails
    loud rather than quietly widening what the paint catalog publishes.
    """
    return crossover_matches(observation, crossover_rule(source_id))


# Why the paint bridge refused a crossed row, KEYED BY THE CATEGORY THE PRODUCT SIDE WILL STAMP.
# Explicit rather than derived from the category string, because this text is the only place the
# PAINT side ever says why (e.g.) `AK712 Acrylic Thinner` is not a paint, and a reader of
# data/paints/harvest/ak-interactive.yaml has no product catalog in front of them.
#
# `paint-set` keeps its wording BYTE-FOR-BYTE (it has been this string since af01ca5). Measured
# 2026-08-11 over the regenerated harvest: of the 562 candidate rows carrying a crossover reason,
# 546 are `paint-set` and 16 are `hobby-auxiliary` -- so rewording the first would rewrite 546 rows
# and five assertions in tests/test_paint_harvest_gate.py to say nothing new, where fixing the
# second rewrites 16. That ratio is the whole reason this is a dict and not a rename.
#
# "CLAIMED BY", not "crosses to", for the auxiliaries, and the asymmetry is deliberate rather than
# sloppy. 16 AK rows stamp `hobby-auxiliary` (measured 2026-08-11) and 3 of them -- AKABT111 /
# AKABT112 / AKABT113, the odourless / matt-effect / fast-dry thinners -- fail the resolver's
# identity floor and reach NEITHER catalog, so "crosses to the product catalog" would be false for
# them. "Claimed by" is true of all 16: the source's own `crossoverToProducts` block claims them,
# which is exactly the fact this gate acted on. The same nuance holds for 29 of the 546 `paint-set`
# rows, and is deliberately NOT fixed by rewording: this script cannot evaluate the identity floor
# without a second spelling of taxonomy.normalize_code (and a pydantic import the pure-pyyaml
# bootstrap at the top of this file exists to avoid), and the resolver already records every one of
# the 32 by name in data/review/conflicts.yaml. Recorded once, in the file that stays current.
CROSSOVER_REASON = {
    "paint-set": "boxed set -- crosses to the product catalog",
    "hobby-auxiliary": "auxiliary agent, not a colour -- claimed by the product catalog",
}


def crossed_reason(observation: dict, source_id: str) -> str:
    """The refusal receipt for a row `is_set` just gated, by that row's own crossover category.

    FAIL LOUD on a category with no entry. A descriptor can grow a new `category` at any time (the
    per-clause override that produced `hobby-auxiliary` landed in PR #107), and the alternatives to
    stopping are both silent corruption of an audit trail: a `.get(..., <the set string>)` default
    files the new kind under the old word -- the exact bug this function fixes -- and an empty
    string writes a refusal with no reason at all. The harvest is the record of what left and why;
    a reason it cannot state is a stop, not a shrug.
    """
    stamp = crossover_category(observation, crossover_rule(source_id))
    reason = CROSSOVER_REASON.get(stamp or "")
    if reason is None:
        raise SystemExit(
            f"gen_paint_harvest: {source_id} crosses {observation.get('sku')!r} as {stamp!r}, "
            f"which has no entry in CROSSOVER_REASON. Add one -- a refusal is recorded, not guessed."
        )
    return reason


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
                 "reason": crossed_reason(observation, source_id)}
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
    def __init__(self, catalog: "Catalog | None" = None) -> None:
        self.enrich: dict[str, dict] = {}
        self.additions: list[dict] = []
        self.candidates: list[dict] = []
        # The brand catalog this harvest enriches, when the bridge has one. `add_enrich` needs it
        # to tell a key TWO paints answer to from a key ONE paint answers to; without it every
        # rival claim is treated as the second, which is the safe direction. See add_enrich.
        self.catalog = catalog
        # Every store product that has claimed an enrich key, in arrival order, and the subset of
        # keys whose claims disagree about which product they are. See add_enrich.
        self.claims: dict[str, list[dict]] = {}
        self.contested: dict[str, list[dict]] = {}

    def routes_by_sku(self, key: str, claims: list[dict]) -> bool:
        """Do these rival claims each name a DIFFERENT catalog paint under one `{Name}|{Set}`?

        The whole of the two-mode distinction in `add_enrich`. True only when the catalog is
        known, every distinct sku among the claims resolves through `Catalog.owner` to exactly
        one paint, and those paints are pairwise different records. Then the collision is in the
        KEY, not in the evidence: the C# routes each entry by sku and each lands correctly.
        """
        if self.catalog is None:
            return False
        skus = {str(c.get("sku") or "") for c in claims}
        owners = [self.catalog.owner(key, sku) for sku in skus]
        if any(owner is None for owner in owners):
            return False
        return len({id(owner) for owner in owners}) == len(owners)

    def add_enrich(self, key: str, **fields: object) -> bool:
        """File ONE store product's evidence under ONE catalog identity. False = withheld.

        THIS USED TO BE A FIRST-WINS MERGE UNCONDITIONALLY, and that is the bug (2026-08-06).
        The body was `if v not in (None, "") and k not in entry`, over a dict `setdefault` had
        already created -- so when two DIFFERENT store products claimed the same `{Name}|{Set}`,
        the second one's ean, imageUrl, price and sku all hit `k in entry` and vanished. Not
        overwritten, not reported: gone, with the winner decided by observations.jsonl row
        order. Measured here, on this branch, against HEAD's generator and HEAD's harvest files
        (the ratchet reads them, so a regenerated tree undercounts monument): 43 keys were
        claimed twice or more and 48 rows were discarded that way --

            green-stuff-world  34 keys / 39 rows     ak-interactive  0 / 0
            vallejo             4 /  4               army-painter    0 / 0
            monument-pro-acryl  4 /  4               turbo-dork      0 / 0
            scale75             1 /  1               reaper          0 / 0
                                                     mr-hobby        0 / 0

        -- and the loss was not hypothetical: three monument-pro-acryl records (Blue, Orange,
        Shadow Flesh) carry a 22 ml Pro Acryl 1-Step bottle's EAN, photo and $6.00 price today
        because the 1-Step row sat earlier in the file than the dropper's own.

        BUT THOSE 43 KEYS ARE TWO DIFFERENT FAILURES, and only one of them is a corruption.

        MODE B -- ONE catalog paint, N store products (gsw 34, monument 4, scale75 1). The entry
        would put one product's barcode, photo and price onto a paint that is a different
        product. REFUSED, by the C#'s own rule read from the other end:
        `HarvestApplier.ApplyEnrichment` meets one entry against N paints and declines because
        "guessing which of two paints a photo belongs to is worse than leaving both blank"
        (HarvestApplier.cs:183). A rival claim marks the key contested, drops whatever the first
        claim filed, and every later claim on it is withheld too.

        MODE A -- ONE catalog KEY, N catalog PAINTS, each store product naming its own (vallejo
        4, all of vallejo's). `Black|Game Color` is 72.051 AND 72.094; the store ships both and
        each row's sku is the exact `productCode` of one of them. Nothing is at risk here,
        because the C# does not route by key alone -- `ApplyEnrichment` disambiguates an
        ambiguous key by `entry.Sku`, so the entry lands on the correct pot. `enrich` is a dict
        keyed by identity, so only ONE of the two can be carried; that is a partial gain (one
        paint enriched, one not), not a wrong value on a right paint. FIRST-WINS IS KEPT, and
        refusing here would have cost 4 correct imageUrls to prevent nothing -- mfr-vallejo
        quotes no ean and no price, so those entries carry a photo and a source URL and nothing
        else. `routes_by_sku` above is the test, and it is `Catalog.owner`, i.e. the same lookup
        the C# does, rather than a second differently-shaped guess.

        The two modes are distinguished by the CATALOG, not by the store, which is why
        `BrandHarvest` now takes one. With no catalog (a bare `BrandHarvest()` in a test) every
        rival claim is Mode B: refusing is the safe default when nothing can vouch for routing.

        `sku` is the rivalry test because it is the only thing an entry carries that names the
        PRODUCT rather than the paint (and it is exactly what the C# disambiguates on). TWO
        HONEST LIMITS OF THAT, both measured over all nine bridges on this branch --

          * A repeat claim under the SAME non-blank sku still merges first-wins, so two rows of
            one product that CONFLICT on a non-blank field lose the second silently. Not
            reported, and not a property of this rule: it is a property of the data. Across
            3,217 `add_enrich` calls there are ZERO repeat claims on any key under one sku (nor
            any with both skus blank, which this rule would likewise read as one product). The
            branch has never fired. mr-hobby, the one bridge that genuinely unions two sources
            per identity, does it INSIDE a single call -- the manufacturer pass fills a
            `confirmed` dict and the retailer pass reads it (see bridge_mrhobby) -- so it never
            claims a key twice. The branch is kept because "the same product seen twice is not
            two products" is the correct rule, not because anything needs it today; if a source
            ever does file one identity from two rows, that silence is the thing to revisit.
          * So "nothing leaves in silence" is a guarantee about RIVAL products only.

        Detection lives here, in the one place all nine bridges pass through, because the
        mechanism is shared even where the evidence is not: bridge_monument can settle its four
        keys with a product code and does (see its two-pass join), bridge_gsw has no code to
        settle anything with and routes its 34 to `candidates` itself. Whatever the bridge does
        not resolve, this refuses and `contested_candidates` reports -- including for the five
        brands that have no contested key today and nobody has had to look at.
        """
        sku = str(fields.get("sku") or "")
        claims = self.claims.setdefault(key, [])
        rival = bool(claims) and sku not in {str(c.get("sku") or "") for c in claims}
        claims.append(dict(fields))
        if rival and not self.routes_by_sku(key, claims):
            self.contested[key] = list(claims)
        if key in self.contested:
            # Re-recorded on every later claim so the report names all of them, and popped
            # rather than left: a key can be Mode A for two claims and become Mode B on a third.
            self.contested[key] = list(claims)
            self.enrich.pop(key, None)
            return False
        entry = self.enrich.setdefault(key, {})
        # A RIVAL claim contributes NOTHING, not even to a blank field. Mode A means the catalog
        # holds several paints under this key and each store sku names a different one -- but the
        # harvest can still carry only ONE entry per key, and the C# routes that entry by its
        # `sku`. So every field in it must come off the product that sku names. Blank-filling from
        # a rival was the corruption this whole change exists to stop, merely narrowed to the
        # fields the winner happened to leave empty: measured on a synthetic two-paint catalog,
        # claim {72.051, imageUrl} then {72.094, imageUrl, ean, priceEur} produced an entry whose
        # sku routes to 72.051 while its ean and price came off 72.094. Zero occurrences today
        # (all 8 vallejo Mode-A claims carry imageUrl and nothing else), which is a property of
        # the data, not of the rule -- hence the rule.
        if rival:
            return True
        for k, v in fields.items():
            if v not in (None, "") and k not in entry:
                entry[k] = v
        return True

    def contested_candidates(self) -> list[dict]:
        """One candidate per withheld claim -- the report half of the refusal above.

        Refusing a row and losing a row are different things (the rule `paint_rows` already
        works to), so a key nobody could settle still has to say so in the file. Pure and
        idempotent: derived from `self.contested`, never appended to `self.candidates`, so a
        bridge that resolves its own contests (gsw, monument) emits nothing here twice.

        `name` is the CATALOG name off the key, not the store title -- this candidate is about
        the identity, and the store row is already pinned by its own sku and sourceUrl. A bridge
        that wants the store's own wording routes the row itself, before calling add_enrich.

        WHAT A CANDIDATE DOES NOT CARRY, said plainly because the deferral downstream rests on
        it: `{name, sku, url, source, reason}` and nothing else -- no ean, no price, no
        imageUrl. A refused row's BARCODE therefore survives only in
        data/evidence/products/<source>/observations.jsonl, and only a human following `url` or
        `sku` back into that file can recover it. That is the shape of the loss the GSW refusal
        below quantifies.
        """
        out: list[dict] = []
        for key, claims in self.contested.items():
            skus = sorted({str(c.get("sku") or "") or "(none)" for c in claims})
            for claim in claims:
                out.append(
                    {"name": key.split("|", 1)[0],
                     "sku": str(claim.get("sku") or "") or None,
                     "url": claim.get("sourceUrl"),
                     "source": claim.get("source"),
                     "reason": f"contested identity ({key}) -- {len(skus)} store products claim "
                               f"it: {', '.join(skus)}"}
                )
        return out

    def to_yaml(self) -> dict:
        out: dict[str, object] = {}
        if self.enrich:
            out["enrich"] = {k: self.enrich[k] for k in sorted(self.enrich)}
        if self.additions:
            out["additions"] = sorted(
                self.additions, key=lambda a: (a.get("set") or "", a.get("name") or "")
            )
        candidates = self.candidates + self.contested_candidates()
        if candidates:
            out["candidates"] = sorted(
                candidates, key=lambda c: (c.get("reason") or "", c.get("name") or "")
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
    catalog = Catalog("vallejo", BRANDS_DIR)
    prior_additions = previous_addition_codes("vallejo")
    out = BrandHarvest(catalog)
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
            # VALLEJO IS `add_enrich`'s MODE A, AND ALL FOUR OF ITS DOUBLE-CLAIMED KEYS ARE.
            # Not monument's failure and not gsw's: the CATALOG key is ambiguous -- two REAL,
            # DIFFERENT paints share one `{Name}|{Set}` -- and each store row's sku is the exact
            # productCode of one of them. Measured on this branch, all four and both claimants
            # each: `Black|Game Color` {72.051, 72.094}, `Green Grey|Model Color` {70.886,
            # 70.971}, `Grey|Mecha Color` {69.037, 70.641}, `Red|Model Air` {71.269, 71.102}.
            # `Catalog.owner` resolves all eight skus to eight distinct records, so
            # `routes_by_sku` is True and first-wins stands -- HarvestApplier disambiguates an
            # ambiguous key by `entry.Sku`, so the entry that IS carried lands on its own pot.
            # The cost is that `enrich` is one dict per key and can only carry one of the two:
            # four paints keep a photo they would otherwise not have, four go without. A partial
            # gain. Refusing both would have cost those four imageUrls and prevented nothing --
            # mfr-vallejo quotes no ean and no price, so there is no wrong value to plant.
            # Carrying BOTH means keying enrichment by product code, a schema change for another
            # day; that is the only thing still missing here.
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

# THE PUBLISHED NAME MAY DROP A SUFFIX ONLY WHEN THIS LIST SAYS THE SUFFIX IS A LABEL.
# INVERTED 2026-08-11. Until then `bridge_ak` published `ak_prettify(base)` unconditionally, so
# the rule was "cut at the last dash" rather than "strip a known range label": ANY suffix the
# mapping above did not recognise was deleted from the name, including the words that said what
# the product WAS. Measured over a live `bridge_ak()` run on the committed evidence: 242
# additions, 143 of which carry a suffix. 141 of those 143 are labels -- 79 QUICK GEN COLOR,
# 28 INK, 18 ACRYLIC WASH, 10 COLOR PUNCH, 2 STANDARD, 1 METALLIC, 3 Spanish glosses -- and lose
# nothing by being dropped. The other 2 are the whole reason this list exists:
#   AK121 'oif & oef – us vehicles wash'              -> `Oif & Oef`
#   AK123 'OIF & OEF – US Vehicles Streaking Effects' -> `Oif & Oef`
# Two different products, one set (`Weathering Effects`), one published name, and the only text
# telling them apart was the part the cut threw away. Inverting the rule changes exactly those 2
# published names and leaves the other 240 additions byte-identical -- so the blast radius of the
# fix is the bug itself. (Their un-swept sibling AK122 is committed as the full
# `Oif & Oef – US Vehicles Base`; it came from the Arcturus base and has no observation at all,
# which is why it never lost its suffix.)
#
# WHY EACH ENTRY IS A LABEL AND NOT NAME TEXT:
#  - the AK_SET_BY_SUFFIX keys ARE the range names, and the `set` the row lands in already says
#    each of them -- the suffix would only repeat half the identity key inside the other half;
#  - ACRYLIC WASH is the same thing one step further out: it routes to set `Acrylic Wash` by
#    slug below, and all 18 of its additions land there;
#  - EFECTO HIERRO / EFECTO BRONCE / AGENTE OXIDANTE (AK11266/7/8) are the SPANISH of the English
#    words immediately before them ('IRON EFFECT – EFECTO HIERRO'), i.e. a translation AK prints
#    in the title, not further product name. They are listed by their literal text because there
#    are three of them and no rule distinguishes a gloss from a qualifier; a fourth needs a line.
#
# `ak_split` itself is deliberately NOT changed. 124 rows reach it with `suffix is None` and the
# set-resolution below reads that value (`AK_SET_BY_SUFFIX.get(suffix or "")`, the `INK` split,
# and the `3rd-acrylics and suffix is None` branch), so moving the cut would move paints between
# sets -- and `set` is half the paint identity key. Only the NAME moved.
AK_LABEL_SUFFIXES = frozenset(AK_SET_BY_SUFFIX) | {
    "ACRYLIC WASH",
    "EFECTO HIERRO",
    "EFECTO BRONCE",
    "AGENTE OXIDANTE",
}

# WIDENED to 3 digits 2026-08-09. AK's legacy weathering and Xtreme Metal ranges number in
# three (AK012 Streaking Grime, AK479 Xtreme Metal Aluminium), and the archive has held 111
# such codes all along -- they arrived via the Arcturus base, so the shape was never in doubt,
# only unreachable through this bridge. Measured over the 951 observations that survive the
# crossover gate: 71 carry a 3-digit sku, ALL 71 sit in a mapped range (48 weathering, 23
# Xtreme Metal) and 0 would fall through to `candidates`, so widening admits exactly the
# paints the boxed sets were asking for and nothing else. The gate still rejects everything
# without a clean AK-number sku, which is what it was written to do.
AK_SINGLE_SKU = re.compile(r"^AK\d{3,5}$")


def ak_prettify(name: str) -> str:
    """ALL-CAPS store name -> the Arcturus capitalization style (plain per-word capitalize:
    'APC INTERIOR LIGHT GREEN (FS24533)' -> 'Apc Interior Light Green (fs24533)'-ish)."""
    words = []
    for word in name.lower().split():
        words.append(word if word.startswith("(") and any(ch.isdigit() for ch in word)
                     else word.capitalize())
    return " ".join(words)


# A dash with whitespace on AT LEAST ONE side, never neither. The first version required a space
# on BOTH (` - ` and ` – `), and AK does not always type one: measured 2026-08-07 over the
# 1,142 committed observations, `WARM YELLOW- QUICK GEN COLOR` (AK17010) and
# `SPACE YELLOW- QUICK GEN COLOR` (AK17011) print the hyphen flush against the colour name. Both
# fell through to `suffix = None`, missed AK_SET_BY_SUFFIX, and landed in `candidates:` --
# report-only -- so two paints AK genuinely sells reached no catalog at all. Verified live
# 2026-08-07: ak-interactive.com/product/space-yellow-quick-gen-color/ returns HTTP 200, SKU
# AK17011, in stock. They are the ONLY gap in the archive's AK17001-AK17079 block, and they were
# lost to one missing space.
#
# "At least one side" and not "any hyphen": a bare `-` would split real colour names on their own
# punctuation. Measured over the same 1,142 rows, exactly 2 rows change classification and 0
# others reclassify.
_AK_SUFFIX = re.compile(r"\s[-–]\s|\s[-–]|[-–]\s")


def ak_split(name: str) -> tuple[str, str | None]:
    """'SPACE MAGENTA – QUICK GEN COLOR' -> ('SPACE MAGENTA', 'QUICK GEN COLOR')."""
    matches = list(_AK_SUFFIX.finditer(name))
    if matches:
        last = matches[-1]
        return name[: last.start()].strip(), name[last.end():].strip().upper()
    return name.strip(), None


def bridge_ak() -> BrandHarvest:
    """CATALOG role for the store's paint singles since 2026-07-24 (owner-approved promotion):
    the Trello-tracked gaps (Quick Gen range, 3rd-gen review) come exactly from here. Sets,
    bundles, guides and everything without a clean AK-number SKU stay out; washes ride along
    as their own set. Additions are born colour-less; chart swatches heal them later."""
    catalog = Catalog("ak-interactive", BRANDS_DIR)
    prior_additions = previous_addition_codes("ak-interactive")
    out = BrandHarvest(catalog)
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
            # THE TWO RANGES THE SWEEP GAINED 2026-08-09, keyed by slug because these products
            # carry no "- RANGE" suffix in their titles the way 3rd Gen and Quick Gen do. Both are
            # colours by AK's own taxonomy (they sit under its `paints` parent) and both are named
            # by the boxed sets: Xtreme Metal answers AK479/AK480/AK488, weathering singles answer
            # AK012/AK014/AK636 and the seven AK121xx wash colours.
            #
            # The auxiliary agents that share these categories never reach here -- the descriptor's
            # crossover block takes them out as `hobby-auxiliary` before `paint_rows` yields, which
            # is the same gate that already removes boxed sets. So "is it a colour?" is answered
            # once, in the descriptor, rather than twice in two spellings.
            elif "xtreme-metal-paints" in slugs:
                set_name = "Xtreme Metal"
            elif "paints-weathering-single" in slugs:
                # ONE set for the whole weathering line rather than one per sub-shelf (filters,
                # washes, deposits, streaking). AK's own slugs partition it four ways and its
                # printed labels do not, so a per-shelf split would invent a taxonomy the bottles
                # do not carry -- and `set` is half the paint identity key, so an invented split is
                # expensive to undo. A future source that states the sub-range can refine it.
                set_name = "Weathering Effects"
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

        # The suffix is dropped only when AK_LABEL_SUFFIXES says it is a label; anything else --
        # including `suffix is None`, where `base` and the raw title are already the same string
        # (verified: 0 of the 124 suffix-less rows differ) -- keeps the FULL title.
        out.additions.append(
            {"name": ak_prettify(base if suffix in AK_LABEL_SUFFIXES else name_raw),
             "set": set_name, "productCode": sku,
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
    catalog = Catalog("army-painter", BRANDS_DIR)
    prior_additions = previous_addition_codes("army-painter")
    out = BrandHarvest(catalog)
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
    """METADATA-ONLY storefront, joined CODE-FIRST IN TWO PASSES since 2026-08-06.

    monumenthobbies.com ships two ranges that share colour names: the 22 ml PRO Acryl 1-Step
    bottles (MPA-5xx) and the original droppers (MPA-005 etc.). The catalog knows the droppers
    by their bare code and the 1-Step range only under the codes a previous harvest minted
    (MPA-501 ... MPA-510), so `match_code("500")` misses and the one-line join this replaced --
    `match_code(code) or match_code(code.zfill(3)) or match_name(name)` -- dropped a 1-Step
    bottle onto the dropper's identity by NAME. First-wins in `add_enrich` then decided the
    winner by file order, and the 1-Step rows sit first: measured 2026-08-06, `Blue`, `Orange`
    and `Shadow Flesh` each carry a 1-Step EAN, photo and $6.00 price in
    data/paints/brands/monument-pro-acryl.yaml (:405-419, :1260-1274, :1393-1407) and only
    `Warm Yellow` escaped, because MPA-072 happens to precede MPA-504.

    So: a code match OWNS the identity it hits, and a name match may only take a key no code
    match claimed. That is the other half of the HarvestApplier precedent add_enrich quotes --
    disambiguate when a SKU can settle it, refuse when it cannot -- and here it settles all four
    (measured 2026-08-06: contested 4 -> 0, three enrich entries flip to MPA-005/007/042, and
    MPA-500/504/506/511 land as `Pro Acryl 1-Step` additions instead of vanishing, taking that
    set from 8 records to 12).

    Ownership is claimed regardless of the `previous_addition_codes` ratchet: a coded product
    whose entry is deferred to `additions` still IS the paint under that key, so letting a
    same-named row from another range take the identity it vacated would be the same theft.

    THE ONE THING THIS FIX DOES NOT DO, AND IT MUST BE HANDLED BEFORE THE PAINT TOOL NEXT RUNS.
    The repair moves three barcodes but cannot un-write the ones already stored, and the
    archive's non-destructive re-barcoding will keep them:

      655368408984  Blue          brands/monument-pro-acryl.yaml:411  -> addition MPA-500
      655368429989  Orange        brands/monument-pro-acryl.yaml:1266 -> addition MPA-511
      655368417375  Shadow Flesh  brands/monument-pro-acryl.yaml:1399 -> addition MPA-506

    Each is a 1-Step bottle's real barcode sitting on a DROPPER record. This harvest now hands
    the dropper its own (628504411056 / 628504411070 / 628504411421) and mints the 1-Step bottle
    as its own addition carrying the barcode natively. When the paint tool runs,
    `PaintRecordAdapter.Merge` gives the primary `ean` slot to fresh and unions the displaced
    value into `additionalEans` (PaintRecordAdapter.cs:25 and :31-32, via
    `BarcodeSet.Union(..., [existing.Ean])`) -- deliberately, because "a paint bought years ago
    must stay resolvable by the barcode on the pot the owner actually has". The result is that
    each of these three barcodes would be held by TWO records at once: primary on the 1-Step
    addition, additional on the dropper.

    THAT IS A CHANGE IN DEGREE, and the first draft of this paragraph called it a change in KIND
    on a claim that is false. Measured 2026-08-06 over ALL 21 files in data/paints/brands (not
    the nine bridged brands, which are 5,710 records / 2,993 barcodes -- the earlier text
    miscited the scope in the one sentence whose job is quantification): 8,528 paint records,
    3,825 distinct barcodes, and exactly ONE barcode held by more than one record --
    8429551724838, on two `Viking Grey|Xpress Color Intense|72.483` records. Those were called
    "one identity written twice". They are not: `PaintRecordAdapter.IdentityKey` is
    set|name|productCode|HEX, and the two differ precisely there (`#374855` vs `#45515D`). So
    cross-identity barcode sharing is already 1, and these three would make it 4.

    The argument survives the correction and is worth keeping for the right reason: it is not the
    COUNT that matters but the provenance. 655368408984 was never on any Blue dropper pot -- it
    was written there by the name-match bug this docstring describes. The union barrier exists to
    keep a barcode a pot GENUINELY carried resolvable; preserving one it never carried archives
    the bug in the one shape nothing downstream reviews.

    AND AN OVERRIDE CANNOT CLEAN IT UP AFTERWARDS, for two reasons that both have to be false
    before one would work. `OverrideApplier.Apply` runs on the FRESH side, before the reconciler
    (PaintCatalogApp.cs:256 vs :497), so it never sees the archived record that holds the wrong
    barcode; and its own union is non-destructive in the same way -- OverrideApplier.cs:83 passes
    `[p.Ean]` into `BarcodeSet.Union`, so even overriding `ean` in place would keep the displaced
    value. The one intervention that works is to correct the stored `ean:` on those three records
    in data/paints/brands/monument-pro-acryl.yaml BEFORE the tool runs: `Union` drops any value
    equal to the primary, so once existing and fresh agree the barcode never enters the set at
    all. That edit belongs to the archive correction pass (the same one the GSW dipping inks and
    scale75's `Titanium Grey` need), and it is a PRECONDITION of running the paint tool on this
    harvest, not a follow-up. Nothing in this change touches the archive, so no duplicate exists
    on disk today -- this is a debt recorded at the moment it is incurred, not one discovered
    later.

    For whoever writes that pass: `volumeMl` will not find these records. All 75
    `Monument Pro Acrylic Paints` records say 22, including `Warm Yellow`, which was never wrong
    -- it is a brand-wide table default, not evidence. Three tells single out exactly these
    three, and agree with each other: the `655368...` barcode prefix (3 records; the other 72
    are `628504...`), `priceUsd` 6.0 (3; 71 are 5.0 and one is 6.25), and a
    `MH-22-ml-1step-*` image filename (3).
    """
    catalog = Catalog("monument-pro-acryl", BRANDS_DIR)
    prior_additions = previous_addition_codes("monument-pro-acryl")
    out = BrandHarvest(catalog)
    rows = [o for o in paint_rows("mfr-monument", out)
            if (o.get("hints") or {}).get("productType") == "Paint Singles"]

    def code_key(observation: dict) -> str | None:
        code = str(observation.get("sku") or "").removeprefix("MPA-")
        return catalog.match_code(code) or catalog.match_code(code.zfill(3))

    claimed_by_code = {key for key in map(code_key, rows) if key is not None}

    for o in rows:
        sku = str(o.get("sku") or "")
        name = MONUMENT_NAME.sub("", o["name"]).strip()
        common = {"ean": o.get("ean"), "imageUrl": o.get("imageUrl"),
                  "sourceUrl": o.get("url"), "source": "mfr-monument"}
        key = code_key(o)
        if key is None:
            named = catalog.match_name(name)
            key = None if named in claimed_by_code else named
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
    catalog = Catalog("turbo-dork", BRANDS_DIR)
    prior_additions = previous_addition_codes("turbo-dork")
    out = BrandHarvest(catalog)
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
    post-Arcturus ranges join as additions with the store SKU as the code.

    THE ONE CONTESTED KEY THIS BRIDGE USED TO CARRY IS GONE (2026-08-14, PR #138), and the way it
    went is worth keeping, because the deferral recorded here for a week rested on a false premise.
    SART-60 and SW-40 are both titled "TITANIUM GREY". The catalog spelled the Warfront one
    `Titanium Gray`, so the in-set match on the line below missed it, SW-40 fell through to the
    BRAND-WIDE `match_name` fallback, and landed on the only `titaniumgrey` in the brand -- the
    ARTIST RANGE record. Two store products claiming one identity is `add_enrich`'s MODE B, so
    `Catalog.owner` returned None for both skus and neither could claim it.

    This docstring used to defer settling it on the grounds that SW-40 would then "fall to the
    addition branch and MINT `Titanium Grey|Warfront  Range` ... i.e. assert a new paint on the
    strength of one store collection tag". THAT WAS WRONG: Warfront already HELD the record, under
    the American spelling. The fix was one `name:` override (`Gray` -> `Grey`) plus its alias in
    data/paints/overrides.yaml, which states the evidence. Both skus then match IN-SET, the two
    claims land on two different keys, and there is nothing left to contest -- no mint, no
    promotion, no bridge change. enrich 294 -> 296, candidates 9 -> 7, contested 1 -> 0.

    THE LESSON, since the shape recurs: a Mode B contest can be a NAME-QUALITY defect wearing a
    routing defect's clothes. Before treating one as unsettleable, check whether the loser's real
    home already exists in the catalog under a spelling the join cannot see. `Catalog.match_name`
    normalizes to lowercase alphanumerics only (`norm`), so gray/grey, a doubled letter and a word
    swap all read as different paints -- and the brand-wide fallback then quietly delivers the row
    to whichever record DID normalize alike, which is the worst available outcome.

    AND THE DAMAGE IT LEFT, now repaired: the Artist Range record carried `.../4254.jpg` and
    priceEur 2.25 -- the WARFRONT bottle's photo and price -- because SW-40 arrives first and won
    the old first-wins merge before this refusal existed. Withholding the entry stopped the wrong
    value being re-asserted but could never take it back out, since `ApplyEnrichment` and
    `BarcodeEnricher` only blank-fill. Clearing the contest is what fixed it: SART-60's entry now
    supplies a NON-BLANK fresh imageUrl and price, and `PaintRecordAdapter.Merge` prefers fresh
    over stored for both (:46-53), so the record moved to its own `.../6139.jpg` and EUR 3.72.
    That leaves monument's Blue, Orange and Shadow Flesh on the archive-pass list, not this one."""
    catalog = Catalog("scale75", BRANDS_DIR)
    prior_additions = previous_addition_codes("scale75")
    out = BrandHarvest(catalog)
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

# Archive sets a store category may legitimately JOIN, where that is more than the one set it
# MINTS into. `suffix_match` filters its candidates through this; every slug not named here
# admits its GSW_SET_BY_CATEGORY value alone.
#
# KEYED BY SLUG, NOT BY SET NAME, and that is not cosmetic: the umbrella is a property of
# greenstuffworld.com's `acrylic-inks` category spanning four archive sets, not of the string
# "Acrylic Inks". Slug-keying also stays correct on the day two slugs map to one set.
#
# WHY EXACTLY THESE FOUR AND NOTHING ELSE, measured 2026-08-06 over the 408 rows `paint_rows`
# yields for mfr-greenstuffworld. 42 rows join a set their own category does not map to, and they
# are not one phenomenon:
#   28 are this umbrella -- 12 Intensity Ink, 8 Wash Ink, 8 Candy Ink Metallic -- real Arcturus
#      ink sets the store files under one category. Dropping them from this map re-mints all 28 as
#      `Acrylic Inks` additions ("Wash Ink Aether Blue|Acrylic Inks"), duplicating 28 archive
#      records. Measured: a strict per-slug filter with NO umbrella costs 31 enrich entries.
#   11 are the three crowded `Fluor Metallic` keys (White x3, Orange x4, Yellow x4 claimants),
#      already refused as contested and filed as candidates. Those are what the filter homes.
#    3 are `Fluor Paint YELLOW-ORANGE` (1702), `Fluor Paint VIOLET` (1706) and `Chrome Paint`
#      (2454), each enriching an archive record that is genuinely the same pot under an
#      Arcturus-era set name (`Fluor Metallic`, `Metallic Colors`). Admitting those two set names
#      here WOULD preserve those three enrichments -- and is a trap, measured: it also un-crowds
#      the three contests, so 1701/1703/1760 then enrich `Yellow|Fluor Metallic` and friends, the
#      very records holding a Transparent Acrylic Ink's barcode, and `PaintRecordAdapter.Merge`
#      would promote the fluor barcode to primary and demote the ink's into `additionalEans` --
#      three archival lies, on records from a range the pot was never part of. So those three are
#      answered in data/paints/overrides.yaml by `retract:` plus a `hex:` override each -- NOT by
#      `aliases:`, which cannot fire for them. All three records come from Arcturus, which the
#      workflow re-clones every run, so `fresh` re-supplies each key, `consumed` is seeded with it
#      and CatalogReconciler.cs:84 refuses the alias. That constraint has been invisible until now
#      because every existing alias in overrides.yaml renames a HARVEST-minted record, which
#      Arcturus never supplies -- worth knowing before reaching for `aliases:` again.
#
# ONE DECISION LEFT OPEN, AND IT EXPIRES AT THE NEXT TOOL RUN. Five of the ink additions this
# unblocks inherit the store's own punctuation through `gsw_clean_name`:
# `Acrylic Ink Opaque- Osl White` (no space after the dash, and `OSL` title-cased to `Osl`) will
# sit beside `Acrylic Ink Opaque - Yellow`. `_GSW_PREFIX`'s `^[-–]` branch is ^-anchored and
# cannot reach a mid-title dash, and its `fluor(escent)? (acrylic )?paint` alternative does not
# cover "Fluor Acrylic Ink". This is NOT a decision with a deadline, as an earlier draft of this
# comment claimed: both spellings are ALREADY committed archive identities, minted by earlier
# harvest runs -- `Acrylic Ink Opaque- Black` (4286), `- Light Brown` (4291) and `- Turquoise`
# (4287) carry the missing space, while `Acrylic Ink Opaque - Blue`/`- Brown`/`- Green`/`- Red`/
# `- Siena` carry it. The ratchet re-emits all of them in this very file. So the inconsistency
# predates these five, tidying it is a `gsw_clean_name` change affecting every one of the 175
# additions (an unaliased rename that mints and strands, per
# test_paint_harvest_gsw_names.py::TestNoRenameStrandsAnArchiveRecord), and nothing about it gets
# easier or harder by running the tool. Left as generated, consistent with its own neighbours.
GSW_UMBRELLA_SETS = {
    "acrylic-inks": {"Acrylic Inks", "Intensity Ink", "Wash Ink", "Candy Ink Metallic"},
}


def gsw_allowed_sets(slug: str) -> set[str] | None:
    """Archive sets `slug` may join, or None when the slug maps to no set at all.

    None means "no hint" and restores the unhinted brand-wide-unique rule, matching
    `Catalog.match_name`'s own None branch. Inert today -- 0 of the 408 joining rows sit in an
    unmapped category (an unmapped row cannot become an addition either, it goes to candidates)
    -- but it is the correct reading of "the store told us nothing", not a silent refusal.
    """
    set_name = GSW_SET_BY_CATEGORY.get(slug)
    if set_name is None:
        return None
    return GSW_UMBRELLA_SETS.get(slug) or {set_name}


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
    catalog name that the store title ends with, unique at that length, AND in a set the row's
    own store category is allowed to reach -- see GSW_UMBRELLA_SETS). Enrichment carries
    the store's REAL gtin13 EANs (100% fill) + images; unmatched paints in mapped categories
    join as additions (cleaned name, mpn as productCode, EAN at birth)."""
    catalog = Catalog("green-stuff-world", BRANDS_DIR)
    prior_additions = previous_addition_codes("green-stuff-world")
    out = BrandHarvest(catalog)
    # normed catalog name -> keys, for suffix lookup
    by_norm: dict[str, list[str]] = catalog.by_name
    norms = sorted(by_norm, key=len, reverse=True)

    def suffix_match(store_name: str, allowed: set[str] | None = None) -> str | None:
        # STILL VOLUME-BLIND, AND THAT IS NOW ANSWERED BY REFUSING, NOT BY MATCHING BETTER.
        # This runs on the RAW title, so norm("Dipping ink 60 ml - PAPYRUS DIP") and
        # norm("Dipping ink 17 ml - Papyrus Dip") both END with `papyrusdip` and both return
        # `Papyrus Dip|Dipping Inks`. Two different pots, two gtin13s, 3.7375 vs 2.125 EUR, one
        # identity. Measured 2026-08-06: 31 keys claimed by more than one row, 62 rows involved,
        # 39 of them formerly discarded in silence by first-wins. (34 keys / 73 rows before the
        # set filter landed later the same day -- the 3 keys and 11 rows it removed were the
        # crowded `Fluor Metallic` ones, which were never a volume collision at all.)
        #
        # WHY NOT MAKE THE MATCH VOLUME-AWARE INSTEAD, AND WHY MINTING THE RECORDS WOULD NOT
        # DO IT. 5b9d39b taught `gsw_clean_name` to keep the volume, but that function names
        # ADDITIONS -- it never touches the catalog side of this join, and 0 of the 41 committed
        # `Dipping Inks` records carry a volume in their name (86 of the brand's 400 end in one,
        # none of them here). The tempting conclusion is that minting "Papyrus Dip 17 ml" and
        # "Papyrus Dip 60 ml" would then let a volume-aware matcher prefer the right one. IT
        # WOULD NOT, and that is a fact about THIS FUNCTION, not about the archive: the rule
        # below is `n.endswith(cand)` -- the store title must END with the catalog name -- and
        # Green Stuff World writes the volume in the MIDDLE of these titles. Measured on this
        # branch over the 73 refused rows: 62 carry a volume mid-title, 0 carry one at the end,
        # 11 carry none. `norm("Dipping ink 60 ml - PAPYRUS DIP")` is `dippingink60mlpapyrusdip`,
        # which does not end with `papyrusdip60ml` and never will. The 86 records that DO end in
        # a volume match only because the store writes it last in THEIR titles (sprays,
        # varnishes: "Chrome Spray Paint 400ml"), which is exactly the position this rule can
        # reach. So a volume-aware join means replacing the suffix rule with one that parses the
        # volume out of the title and matches on (colour, volume) -- a different matcher, not a
        # richer catalog. Minting the records is necessary and NOT sufficient, and doing it
        # first, as a pure archive pass, is still the right order.
        #
        # And no SKU can settle it either -- the test `Catalog.owner` and HarvestApplier both
        # apply. All 31 contested keys have exactly ONE catalog paint and 0 of those paints
        # carry a productCode (nor does any of the 171 current enrich targets; 5 of 41
        # `Dipping Inks` and 0 of 9 `Fluor Metallic` records have one, none of them here). So
        # this is `add_enrich`'s MODE B throughout -- one paint, N products -- and the caller
        # refuses BOTH claimants and reports them, which is the half of the HarvestApplier
        # precedent that applies when nothing can disambiguate.
        #
        # NO LONGER SET-BLIND, AND THE FIX IS A FILTER, NOT A TIEBREAK (2026-08-06). `allowed` is
        # `gsw_allowed_sets(categorySlug)` and it is applied with `Catalog.match_name`'s exact
        # IN-SET-ONLY semantics (:405-414): the out-of-set keys are DISCARDED before the
        # uniqueness test, with no fallback branch, so a name that exists only in some other set
        # is refused outright. Two softer shapes were simulated against all 408 rows and are exact
        # NO-OPS -- a tiebreak (consult the sets only when several keys match) and a preference
        # (in-set first, unhinted fallback) each change 0 rows and home 0 of the 8 orphans,
        # because every one of the 42 cross-set joins already has `len(keys) == 1` at the matched
        # candidate. Widening the FILTER SET is therefore the only lever; see GSW_UMBRELLA_SETS
        # for why it holds exactly four names and why admitting `Fluor Metallic` is a trap.
        #
        # WHAT IT COSTS AND WHAT IT BUYS, measured over the 408 rows: 14 change disposition,
        # 394 do not, and no enrich entry changes CONTENT. 174/161/142 (enrich/additions/
        # candidates) becomes 171/175/131. All 28 umbrella joins survive. 11 rows leave the three
        # crowded `Fluor Metallic` contests and 3 leave `enrich` (1702/1706/2454, answered by
        # `retract:` + `hex:` in overrides.yaml -- see the GSW_UMBRELLA_SETS note for why an alias
        # cannot fire for an Arcturus-supplied record). The point of it is the 8 barcodes that were held by no
        # paint record and no product at all -- 8435646516455/516486/516547 (Acrylic Ink Opaque
        # OSL White/Orange/Yellow), 8435646524566/524580 (Fluor Acrylic Ink Yellow/Orange),
        # 8436574500608/500622/501193 (Fluor Paint YELLOW/ORANGE/WHITE) -- which now home as
        # additions. The `Fluor Paint` three land beside the Blue/Lime/Red/Rose/Turquoise
        # `Fluorescent` already holds; the ink five had no catalog representation whatsoever.
        #
        # AND THE CROWDING, NOT THE MATCH, IS WHAT UNHOMED THEM. The set-blind join wrote ZERO
        # wrong values into today's harvest: 11 of its 14 wrong-set rows were ALREADY refused as
        # contested and the other 3 put their own barcode on a record that holds exactly it. What
        # it did was pile 3-4 claimants onto `White|Fluor Metallic`, `Orange|Fluor Metallic` and
        # `Yellow|Fluor Metallic` until the refusal above fired on all of them. The three wrong
        # barcodes sitting on those records on disk are residue from 7873af8, predating contest
        # detection -- this filter stops nothing that is currently happening, it promotes 11
        # candidates to correct homes.
        #
        # NOT the reason Blue/Lime/Red/Rose escaped, though it looks like it: those four names
        # exist in BOTH `Fluorescent` and `Fluor Metallic`, but the loop never gets far enough to
        # notice. `blue`/`lime`/`rose` norm to 4 characters and `red` to 3, so `len(cand) < 5`
        # breaks first and they match nothing at all. `white` (5) is the shortest name that clears
        # the floor and is exactly the shortest that got mis-joined. Anyone lowering that floor is
        # relying on the two-set ambiguity, which is a second line of defence, not the operative
        # one.
        #
        # WHAT THIS DOES NOT REPAIR, and it is most of it. Re-measured 2026-08-06 over the 39
        # committed `Dipping Inks` records (41 before 2277fb1 retracted the 2 boxed sets; the
        # brand is 381 records, not 400): 33 carry a 60 ml row's ean/EUR 3.7375/image, 5 carry a
        # 17 ml row's, 1 has none. Withholding an entry never un-writes a populated field
        # (`HarvestApplier.ApplyEnrichment` and `BarcodeEnricher` blank-fill), so all 33 stay
        # exactly as they are, and this bridge cannot repair one of them.
        #
        # THAT ARCHIVE PASS HAS NOW LANDED FOR 31 OF THE 33, BY HAND, in data/paints/overrides.yaml
        # (2026-08-06) -- and it is invisible from here, deliberately. Those 31 are the ones whose
        # 17 ml sibling barcode was held by NOTHING; the file declares the bare record to be the
        # 60 ml pot (`volumeMl: 60`) and mints the 17 ml pot with its own ean/imageUrl, so no
        # barcode moves. This function is unaffected: simulated with all 31 minted records in the
        # archive, this bridge's output is unchanged (+0/-0 on enrich 174, additions 161,
        # candidates 142), because the rule below is still `n.endswith(cand)` and
        # `dippingink17mlpapyrusdip` ends with `papyrusdip`, never `papyrusdip17ml`. Minting was
        # necessary and, exactly as the paragraph above says, not sufficient.
        #
        # CLOSED 2026-08-06, and it was NOT a barcode question -- `volumeMl` said nothing about
        # which pot a record meant anywhere else in this brand. The brand-wide
        # `("Green Stuff World", null, 17, "dropper")` rule, written unconditionally by
        # VolumeEnricher, contradicted 79 records' own `hints.ml` (Flexible 26, Dry Brush 20,
        # Primer 9, Spray Primer 9, Chameleon Spray 7, Varnish 5, Chrome Spray 2, Blackest Black 1
        # -- the 2 Dipping Inks of the old count of 81 having been taken by overrides.yaml in
        # fe4a2dd), and the same line stamped `container: dropper` on 18 aerosol cans. It was a
        # volume-table change, not a bridge one, and that is where it went: three per-set rows above
        # the brand-wide one in VolumeTable.cs cover 64 of the 79 plus all 18 containers, and the
        # 15 in the three mixed-volume sets are per-record `volumeMl` assertions in overrides.yaml.
        # Nothing here moved, and nothing here should: the bridge was never the right home, since
        # `--barcodes` is a single hardcoded FileInfo and BarcodeEnricher cannot write Packaging.
        # Worse in kind and NOT a volume question at all: `Orange`, `Yellow` and `White` in
        # `Fluor Metallic` hold a Transparent Acrylic Ink's / Intensity Ink OSL's barcode, from a
        # different range entirely, and in all three contests the row first-wins discarded was
        # the `Fluor Paint` one that belongs there. STILL TRUE ON DISK after this change: the
        # filter mints those inks' rightful owners (3506/4273/4281 -> `Acrylic Inks`) but nothing
        # here can take a barcode OFF a record -- `OverrideApplier` unions the displaced primary
        # back into `additionalEans` and so does `PaintRecordAdapter.Merge`, leaving `retract:` as
        # the only mechanism in the pipeline that removes one. That is an archive change, tracked
        # separately; the ordering it needs is supplied here, because a retraction whose barcode
        # lands on a same-brand, same-role record in the SAME run is `moved`, not `lost`.
        n = norm(store_name)
        for cand in norms:
            if len(cand) < 5:
                break  # sorted by length desc; everything after is shorter
            if n == cand or n.endswith(cand):
                keys = by_norm[cand]
                if allowed is not None:
                    # `rsplit`, not `endswith(f"|{set}")`: equivalent only while no paint name
                    # contains a pipe, and this is the spelling that stays true if one ever does.
                    keys = [k for k in keys if k.rsplit("|", 1)[1] in allowed]
                if len(keys) == 1:
                    return keys[0]
                return None  # ambiguous (or out of set) at the longest match -- refuse
        return None

    rows = paint_rows("mfr-greenstuffworld", out)
    # PASS 1 -- WHO CLAIMS WHAT. A store product is identified by its sku, so a key two skus
    # reach is two products claiming one paint. Counted before anything is filed, because
    # first-wins cannot be undone from inside the loop: by the time the 17 ml row arrives the
    # 60 ml row has already filed the ean, and `add_enrich` (which does catch this now) would
    # report it under the catalog's name rather than the store's own two titles.
    #
    # Only rows that would actually enrich count as claimants: a `previous_addition_codes` row
    # is on its way to `additions` and takes no identity here (0 of the 62 contested rows are
    # prior additions today, and 0 of the 14 the set filter promoted out of the contests were
    # either -- the guard is for the day one is).
    #
    # The `allowed` argument MUST be computed the same way here as in the filing loop below.
    # A pass that counts claims on an unfiltered join and files them on a filtered one contests
    # keys the filing loop never reaches, and vice versa -- the two would disagree about which
    # rows are refused, which is the one thing this two-pass shape exists to make impossible.
    claims: dict[str, set[str]] = {}
    for o in rows:
        key = suffix_match(o["name"],
                           gsw_allowed_sets((o.get("hints") or {}).get("categorySlug") or ""))
        if key is not None and str(o.get("sku") or "") not in prior_additions:
            claims.setdefault(key, set()).add(str(o.get("sku") or ""))
    contested = {key: skus for key, skus in claims.items() if len(skus) > 1}

    for o in rows:
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
        key = suffix_match(o["name"], gsw_allowed_sets(slug))
        if key is not None and sku not in prior_additions:
            if key in contested:
                # REFUSED EXPLICITLY, and the explicitness is the whole point: in this bridge a
                # missing match is not a refusal. `suffix_match` returning None falls through to
                # the GSW_SET_BY_CATEGORY branch below, and all 62 contested rows sit in a mapped
                # category -- so "refuse both" written as "return None" PROPOSES 62 NEW PAINTS
                # (measured on this branch; since 5b9d39b their cleaned names are volume-suffixed,
                # 0 colliding with each other and 0 with an existing catalog key, so they would
                # all mint). Those 62 records are probably the right end state, but not yet:
                # minting "Papyrus Dip 60 ml" and "Papyrus Dip 17 ml" beside a bare "Papyrus Dip"
                # that still holds the 60 ml barcode grows the catalog instead of repairing it.
                # Candidates now, additions after the archive pass -- in that order.
                #
                # WHAT THAT COSTS, EXACTLY, because a candidate carries only
                # {name, sku, url, source, reason} -- no ean, no price, no imageUrl (see
                # `BrandHarvest.contested_candidates`). All 62 of these rows carry a gtin13, 62
                # DISTINCT ones. Before the refusal landed, 31 of them reached data/paints/harvest
                # as the first-wins winner's `ean`; after it, 0 appear anywhere under
                # data/paints/harvest. Of the 62 barcodes, 31 are already written into
                # data/paints/brands/green-stuff-world.yaml (the winners, all 31 on `Dipping Inks`
                # records) and 31 exist NOWHERE under data/ outside
                # data/evidence/products/mfr-greenstuffworld/observations.jsonl. So the refusal
                # does not lose a barcode the repo had; it declines to promote 31 and reports,
                # rather than hides, the other 31. Recovering any of them means reading the
                # evidence file.
                #
                # The 3 `Fluor Metallic` winners this paragraph used to count here are gone from
                # the tally (2026-08-06): the set filter took all 11 of those rows out of the
                # contests entirely, and the 8 barcodes that were held by nothing at all now home
                # as additions. What is left is one phenomenon, not two -- 31 dipping-ink pairs.
                out.candidates.append(
                    {"name": o["name"], "sku": sku or None, "url": o.get("url"),
                     "source": "mfr-greenstuffworld",
                     "reason": f"contested identity ({key}) -- {len(contested[key])} store "
                               f"products claim it: {', '.join(sorted(contested[key]))}"}
                )
                continue
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
    # NO LINE PAGE ANYWHERE ON reapermini.com, and that is the point. Reaper's High Density range
    # is named only inside set contents now (`associatedProducts.category`), which is why 29815
    # "HD Dragon Blue" resolved to nothing for so long -- see strategies/reaper.py::
    # _set_only_paints. Without this row the observation would land in `candidates` as an "unmapped
    # line" and stay unpublished, which is the same silence in a different file.
    #
    # The set NAME matches the site's own label rather than the shorter "Master Series Paints
    # High Density Colors" the boxes print: `set` is half the paint identity key, and every other
    # entry here takes the site's wording too (only Pathfinder is shortened, and only because the
    # Arcturus base already spells it that way and the archive must agree with itself).
    "Master Series Paints High Density": "Master Series Paints High Density",
}


def bridge_reaper() -> BrandHarvest:
    """CATALOG role (owner-activated + promotion 2026-07-24). Site skus are zero-padded
    ("09412") while the Arcturus base stores bare digits ('9412') -- codes normalize by
    stripping leading zeros, and additions adopt the base convention. Singles only; the
    set-kind observations (triads/sets/LTPK, hints.category paint-set) carry contentSkus as
    committed set-membership evidence but never promote. No EANs exist in the site data.

    The set filter is also what keeps SET prices out: 114 of the 576 observations are
    paint-set kind and all 114 quote a priceUsd (a $47.99 Learn To Paint Kit, a $659.99 full
    range). A set's price is not a paint's price, and `paint_rows` now removes all 115 before
    this loop sees them, so no ordering inside this bridge can expose one. `observed_price`
    asks the same predicate as a second line -- but only for a source that DECLARES one, so it
    is not the backstop an earlier version of this docstring implied it was for every source."""
    catalog = Catalog("reaper", BRANDS_DIR)
    prior_additions = previous_addition_codes("reaper")
    out = BrandHarvest(catalog)
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
            # exactly two categories across all 576 observations (paint 462 -- 427 listed plus
            # 35 named only inside sets -- and paint-set 114, measured 2026-08-08) and
            # `paint_rows` already removed every paint-set. If the
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
    catalog = Catalog("mr-hobby", BRANDS_DIR)
    out = BrandHarvest(catalog)

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


# --- Steamforged P3 (the RELAUNCHED Formula P3) --------------------------------------------

# Every row the store publishes for this range is titled "P3 Paints: <Colour>" -- singles,
# trade cases and the starter set alike (222 of 222, measured 2026-08-13).
P3_TITLE = re.compile(r"^P3 Paints:\s*")

# `SFP3-N###-S` is the SINGLE bottle; the same N-code WITHOUT the suffix is the trade case of
# six identical bottles, and SFP3-N128 is the starter set. Measured over the committed
# evidence 2026-08-13, the 222 SFP3 rows are exactly 110 singles + 110 `(Pack of 6)` cases +
# 2 rows for the one starter set, and the singles are clean: 110/110 carry a check-digit-valid
# EAN-13, a priceUsd, an imageUrl, and 110 DISTINCT names and 110 distinct barcodes.
P3_SINGLE_SKU = re.compile(r"^SFP3-N\d{3}-S$")

# THE SET STRING IS THE WHOLE SEPARATION, so it is chosen rather than defaulted. Identity is
# `set|name|productCode|hex`, and 98 of the 110 relaunched colours name-match a legacy record,
# so this string is the only thing keeping `Cygnar Blue|P3 Paints` off
# `Cygnar Blue Base|Privateer Press Formula P3`.
#
# "P3 Paints" is the MANUFACTURER'S OWN name for the relaunched range -- it is the literal
# title prefix on all 222 evidence rows and the store's own /pages/p3-paints -- which is the
# same rule the other bridges follow ("Warpaints Fanatic", "Quick Gen", "Xtreme Metal"): the
# range's printed name, never a coined disambiguator. Rejected: bare "P3" (says less than the
# evidence does, and reads as an abbreviation of the legacy set rather than a different range)
# and "Steamforged P3" (accurate about the maker, but Steamforged does not print it -- and
# inventing wording for one half of a pair invites re-inventing it for the next relaunch).
# Verified 2026-08-13: 0 of the 131 committed P3 records carry this set, so no minted identity
# can land on one of them.
P3_SET = "P3 Paints"


def bridge_p3() -> BrandHarvest:
    """CATALOG role for warmachine.gg's P3 singles -- THE ONE STOREFRONT ALLOWED TO MINT.

    ROLE EXCEPTION, maintainer-authorised 2026-08-13, against the doctrine at the top of this
    file (owner decision, docs/research/2026-07-23-paint-manufacturer-harvest-design.md:
    "Shopify storefronts are never catalog-providers"). Three grounds, all of which have to
    hold -- this is a carve-out for THIS range, not a precedent that a storefront may mint:

      1. The relaunched range exists on NO other source. The doctrine's reason for refusing a
         storefront is that a shop is a sales surface and some catalog source is the authority
         on what the range contains; here there is no such source to defer to. Left refused,
         these 110 paints reach no catalog at all.
      2. The store is the MANUFACTURER'S OWN. warmachine.gg is where Steamforged moved a line
         it already sold -- 352 products vanished from steamforged.com between 2026-07-13 and
         2026-08-12 and reappeared here, 350 under an identical handle and all 352 matched by
         sku (see docs/research/2026-08-12-steamforged-warmachine-store-split.md). It is not a
         reseller listing somebody else's range.
      3. The range carries MANUFACTURER PRODUCT CODES. `SFP3-N###-S` is Steamforged's own part
         number, so each minted paint has a stable identity that is not its name -- the thing a
         storefront usually cannot supply, and the reason a name-keyed shop listing is weak
         evidence. Independently corroborated: 1001hobbies publishes code+name+EAN per product
         and 3 of 3 spot-checks matched this harvest exactly on both fields.

    WHAT THIS BRIDGE MUST NEVER DO, and the reason it is written catalog-blind: it never calls
    `match_name`. 98 of the 110 relaunched colours name-match a committed P3 record, and
    joining on that is precisely the backfill PR #128 landed and then reverted -- 97 EANs put
    onto the ORIGINAL Privateer Press pots. Those records are a different product: `container:
    pot`, no product codes, Arcturus5404 import, against an 18 ml dropper bottle with preloaded
    mixing balls; the relaunch drops the old Ink (8) and Wash (5) sub-ranges entirely and adds
    colours the old range never had; and the measured colour delta over 89 same-named pairs is
    a median of 39.7 RGB, a systematic reformulation offset rather than measurement noise. A
    barcode is an assertion about one physical product. Same name and shared heritage are not
    the same pot, so this bridge does not look at the archive at all: every single mints, and
    the C#'s (Name, Set, ProductCode) skip in `AppendAdditions` is what keeps that idempotent.
    That is also why there is no `previous_addition_codes` ratchet here -- the ratchet exists
    for bridges that WOULD flip an addition to enrich-only once the catalog code-matches it,
    and a bridge that never consults the catalog cannot flip. `additions` is already the pure
    projection of the source that `previous_addition_codes` asks every bridge to be.

    WHY THE SHAPE TEST IS THIS BRIDGE'S OWN AND NOT THE CROSSOVER GATE'S. `paint_rows` still
    reads the evidence, so the universal invariant holds and a block added later would be
    honoured -- but it selects nothing today, and that is correct rather than an oversight.
    `crossoverToProducts` is the carve-out a `catalog: paints` source needs in order to send a
    row to the PRODUCT catalog instead; mfr-warmachine carries no `catalog:` key, so it is not
    a paint source and all 609 of its rows already publish as products (the 222 P3 rows as
    `category: paint` since PR #128). There is nothing to carve out. The 112 rows that must not
    mint are therefore refused HERE, by sku shape, and reported as candidates.

    Nor does minting re-open the double-publish that invariant guards. That guard is about a
    BOXED SET reaching both catalogs; an individual paint legitimately appears in both, and
    already does by this exact route -- gen_paint_barcodes.py reads mfr-gw-trade's product
    evidence (also a source with no `catalog:` key) to barcode the paint catalog's GW records.
    What must not happen is a case of six, or a starter set, becoming a paint. That is what
    `P3_SINGLE_SKU` refuses, and the refusal is the same shape the product side already draws:
    the case's own sku is the single's minus `-S`.

    MINTED COLOUR-LESS BY DESIGN (`AppendAdditions` stamps Hex "" and R/G/B 0). See
    data/paints/swatch-sources.yaml for the P3 swatch pass that fills them.
    """
    catalog = Catalog("p3", BRANDS_DIR)
    out = BrandHarvest(catalog)
    for o in paint_rows("mfr-warmachine", out):
        sku = str(o.get("sku") or "")
        if not sku.startswith("SFP3-"):
            continue  # the other 387 rows are miniatures, books and digital downloads
        name = P3_TITLE.sub("", o["name"]).strip()
        common = {"sourceUrl": o.get("url"), "source": "mfr-warmachine"}
        if not P3_SINGLE_SKU.fullmatch(sku):
            # The trade case and the starter set. Reported, not dropped: both are real products
            # and both already publish as such, so the harvest has to say why the paint catalog
            # declined them rather than leave a reader to infer it from an absence.
            out.candidates.append(
                {"name": name, "sku": sku, "url": o.get("url"), "source": "mfr-warmachine",
                 "reason": "multi-bottle pack -- crosses to the product catalog"}
            )
            continue

        price = observed_price(o, "mfr-warmachine")
        # `productCode` is the SINGLE's full sku, `-S` INCLUDED. The suffix is Steamforged's,
        # not ours, and it is what names the one physical product this record is about: strip
        # it and the paint carries `SFP3-N173`, which is the trade case's own part number and
        # the code that case publishes under in the product catalog. One code, two products,
        # and a later set-contents or barcode join with no way to tell them apart.
        out.additions.append(
            {"name": name, "set": P3_SET, "productCode": sku,
             "imageUrl": o.get("imageUrl"), **common, **price}
        )
        # AND an enrich entry on the identity the addition just minted. Not redundant: this is
        # the route the barcode takes (`additions` mint colour-less and barcode-less; the C#
        # runs `AppendAdditions` BEFORE `ApplyEnrichment`, so the paint born this run takes its
        # EAN in the same run), and it is what still lands the barcode on the day some other
        # import ships `<name>|P3 Paints|SFP3-N###-S` first -- `AppendAdditions` skips an
        # addition whose (Name, Set, ProductCode) already exists, and would otherwise leave
        # that record barcode-less forever.
        key = f"{name}|{P3_SET}"
        ean = str(o.get("ean") or "")
        out.add_enrich(
            key,
            ean=ean if ean13_ok(ean) else None,
            imageUrl=o.get("imageUrl"),
            sku=sku,
            **common,
            **pinned_price(catalog, key, sku, o, "mfr-warmachine"),
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
    "p3": bridge_p3,
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
            # dump_yaml, NOT yaml.safe_dump, because `sku` is a zero-padded numeric string on
            # Reaper and stock PyYAML emits half of those unquoted. Its YAML 1.1 resolver quotes
            # '89556' (that reads as an int, so it must be protected) but leaves '09736' BARE --
            # the 9 makes it invalid octal, so PyYAML itself reads it back as a string and never
            # notices the omission. A YAML 1.2 consumer has no octal rule for a bare leading zero
            # and reads 9736, losing the pad.
            #
            # Measured 2026-08-07 on the committed data/paints/harvest/reaper.yaml: 115 of 487
            # `sku` scalars bare against 372 quoted -- ONE field contradicting itself, decided by
            # nothing but which digits happen to appear. Every one of the 115 carries `reason:
            # boxed set -- crosses to the product catalog`, and the pad IS the join: 115 of 115
            # match a productCode in data/catalog/products/reaper.yaml verbatim (which stores them
            # quoted, '08906'), and 0 of 115 match once a 1.2 reader strips the zero.
            #
            # Nothing consumes it wrongly today -- the C# ignores `candidates` outright and PyYAML
            # round-trips its own output -- so this closes an exposure rather than a live bug. The
            # sibling generator gen_set_contents.py already refuses safe_dump for this exact shape
            # and says so in the same words. The wider reformat in the same commit (indented
            # sequences, longer lines) is _Dumper doing what it does everywhere else in the repo.
            #
            # This comment used to end "this was the last generator of committed data still using
            # it", and that was simply WRONG -- audited 2026-08-11, three more were still on
            # safe_dump: gen_paint_barcodes.py, gen_paint_store_barcodes.py and
            # gen_paint_swatches.py. All three are migrated now, which is why the claim is not
            # restated in the present tense either: the standing guarantee lives in
            # tests/test_repo_data.py::test_no_committed_yaml_string_changes_type_between_readers,
            # which scans the committed data instead of trusting a prose count that goes stale the
            # next time somebody adds a generator.
            + dump_yaml({slug: data})
        )
        out_path.write_bytes(content.encode("utf-8"))
        # `contested` is the count of Mode B identities NO evidence could settle, withheld by
        # add_enrich rather than resolved by the bridge. It should stay at 0 for a brand whose
        # bridge disambiguates (monument by code, gsw by routing its own refusals) and for one
        # whose collisions are Mode A (vallejo -- an ambiguous catalog key the store's skus
        # route correctly, so nothing is withheld). scale75's 1 is the only one left.
        contested = f" contested={len(harvest.contested)}" if harvest.contested else ""
        print(
            f"{slug}: enrich={len(harvest.enrich)} additions={len(harvest.additions)} "
            f"candidates={len(data.get('candidates') or [])}{contested}"
        )


if __name__ == "__main__":
    main()
