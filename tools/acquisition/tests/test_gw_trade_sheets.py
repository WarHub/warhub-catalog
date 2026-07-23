"""gw-trade-sheets strategy: the parsing gates that keep bad barcodes out of the catalog.

The three hazards under test are the ones measured in
`docs/research/2026-07-22-gw-trade-barcode-retrieval.md` SS4.2 -- each would silently corrupt data
rather than fail loudly, which is why they get dedicated tests:

1. GW's 12-digit INTERNAL codes parse as valid UPC-A and would be stored as retail barcodes.
2. 14-digit `Barcode (6-Pack)` values are GTIN-14 case codes, not retail barcodes.
3. The media API degrades to an empty-assets HTTP 200 under load instead of returning 429, which
   makes a paginator silently under-report and still pass its contract.
"""
import datetime as dt

import pytest

from warhub_acquisition.acquire.client import FetchError
from warhub_acquisition.acquire.strategies.gw_trade_sheets import (
    _clean_ean,
    _fetch_page,
    _is_discontinued,
    _merge,
    _release_date_is_future,
    _rows,
    _select_workbooks,
    _sheet_role,
)
from warhub_acquisition.models.observation import Observation


def _obs(**kwargs):
    base = dict(
        key="mfr-gw-trade:99120202075",
        manufacturer="Games Workshop",
        name="CITIES OF SIGMAR: MALLUS",
        sku="99120202075",
        ean="5011921252848",
        firstSeen="2026-07-22",
        lastSeen="2026-07-22",
        extractor="gw-trade-sheets",
    )
    base.update(kwargs)
    return Observation(**base)


class _FakeSheet:
    def __init__(self, title, rows):
        self.title = title
        self._rows = rows

    def iter_rows(self, values_only=True):
        yield from self._rows


# --- hazard 1: GW internal codes must never become barcodes ------------------------------------


def test_gw_internal_12_digit_code_is_rejected():
    """`608899990183` is product code 60889999018 + a check digit -- NOT a retail barcode.

    It is a valid UPC-A, so `ean.canonical_ean` zero-pads it to `0608899990183` and returns it
    happily. Only the GS1-prefix allowlist stops it. ~85 such rows exist in the live register.
    """
    assert _clean_ean("608899990183") is None


def test_real_gw_ean13_is_accepted():
    assert _clean_ean("5011921185917") == "5011921185917"


def test_hyphenated_ean_is_accepted():
    """Trade Direct Range and the paint sheets present barcodes hyphenated before the check digit."""
    assert _clean_ean("501192118591-7") == "5011921185917"


def test_black_library_isbn13_is_accepted():
    """Bookland 978/979 prefixes are legitimate EAN-13s and already first-class in the catalog."""
    assert _clean_ean("9781836092940") == "9781836092940"


def test_foreign_prefix_ean_is_rejected():
    """A checksum-valid EAN-13 outside GW's GS1 prefix is not a GW barcode -- reject rather than
    trust a sheet cell that has drifted into the wrong column."""
    assert _clean_ean("4006381333931") is None


def test_bad_checksum_is_rejected():
    assert _clean_ean("5011921185918") is None


# --- hazard 2: case codes are not retail barcodes ----------------------------------------------


def test_gtin14_six_pack_case_code_is_rejected():
    """`Barcode (6-Pack)` carries a 14-digit trade/case code for the outer, not the unit EAN."""
    assert _clean_ean("99189950208064") is None


@pytest.mark.parametrize("raw", [None, "", "   ", "n/a", "0"])
def test_empty_and_junk_values_are_rejected(raw):
    assert _clean_ean(raw) is None


# --- hazard 3: silent throttle must not read as end-of-results ---------------------------------


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    def get_json_response(self, url, params=None, headers=None):
        return self._payload, {}


def test_empty_assets_while_items_outstanding_raises_rate_limited():
    """GW returns HTTP 200 + `assets: []` under load rather than 429.

    Accepting that as end-of-results is how a run collects a fraction of the data and still passes
    its contract. It must surface as a rate-limited FetchError so the run is marked degraded.
    """
    client = _FakeClient({"page": 5, "total_items": 468, "assets": []})
    with pytest.raises(FetchError) as excinfo:
        _fetch_page(client, "https://x", "nonce", 220, 5, expect_more=True)
    assert excinfo.value.rate_limited is True


def test_empty_assets_at_genuine_end_is_not_an_error():
    """The same empty page IS end-of-results once the caller has all `total_items` -- no error."""
    client = _FakeClient({"page": 6, "total_items": 468, "assets": []})
    payload = _fetch_page(client, "https://x", "nonce", 220, 6, expect_more=False)
    assert payload["assets"] == []


# --- unreleased-product policy gate ------------------------------------------------------------


def test_future_release_date_is_dropped():
    """Policy, not data quality: GW's Trade Terms name product release dates and unreleased product
    info as Confidential Information, so not-yet-released rows never enter the catalog."""
    row = {"Release Date": dt.datetime(2026, 8, 8)}
    assert _release_date_is_future(row, "2026-07-22") is True


def test_past_release_date_is_kept():
    row = {"Release Date": dt.datetime(2026, 5, 30)}
    assert _release_date_is_future(row, "2026-07-22") is False


def test_row_without_release_date_is_kept():
    """Most rows (the whole InsertDelete register) have no release-date column at all."""
    assert _release_date_is_future({"Product Code": "99120202075"}, "2026-07-22") is False


# --- header handling ---------------------------------------------------------------------------


