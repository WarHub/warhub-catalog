# tools/acquisition/tests/test_paint_weight.py
"""Products sold by MASS: the population, the two assertions, and the decoy that must stay out.

WHAT WAS ACTUALLY BROKEN. `volumeMl` was the only net-contents field either catalog had, and
nothing in the write path could decline to fill it: `VolumeRule` took a non-nullable `int VolumeMl`
and a non-nullable `string Packaging`, `VolumeEnricher` wrote both unconditionally, and all three
merges downstream (`BarcodeEnricher`, `OverrideApplier.Apply`, `PaintRecordAdapter.Merge`) were
`incoming ?? current` coalesces that can replace a value but never withdraw one. So the pipeline
was structurally incapable of saying "this is not measured in millilitres", and the two Green Stuff
World foam-primer tubs published `volumeMl: 17, container: dropper` -- a figure and a vessel both
inherited wholesale from the brand-wide GSW row at VolumeTable.cs:154. Adding a `weightG` field
alone would have fixed NOTHING visible: the 17 is committed to the archive, and any one of those
three coalesces re-supplies it forever. The field plus the clearing rule (Models/NetContents.cs) is
the change; this module guards the data half of it.

THE POPULATION IS 5 ROWS, MEASURED, NOT ESTIMATED -- 2 paint records and 3 product rows (2 distinct
products), across 8,547 paint records, 22,529 products and 31,076 catalog names, 2026-08-06. The
brief that commissioned this expected "dry pigments, weathering powders, basing sands, texture
pastes and modelling putties" to be a large hidden set. In this corpus they are not: of 317 paint
records in pigment/powder/paste/putty/sand/glue-named sets, 3 state a volume and ZERO state a mass;
VolumeTable.cs:51 already prices Vallejo `Pigment FX` at 30 ml in a jar; Mantic sells 5 of its 6
Colour Forge basing sands at 275 ml and only Fine Grit at 400 g. Miniature-hobby dry goods are sold
by jar volume. The change is worth making as a CONTRACT fix, not as a repair, and this module pins
the population so nobody re-sizes the work on the old premise.

THE MATCHING RULE HAS FOUR CLAUSES AND ALL OF THEM ARE LOAD-BEARING. The obvious `\\d+\\s?g\\b`
is unusable in both directions at once: measured over all 31,076 catalog names it returns 11 hits
of which 8 are junk (`Bf 109G Ace`, `2G Proxies`, `SIGNATURE SET - JOSEDAVINCI 3G`, ...) AND it
misses both records that matter, because `250gr` has no word boundary after the `g`. `_MASS_RE`
below plus `_mass_g` is the rule that survives every one of those; `TestTheRuleItself` keeps it
honest against the named traps rather than trusting the count.

TWO LEGITIMATE ARCHIVE STATES, the pattern test_paint_overrides_gsw_dips.py established and
test_paint_volume_gsw.py reuses. Only the C# paint tool writes data/paints/brands/*.yaml and the
commit adding this does not run it, so before that run the two tubs still say `volumeMl: 17,
container: dropper` and after it they say `weightG: 250` and nothing else. Both endpoints pass
here. The states in BETWEEN are what this rejects -- above all `weightG: 250` sitting beside a
surviving `volumeMl: 17`, which is precisely what shipping the field without the clearing rule
would have produced.
"""
import json
import re
from functools import cache
from pathlib import Path

import pytest
import yaml

from warhub_acquisition.models.catalog import CanonicalProduct
from warhub_acquisition.resolve.attributes import _HINT_FIELDS

REPO_ROOT = Path(__file__).resolve().parents[3]
PAINT_BRANDS = REPO_ROOT / "data/paints/brands"
PRODUCTS = REPO_ROOT / "data/catalog/products"
OVERRIDES = REPO_ROOT / "data/paints/overrides.yaml"
EVIDENCE = REPO_ROOT / "data/evidence/products"
PAINT_SCHEMA = REPO_ROOT / "tools/WarHub.Catalog.Publish/schema/paint-catalog.json"
PRODUCT_SCHEMA = REPO_ROOT / "tools/WarHub.Catalog.Publish/schema/product-catalog.json"

