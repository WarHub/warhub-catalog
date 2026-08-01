"""Unit tests for the Mr Hobby range parser in scripts/gen_paint_harvest.py.

The bridge scripts are not part of the installed package (they run standalone under
`uv run --with pyyaml`), so they are imported by path. Only the fiddly part is pinned here:
mr-hobby.com prints its product numbers as free-text ranges typed by a CMS in two scripts,
and every barcode this bridge plants depends on expanding them correctly.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "tools/acquisition/scripts/gen_paint_harvest.py"


def _load():
    if not SCRIPT.exists():
        pytest.skip("gen_paint_harvest.py not present (package tested outside the monorepo)")
    spec = importlib.util.spec_from_file_location("gen_paint_harvest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harvest = _load()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The plain case, and the one that carries 189 paints.
        ("C1~C189", ["C1", "C2", "C3"]),
        ("MC211~219", ["MC211", "MC212", "MC213", "MC214", "MC215", "MC216", "MC217", "MC218", "MC219"]),
        # Padding follows the range's own lower bound, per range.
        ("WP01-05", ["WP01", "WP02", "WP03", "WP04", "WP05"]),
        ("HCR1~3", ["HCR1", "HCR2", "HCR3"]),
        # Fullwidth tilde, ideographic comma, katakana middle dot, slash -- all real CMS input.
        ("CV01～03", ["CV01", "CV02", "CV03"]),
        ("T106・T108", ["T106", "T108"]),
        ("WCT101/WCT102", ["WCT101", "WCT102"]),
        # The prefix carries across groups once the site stops repeating it.
        ("XAC01,02", ["XAC01", "XAC02"]),
        ("NGA01～20、201～204", ["NGA01", "NGA20", "NGA201", "NGA204"]),
        # A group may reintroduce its own prefix mid-string.
        ("S1~151・SJ01・02", ["S1", "S151", "SJ01", "SJ02"]),
    ],
)
def test_expand_covers_the_site_formats(raw: str, expected: list[str]) -> None:
    codes = harvest.mrhobby_expand(raw)
    assert codes is not None
    assert set(expected) <= set(codes)


def test_expand_spans_are_complete_and_ordered() -> None:
    codes = harvest.mrhobby_expand("H1~110,151,301~340,511~515")
    assert len(codes) == 110 + 1 + 40 + 5
    assert codes[:2] == ["H1", "H2"] and codes[-1] == "H515"


@pytest.mark.parametrize("raw", ["LG", "GGX", "", None, "C1~D5"])
def test_expand_refuses_what_is_not_a_code_range(raw: str | None) -> None:
    """Letter-only product numbers and mixed-prefix spans must fail, not guess -- an unparsed
    row becomes a candidate a human reads, a wrongly-parsed one becomes a wrong barcode."""
    assert harvest.mrhobby_expand(raw) is None


def test_code_forms_prefer_the_alias() -> None:
    """C38 is Mr.COLOR 38. The base also keeps a "Mr Color Modulation Set" copy under C38, so
    the bare form must be tried first or the barcode lands on the set copy."""
    assert harvest.mrhobby_code_forms("C38")[0] == "38"
    assert "C38" in harvest.mrhobby_code_forms("C38")


def test_code_forms_drop_the_alias_when_uncorroborated() -> None:
    """A retailer sku alone cannot justify dropping a prefix: aztoyhobby lists MC124 but the
    manufacturer publishes only MC211~219, and bare 124 is an unrelated Mr Color paint."""
    assert harvest.mrhobby_code_forms("MC124", alias_ok=False) == ["MC124"]
    assert "124" in harvest.mrhobby_code_forms("MC124", alias_ok=True)


def test_canonical_ignores_padding() -> None:
    assert harvest.mrhobby_canonical("NGA01") == harvest.mrhobby_canonical("NGA1") == "NGA1"


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("4973028535600", True),   # Mr.COLOR C1, live-verified JAN
        ("4973028535601", False),  # last digit off by one
        ("497302853560", False),   # 12 digits
        ("49730285356OO", False),
        (None, False),
    ],
)
def test_ean13_check_digit(value: str | None, ok: bool) -> None:
    assert harvest.ean13_ok(value) is ok
