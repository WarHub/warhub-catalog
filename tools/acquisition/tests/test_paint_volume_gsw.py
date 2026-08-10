# tools/acquisition/tests/test_paint_volume_gsw.py
"""Green Stuff World's per-record pot sizes, re-derived from the manufacturer's own evidence.

THE BUG THIS EXISTS FOR. `VolumeTable.cs` held one brand-wide rule for Green Stuff World --
`new("Green Stuff World", null, 17, "dropper")` -- and `VolumeEnricher.Enrich` writes both fields
unconditionally (VolumeEnricher.cs:26-30), so every GSW record published `volumeMl: 17,
container: dropper` no matter what it was. Measured 2026-08-06 by joining each committed record's
own `ean` to data/evidence/products/mfr-greenstuffworld/observations.jsonl on `hints.ml`: 412
records, 400 with an ean, 400 joining, 158 of those joins carrying an ml hint, and 79 of the 158
CONTRADICTING the 17 -- 240 ml x30, 30 ml x20, 400 ml x18, 60 ml x11. Eighteen of them are 400 ml
aerosol cans calling themselves droppers.

The repair is a SPLIT, and this module is what makes the split safe:

  * 64 are five volume-uniform sets and became three per-set rows in VolumeTable.cs. Durable --
    every run re-applies them -- but nothing in the repo ever CHECKS them against the evidence,
    which is precisely how the brand-wide 17 survived this long.
  * 15 sit in Primer / Varnish / Blackest Black, which are mixed-volume sets no constant can
    express, and became per-record `volumeMl` assertions in data/paints/overrides.yaml. Exact, but
    fe4a2dd had to record that a hand override has one asserter and no regeneration re-confirms it.

Both weaknesses are the same weakness -- a value nobody re-derives -- so the guard is deliberately
MECHANISM-BLIND. It reads the committed archive and the evidence and asks whether they agree; it
does not care, and mostly cannot tell, which of the two mechanisms produced any given figure. That
is why it covers the table half as well as the overrides half, and why it would have failed on the
day the brand-wide rule was written.

THE SPLIT ITSELF IS DERIVED, NOT LISTED. `TestTheSplitIsWhereTheEvidencePutsIt` recomputes which
sets are volume-uniform (a constant CAN describe them, so VolumeTable is the durable home) and
which are mixed (a constant is wrong by construction, so a per-record assertion is the only honest
one), and demands the override block be exactly the second group. So the boundary moves on its own
when the range does: the day GSW ships a second Flexible size, `Flexible` becomes mixed and this
fails until its records are asserted by hand instead.

TWO LEGITIMATE STATES, the pattern test_paint_overrides_gsw_dips.py established. Only the paint
tool writes data/paints/brands/green-stuff-world.yaml and the commit adding this does not run it,
so before that run the 79 still say 17 and after it they say their evidence figure. Assertions here
accept both endpoints and reject the states in between.

WHAT IS NOT COVERED, stated so the coverage is not overread: 254 of the 412 records have no
`hints.ml` to join against (the hint is on 158 of 477 observation rows) and 12 carry no ean at all.
This module can neither confirm nor deny their 17. `Foam Primer and Coat - Black/Grey 250gr` were
the two known-wrong members of that group -- sold by weight, still publishing 17 ml. They are now
covered by test_paint_weight.py instead, through a `weightG:` assertion rather than a millilitre
one: the answer was a contract change (the write path could not say "no volume" at all), not a
figure this module could have found, and there is no gram hint in the evidence to join against.
The only trace of them here is the container assertion at the bottom, which now has to accept a
weight-sold record carrying NO container at all.
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
OBSERVATIONS = REPO_ROOT / "data/evidence/products/mfr-greenstuffworld/observations.jsonl"
ARCHIVE = REPO_ROOT / "data/paints/brands/green-stuff-world.yaml"
OVERRIDES = REPO_ROOT / "data/paints/overrides.yaml"

SLUG = "green-stuff-world"

# The brand-wide VolumeTable constant these records used to publish, and still do until the paint
# tool runs. Named rather than inlined because "still says the table default" is a legitimate
# pre-tool state, not a magic number.
TABLE_DEFAULT_ML = 17
TABLE_DEFAULT_CONTAINER = "dropper"

# The reach measured 2026-08-06. A floor, not an equality -- the archive grows -- because the
# failure worth catching is this guard quietly shrinking toward vacuity.
JOINS_WITH_AN_ML_HINT = 158

# The three sets whose per-set VolumeTable row also asserts `container: spray`, and the
# categorySlugs the evidence files them under. Both halves are re-checked below, not trusted.
SPRAY_SETS = {"Spray Primer", "Chameleon Spray", "Chrome Spray"}
SPRAY_SLUGS = {"colour-primers-spray", "colorshift-chameleon-spray", "chrome-spray-paint"}


def _yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _archive():
    if not ARCHIVE.exists():
        pytest.skip("green-stuff-world archive not present")
    return _yaml(ARCHIVE).get("paints") or []


def _by_ean():
    if not OBSERVATIONS.exists():
        pytest.skip("mfr-greenstuffworld evidence not present")
    rows = [json.loads(line) for line in
            OBSERVATIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {str(o["ean"]): o for o in rows if o.get("ean")}


def _volume_overrides():
    """`{Name}|{Set}` -> volumeMl, the hand assertions in the green-stuff-world section."""
    if not OVERRIDES.exists():
        pytest.skip("data/paints/overrides.yaml not present")
    section = _yaml(OVERRIDES).get(SLUG) or {}
    return {k: v["volumeMl"] for k, v in section.items() if "volumeMl" in v}


def _key(record, details):
    return f"{record['name']}|{details.get('set') or ''}"


def _judged():
    """(key, set, committed volumeMl, evidenced ml) for every record its own barcode describes.

    The join is the record's OWN `ean` against the observation publishing it -- exact, not a name
    match -- so each row is the manufacturer describing this exact SKU and nothing weaker.
    """
    by_ean = _by_ean()
    out = []
    for record in _archive():
        details = record.get("details") or {}
        row = by_ean.get(str(record.get("ean") or ""))
        if row is None:
            continue
        hinted = (row.get("hints") or {}).get("ml")
        if hinted is None:
            continue
        out.append((_key(record, details), details.get("set"), details.get("volumeMl"), hinted))
    return out


def _volumes_by_set(judged):
    grouped = defaultdict(set)
    for _key_, set_name, _committed, hinted in judged:
        grouped[set_name].add(hinted)
    return grouped


class TestTheEvidenceStillSaysWhatTheRepairWasBuiltOn:
    """The premises. If these move, the repair's arithmetic is stale and its values may be too."""

    def test_every_committed_barcode_still_joins_an_observation(self):
        by_ean = _by_ean()
        unjoined = [r["name"] for r in _archive()
                    if r.get("ean") and str(r["ean"]) not in by_ean]
        assert not unjoined, (
            "committed records whose ean is in no observation -- the join underpinning every "
            f"assertion in this module is no longer total: {unjoined[:5]}"
        )

    def test_the_guard_still_reaches_as_far_as_it_was_designed_to(self):
        reach = len(_judged())
        assert reach >= JOINS_WITH_AN_ML_HINT, (
            f"only {reach} records still join an ml hint, down from {JOINS_WITH_AN_ML_HINT} "
            "measured 2026-08-06 -- this guard now checks less than it was built to, and the "
            "shrinkage is silent everywhere else"
        )

    def test_the_records_own_name_agrees_with_the_evidence_wherever_it_speaks(self):
        """The second, independent signal, which agreed on 79/79 with no abstentions.

        It is why the repair could be made at all: a store title and a store `ml` hint are not the
        same claim, and both saying 240 is much stronger than either alone. A disagreement here is
        not a test bug -- it means one of the two signals has drifted and every figure asserted
        anywhere in this repair needs re-deriving before it can be trusted again.
        """
        disagreed = []
        for key, _set_name, _committed, hinted in _judged():
            stated = re.findall(r"(\d+)\s*ml", key.rsplit("|", 1)[0], flags=re.IGNORECASE)
            if stated and int(stated[-1]) != hinted:
                disagreed.append((key, int(stated[-1]), hinted))
        assert not disagreed, (
            "records whose own name states a volume its barcode contradicts "
            f"(key, name-ml, evidence-ml): {disagreed}"
        )


