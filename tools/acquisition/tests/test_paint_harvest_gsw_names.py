# tools/acquisition/tests/test_paint_harvest_gsw_names.py
"""`gsw_clean_name` in scripts/gen_paint_harvest.py, and the archive it renames.

greenstuffworld.com wraps the paint name in marketing prefixes ("Acrylic Color WONKA VIOLET",
"Dipping ink 60 ml - Papyrus DIP") while the catalog keeps bare names, so the bridge strips a
leading-descriptor regex iteratively. Two ways that went wrong, and one test class each:

- IT ERASED THE VOLUME. `\\d+ ?ml` sat in the alternation as a peer of the marketing words, so
  the 17 ml and 60 ml dipping inks -- different skus, different gtin13s, 2.125 vs 3.7375 EUR --
  cleaned to one name. Measured 2026-08-05: 32 (set, cleanedName) collisions that do not exist
  on the raw titles (0).
- IT ATE A PREFIX MID-WORD. The word alternatives carried no trailing `\\b`, so `metallic paint`
  matched 14 characters of "Metallic Paints Set - Colours" and the following `\\s*` matched zero,
  leaving "s Set - Colours" (skus 9910-9912).

The third class is the expensive one. Paint identity is `set|name|productCode|hex` and
`PaintRecordAdapter.Url => null` deliberately disables URL-based rename detection, so an
`aliases:` entry in data/paints/overrides.yaml is the ONLY rename path a paint has. A bare name
change does not rename a record -- CatalogReconciler falls through to "New record" and MINTS one,
stranding the old. TestNoRenameStrandsAnArchiveRecord pins that across EVERY brand, not just this
one, because nothing about the hazard is GSW-specific: it is the shape of any bridge that derives
a name. Verified to be a live tripwire, not a tautology -- deleting the three green-stuff-world
aliases makes it report exactly 3 strandings.

Imported by path: the bridge scripts are not part of the installed package (they run standalone
under `uv run --with pyyaml`), same as test_paint_harvest_price.py.
"""
import importlib.util
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools/acquisition/scripts/gen_paint_harvest.py"
OBSERVATIONS = REPO_ROOT / "data/evidence/products/mfr-greenstuffworld/observations.jsonl"
HARVEST_DIR = REPO_ROOT / "data/paints/harvest"
BRANDS_DIR = REPO_ROOT / "data/paints/brands"
SWATCHES_DIR = REPO_ROOT / "data/paints/swatches"
OVERRIDES = REPO_ROOT / "data/paints/overrides.yaml"