SLUG = "green-stuff-world"

# The pre-change state of the two tubs, named rather than inlined: "still says the table default"
# is a legitimate state until the paint tool next runs, not a magic number.
TABLE_DEFAULT_ML = 17
TABLE_DEFAULT_CONTAINER = "dropper"

# The whole weight-sold population, measured 2026-08-06. Listed so a change in it is a test
# failure with a name attached rather than a silent drift in a count.
WEIGHT_SOLD_PAINTS = {
    "Foam Primer and Coat - Black 250gr|Primer": 250,
    "Foam Primer and Coat - Grey 250gr|Primer": 250,
}
WEIGHT_SOLD_PRODUCTS = {
    "games-workshop/80219999043": 15,
    "games-workshop/99219999043": 15,
    "mantic-games/colour-forge-basing-sand-fine-grit-400g": 400,
}

# (1) the digit run is not preceded by a letter or digit -- kills `Bf109G`, `3G`;
# (2) the unit is not followed by any letter, accented ones included -- kills `Grün`, `Grit`;
# (3) enforced separately in _mass_g: the token is terminal or bracket-closed -- kills
#     `Bf 109G Ace`, `Messerschmitt Bf 109G squadron`;
# (4) also in _mass_g: a BARE single-letter unit must be lowercase `g` -- kills `... 3G`.
_MASS_RE = re.compile(r"(?<![A-Za-z0-9])(\d+)\s*(g|gr|gram|grams)(?![^\W\d_])", re.IGNORECASE)


def _mass_g(name: str) -> int | None:
    """Net mass in grams stated by a product NAME, or None. See the four clauses above."""
    for match in _MASS_RE.finditer(name):
        unit = match.group(2)
        if len(unit) == 1 and unit != "g":  # clause (4): `3G` is a signature set, not 3 grams
            continue
        tail = name[match.end():].strip()
        if tail and not tail.startswith((")", "]", "}")):  # clause (3)
            continue
        return int(match.group(1))
    return None


def _yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# Cached: the three corpora are 8,547 + 22,529 + 55,096 rows and every class below re-reads them.
# Uncached this module ran ~6 minutes on its own, which is how a guard stops being run.
@cache
def _paint_records():
    if not PAINT_BRANDS.is_dir():
        pytest.skip("data/paints/brands not present")
    out = []
    for path in sorted(PAINT_BRANDS.glob("*.yaml")):
        doc = _yaml(path)
        for record in doc.get("paints") or []:
            out.append((doc.get("brandSlug") or path.stem, record))
    return out


@cache
def _products():
    if not PRODUCTS.is_dir():
        pytest.skip("data/catalog/products not present")
    return [product for path in sorted(PRODUCTS.glob("*.yaml"))
            for product in _yaml(path).get("products") or []]


