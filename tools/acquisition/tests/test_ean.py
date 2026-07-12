import pytest

from warhub_acquisition.ean import canonical_ean, is_valid_ean, normalize_ean


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5011921194285", "5011921194285"),   # GW Combat Patrol: Necrons
        ("812152031524", "0812152031524"),    # Wyrd UPC-A, zero-padded
        (" 5011921 194285 ", "5011921194285"),
        ("501-1921-194285", "5011921194285"),
        ("0", None),
        ("0000000000000", None),               # all-zero rejection test
        ("", None),
        (None, None),
        ("not-a-code", None),
        ("501192119428²", None),               # non-decimal digit regression test
        ("12345", None),                       # too short
        ("50119211942850000", None),           # too long
    ],
)
def test_normalize_ean(raw: str | None, expected: str | None) -> None:
    assert normalize_ean(raw) == expected


@pytest.mark.parametrize(
    ("ean", "valid"),
    [
        ("5011921194285", True),
        ("5011921142361", True),   # GW Primaris Intercessors
        ("5011921146000", True),   # GW Stormraven Gunship
        ("0812152031524", True),   # Wyrd Miss Feasance (padded UPC)
        ("5011921194286", False),  # bad check digit
        ("5060924988049", True),   # Mantic Maul Battleship
    ],
)
def test_is_valid_ean(ean: str, valid: bool) -> None:
    assert is_valid_ean(ean) is valid


def test_canonical_ean_end_to_end() -> None:
    assert canonical_ean("812152031524") == "0812152031524"
    assert canonical_ean("5011921194286") is None  # normalizes but fails checksum
    assert canonical_ean(None) is None
