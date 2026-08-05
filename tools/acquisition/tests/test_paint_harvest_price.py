# tools/acquisition/tests/test_paint_harvest_price.py
"""The price bridge in scripts/gen_paint_harvest.py: which currency, and onto which paint.

Two ways a price can be worse than no price, and one test class each:

- WRONG CURRENCY. Both storefront extractors fall back to `priceGbp` for a currency code they
  do not recognize (`_PRICE_FIELDS.get(str(currency).casefold(), "priceGbp")` in woo.py and
  shopify.py), so a store that starts answering in something new would land euros in a pounds
  field. The bridge reads only the field its source is pinned to, which turns that into a
  dropped price instead of a mislabelled one.
- WRONG PAINT. `{Name}|{Set}` is not unique -- the same collision that put one store photo on
  two different Vallejo paints. A price is a claim about a specific product; it may only ride
  an entry that names exactly one.

Imported by path: the bridge scripts are not part of the installed package (they run
standalone under `uv run --with pyyaml`), same as test_paint_harvest_mrhobby.py.
"""
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools/acquisition/scripts/gen_paint_harvest.py"
HARVEST_DIR = REPO_ROOT / "data/paints/harvest"

PRICE_FIELDS = ("priceGbp", "priceUsd", "priceEur", "priceCad")


def _load():
    if not SCRIPT.exists():
        pytest.skip("gen_paint_harvest.py not present (package tested outside the monorepo)")
    spec = importlib.util.spec_from_file_location("gen_paint_harvest_price", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harvest = _load()


# --- currency mapping ----------------------------------------------------------------------

@pytest.mark.parametrize(
    ("source_id", "field"),
    [
        # Measured over the committed observations, 2026-08-05. EUR stores...
        ("mfr-ak-interactive", "priceEur"),
        ("mfr-scale75", "priceEur"),
        ("mfr-greenstuffworld", "priceEur"),
        # ...and USD stores. Not one paint source quotes GBP, which is exactly why the default
        # in the extractors is the wrong thing to inherit here.
        ("mfr-armypainter", "priceUsd"),
        ("mfr-reaper", "priceUsd"),
        ("mfr-turbodork", "priceUsd"),
        ("mfr-monument", "priceUsd"),
    ],
)
def test_each_source_carries_its_own_currency(source_id: str, field: str) -> None:
    assert harvest.observed_price({"name": "Ruby Red", field: 2.5}, source_id) == {field: 2.5}


@pytest.mark.parametrize("source_id", ["mfr-ak-interactive", "mfr-scale75", "mfr-armypainter"])
def test_a_price_in_the_wrong_currency_is_dropped_not_relabelled(source_id: str) -> None:
    """The failure this guard exists for: woo/shopify default an unknown currency code to
    `priceGbp`. If that ever fires, the number must not reach the catalog wearing the source's
    usual label -- and must not reach it as GBP either."""
    for wrong in set(PRICE_FIELDS) - {harvest.SOURCE_PRICE_FIELD[source_id]}:
        assert harvest.observed_price({"name": "Ruby Red", wrong: 2.5}, source_id) == {}


def test_a_source_that_quotes_no_price_carries_none() -> None:
    """mfr-vallejo (0 of 1194 observations) and mfr-mr-hobby (0 of 134) publish no price, and
    an unlisted source must stay unpriced even if its evidence sprouts a price field."""
    for source_id in ("mfr-vallejo", "mfr-mr-hobby", "mfr-brand-new"):
        assert source_id not in harvest.SOURCE_PRICE_FIELD
        assert harvest.observed_price({"name": "Ruby Red", "priceEur": 2.5}, source_id) == {}


@pytest.mark.parametrize("value", [0, 0.0, -1.0, None, "", "2.50", True, False])
def test_a_non_positive_or_non_numeric_price_is_not_a_price(value: object) -> None:
    """ak-interactive lists "QUICK GEN COLOR GUIDE [PDF]" (AK17000GUIDE) at 0.00. A free PDF is
    not a free paint, and `True` is not 1 euro."""
    observation = {"name": "Ruby Red", "priceEur": value}
    assert harvest.observed_price(observation, "mfr-ak-interactive") == {}


def test_the_price_is_carried_verbatim_never_rounded() -> None:
    """greenstuffworld.com quotes a pre-rounding decimal when a product is discounted (294 of
    its 477 observations). Rounding it would invent a price the store never showed."""
    assert harvest.observed_price(
        {"name": "Coagulated Blood", "priceEur": 2.745}, "mfr-greenstuffworld"
    ) == {"priceEur": 2.745}


# --- sets ---------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title",
    [
        # Real titles that reach `additions` today, because greenstuffworld.com files its range
        # sets under the RANGE category and reapermini.com calls this one hints.category=paint.
        "Paint Set - Chrome",
        "Set x8 Fluor Paints",
        "Acrylic Inks Set - Basic Opaque (x4)",
        "Sophie's Mystery Paint Set",
        "Paint Set - Dipping collection 01",
        "AK INTERACTIVE FULL RANGE WOODEN BOX",
    ],
)
def test_a_sets_price_is_not_a_paints_price(title: str) -> None:
    assert harvest.observed_price({"name": title, "priceEur": 22.75}, "mfr-greenstuffworld") == {}


