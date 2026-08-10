# tools/acquisition/tests/test_paint_harvest_contested.py
"""One catalog identity, two store products: `add_enrich` in scripts/gen_paint_harvest.py.

`{Name}|{Set}` is the whole vocabulary a harvest entry has for saying which paint it means, so a
store that ships two products under one catalog name has no way to file both. Before this change
`add_enrich` merged them first-wins (`if v not in (None, "") and k not in entry`) and the second
product's ean, image, price and sku vanished with no record anywhere -- the winner picked by row
order in observations.jsonl. Baseline measured for THIS change (not supplied by the task brief,
which quoted only green-stuff-world's 39 discarded rows): running HEAD's generator with HEAD's
harvest files in place, so the `previous_addition_codes` ratchet sees what HEAD saw, gives 43
keys claimed more than once and 48 discarded rows -- gsw 34/39, vallejo 4/4, monument 4/4,
scale75 1/1, and 0/0 for the other five. Regenerate the tree first and monument reads 0/0,
because its four rows have by then become prior additions; that trap is why the figure is
written down with its method.

THOSE 43 KEYS ARE TWO DIFFERENT FAILURES and the rule treats them differently:

- MODE B, one catalog paint and N store products (gsw 34, monument 4, scale75 1). The entry
  would put one product's data on a different product's paint. Refused, mirroring
  `HarvestApplier.ApplyEnrichment`, which meets the collision from the other side (one entry, N
  paints) and declines: "guessing which of two paints a photo belongs to is worse than leaving
  both blank" (HarvestApplier.cs:183).
- MODE A, one catalog KEY over N catalog PAINTS, each store product naming its own by sku
  (vallejo 4, all of vallejo's). The C# disambiguates an ambiguous key by `entry.Sku`, so the
  one entry `enrich` can hold lands on the correct pot. First-wins is KEPT: refusing would cost
  four correct imageUrls and prevent nothing, since mfr-vallejo quotes no ean and no price.

Classes here follow that plus the two bridge-side halves:

- DETECTION AND REFUSAL, in `add_enrich`, shared by every bridge including the five with no
  contested key today -- and the Mode A / Mode B split, which needs the `Catalog`.
- DISAMBIGUATION, where a bridge holds evidence that settles it: bridge_monument's code-first
  two-pass. Refusal is the floor, not the goal -- monument's four keys are all settled, and three
  of them flip to a different SKU, EAN, photo and price than first-wins chose.
- ROUTING, where nothing settles it: bridge_gsw must send the refused rows to `candidates`
  EXPLICITLY. Its `suffix_match` returning None falls through to the additions branch, so a
  refusal expressed as "no match" would MINT a paint per refused row (73 of them) instead of
  reporting a collision.

Imported by path: the bridge scripts are not part of the installed package (they run standalone
under `uv run --with pyyaml`), same as test_paint_harvest_gate.py.
"""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools/acquisition/scripts/gen_paint_harvest.py"
HARVEST_DIR = REPO_ROOT / "data/paints/harvest"

CONTESTED = "contested identity ("