def _load():
    if not SCRIPT.exists():
        pytest.skip("gen_paint_harvest.py not present (package tested outside the monorepo)")
    spec = importlib.util.spec_from_file_location("gen_paint_harvest_gsw_names", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _observations():
    if not OBSERVATIONS.exists():
        pytest.skip("mfr-greenstuffworld evidence not present")
    return [json.loads(line) for line in
            OBSERVATIONS.read_text(encoding="utf-8").splitlines() if line.strip()]


def _yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _normalize(value):
    """NameNormalizer.Normalize, in Python -- NFKC, collapse whitespace, trim quotes, lowercase.

    Deliberately a local copy rather than a call into the C#: this test asserts that the YAML a
    human writes lines up with the key the reconciler computes, and borrowing the very code under
    discussion would assert only that a function equals itself.
    """
    text = unicodedata.normalize("NFKC", value or "")
    text = re.sub(r"\s+", " ", text).strip().strip("'\"")
    return re.sub(r"\s+", " ", text).strip().lower()


def _identity(set_name, name, code, hex_value):
    """PaintRecordAdapter.IdentityKey -- `set|name|productCode|hex`, each part normalized."""
    return "|".join(_normalize(part) for part in (set_name, name, code or "", hex_value or ""))


class TestTheVolumeIsAName:
    """A volume is a distinguishing attribute, not a marketing descriptor."""

    def test_the_two_volumes_of_one_colour_clean_to_different_names(self):
        module = _load()
        assert module.gsw_clean_name("Dipping ink 60 ml - GREEN STONE DIP") != \
            module.gsw_clean_name("Dipping ink 17 ml - Green Stone Dip")

    def test_the_volume_survives_as_a_suffix(self):
        module = _load()
        # Suffix, not prefix: 86 GSW archive records already end in a volume ("Alpha Turquoise
        # 30 ml") purely because the store writes it last in THOSE titles. Emitting "60 ml -
        # Green Stone Dip" would fix the collision and invent a second convention.
        assert module.gsw_clean_name("Dipping ink 60 ml - GREEN STONE DIP") == \
            "Green Stone Dip 60 ml"
        assert module.gsw_clean_name("Dipping ink 17 ml - Green Stone Dip") == \
            "Green Stone Dip 17 ml"

    def test_the_volume_spelling_is_canonical(self):
        # A store retitle from "60ml" to "60 ml" must not read as a rename -- an unaliased
        # rename mints a new archive record and strands the old one.
        module = _load()
        assert module.gsw_clean_name("Dipping ink 60ml - Papyrus DIP") == \
            module.gsw_clean_name("Dipping ink 60 ml - Papyrus DIP") == "Papyrus Dip 60 ml"

    def test_a_title_that_is_only_a_volume_gains_no_leading_space(self):
        module = _load()
        assert module.gsw_clean_name("Dipping ink 60 ml") == "60 ml"

    def test_no_set_and_name_collision_over_the_committed_evidence(self):
        """The 32-collision regression, pinned on the real 477 observations."""
        module = _load()
        groups = defaultdict(list)
        for observation in _observations():
            slug = (observation.get("hints") or {}).get("categorySlug") or ""
            set_name = module.GSW_SET_BY_CATEGORY.get(slug)
            if set_name is None:
                continue
            groups[(set_name, module.gsw_clean_name(observation["name"]))].append(
                str(observation.get("sku") or ""))
        collisions = {key: skus for key, skus in groups.items() if len(skus) > 1}
        assert collisions == {}, f"{len(collisions)} cleaned-name collisions: {collisions}"


class TestAPrefixIsNeverEatenMidWord:
    def test_a_plural_of_a_prefix_word_is_not_stripped(self):
        module = _load()
        # skus 9912 / 9911 / 9910. `metallic paint` used to consume 14 characters of these.
        assert module.gsw_clean_name("Metallic Paints Set - Colours") == \
            "Metallic Paints Set - Colours"
        assert module.gsw_clean_name("Metallic Paints Set - Gold") == "Metallic Paints Set - Gold"

    def test_the_punctuation_alternative_still_fires(self):
        """`[-]` must stay OUTSIDE the word boundary or the whole strip stops working.

        A hyphen followed by a space has no word boundary between them, so `(-)\\b` never fires
        and every "<descriptor> - <Colour>" title keeps its dash and descriptor.
        """
        module = _load()
        assert module.gsw_clean_name("Dipping ink 60 ml - PAPYRUS DIP") == "Papyrus Dip 60 ml"
        assert module.gsw_clean_name("Chrome paint - Antique Gold") == "Antique Gold"

    def test_the_ordinary_marketing_strip_is_unchanged(self):
        module = _load()
        assert module.gsw_clean_name("Acrylic Color WONKA VIOLET") == "Wonka Violet"
        assert module.gsw_clean_name("Dry brush paint - ALPHA TURQUOISE 30 ml") == \
            "Alpha Turquoise 30 ml"


class TestNoRenameStrandsAnArchiveRecord:
    """Every committed addition that renames a record it already owns must carry an alias.

    The strand condition, exactly: the addition's productCode IS in the brand archive, no record
    under that code answers to the addition's (name, set), and no `aliases:` entry maps the
    addition's identity key onto one of those records. That is the case where CatalogReconciler
    step 4 mints a second record for one pot and the first is left with no source that can ever
    reach it again. Additions whose code is absent from the archive are genuinely new paints and
    are skipped -- they are supposed to mint.

    Hex matters here because it is part of the identity key and harvest additions are born
    colour-less: the key the reconciler computes carries whatever SwatchApplier
    ({Name}|{Set}|{ProductCode}) filled in, so this test reads the swatch file the same way the
    C# does. That is also what makes a swatch re-key part of a rename rather than an afterthought.
    """

    @pytest.mark.parametrize("harvest_path", sorted(HARVEST_DIR.glob("*.yaml")),
                             ids=lambda p: p.stem)
    def test_every_renaming_addition_has_an_alias(self, harvest_path):
        slug = harvest_path.stem
        additions = (_yaml(harvest_path).get(slug) or {}).get("additions") or []
        archive_path = BRANDS_DIR / f"{slug}.yaml"
        if not archive_path.exists():
            pytest.skip(f"{slug} has no committed archive yet")
        by_code = defaultdict(list)
        for record in _yaml(archive_path).get("paints") or []:
            by_code[str(record.get("productCode") or "")].append(record)

        swatch_path = SWATCHES_DIR / f"{slug}.yaml"
        swatches = (_yaml(swatch_path).get(slug) or {}) if swatch_path.exists() else {}
        aliases = {_normalize(new): _normalize(old) for new, old in
                   ((_yaml(OVERRIDES).get("aliases") or {}).get(slug) or {}).items()}

        stranded = []
        for addition in additions:
            code = str(addition.get("productCode") or "")
            owners = by_code.get(code)
            if not code or not owners:
                continue  # a genuinely new paint: nothing to strand
            set_name = addition.get("set") or ""
            if any(_normalize(r["name"]) == _normalize(addition["name"])
                   and _normalize((r.get("details") or {}).get("set") or "") == _normalize(set_name)
                   for r in owners):
                continue  # composite key still matches -- no rename at all
            hex_value = (swatches.get(f"{addition['name']}|{set_name}|{code}") or {}).get("hex")
            target = aliases.get(_identity(set_name, addition["name"], code, hex_value))
            if not any(target == _identity((r.get("details") or {}).get("set") or "", r["name"],
                                           code, (r.get("details") or {}).get("hex") or "")
                       for r in owners):
                stranded.append(
                    f"{code}: harvest {addition['name']!r} vs archive "
                    f"{[r['name'] for r in owners]!r} -- no aliases entry for "
                    f"{_identity(set_name, addition['name'], code, hex_value)!r}")
        assert stranded == [], (
            f"{len(stranded)} rename(s) would mint a new {slug} record and strand the old:\n"
            + "\n".join(stranded))

    def test_no_alias_can_erase_an_archived_hex(self) -> None:
        """The trap `data/paints/overrides.yaml` argues against in prose, now pinned.

        `CatalogReconciler` step 3 renames via `PaintRecordAdapter.ApplyRename`, which assigns
        `Hex = fresh.Details.Hex` wholesale. So a HEXLESS alias key (`...|4220|`) pointing at a
        record whose archived hex is non-empty fires exactly when `SwatchApplier` misses -- and
        then overwrites the archived colour with the empty string it just failed to supply. It is
        armed to go off precisely when the thing it was added as insurance against happens.

        The test above cannot see this: it looks up only the ONE key it computes, so a second,
        dangerous alias sitting beside a correct one is never consulted and passes silently. This
        walks every alias instead.

        Legitimate hexless aliases exist -- record 3487 has `hex: ''` in the archive, so
        `Dipping Inks|Green Stone Dip 60 ml|3487|` is correct and must keep passing. The rule is
        narrow on purpose: an alias may omit the hex only when the record it targets HAS no hex,
        OR when the erasure is DECLARED by a `colourless: true` override on that same record.

        THE DECLARED CASE IS NOT A LOOPHOLE, it is the same hazard pointed the other way. A medium
        or varnish has no colour, so the 94 stand-in greys the archive carried for them were the
        error and clearing them is the fix (see PaintRecord.Colourless); the alias exists because
        clearing a hex MOVES the identity, and without it the run mints a hexless twin instead of
        renaming. What the exception requires is that a human wrote the assertion down next to the
        record -- an alias that erases a colour NOBODY declared colourless is still armed, and is
        still what this test is for.

        MATCHING IS ON THE WHOLE IDENTITY, NOT ON THE CODE. It used to compare `productCode` alone,
        which is not identifying when the code is empty: every codeless record in the brand matched
        every codeless alias, so 144 unrelated Army Painter colours were reported against one
        mixing-medium alias. Set and name are part of the key the alias states; use them.
        """
        archives = {p.stem: _yaml(p).get("paints") or [] for p in sorted(BRANDS_DIR.glob("*.yaml"))}
        overrides = _yaml(OVERRIDES)
        armed = []
        for slug, entries in ((overrides.get("aliases") or {})).items():
            declared = {
                key for key, fields in (overrides.get(slug) or {}).items()
                if isinstance(fields, dict) and fields.get("colourless")
            }
            for new_key in entries:
                parts = str(new_key).split("|")
                if len(parts) != 4 or parts[3]:
                    continue  # carries a hex, or is not an identity key -- not this hazard
                set_name, name, code = parts[0], parts[1], parts[2]
                if f"{name}|{set_name}" in declared:
                    continue  # the erasure is asserted on the record itself
                for record in archives.get(slug) or []:
                    details = record.get("details") or {}
                    if (str(record.get("productCode") or "") != code
                            or str(record.get("name") or "") != name
                            or str(details.get("set") or "") != set_name):
                        continue
                    archived_hex = details.get("hex") or ""
                    if archived_hex:
                        armed.append(
                            f"{slug}: alias {new_key!r} omits the hex, but archived record "
                            f"{record['name']!r} (code {code}) holds {archived_hex!r} -- "
                            f"ApplyRename would erase it"
                        )
        assert armed == [], (
            "alias(es) that would destroy an archived colour on rename:\n" + "\n".join(armed)
        )