@pytest.mark.parametrize(
    "title",
    [
        "Box Wine",          # a real Turbo Dork colour -- why \bBOX\b is not in the word list
        "Sunset Opaque",     # \bSET\b must not match inside a word
        "Setting Sun",       # ...nor at the start of one
        "Black Chrome Spray Paint 400ml",
        "Coagulated Blood",
    ],
)
def test_a_single_pot_keeps_its_price(title: str) -> None:
    assert harvest.observed_price({"name": title, "priceEur": 2.75}, "mfr-greenstuffworld") == {
        "priceEur": 2.75
    }


# --- the ambiguous-key guard ----------------------------------------------------------------

def _catalog(monkeypatch, tmp_path: Path, paints: list[dict]) -> object:
    (tmp_path / "brand.yaml").write_text(
        yaml.safe_dump({"paints": paints}, sort_keys=False), encoding="utf-8"
    )
    monkeypatch.setattr(harvest, "BRANDS_DIR", tmp_path)
    return harvest.Catalog("brand")


def _paint(name: str, set_name: str, code: str | None, hex_value: str) -> dict:
    return {"name": name, "productCode": code, "details": {"set": set_name, "hex": hex_value}}


def test_a_unique_key_needs_no_disambiguation(monkeypatch, tmp_path: Path) -> None:
    catalog = _catalog(monkeypatch, tmp_path, [_paint("Bloody Red", "Game Air", "72.710", "#CD3230")])
    assert catalog.pins("Bloody Red|Game Air", "72.710")
    assert catalog.pins("Bloody Red|Game Air", None)


def test_an_ambiguous_key_is_settled_by_the_entrys_own_sku(monkeypatch, tmp_path: Path) -> None:
    """The real collision, from data/paints/brands/vallejo.yaml: two Game Air paints named
    "Bloody Red", different codes and different colours. The entry's sku says which pot the
    generator actually matched, so the price may ride -- and only on that one."""
    catalog = _catalog(monkeypatch, tmp_path, [
        _paint("Bloody Red", "Game Air", "72.710", "#CD3230"),
        _paint("Bloody Red", "Game Air", "76.010", "#D41C1C"),
    ])
    assert "Bloody Red|Game Air" in catalog.ambiguous
    assert catalog.pins("Bloody Red|Game Air", "72.710")
    assert catalog.pins("Bloody Red|Game Air", "76.010")


@pytest.mark.parametrize("sku", [None, "", "99.999"])
def test_an_ambiguous_key_no_sku_can_settle_carries_no_price(
    monkeypatch, tmp_path: Path, sku: str | None
) -> None:
    """A store SKU that is not either paint's product code (the common case: most bridges emit
    the STORE's sku, not the catalog code) must withhold, not guess. Two paints splitting one
    price between them is a lie about both."""
    catalog = _catalog(monkeypatch, tmp_path, [
        _paint("Bloody Red", "Game Air", "72.710", "#CD3230"),
        _paint("Bloody Red", "Game Air", "76.010", "#D41C1C"),
    ])
    assert not catalog.pins("Bloody Red|Game Air", sku)


def test_two_paints_sharing_one_product_code_cannot_be_pinned(monkeypatch, tmp_path: Path) -> None:
    """Real, and the one case the sku genuinely cannot solve: Vallejo ships two
    "Viking Grey|Xpress Color Intense" paints BOTH coded 72.483, differing only by hex."""
    catalog = _catalog(monkeypatch, tmp_path, [
        _paint("Viking Grey", "Xpress Color Intense", "72.483", "#5E6A6E"),
        _paint("Viking Grey", "Xpress Color Intense", "72.483", "#6B7478"),
    ])
    assert not catalog.pins("Viking Grey|Xpress Color Intense", "72.483")