class TestTheSplitIsWhereTheEvidencePutsIt:
    """Which mechanism owns which record, recomputed from the evidence rather than listed.

    A hand override is the expensive mechanism -- one asserter, and until this module existed
    nothing re-derived it -- so it is spent only where a per-set constant CANNOT be right, and
    everywhere it can be, the durable mechanism has to be the one used.
    """

    def test_the_override_block_is_exactly_the_records_no_constant_can_reach(self):
        """Both directions, because under-reach and over-reach fail differently and both silently.

        A record in a MIXED-volume set whose size differs from the brand-wide default is
        unreachable by any per-set row -- `Gloss Black Primer` ships at 60 ml and at 240 ml under
        two barcodes, so a `Primer` constant is wrong for one of them whichever number it picks --
        and if no override names it, it publishes the default forever with nothing complaining.
        In the other direction an override inside a volume-UNIFORM set is a value that a
        regenerable table row should be asserting instead, paying the single-asserter cost for
        nothing and hiding a table bug behind a hand fix.
        """
        judged = _judged()
        volumes = _volumes_by_set(judged)
        must = {k for k, s, _c, hinted in judged
                if len(volumes[s]) > 1 and hinted != TABLE_DEFAULT_ML}
        must_not = {k for k, s, _c, _h in judged if len(volumes[s]) == 1}
        asserted = set(_volume_overrides())

        assert not (must - asserted), (
            "records in a mixed-volume set whose barcode disagrees with the brand-wide "
            f"{TABLE_DEFAULT_ML} ml default and which no override names -- no per-set row in "
            f"VolumeTable can reach them: {sorted(must - asserted)}"
        )
        assert not (asserted & must_not), (
            "hand assertions on records whose entire set is volume-uniform -- these belong in "
            "VolumeTable.cs, where every run re-applies and this module re-derives them: "
            f"{sorted(asserted & must_not)}"
        )

    def test_every_volume_assertion_names_exactly_one_committed_record(self):
        """`OverrideApplier.Apply` looks the key up ordinally (OverrideApplier.cs:52-55).

        A key matching nothing is a silent no-op, so one mistyped character leaves a record at the
        default volume and reports nothing, anywhere, ever.
        """
        counts = Counter(_key(r, r.get("details") or {}) for r in _archive())
        missing = {k: counts[k] for k in _volume_overrides() if counts[k] != 1}
        assert not missing, (
            "volume-assertion keys naming other than one record -- OverrideApplier silently "
            f"skips them: {missing}"
        )

    def test_every_asserted_volume_is_the_one_that_records_barcode_belongs_to(self):
        """The assertions re-derived from scratch: each must BE its own barcode's `hints.ml`.

        This is the half fe4a2dd could not have: those 33 `volumeMl: 60` lines were generated by a
        join and then left in a hand-edited file where the next editor copies a line and changes
        two digits. From here on the join runs again on every CI pass.
        """
        by_ean = _by_ean()
        by_key = {_key(r, r.get("details") or {}): r for r in _archive()}
        wrong = []
        for key, asserted in _volume_overrides().items():
            record = by_key.get(key)
            if record is None:
                continue  # reported by the test above
            row = by_ean.get(str(record.get("ean") or ""))
            if row is None:
                wrong.append((key, "ean joins no observation", record.get("ean")))
                continue
            hinted = (row.get("hints") or {}).get("ml")
            if hinted != asserted:
                wrong.append((key, f"asserts {asserted} ml", f"barcode {record['ean']} is {hinted}"))
        assert not wrong, f"volume assertions the evidence does not support: {wrong}"

    def test_no_override_asserts_a_barcode(self):
        """Same claim fe4a2dd's block makes, extended to the 15 added beside it.

        An `ean:` here does not replace a barcode, it demotes one: the displaced value is unioned
        back as `additionalEans` (OverrideApplier.cs:83) and `_check_paints` answers a demotion
        with `paint_moved`, exit 0. Correcting a volume must never become correcting a barcode.
        """
        section = _yaml(OVERRIDES).get(SLUG) or {}
        offenders = {k: sorted(v) for k, v in section.items()
                     if "ean" in v or "additionalEans" in v}
        assert not offenders, (
            f"green-stuff-world overrides asserting a barcode rather than a volume: {offenders}"
        )


