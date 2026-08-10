# tools/acquisition/tests/test_paint_harvest_gsw_sets.py
"""The set filter on bridge_gsw's `suffix_match`, and the archive debt it forces.

greenstuffworld.com tells every observation which category it came from, and
GSW_SET_BY_CATEGORY turns that into the archive set an unmatched row MINTS into. Until
2026-08-06 the JOIN ignored it: `suffix_match` took the longest catalog name the store title
ends with, from any set at all. 42 of the 408 rows landed in a set their own category
contradicts.

WHAT THAT COST, and it is not what it looks like. The set-blind join wrote no wrong values into
the harvest -- 11 of its 14 non-umbrella cross-set rows were already refused as contested, and
the other 3 put their own barcode on a record that holds exactly it. What it did was CROWD three
`Fluor Metallic` keys (White, Orange, Yellow) with 3-4 claimants each until `add_enrich`'s
contest refusal fired on all 11, leaving 8 real, currently-sold barcodes held by no paint record
and no product anywhere in the repo.

THREE CLASSES OF TEST, because three different things can regress:

- THE SEMANTICS. The filter must be `Catalog.match_name`'s IN-SET-ONLY rule (:405-414) and not
  the two softer shapes that read as equivalent. A tiebreak (consult sets only when several keys
  match) and a preference (in-set first, unhinted fallback) change 0 of the 408 committed rows
  and home 0 of the 8 orphans, because every one of the 42 bad joins has exactly one key at the
  matched candidate. `test_an_out_of_set_unique_name_does_not_fall_back` is the one that tells
  them apart.
- THE UMBRELLA. greenstuffworld.com's `acrylic-inks` category genuinely spans four archive sets,
  so a strict per-slug filter costs 31 enrich entries and re-mints 28 records that already exist.
  The allow-list must stay wide enough for those and narrow enough to keep `Fluor Metallic` out.
- THE ARCHIVE DEBT. A row that stops enriching a record starts MINTING one, with the same
  barcode -- so a set filter is also a duplicate-barcode generator unless every displaced record
  is retracted. `test_every_displaced_barcode_is_retracted_or_listed` walks that exhaustively
  and pins the three still outstanding by barcode, so the follow-up can only shrink the list.

Imported by path: the bridge scripts are not part of the installed package (they run standalone
under `uv run --with pyyaml`), same as test_paint_harvest_contested.py.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools/acquisition/scripts/gen_paint_harvest.py"
HARVEST = REPO_ROOT / "data/paints/harvest/green-stuff-world.yaml"
ARCHIVE = REPO_ROOT / "data/paints/brands/green-stuff-world.yaml"
OVERRIDES = REPO_ROOT / "data/paints/overrides.yaml"
OBSERVATIONS = REPO_ROOT / "data/evidence/products/mfr-greenstuffworld/observations.jsonl"


def _load():
    if not SCRIPT.exists():
        pytest.skip("gen_paint_harvest.py not present (package tested outside the monorepo)")
    spec = importlib.util.spec_from_file_location("gen_paint_harvest_gsw_sets", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harvest = _load()


def _yaml(path: Path) -> dict:
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _committed() -> dict:
    return _yaml(HARVEST).get("green-stuff-world") or {}


def _observations() -> list[dict]:
    if not OBSERVATIONS.exists():
        pytest.skip("mfr-greenstuffworld evidence not present")
    return [json.loads(line) for line in
            OBSERVATIONS.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def gsw(monkeypatch, tmp_path: Path):
    """Synthetic evidence + catalog for mfr-greenstuffworld, real descriptors.

    `crossover_rule` is lru_cached on the source id, so the descriptor directory is left alone
    (the trap test_paint_harvest_gate.py documents); only the data directories are redirected.
    """
    monkeypatch.setattr(harvest, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(harvest, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(harvest, "STORES_DIR", tmp_path / "stores")
    monkeypatch.setattr(harvest, "OUT_DIR", tmp_path / "out")
    for name in ("evidence", "brands", "stores", "out"):
        (tmp_path / name).mkdir()

    def run(rows: list[dict], paints: list[dict]):
        directory = tmp_path / "evidence" / "mfr-greenstuffworld"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "observations.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        (tmp_path / "brands" / "green-stuff-world.yaml").write_text(
            yaml.safe_dump({"paints": paints}, sort_keys=False), encoding="utf-8")
        return harvest.bridge_gsw()

    return run


def _row(name: str, sku: str, slug: str, ean: str) -> dict:
    return {"name": name, "sku": sku, "ean": ean, "url": f"https://x/{sku}",
            "hints": {"categorySlug": slug}}


def _paint(name: str, set_name: str, ean: str | None = None) -> dict:
    return {"name": name, "details": {"set": set_name, "hex": "#000000"},
            **({"ean": ean} if ean else {})}


# --- the semantics: a FILTER, not a tiebreak and not a preference ------------------------------


class TestTheFilterIsInSetOnly:
    def test_an_out_of_set_unique_name_does_not_fall_back(self, gsw) -> None:
        """The single test that separates a filter from a preference.

        `Sunburst` exists once in the whole catalog, so the unhinted rule (and any
        "in-set first, then brand-wide unique" fallback) matches it. The store says the row is a
        fluorescent paint and the only `Sunburst` is a Chrome one, so the join must be refused
        and the row must MINT into `Fluorescent` instead. A preference would enrich
        `Sunburst|Chrome` and this assertion would read `enrich`.
        """
        out = gsw([_row("Fluor Paint SUNBURST", "1", "fluorescent-acrylic-paints", "1" * 13)],
                  [_paint("Sunburst", "Chrome")])
        assert out.enrich == {}
        assert [(a["name"], a["set"]) for a in out.additions] == [("Sunburst", "Fluorescent")]

    def test_an_in_set_name_still_joins(self, gsw) -> None:
        out = gsw([_row("Fluor Paint SUNBURST", "1", "fluorescent-acrylic-paints", "1" * 13)],
                  [_paint("Sunburst", "Fluorescent")])
        assert list(out.enrich) == ["Sunburst|Fluorescent"]
        assert out.additions == []

    def test_the_filter_runs_before_the_uniqueness_test(self, gsw) -> None:
        """One name in two sets, one of them allowed: the filter must REDUCE the candidate list
        and then find it unique, not see `len(keys) != 1` and refuse. This is the case the 8
        orphans died on -- `White` exists in both `Fluorescent` and `Fluor Metallic`."""
        out = gsw([_row("Fluor Paint WHITE", "1760", "fluorescent-acrylic-paints", "1" * 13)],
                  [_paint("White", "Fluorescent"), _paint("White", "Fluor Metallic")])
        assert list(out.enrich) == ["White|Fluorescent"]

    def test_an_unmapped_category_keeps_the_unhinted_rule(self, gsw) -> None:
        """`gsw_allowed_sets` returns None for a slug that maps to no set, and None means the
        brand-wide-unique rule, matching `Catalog.match_name`'s own None branch. Inert on the
        committed data (an unmapped row cannot mint either -- it goes to candidates), so it is
        pinned here rather than measured there."""
        assert harvest.gsw_allowed_sets("brushes-and-tools") is None
        out = gsw([_row("Acrylic Color SUNBURST", "1", "brushes-and-tools", "1" * 13)],
                  [_paint("Sunburst", "Chrome")])
        assert list(out.enrich) == ["Sunburst|Chrome"]


class TestTheUmbrella:
    def test_acrylic_inks_reaches_its_three_sibling_sets(self, gsw) -> None:
        """The store files Intensity Ink, Wash Ink and Candy Ink Metallic under one category.
        A strict per-slug filter refuses all 28 of those joins on the committed data and re-mints
        them as `Acrylic Inks` additions -- 28 duplicated archive records."""
        rows = [_row("Intensity Ink OCEAN", "1", "acrylic-inks", "1" * 13),
                _row("Wash Ink AETHER BLUE", "2", "acrylic-inks", "2" * 13),
                _row("Candy Ink CRIMSON", "3", "acrylic-inks", "3" * 13)]
        paints = [_paint("Intensity Ink Ocean", "Intensity Ink"),
                  _paint("Wash Ink Aether Blue", "Wash Ink"),
                  _paint("Candy Ink Crimson", "Candy Ink Metallic")]
        out = gsw(rows, paints)
        assert sorted(out.enrich) == ["Candy Ink Crimson|Candy Ink Metallic",
                                      "Intensity Ink Ocean|Intensity Ink",
                                      "Wash Ink Aether Blue|Wash Ink"]
        assert out.additions == []

    def test_the_umbrella_does_not_leak_to_other_categories(self, gsw) -> None:
        """The allow-list is keyed by SLUG, so widening `acrylic-inks` must not widen anything
        else. A dry-brush row may not reach `Wash Ink` just because some other category may."""
        out = gsw([_row("Dry brush paint - AETHER BLUE", "1", "dry-brush-paints", "1" * 13)],
                  [_paint("Aether Blue", "Wash Ink")])
        assert out.enrich == {}
        assert [(a["name"], a["set"]) for a in out.additions] == [("Aether Blue", "Dry Brush")]

    def test_admitting_fluor_metallic_would_barcode_the_wrong_record(self, gsw, monkeypatch):
        """The trap, run rather than argued -- and the proof this suite has teeth.

        Widening the allow-list to admit `Fluor Metallic` for fluorescent-acrylic-paints keeps
        the two currently-correct enrichments (1702/1706) and mints nothing, which is why it is
        tempting. It also UN-CROWDS the three contested keys: the `Fluor Paint` row then joins
        the `Fluor Metallic` record uncontested -- and on the real archive that record is the one
        holding a Transparent Acrylic Ink's barcode, which `PaintRecordAdapter.Merge:25-33` would
        demote into `additionalEans` rather than drop. Five of the eight orphans home; three
        archival lies are minted to do it.
        """
        rows = [_row("Fluor Paint WHITE", "1760", "fluorescent-acrylic-paints", "8" * 13)]
        paints = [_paint("White", "Fluor Metallic", ean="8435646508665")]
        assert gsw(rows, paints).enrich == {}  # the shipped map refuses it

        monkeypatch.setitem(harvest.GSW_UMBRELLA_SETS, "fluorescent-acrylic-paints",
                            {"Fluorescent", "Fluor Metallic"})
        widened = gsw(rows, paints)
        assert list(widened.enrich) == ["White|Fluor Metallic"], (
            "widening no longer reaches the ink-barcoded record -- either the trap is gone or "
            "this test has stopped exercising it")


# --- the committed data ------------------------------------------------------------------------


class TestTheCommittedHarvest:
    # sku -> (barcode, minted key). Every one is a real, currently-sold greenstuffworld.com
    # product whose gtin13 was held by NO paint record and NO product on 2026-08-06.
    ORPHANS = {
        "1701": ("8436574500608", "Yellow|Fluorescent"),
        "1703": ("8436574500622", "Orange|Fluorescent"),
        "1760": ("8436574501193", "White|Fluorescent"),
        "4285": ("8435646516455", "Acrylic Ink Opaque- Osl White|Acrylic Inks"),
        "4288": ("8435646516486", "Acrylic Ink Opaque- Orange|Acrylic Inks"),
        "4294": ("8435646516547", "Acrylic Ink Opaque - Yellow|Acrylic Inks"),
        "5096": ("8435646524566", "Fluor Acrylic Ink - Yellow|Acrylic Inks"),
        "5098": ("8435646524580", "Fluor Acrylic Ink - Orange|Acrylic Inks"),
    }

    def test_every_orphan_barcode_is_carried_by_exactly_one_addition(self) -> None:
        additions = _committed().get("additions") or []
        by_code = {str(a.get("productCode") or ""): a for a in additions}
        missing = []
        for sku, (ean, key) in self.ORPHANS.items():
            addition = by_code.get(sku)
            if addition is None:
                missing.append(f"{sku}: no addition")
                continue
            got = f"{addition.get('name')}|{addition.get('set')}"
            if got != key or addition.get("ean") != ean:
                missing.append(f"{sku}: {got!r} ean={addition.get('ean')!r} "
                               f"(expected {key!r} ean={ean!r})")
        assert missing == [], "unhomed GSW barcodes:\n" + "\n".join(missing)

    def test_no_enrich_entry_crosses_a_set_its_category_disallows(self) -> None:
        """The filter, re-derived from the evidence rather than trusted.

        Every committed enrich entry carries the `sku` that filed it, so the row's own
        categorySlug is recoverable -- and its key's set must be one `gsw_allowed_sets` admits.
        This is what the 42 cross-set joins looked like; 28 of them (the umbrella) still pass.
        """
        slugs = {str(o.get("sku") or ""): (o.get("hints") or {}).get("categorySlug") or ""
                 for o in _observations()}
        bad = []
        for key, entry in (_committed().get("enrich") or {}).items():
            allowed = harvest.gsw_allowed_sets(slugs.get(str(entry.get("sku") or ""), ""))
            if allowed is not None and key.rsplit("|", 1)[1] not in allowed:
                bad.append(f"{key} <- sku {entry.get('sku')} in {slugs.get(str(entry.get('sku')))}")
        assert bad == [], "enrich entries the store's own category contradicts:\n" + "\n".join(bad)

    def test_the_umbrella_joins_are_still_there(self) -> None:
        """28 of them, and a strict filter would have re-minted every one. Counted by set so a
        regression that keeps the total but moves a set is still visible."""
        counts = {"Intensity Ink": 0, "Wash Ink": 0, "Candy Ink Metallic": 0}
        for key in _committed().get("enrich") or {}:
            set_name = key.rsplit("|", 1)[1]
            if set_name in counts:
                counts[set_name] += 1
        assert counts == {"Intensity Ink": 12, "Wash Ink": 8, "Candy Ink Metallic": 8}

    def test_every_contested_candidate_names_a_key_its_own_category_allows(self) -> None:
        """The two passes must filter identically. PASS 1 counts claims and the filing loop acts
        on them, so a pass that joined unfiltered would contest keys the filing loop can never
        reach -- and the rows would be reported as contesting an identity they no longer claim.
        62 candidates carry a contested reason today; every key in them is checkable.
        """
        slugs = {str(o.get("sku") or ""): (o.get("hints") or {}).get("categorySlug") or ""
                 for o in _observations()}
        bad = []
        for candidate in _committed().get("candidates") or []:
            reason = str(candidate.get("reason") or "")
            if not reason.startswith("contested identity ("):
                continue
            key = reason[len("contested identity ("):reason.index(")")]
            allowed = harvest.gsw_allowed_sets(slugs.get(str(candidate.get("sku") or ""), ""))
            if allowed is not None and key.rsplit("|", 1)[1] not in allowed:
                bad.append(f"sku {candidate.get('sku')}: contested {key!r}")
        assert bad == [], (
            "PASS 1 and the filing loop disagree about which sets a row may join:\n"
            + "\n".join(bad))


# --- the archive debt the filter creates -------------------------------------------------------


def test_every_displaced_barcode_is_retracted_or_listed() -> None:
    """A set filter is a duplicate-barcode generator, and this is the only thing that says so.

    When a row stops enriching a record and starts minting one, the mint carries the SAME
    barcode: the archive record keeps it (nothing in the pipeline removes a barcode -- an `ean:`
    override unions the displaced primary back in at OverrideApplier.cs:83 and so does
    `PaintRecordAdapter.Merge:31-33`) and the new record is born with it. `report --ean-guard`
    cannot see this: its no-finding rule keys on (brand, role) (report.py:229), so one barcode on
    two records of one brand in the primary role is silent.

    So the rule has to be stated here. Every addition that would MINT a record whose ean is
    already on a different archive record must be answered by a `retract:` key naming that
    record.

    THE `deferred` DICT BELOW IS NOW EMPTY, and the reason is worth keeping. It once held three
    barcodes that a `Fluor Metallic` record and a newly minted `Acrylic Inks` record shared,
    deferred with the rest of the set-naming question. That question is settled -- `Fluor
    Metallic` is not a Green Stuff World range, it is the upstream grouping label for GSW's own
    `Fluor Paint` line -- and all seven records are retracted, so the three duplicates are gone.
    The dict stays as the mechanism because the NEXT such deferral needs somewhere honest to
    live; it is not a permanent excuse, and an entry here should read as a debt with an owner.

    "Would mint" is `HarvestApplier.AppendAdditions`' own skip key, `{Name}|{Set}|{ProductCode}`
    (HarvestApplier.cs:124-134): 161 of the 175 committed additions are prior additions the
    ratchet re-emits every run, and each of those IS the archive record holding its barcode. Test
    that without the skip key and it reports 161 false collisions.

    Live tripwire, measured 2026-08-06: of the 14 additions that would actually mint, exactly 6
    carry a barcode an archive record already holds, and every one is answered by a `retract:`
    key -- delete any of them and this test names it. (An earlier draft said "three are answered
    ... the other three are deferred". That stopped being true once those three Acrylic Inks
    records landed in the archive, at which point the ratchet skip short-circuits before the
    deferred check ever runs, so emptying the dict changed no result. The claim was corrected in
    overrides.yaml but not here, which is exactly how a reader ends up trusting a dead comment.)
    """
    # ean -> the archive record wearing it, and the record this run mints for it. EMPTY on
    # purpose: the three that lived here (8435646508665 / 516332 / 516417, the Fluor Metallic
    # White/Orange/Yellow records) are retracted, so the duplication is declared away rather than
    # tolerated. Kept as the mechanism for the next one -- see the docstring.
    deferred: dict[str, str] = {}
    records = _yaml(ARCHIVE).get("paints") or []
    holders: dict[str, list[dict]] = {}
    for record in records:
        for ean in [record.get("ean"), *(record.get("additionalEans") or [])]:
            if ean:
                holders.setdefault(str(ean), []).append(record)

    retracted = {str(k).strip().lower() for k in
                 ((_yaml(OVERRIDES).get("retract") or {}).get("green-stuff-world") or [])}

    def identity(record: dict) -> str:
        details = record.get("details") or {}
        return "|".join([str(details.get("set") or ""), str(record["name"]),
                         str(record.get("productCode") or ""),
                         str(details.get("hex") or "")]).strip().lower()

    minted = {f"{r['name']}|{(r.get('details') or {}).get('set') or ''}|"
              f"{r.get('productCode') or ''}".lower() for r in records}

    unanswered = []
    for addition in _committed().get("additions") or []:
        ean = str(addition.get("ean") or "")
        skip_key = (f"{addition.get('name')}|{addition.get('set')}|"
                    f"{addition.get('productCode') or ''}").lower()
        if skip_key in minted:
            continue  # the ratchet re-emitting a record it already minted -- same record
        for record in holders.get(ean, []):
            if identity(record) in retracted or ean in deferred:
                continue
            unanswered.append(
                f"{ean}: addition {addition.get('name')}|{addition.get('set')} "
                f"(code {addition.get('productCode')}) duplicates archive record "
                f"{(record.get('details') or {}).get('set')}|{record['name']}")
    assert unanswered == [], (
        "additions that would put one barcode on two records, with no retraction to answer "
        "them:\n" + "\n".join(unanswered))