def test_pinned_price_withholds_exactly_when_the_key_cannot_be_pinned(
    monkeypatch, tmp_path: Path
) -> None:
    catalog = _catalog(monkeypatch, tmp_path, [
        _paint("Bloody Red", "Game Air", "72.710", "#CD3230"),
        _paint("Bloody Red", "Game Air", "76.010", "#D41C1C"),
        _paint("Cold Grey", "Game Air", "72.050", "#7C8A8F"),
    ])
    observation = {"name": "Bloody Red", "priceEur": 3.23}
    assert harvest.pinned_price(
        catalog, "Bloody Red|Game Air", "72.710", observation, "mfr-scale75"
    ) == {"priceEur": 3.23}
    assert harvest.pinned_price(
        catalog, "Bloody Red|Game Air", "SC-08", observation, "mfr-scale75"
    ) == {}
    assert harvest.pinned_price(
        catalog, "Cold Grey|Game Air", None, observation, "mfr-scale75"
    ) == {"priceEur": 3.23}


# --- the committed files ---------------------------------------------------------------------

def _committed_harvests() -> list[tuple[str, dict]]:
    if not HARVEST_DIR.exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")
    out = []
    for path in sorted(HARVEST_DIR.glob("*.yaml")):
        data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(path.stem) or {}
        out.append((path.stem, data))
    return out


def test_committed_prices_match_their_sources_declared_currency() -> None:
    """The end-to-end contract: whatever a bridge does, a price in a committed file must be in
    the currency SOURCE_PRICE_FIELD says that source quotes -- and a source with no declared
    currency must have emitted no price at all."""
    for slug, data in _committed_harvests():
        entries = list((data.get("enrich") or {}).values()) + list(data.get("additions") or [])
        for entry in entries:
            fields = [f for f in PRICE_FIELDS if f in entry]
            assert len(fields) <= 1, f"{slug}: {entry} quotes {fields} -- one currency per entry"
            if not fields:
                continue
            expected = harvest.SOURCE_PRICE_FIELD.get(str(entry.get("source")))
            assert expected == fields[0], (
                f"{slug}: entry from {entry.get('source')!r} carries {fields[0]}, "
                f"expected {expected!r}"
            )


def test_no_committed_price_rides_a_set_or_a_free_download() -> None:
    for slug, data in _committed_harvests():
        entries = [(k.split("|")[0], v) for k, v in (data.get("enrich") or {}).items()]
        entries += [(str(a.get("name") or ""), a) for a in (data.get("additions") or [])]
        for name, entry in entries:
            for field in PRICE_FIELDS:
                if field in entry:
                    assert entry[field] > 0, f"{slug}: {name} priced at {entry[field]}"
                    assert not harvest.SET_WORDS.search(name), f"{slug}: set {name!r} is priced"


def test_candidates_are_never_priced() -> None:
    """`candidates` is a report for a human about products the bridge refused to join. Pricing
    one would imply it had landed on a paint."""
    for slug, data in _committed_harvests():
        for candidate in data.get("candidates") or []:
            assert not [f for f in PRICE_FIELDS if f in candidate], f"{slug}: {candidate}"


def test_no_committed_addition_is_a_boxed_set() -> None:
    """A multi-pot box must never be proposed as a new individual paint.

    Until 2026-08-05 twenty of them were: 19 green-stuff-world (the store files its RANGE sets
    under the range's own category, so `categorySlug == "paint-sets"` never fired) and 1 reaper
    ("Sophie's Mystery Paint Set", which the store labels `category=paint`). They published as
    single 17 ml droppers with an empty hex.

    SCOPE, deliberately: this asserts over EVERY brand, but only bridge_ak, bridge_gsw and
    bridge_reaper actually carry a name-level set check. The other six bridges gate on per-source
    signals alone and pass today only because no set has yet slipped past them (measured: 0
    SET_WORDS hits across their 619 additions). That is intentional -- this is a tripwire for the
    whole surface, not a restatement of the three gates. If it ever fails for vallejo or
    army-painter, the fix is a gate in that bridge, not an edit to this test.
    """
    offenders = [
        (slug, addition.get("name"))
        for slug, data in _committed_harvests()
        for addition in data.get("additions") or []
        if harvest.SET_WORDS.search(str(addition.get("name") or ""))
    ]
    assert not offenders, f"boxed sets proposed as individual paints: {offenders}"