def _load():
    if not SCRIPT.exists():
        pytest.skip("gen_paint_harvest.py not present (package tested outside the monorepo)")
    spec = importlib.util.spec_from_file_location("gen_paint_harvest_contested", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harvest = _load()


@pytest.fixture
def evidence(monkeypatch, tmp_path: Path):
    """Synthetic evidence, catalog and prior harvest; the REAL descriptors (see
    test_paint_harvest_gate.py -- `crossover_rule` is lru_cached on the source id, so a
    redirected SOURCES_DIR would leak into every other test in the session)."""
    monkeypatch.setattr(harvest, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(harvest, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(harvest, "STORES_DIR", tmp_path / "stores")
    monkeypatch.setattr(harvest, "OUT_DIR", tmp_path / "out")
    for name in ("evidence", "brands", "stores", "out"):
        (tmp_path / name).mkdir()

    def write(source_id: str, rows: list[dict]) -> None:
        directory = tmp_path / "evidence" / source_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "observations.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
        )

    def catalog(slug: str, paints: list[dict]) -> None:
        (tmp_path / "brands" / f"{slug}.yaml").write_text(
            yaml.safe_dump({"paints": paints}, sort_keys=False), encoding="utf-8"
        )

    write.catalog = catalog  # type: ignore[attr-defined]
    return write


def _committed(slug: str) -> dict:
    path = HARVEST_DIR / f"{slug}.yaml"
    if not path.exists():
        pytest.skip(f"data/paints/harvest/{slug}.yaml not generated")
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(slug) or {}


# --- detection and refusal --------------------------------------------------------------------


class TestASecondProductCannotTakeAnIdentity:
    def test_a_rival_sku_withholds_the_entry_that_had_already_landed(self) -> None:
        """The exact shape of the GSW dipping inks: the 60 ml row files first, the 17 ml row
        arrives second. First-wins kept the 60 ml ean AND left the key looking enriched."""
        out = harvest.BrandHarvest()
        assert out.add_enrich("Papyrus Dip|Dipping Inks", ean="8435646508412", sku="3481") is True
        assert out.add_enrich("Papyrus Dip|Dipping Inks", ean="8435646514208", sku="4214") is False
        assert out.enrich == {}
        assert list(out.contested) == ["Papyrus Dip|Dipping Inks"]

    def test_a_repeat_of_the_same_product_still_fills_blanks(self) -> None:
        """Two ROWS are not two products -- the rule keys on `sku`, not on call count.

        NOT justified by any live caller, and the docstring in add_enrich says so: measured over
        3,217 add_enrich calls across all nine bridges, ZERO keys are claimed twice under one
        sku. bridge_mrhobby does union a manufacturer range with a retailer snapshot, but INSIDE
        a single call (the manufacturer pass fills a `confirmed` dict the retailer pass reads),
        so it never claims a key twice either. This pins the rule that is correct, not a
        mechanism that exists.
        """
        out = harvest.BrandHarvest()
        assert out.add_enrich("Light Blue|Mr Color", sku="C20", sourceUrl="series") is True
        assert out.add_enrich("Light Blue|Mr Color", sku="C20", ean="4973028718201") is True
        assert out.enrich == {
            "Light Blue|Mr Color": {"sku": "C20", "sourceUrl": "series", "ean": "4973028718201"}
        }
        assert out.contested == {}

    def test_a_contested_key_stays_contested(self) -> None:
        """A third claim repeating a sku already seen must not reinstate the key -- `Orange|Fluor
        Metallic` is claimed by four GSW products, and the last of them (`Fluor Paint ORANGE`) is
        the one that would look like a clean single claim."""
        out = harvest.BrandHarvest()
        out.add_enrich("Orange|Fluor Metallic", ean="8435646516332", sku="4273")
        out.add_enrich("Orange|Fluor Metallic", ean="8435646524580", sku="5098")
        assert out.add_enrich("Orange|Fluor Metallic", ean="8435646516332", sku="4273") is False
        assert out.enrich == {}
        assert len(out.contested["Orange|Fluor Metallic"]) == 3

    def test_a_withheld_claim_is_reported_not_dropped(self) -> None:
        """`paint_rows` established the rule for gated rows: refusing and losing are different
        things. A key no bridge could settle still has to say so in the file."""
        out = harvest.BrandHarvest()
        out.add_enrich("Papyrus Dip|Dipping Inks", sku="3481", sourceUrl="a", source="gsw")
        out.add_enrich("Papyrus Dip|Dipping Inks", sku="4214", sourceUrl="b", source="gsw")
        candidates = out.to_yaml()["candidates"]
        assert candidates == [
            {"name": "Papyrus Dip", "sku": "3481", "url": "a", "source": "gsw",
             "reason": "contested identity (Papyrus Dip|Dipping Inks) -- 2 store products claim "
                       "it: 3481, 4214"},
            {"name": "Papyrus Dip", "sku": "4214", "url": "b", "source": "gsw",
             "reason": "contested identity (Papyrus Dip|Dipping Inks) -- 2 store products claim "
                       "it: 3481, 4214"},
        ]

    def test_reporting_is_idempotent(self) -> None:
        """`to_yaml` is called once per run today, and `contested_candidates` is derived rather
        than appended to `self.candidates` so that stays a fact about the design, not about the
        caller."""
        out = harvest.BrandHarvest()
        out.add_enrich("Papyrus Dip|Dipping Inks", sku="3481")
        out.add_enrich("Papyrus Dip|Dipping Inks", sku="4214")
        assert out.to_yaml() == out.to_yaml()
        assert out.candidates == []


# --- mode A vs mode B: whose collision is it, the store's or the catalog's? -------------------


def _catalog(tmp_path: Path, slug: str, paints: list[dict]):
    """A real `Catalog` over a synthetic brand file (BRANDS_DIR is monkeypatched by `evidence`)."""
    (harvest.BRANDS_DIR / f"{slug}.yaml").write_text(
        yaml.safe_dump({"paints": paints}, sort_keys=False), encoding="utf-8"
    )
    return harvest.Catalog(slug)


class TestTheTwoModes:
    """Same collision at the key, opposite verdicts, decided by the CATALOG."""

    def test_mode_a_two_real_paints_each_named_by_its_own_sku_keeps_first_wins(
        self, evidence, tmp_path: Path
    ) -> None:
        """Vallejo's four, in miniature. 72.051 and 72.094 are two DIFFERENT Game Color blacks
        that happen to share a name, and each store row's sku is one of their product codes.
        `HarvestApplier.ApplyEnrichment` routes an ambiguous key by `entry.Sku`, so the entry
        that is carried lands on the correct pot -- one paint enriched, one not, nothing wrong
        anywhere. Refusing would have cost a correct photo to prevent nothing.
        """
        catalog = _catalog(tmp_path, "vallejo", [
            {"name": "Black", "productCode": "72.051", "details": {"set": "Game Color"}},
            {"name": "Black", "productCode": "72.094", "details": {"set": "Game Color"}},
        ])
        out = harvest.BrandHarvest(catalog)
        assert out.add_enrich("Black|Game Color", sku="72.051", imageUrl="a") is True
        assert out.add_enrich("Black|Game Color", sku="72.094", imageUrl="b") is True
        assert out.enrich == {"Black|Game Color": {"sku": "72.051", "imageUrl": "a"}}
        assert out.contested == {}
        assert out.to_yaml().get("candidates") is None

    def test_mode_b_one_paint_two_products_is_refused(self, evidence, tmp_path: Path) -> None:
        """scale75's Titanium Grey: ONE `Titanium Grey|Artist Range` record, carrying no
        productCode, claimed by the Warfront bottle SW-40 and the Artist Range's own SART-60.
        Neither sku names it, so the entry would put one bottle's photo and price on whichever
        paint the C# finds -- the corruption Mode A does not have.
        """
        catalog = _catalog(tmp_path, "scale75", [
            {"name": "Titanium Grey", "details": {"set": "Artist Range"}},
        ])
        out = harvest.BrandHarvest(catalog)
        assert out.add_enrich("Titanium Grey|Artist Range", sku="SW-40", priceEur=2.25) is True
        assert out.add_enrich("Titanium Grey|Artist Range", sku="SART-60", priceEur=3.72) is False
        assert out.enrich == {}
        assert list(out.contested) == ["Titanium Grey|Artist Range"]

    def test_an_ambiguous_key_whose_skus_do_not_name_the_paints_is_still_refused(
        self, evidence, tmp_path: Path
    ) -> None:
        """The trap in the middle. The key is ambiguous, so `Catalog.pins` says yes to a
        non-blank sku -- but neither sku is either paint's productCode, so nothing routes and
        both entries would land by name. `Catalog.owner`, not `pins`, is the test.
        """
        catalog = _catalog(tmp_path, "vallejo", [
            {"name": "Black", "productCode": "72.051", "details": {"set": "Game Color"}},
            {"name": "Black", "productCode": "72.094", "details": {"set": "Game Color"}},
        ])
        out = harvest.BrandHarvest(catalog)
        assert out.add_enrich("Black|Game Color", sku="STORE-1") is True
        assert out.add_enrich("Black|Game Color", sku="STORE-2") is False
        assert out.enrich == {}

    def test_a_third_claim_can_turn_mode_a_into_mode_b(self, evidence, tmp_path: Path) -> None:
        """Mode A is not a latch. Two rivals that route cleanly stay merged; a third product
        that names neither paint makes the whole key unroutable, and the entry already filed
        has to come back out."""
        catalog = _catalog(tmp_path, "vallejo", [
            {"name": "Black", "productCode": "72.051", "details": {"set": "Game Color"}},
            {"name": "Black", "productCode": "72.094", "details": {"set": "Game Color"}},
        ])
        out = harvest.BrandHarvest(catalog)
        out.add_enrich("Black|Game Color", sku="72.051", imageUrl="a")
        out.add_enrich("Black|Game Color", sku="72.094", imageUrl="b")
        assert out.enrich != {}
        assert out.add_enrich("Black|Game Color", sku="72.999", imageUrl="c") is False
        assert out.enrich == {}
        assert len(out.contested["Black|Game Color"]) == 3

    def test_with_no_catalog_every_rival_claim_is_refused(self) -> None:
        """The default a bare `BrandHarvest()` gets. Mode A is a claim ABOUT THE CATALOG, so
        without one there is nothing to vouch that the C# would route these anywhere; refusing
        is the safe direction and the classes above rely on it."""
        out = harvest.BrandHarvest()
        assert out.add_enrich("Black|Game Color", sku="72.051") is True
        assert out.add_enrich("Black|Game Color", sku="72.094") is False
        assert out.enrich == {}

    def test_the_committed_vallejo_entries_are_not_withheld(self) -> None:
        """The regression this mode split exists to prevent, on the committed file: all four of
        vallejo's double-claimed keys keep an entry, and none is reported as contested."""
        data = _committed("vallejo")
        enrich = data.get("enrich") or {}
        for key in ("Black|Game Color", "Green Grey|Model Color", "Grey|Mecha Color",
                    "Red|Model Air"):
            assert key in enrich, f"{key} withheld -- mode A regressed"
            assert enrich[key].get("imageUrl"), f"{key} carries no imageUrl"
        assert [c for c in (data.get("candidates") or [])
                if str(c.get("reason", "")).startswith(CONTESTED)] == []


# --- disambiguation: monument's code-first two-pass -------------------------------------------


def test_a_1_step_bottle_cannot_take_a_droppers_identity_by_name(evidence) -> None:
    """The live damage, reduced to two rows in the order the store publishes them.

    MPA-500's code is unknown to the catalog (which spells the 1-Step range MPA-5xx only once a
    harvest has minted it), so the old `match_code(...) or match_code(...) or match_name(name)`
    fell through to the NAME and hit the dropper. First-wins then made it permanent, and
    data/paints/brands/monument-pro-acryl.yaml:405-419 still shows the result: `Blue` carrying
    655368408984, a 22 ml 1-Step bottle's barcode, at the 1-Step's $6.00.
    """
    evidence.catalog("monument-pro-acryl", [
        {"name": "Blue", "productCode": "005",
         "details": {"set": "Monument Pro Acrylic Paints", "hex": "#1F4E9C"}},
    ])
    evidence("mfr-monument", [
        {"name": "PRO Acryl 1-Step 500 - Blue", "sku": "MPA-500", "ean": "655368408984",
         "url": "one-step", "priceUsd": 6.0, "hints": {"productType": "Paint Singles"}},
        {"name": "005-Pro Acryl Blue", "sku": "MPA-005", "ean": "628504411056",
         "url": "dropper", "priceUsd": 5.0, "hints": {"productType": "Paint Singles"}},
    ])
    out = harvest.bridge_monument()
    assert out.enrich == {
        "Blue|Monument Pro Acrylic Paints": {
            "sku": "MPA-005", "ean": "628504411056", "sourceUrl": "dropper",
            "source": "mfr-monument", "priceUsd": 5.0,
        }
    }
    # And the displaced row is not lost either: it is a real product of a promoted range.
    assert [(a["name"], a["set"], a["productCode"]) for a in out.additions] == [
        ("Blue", "Pro Acryl 1-Step", "MPA-500")
    ]
    assert out.contested == {}


def test_a_code_match_owns_its_identity_even_when_the_ratchet_defers_it(evidence) -> None:
    """`previous_addition_codes` keeps a landed addition an addition, so a coded row can leave
    `enrich` empty for its key. It still OWNS that identity -- a same-named row from another
    range taking the slot it vacated is the same theft with an extra step. (MPA-005 then leaves
    as a candidate rather than an addition: monument promotes only the MPA-5xx and AMP- ranges.)
    """
    evidence.catalog("monument-pro-acryl", [
        {"name": "Blue", "productCode": "005",
         "details": {"set": "Monument Pro Acrylic Paints", "hex": "#1F4E9C"}},
    ])
    (harvest.OUT_DIR / "monument-pro-acryl.yaml").write_text(
        yaml.safe_dump({"monument-pro-acryl": {"additions": [{"productCode": "MPA-005"}]}}),
        encoding="utf-8",
    )
    evidence("mfr-monument", [
        {"name": "PRO Acryl 1-Step 500 - Blue", "sku": "MPA-500", "ean": "655368408984",
         "url": "one-step", "hints": {"productType": "Paint Singles"}},
        {"name": "005-Pro Acryl Blue", "sku": "MPA-005", "ean": "628504411056",
         "url": "dropper", "hints": {"productType": "Paint Singles"}},
    ])
    out = harvest.bridge_monument()
    assert out.enrich == {}
    assert [a["productCode"] for a in out.additions] == ["MPA-500"]
    assert [c["sku"] for c in out.candidates] == ["MPA-005"]


def test_the_committed_monument_entries_name_the_dropper_not_the_1_step() -> None:
    """The three flips, on the committed file -- pinned on the values that ARE the repair.

    `sku` alone is not enough and pinning only `sku` was a real hole: the whole damage is a
    1-Step bottle's EAN, photo and $6.00 price sitting on a dropper, so a regression that put
    655368408984 back under sku MPA-005 would have passed. The barcode, the price and the image
    are asserted here; `Warm Yellow` is the control that never flipped.
    """
    data = _committed("monument-pro-acryl")
    enrich = data.get("enrich") or {}
    keys = ("Blue|Monument Pro Acrylic Paints", "Orange|Monument Pro Acrylic Paints",
            "Shadow Flesh|Monument Pro Acrylic Paints", "Warm Yellow|Monument Pro Acrylic Paints")
    assert {k: (enrich[k]["sku"], enrich[k]["ean"], enrich[k]["priceUsd"]) for k in keys} == {
        "Blue|Monument Pro Acrylic Paints": ("MPA-005", "628504411056", 5.0),
        "Orange|Monument Pro Acrylic Paints": ("MPA-007", "628504411070", 5.0),
        "Shadow Flesh|Monument Pro Acrylic Paints": ("MPA-042", "628504411421", 5.0),
        "Warm Yellow|Monument Pro Acrylic Paints": ("MPA-072", "628504411728", 5.0),
    }
    # The photo has to move too -- the dropper record still shows the 22 ml bottle otherwise.
    assert [enrich[k]["imageUrl"].rsplit("/", 1)[-1].split("?")[0] for k in keys] == [
        "MPA-005-Blue.png", "MPA-007-Orange.png", "MPA-042-ShadowFlesh.png",
        "MPA-072-WarmYellow.png",
    ]
    # And the three displaced barcodes are re-homed onto the 1-Step additions, not dropped.
    one_step = {a["productCode"]: a.get("ean") for a in (data.get("additions") or [])
                if a.get("set") == "Pro Acryl 1-Step"}
    assert sorted(one_step) == ["MPA-500", "MPA-501", "MPA-502", "MPA-503", "MPA-504", "MPA-505",
                                "MPA-506", "MPA-507", "MPA-508", "MPA-509", "MPA-510", "MPA-511"]
    assert (one_step["MPA-500"], one_step["MPA-511"], one_step["MPA-506"]) == (
        "655368408984", "655368429989", "655368417375")


# --- routing: a GSW refusal must not mint a paint ---------------------------------------------


def test_two_volumes_of_one_ink_are_reported_not_published(evidence) -> None:
    """THE TRAP THIS TEST EXISTS FOR: in bridge_gsw a missing match is not a refusal.

    `suffix_match` returning None falls straight through to `GSW_SET_BY_CATEGORY`, and every one
    of the 62 contested rows sits in a mapped category -- so "refuse both" implemented as "return
    None" proposes 62 NEW paints. The refusal has to be routed to `candidates` by name.
    """
    evidence.catalog("green-stuff-world", [
        {"name": "Papyrus Dip", "productCode": None,
         "details": {"set": "Dipping Inks", "hex": "#C9A227"}},
    ])
    evidence("mfr-greenstuffworld", [
        {"name": "Dipping ink 60 ml - PAPYRUS DIP", "sku": "3481", "ean": "8435646508412",
         "url": "sixty", "priceEur": 3.7375, "hints": {"categorySlug": "dipping-inks"}},
        {"name": "Dipping ink 17 ml - Papyrus Dip", "sku": "4214", "ean": "8435646514208",
         "url": "seventeen", "priceEur": 2.125, "hints": {"categorySlug": "dipping-inks"}},
    ])
    out = harvest.bridge_gsw()
    assert out.enrich == {}
    assert out.additions == [], "a refused row must not publish as a new paint"
    assert [(c["sku"], c["reason"]) for c in out.candidates] == [
        ("3481", "contested identity (Papyrus Dip|Dipping Inks) -- 2 store products claim it: "
                 "3481, 4214"),
        ("4214", "contested identity (Papyrus Dip|Dipping Inks) -- 2 store products claim it: "
                 "3481, 4214"),
    ]
    # The bridge routes its own contests, so the shared net has nothing left to catch.
    assert out.contested == {}


def test_an_uncontested_new_colour_still_becomes_an_addition(evidence) -> None:
    """The control. Without it the test above passes just as well with additions switched off,
    and GSW's 161 additions are the reason this bridge has a catalog role at all."""
    evidence.catalog("green-stuff-world", [
        {"name": "Papyrus Dip", "productCode": None,
         "details": {"set": "Dipping Inks", "hex": "#C9A227"}},
    ])
    evidence("mfr-greenstuffworld", [
        {"name": "Dipping ink 17 ml - Nude Skin Dip", "sku": "4230", "ean": "8435646514307",
         "url": "u", "priceEur": 2.125, "hints": {"categorySlug": "dipping-inks"}},
    ])
    out = harvest.bridge_gsw()
    assert out.enrich == {}
    assert [(a["name"], a["set"], a["productCode"]) for a in out.additions] == [
        ("Nude Skin Dip 17 ml", "Dipping Inks", "4230")
    ]


def test_a_refused_gsw_row_is_never_also_published() -> None:
    """The same invariant over the committed file, where the count is 62 rows on 31 keys: no sku
    reported as contested may appear as an enrich sku or an addition's productCode.

    Was 73 on 34 until 2026-08-06, when `suffix_match` gained the set filter. The 11 rows and 3
    keys that left were never a real contest: `White|Fluor Metallic`, `Orange|Fluor Metallic` and
    `Yellow|Fluor Metallic` were CROWDED by rows the store files under other categories -- inks
    reaching a fluor set -- and the refusal was the join's own blindness reported as a collision.
    The 62 that remain are the genuine article, dipping inks whose 17 ml and 60 ml rows really do
    both end with the one catalog name. See test_paint_harvest_gsw_sets.py.
    """
    data = _committed("green-stuff-world")
    published = {str(e.get("sku")) for e in (data.get("enrich") or {}).values()}
    published |= {str(a.get("productCode")) for a in (data.get("additions") or [])}
    refused = [c for c in (data.get("candidates") or []) if str(c.get("reason", "")).startswith(CONTESTED)]
    assert len(refused) == 62
    assert len({c["reason"] for c in refused}) == 31
    assert [c for c in refused if str(c.get("sku")) in published] == []


# --- the invariant across every bridge ---------------------------------------------------------


def test_no_bridge_lets_a_contested_key_leave_in_silence() -> None:
    """Whatever a bridge does about a collision, the file must still say it happened.

    Runs all nine bridges against the committed evidence: a key `add_enrich` withheld must be
    absent from `enrich` AND present in the emitted candidates. That is ONE key today -- scale75's
    `Titanium Grey|Artist Range`, the only Mode B collision no bridge resolves for itself
    (monument settles its four by code, gsw routes its 31 by hand, and vallejo's four are Mode A
    and are not withheld at all).
    """
    if not (REPO_ROOT / "data/evidence/products").exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")
    withheld = []
    for slug, bridge in harvest.BRIDGES.items():
        out = bridge()
        data = out.to_yaml()
        reasons = Counter(str(c.get("reason") or "") for c in (data.get("candidates") or []))
        for key in out.contested:
            withheld.append((slug, key))
            assert key not in (data.get("enrich") or {}), f"{slug}: {key} withheld yet emitted"
            assert any(key in reason for reason in reasons), f"{slug}: {key} vanished silently"
    assert withheld == [("scale75", "Titanium Grey|Artist Range")]


    def test_a_mode_a_rival_cannot_blank_fill_the_winners_entry(
        self, evidence, tmp_path: Path
    ) -> None:
        """Mode A carries ONE entry, so every field in it must come off ONE product.

        `HarvestApplier.ApplyEnrichment` routes the entry to whichever paint its own `sku` names.
        If a rival -- a DIFFERENT store product -- could fill fields the winner left blank, the
        published entry would carry one product's sku beside another's ean and price, and the C#
        would land the pair on the paint the sku names. That is Mode B's corruption, narrowed to
        blank fields.

        Zero occurrences on today's data (all 8 vallejo Mode-A claims carry only an imageUrl), so
        this pins the rule rather than a symptom.
        """
        catalog = _catalog(tmp_path, "vallejo", [
            {"name": "Black", "productCode": "72.051", "details": {"set": "Game Color"}},
            {"name": "Black", "productCode": "72.094", "details": {"set": "Game Color"}},
        ])
        out = harvest.BrandHarvest(catalog)
        assert out.add_enrich("Black|Game Color", sku="72.051", imageUrl="first.jpg") is True
        assert out.add_enrich("Black|Game Color", sku="72.094", imageUrl="second.jpg",
                              ean="1234567890128", priceEur=9.99) is True
        assert out.contested == {}
        entry = out.enrich["Black|Game Color"]
        assert entry == {"sku": "72.051", "imageUrl": "first.jpg"}, entry