@cache
def _observation_hints():
    """`source-id -> list of hint dicts`, read once for the whole module."""
    if not EVIDENCE.is_dir():
        pytest.skip("data/evidence/products not present")
    out = {}
    for path in sorted(EVIDENCE.glob("*/observations.jsonl")):
        out[path.parent.name] = [
            json.loads(line).get("hints") or {}
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
    return out


def _key(record):
    return f"{record['name']}|{(record.get('details') or {}).get('set') or ''}"


@cache
def _weight_overrides():
    """`{Name}|{Set}` -> weightG, the hand assertions in the green-stuff-world section."""
    if not OVERRIDES.exists():
        pytest.skip("data/paints/overrides.yaml not present")
    section = _yaml(OVERRIDES).get(SLUG) or {}
    return {k: v["weightG"] for k, v in section.items() if isinstance(v, dict) and "weightG" in v}


class TestTheRuleItself:
    """Pinned against the named traps, so nobody replaces it with the regex that looks obvious."""

    @pytest.mark.parametrize("name, expected", [
        ("Foam Primer and Coat - Black 250gr", 250),
        ("WH COLOUR PLASTIC GLUE (15g) (NEU)", 15),
        ("Colour Forge Basing Sand – Fine Grit – 400g", 400),
        # every real trap in the corpus, measured 2026-08-06
        ("Jagdgeschwader 52 (JG 52) Bf109G Squadron", None),
        ("Messerschmitt Bf 109G Ace: Erich Hartmann", None),
        ("Messerschmitt Bf 109G squadron", None),
        ("Infinity: Aleph Posthumans, 2G Proxies", None),
        ("SIGNATURE SET – JOSEDAVINCI 3G", None),
        ("Ral 6007 Grün", None),
        ("Colour Forge Basing Sand – Fine Grit – 275ml", None),
    ])
    def test_the_four_clauses_hold(self, name, expected):
        assert _mass_g(name) == expected

    def test_the_obvious_regex_is_wrong_in_both_directions(self):
        """Why the rule is not one line. It over-matches AND under-matches simultaneously.

        Under-matching is the half that would be invisible: `250gr` has no word boundary after the
        `g`, so the naive pattern silently misses both records this whole change exists for while
        confidently reporting eight aircraft and three signature sets.
        """
        naive = re.compile(r"\d+\s?g\b", re.IGNORECASE)
        assert naive.search("Foam Primer and Coat - Black 250gr") is None
        assert naive.search("Messerschmitt Bf 109G squadron") is not None


class TestThePopulationIsWhatTheChangeWasSizedFor:
    """5 rows, 4 physical products, 3 manufacturers -- and not one weight-sold RANGE."""

    def test_the_paint_archive_holds_exactly_the_two_known_records(self):
        found = {_key(r): _mass_g(r["name"]) for _brand, r in _paint_records() if _mass_g(r["name"])}
        assert found == WEIGHT_SOLD_PAINTS, (
            "the weight-sold paint population moved. A NEW row here is not a failure of this "
            "repo, it is a record that needs a `weightG:` assertion in data/paints/overrides.yaml "
            "and the same volume-clearing treatment as the two tubs"
        )

    def test_the_product_catalog_holds_exactly_the_three_known_rows(self):
        found = {p["id"]: _mass_g(p["name"]) for p in _products() if _mass_g(p["name"])}
        assert found == WEIGHT_SOLD_PRODUCTS

    def test_no_set_is_weight_sold_as_a_whole(self):
        """Why no VolumeTable row carries a WeightG and none should be added speculatively.

        A per-(brand, set) constant is only honest when the whole set shares it. Both weight-sold
        paints sit in Green Stuff World `Primer`, which also holds nine millilitre bottles -- so a
        `Primer` weight row would stamp grams onto them, the mirror image of the bug being fixed.
        """
        by_set = {}
        for _brand, record in _paint_records():
            set_name = (record.get("details") or {}).get("set") or ""
            by_set.setdefault(set_name, []).append(record["name"])
        for key in WEIGHT_SOLD_PAINTS:
            set_name = key.rsplit("|", 1)[1]
            members = by_set[set_name]
            by_mass = [n for n in members if _mass_g(n)]
            assert len(by_mass) < len(members), (
                f"set {set_name!r} is now entirely weight-sold ({len(members)} members) -- a "
                "VolumeTable row with a WeightG is now the right home for it, and these per-record "
                "overrides should be retired in its favour"
            )


class TestEveryAssertionIsDerivedFromTheRecordsOwnName:
    """The values are re-derived here on every run, so they are single-authored but not unchecked.

    This is weaker evidence than the 15 millilitre assertions beside them in overrides.yaml, which
    join each record's own `ean` to `hints.ml` in the manufacturer's observations, and it is worth
    being explicit about why: there is no gram sibling to join against. `_ML_RE`
    (sitemap_sd_paints.py) is the only size parser in the Green Stuff World strategy and it looks
    for `ml` alone, so both tubs carry `hints: {category, categorySlug, reference}` and no size at
    all. The NAME is the same second signal that agreed with the evidence 79/79 on the millilitre
    half; the manufacturer wrote it, and `250gr` is not ambiguous.
    """

    def test_each_assertion_names_exactly_one_committed_record(self):
        """`OverrideApplier.Apply` looks the key up ordinally: a typo is a silent no-op."""
        keys = [_key(r) for _brand, r in _paint_records()]
        missing = {k: keys.count(k) for k in _weight_overrides() if keys.count(k) != 1}
        assert not missing, f"weight-assertion keys naming other than one record: {missing}"

    def test_each_asserted_mass_is_the_one_that_records_own_name_states(self):
        by_key = {_key(r): r for _brand, r in _paint_records()}
        wrong = []
        for key, asserted in _weight_overrides().items():
            record = by_key.get(key)
            if record is None:
                continue  # reported by the test above
            stated = _mass_g(record["name"])
            if stated != asserted:
                wrong.append((key, f"asserts {asserted} g", f"name states {stated}"))
        assert not wrong, f"weight assertions the record's own name does not support: {wrong}"

    def test_the_assertions_are_neither_short_nor_long_of_the_population(self):
        """Both directions, because under- and over-reach fail differently and both silently."""
        assert set(_weight_overrides()) == set(WEIGHT_SOLD_PAINTS), (
            "a record whose name states a mass with no `weightG:` keeps publishing an inherited "
            "millilitre figure forever, and a `weightG:` on a record whose name states no mass is "
            "an invented net content"
        )

    def test_no_weight_assertion_moves_a_barcode(self):
        """Same claim the volume block makes: correcting contents must not become re-barcoding."""
        section = _yaml(OVERRIDES).get(SLUG) or {}
        offenders = {k: sorted(v) for k, v in section.items()
                     if "weightG" in v and ("ean" in v or "additionalEans" in v)}
        assert not offenders, f"weight assertions also asserting a barcode: {offenders}"


class TestTheArchiveIsInOneOfTheTwoLegitimateStates:
    """Before the paint tool runs, and after it. Nothing in between."""

    def test_each_weight_sold_record_either_still_says_17ml_or_says_only_its_mass(self):
        by_key = {_key(r): r for _brand, r in _paint_records()}
        for key, mass in WEIGHT_SOLD_PAINTS.items():
            details = (by_key[key].get("details") or {})
            before = (details.get("volumeMl"), details.get("container"), details.get("weightG"))
            assert before in (
                (TABLE_DEFAULT_ML, TABLE_DEFAULT_CONTAINER, None),  # tool not yet re-run
                (None, None, mass),                                  # tool re-run
            ), (
                f"{key} is in neither legitimate state: {before}. The state worth naming is "
                f"`weightG: {mass}` sitting BESIDE a surviving `volumeMl: {TABLE_DEFAULT_ML}` -- "
                "that is what adding the field without the NetContents clearing rule produces, "
                "and it is a record claiming to be two sizes at once"
            )

    def test_no_other_paint_record_gained_a_weight(self):
        """The 8,545 genuinely volume-sold records must be untouched by this change."""
        strays = {_key(r) for _brand, r in _paint_records()
                  if (r.get("details") or {}).get("weightG") is not None
                  and _key(r) not in WEIGHT_SOLD_PAINTS}
        assert not strays, f"records carrying a mass nothing in this repair asserted: {strays}"

    def test_the_product_side_gained_the_capability_and_not_a_value(self):
        """Its three rows carry no volume, so unlike the paint side nothing false is published.

        They are deliberately NOT asserted: `data/catalog/products/*.yaml` is generated by
        `warhub-data resolve` from evidence, and the honest way for a mass to arrive there is a
        source emitting a `weightG` hint, not a hand-typed figure in a generated file. Games
        Workshop's own register says `15g` on both glue SKUs while ret-gamenerdz names the same
        product `(15ml)` under a third barcode (5011921259304), so there is a live disagreement to
        settle first -- recorded here rather than resolved silently.
        """
        by_id = {p["id"]: p for p in _products()}
        for product_id in WEIGHT_SOLD_PRODUCTS:
            assert by_id[product_id].get("volumeMl") is None, (
                f"{product_id} now claims a volume as well as naming a mass -- the product side "
                "had an absence, not an error, and that has changed"
            )

    def test_the_canonical_product_model_accepts_a_mass(self):
        """extra='forbid', so this fails loudly if the field is ever dropped from the model."""
        product = CanonicalProduct.model_validate(
            {"id": "x/1", "name": "n", "manufacturer": "x", "status": "current",
             "firstSeen": "2026-08-06", "weightG": 15})
        assert product.weightG == 15
        assert product.volumeMl is None  # siblings, not alternatives


class TestTheGrossShippingWeightStaysOut:
    """The trap that would have been far worse than the bug: 1,843 records instead of 2.

    `hints.grams` is Shopify's `variant.grams`, the weight of the parcel. It is already load-bearing
    with that meaning -- gen_paint_harvest.py uses TAP_SINGLE_MAX_GRAMS = 130 as a singles-vs-sets
    discriminator -- and wiring it to `weightG` would have every 22 ml Pro Acryl bottle claiming to
    contain 28 g and every Scale75 accessory claiming 1 g.
    """

    def _grams(self):
        return {source: [h["grams"] for h in hints if "grams" in h]
                for source, hints in _observation_hints().items()
                if any("grams" in h for h in hints)}

    def test_grams_is_not_a_net_contents_hint(self):
        assert "weightG" in _HINT_FIELDS, (
            "the product resolver no longer carries weightG, so a source emitting the hint would "
            "be silently dropped"
        )
        assert "grams" not in _HINT_FIELDS, (
            "`grams` is Shopify gross shipping weight on 1,843 observations. In _HINT_FIELDS it "
            "would land in CanonicalProduct.weightG and fabricate net contents on all of them"
        )

    def test_the_grams_values_are_visibly_not_net_contents(self):
        """The demonstration, not the assertion of a rule -- so the reason survives the reasoner.

        One source's range spanning three orders of magnitude over a catalogue of 18-22 ml bottles
        is only explicable as parcel weight: measured 2026-08-06, mfr-scale75 runs 1 g (`ALUMINIUM`)
        to 2450 g (`DR FLOWS PAINT CASE`) and mfr-turbodork 28 g to 34,019 g (a full display rack).
        """
        grams = self._grams()
        assert grams, "no source carries a grams hint any more; this guard is now vacuous"
        for source, values in grams.items():
            assert max(values) > 1000, (
                f"{source}'s grams hint no longer looks like a shipping weight (max "
                f"{max(values)}) -- re-read the extractor before assuming it is still gross"
            )

    def test_no_source_emits_a_weight_hint_today(self):
        """So the five rows above are the whole story and nothing is quietly flowing behind them.

        When a strategy does start emitting `weightG` this fails, and that is the moment to check
        it is a stated NET content off a label and not a `grams` field renamed.
        """
        emitting = {source for source, hints in _observation_hints().items()
                    if any("weightG" in h for h in hints)}
        assert not emitting, f"sources now emitting a weightG hint -- verify it is net: {emitting}"


class TestBothPublishedSchemasCarryTheField:
    """A field that reaches the archive but not the published documents is not support."""

    @pytest.mark.parametrize("schema_path, definition, minimum", [
        (PAINT_SCHEMA, "paint", None),
        (PRODUCT_SCHEMA, "product", 1),
    ])
    def test_weightG_is_published_beside_volumeMl(self, schema_path, definition, minimum):
        if not schema_path.exists():
            pytest.skip(f"{schema_path.name} not present")
        properties = json.loads(schema_path.read_text(encoding="utf-8"))["$defs"][definition]["properties"]
        assert "volumeMl" in properties, "volumeMl vanished; weightG is defined relative to it"
        assert properties["weightG"]["type"] == "integer"
        # Each side keeps its OWN convention rather than being unified in this change: the product
        # schema constrains volumeMl with `minimum: 1` and the paint schema does not.
        assert properties["weightG"].get("minimum") == properties["volumeMl"].get("minimum") == minimum