class TestTheArchiveAgreesWithTheManufacturer:
    """The mechanism-blind guard: whatever wrote a value, it has to match the record's barcode."""

    def test_no_record_publishes_a_volume_that_is_neither_its_barcodes_nor_the_table_default(self):
        """Actively-wrong values, separated from merely-not-yet-applied ones.

        The brand-wide default is the one disagreement with an innocent explanation, and only
        until the paint tool next runs. Any OTHER disagreement means some mechanism asserted a
        figure and got it wrong, which no amount of waiting fixes.
        """
        wrong = [(k, c, h) for k, _s, c, h in _judged()
                 if c != h and c != TABLE_DEFAULT_ML]
        assert not wrong, (
            "records publishing a volume that is neither their barcode's nor the untouched "
            f"brand-wide default (key, published, evidence): {wrong}"
        )

    def test_each_set_a_per_set_row_covers_is_repaired_whole_or_not_at_all(self):
        """A VolumeTable row cannot half-fire, so a partially-repaired set is proof it was not one.

        The five covered sets are volume-uniform, so a row applies one constant to every member at
        once: before the tool every member says the default and after it every member says its
        size. A split inside one set means the value came from somewhere else -- a stray override,
        a harvest addition, a hand edit to the archive -- and that source is unknown and unchecked.
        """
        judged = _judged()
        volumes = _volumes_by_set(judged)
        split = {}
        for set_name, sizes in volumes.items():
            if len(sizes) != 1:
                continue
            (size,) = sizes
            if size == TABLE_DEFAULT_ML:
                continue  # indistinguishable from the default; nothing to observe
            published = {c for k, s, c, _h in judged if s == set_name}
            if published not in ({size}, {TABLE_DEFAULT_ML}):
                split[set_name] = sorted(published, key=lambda v: (v is None, v))
        assert not split, (
            "volume-uniform sets publishing more than one volume -- before the paint tool every "
            f"member says {TABLE_DEFAULT_ML} and after it every member says its evidenced size; "
            f"a mix has a third, unaccounted writer: {split}"
        )

    def test_container_spray_lands_on_the_aerosols_and_nowhere_else(self):
        """The 18 cans, and the 61 records this repair deliberately leaves saying `dropper`.

        Three independent signals pick out the same 18 -- the name contains "Spray", the evidence
        `categorySlug` is one of the three spray lines, and the size is 400 ml -- and the first
        assertion is that they keep picking out the same 18, because `spray` is asserted per SET
        and a set drifting by one member would silently mislabel a bottle as a can.

        The second assertion is the more interesting one. The evidence carries NO packaging signal
        at all (hint keys across all 477 observation rows are only category, categorySlug,
        reference, ml), so `spray` anywhere else would be a guess. A 240 ml Flexible paint keeps an
        almost certainly wrong `dropper` because the committed vocabulary is exactly
        dropper/jar/pot/tin/spray and none of them describes a squeeze bottle -- visibly wrong
        beats confidently wrong, and this pins that decision so it is not quietly reversed.
        """
        by_ean = _by_ean()
        by_name, by_slug, by_set = set(), set(), set()
        containers, weights = {}, {}
        for record in _archive():
            details = record.get("details") or {}
            key = _key(record, details)
            containers[key] = details.get("container")
            weights[key] = details.get("weightG")
            if "spray" in record["name"].lower():
                by_name.add(key)
            if details.get("set") in SPRAY_SETS:
                by_set.add(key)
            row = by_ean.get(str(record.get("ean") or ""))
            if row and (row.get("hints") or {}).get("categorySlug") in SPRAY_SLUGS:
                by_slug.add(key)

        assert by_name == by_slug == by_set, (
            "the three spray signals no longer agree, so the per-set rule now fires on a set the "
            f"evidence does not call an aerosol line. name-only={sorted(by_name - by_slug)} "
            f"slug-only={sorted(by_slug - by_name)} set-only={sorted(by_set - by_slug)}"
        )

        sprayed = {k for k, v in containers.items() if v == "spray"}
        assert sprayed in (set(), by_set), (
            f"`container: spray` is on {len(sprayed)} records but the aerosols are {len(by_set)}. "
            "Before the paint tool none of them says spray and after it all of them do; a mix "
            f"means the row lists a set that is not an aerosol line: {sorted(sprayed ^ by_set)[:5]}"
        )
        # `None` is admissible from 2026-08-06 and only for a weight-sold record: the two 250 g
        # foam-primer tubs had `container: dropper` from the same brand-wide row that gave them
        # `volumeMl: 17`, and a mass assertion now clears the pair (Models/NetContents.cs). The
        # committed vocabulary -- dropper/jar/pot/tin/spray -- has no word for a tub, so "no word
        # for it" is the honest value. Every OTHER record must still be `dropper`, which keeps the
        # decision recorded above (a 240 ml squeeze bottle stays visibly wrong, not confidently
        # wrong) from being quietly reversed by nulling containers wholesale.
        unjustified = {
            key: value for key, value in containers.items()
            if key not in by_set
            and value != TABLE_DEFAULT_CONTAINER
            and not (value is None and weights.get(key) is not None)
        }
        assert not unjustified, (
            "a non-aerosol Green Stuff World record carries a container this repair never "
            f"justified: {unjustified}"
        )