def test_rows_skips_leading_banner_row():
    """AU/NZ price files put a paragraph of RRP small print in row 1 and the header in row 2."""
    sheet = _FakeSheet(
        "Australia Price Change",
        [
            ("Note: Recommended Retail prices (RRPs) are not binding...", None, None, None),
            ("Range", "Code", "Barcode", "Product Description"),
            ("Best Sellers", "60010199059", "5011921199280", "40K Introductory Set"),
        ],
    )
    rows = list(_rows(sheet))
    assert len(rows) == 1
    assert rows[0]["Barcode"] == "5011921199280"
    assert rows[0]["Code"] == "60010199059"


# --- workbook selection ------------------------------------------------------------------------


def test_select_workbooks_matches_wordpress_dedup_suffixes():
    """WordPress appends unpredictable `__1`/`__2`/`(1)` suffixes, so patterns anchor on the stable
    part of the name and must never be exact-matched."""
    assets = {
        "https://x/assets/2025/04/Individual Barcodes April 2025__1.xlsx": {
            "file_name": "Individual Barcodes April 2025__1.xlsx"
        },
        "https://x/assets/2026/05/InsertDelete18.05.2026.xlsx": {
            "file_name": "InsertDelete18.05.2026.xlsx"
        },
        "https://x/assets/2026/06/P20 Planogram.xlsx": {"file_name": "P20 Planogram.xlsx"},
        "https://x/assets/2026/06/Trade Terms.pdf": {"file_name": "Trade Terms.pdf"},
    }
    selected = _select_workbooks(assets, ["InsertDelete", "Individual Barcodes"])
    names = sorted(a["file_name"] for _u, a in selected)
    assert names == ["Individual Barcodes April 2025__1.xlsx", "InsertDelete18.05.2026.xlsx"]


# --- cross-workbook merge ----------------------------------------------------------------------


def test_merge_keeps_price_from_the_workbook_that_has_one():
    """Regression: the same code appears in InsertDelete (no price column) and Trade Direct Range
    (the RRP). Last-wins assignment blanked priceGbp for every product depending on filename sort
    order -- caught only by inspecting a real harvest, where every priceGbp came back null."""
    priced = _obs(priceGbp=25.0)
    unpriced = _obs(priceGbp=None)
    assert _merge(priced, unpriced).priceGbp == 25.0
    assert _merge(unpriced, priced).priceGbp == 25.0


def test_insertions_row_does_not_revive_a_deleted_product():
    """The trap: `Insertions` means "entered the range on date X", NOT "currently sold".

    1,683 codes (measured 2026-07-22) appear in BOTH Insertions and Deletions -- added, later
    withdrawn, genuinely discontinued. An earlier version of this strategy treated any
    non-archived sighting as evidence of currency and silently revived all of them, halving the
    discontinued count from 2,658 to 1,216.
    """
    assert _is_discontinued({"withdrawn", "historical"}) is True


def test_current_range_listing_does_revive_a_deleted_product():
    """Presence in a CURRENT range sheet (Trade Direct Range, paint sheets) legitimately overrides
    a stale Deletions row -- that is a genuine re-introduction."""
    assert _is_discontinued({"withdrawn", "current"}) is False


def test_never_deleted_is_not_discontinued():
    assert _is_discontinued({"historical"}) is False
    assert _is_discontinued({"current"}) is False
    assert _is_discontinued(set()) is False


def test_unknown_vendor_name_fails_loudly():
    """Emitting the raw vendor NAME instead of the taxonomy SLUG mints a parallel manufacturer and
    duplicates the entire GW catalog (+7,999 products, +7,157 conflicts when this regressed). The
    lookup must therefore fail loudly rather than pass an unresolved string through."""
    from warhub_acquisition.acquire.runner import AcquireContext
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import gw_trade_sheets_strategy
    from warhub_acquisition.models.descriptor import SourceDescriptor
    from warhub_acquisition.taxonomy import Taxonomy

    descriptor = SourceDescriptor(
        id="mfr-gw-trade",
        kind="manufacturer",
        strategy="gw-trade-sheets",
        baseUrl="https://trade.games-workshop.com",
        scope={"manufacturer": "Not A Real Vendor", "filePatterns": ["InsertDelete"]},
    )
    context = AcquireContext(taxonomy=Taxonomy(manufacturers={}), mappings={}, run_date="2026-07-22")
    with pytest.raises(ValueError, match="not a known vendor name"):
        gw_trade_sheets_strategy(descriptor, _FakeClient({}), {}, context)


@pytest.mark.parametrize(
    "title,role",
    [
        ("Deletions", "withdrawn"),
        ("deletions", "withdrawn"),
        ("Insertions", "historical"),
        ("Code Changes", "historical"),
        ("Sheet1", "current"),
        ("Paints", "current"),
        ("Brushes", "current"),
    ],
)
def test_sheet_roles(title, role):
    assert _sheet_role(title) == role


def test_merge_unions_hints():
    merged = _merge(_obs(hints={"sscCode": "70-863"}), _obs(hints={"tradeCategory": "BS:A"}))
    assert merged.hints == {"sscCode": "70-863", "tradeCategory": "BS:A"}


def test_select_workbooks_excludes_legacy_xls():
    """openpyxl cannot read BIFF .xls; excluding it at selection makes that a deliberate choice
    rather than a parse failure counted against the run."""
    assets = {"https://x/a/Pricelist UK.xls": {"file_name": "Pricelist UK.xls"}}
    assert _select_workbooks(assets, ["Pricelist"]) == []
