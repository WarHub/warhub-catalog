"""gw-trade-sheets strategy: the parsing gates that keep bad barcodes out of the catalog.

The three hazards under test are the ones measured in
`docs/research/2026-07-22-gw-trade-barcode-retrieval.md` SS4.2 -- each would silently corrupt data
rather than fail loudly, which is why they get dedicated tests:

1. GW's 12-digit INTERNAL codes parse as valid UPC-A and would be stored as retail barcodes.
2. 14-digit `Barcode (6-Pack)` values are GTIN-14 case codes, not retail barcodes.
3. The media API degrades to an empty-assets HTTP 200 under load instead of returning 429, which
   makes a paginator silently under-report and still pass its contract.
"""
import collections
import datetime as dt

import pytest

from warhub_acquisition.acquire.client import FetchError
from warhub_acquisition.acquire.strategies.gw_trade_sheets import (
    _clean_ean,
    _fetch_page,
    _volume_ml,
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


@pytest.mark.parametrize(
    "size,name,expected",
    [
        ("12ml", "BASE: AVERLAND SUNSET (12ML) (6-PACK)", 12),
        ("400ml", "CHAOS BLACK SPRAY (6-PK)", 400),
        ("-", "MEPHISTON RED 12ML (6-PACK)", 12),          # size column blank -> parse from name
        (None, "SHADE: NULN OIL (18ML) (6 PACK)", 18),
        ("-", "SYNTHETIC BASE BRUSH (SMALL) (X3)", None),  # a brush has no ml
        (None, "COMBAT PATROL: SPACE MARINES", None),
    ],
)
def test_volume_ml(size, name, expected):
    assert _volume_ml(size, name) == expected


def test_rows_finds_china_header_under_multi_cell_banner():
    """The China Order Form's row 1 is a label banner with >=3 non-empty cells -- a naive
    "first substantial row" detector picks it and every real row zips against the wrong keys,
    silently yielding zero observations. The header must be found by column token instead."""
    sheet = _FakeSheet(
        "20.07.2026",
        [
            ("Releases For Next Week", None, "Releases For This Week", None, None, "Order Total:", "0"),
            ("下周新品", None, "这周新品", None, None, "订单总额：", None),
            (None, None, None, None, None, None, None),
            ("Release Date (China)", "Product Code", "Short Code", "Description (ENG)",
             "Category (ENG)", "Barcode", "Release Date (Global)"),
            ("2026-08-08", "99120199169", "73-401", "COMBAT PATROL: BATTLEZONE",
             "40K - Generic", "5011921274604", "2026-08-08"),
        ],
    )
    rows = list(_rows(sheet))
    assert len(rows) == 1
    assert rows[0]["Product Code"] == "99120199169"
    assert rows[0]["Barcode"] == "5011921274604"
    assert rows[0]["Category (ENG)"] == "40K - Generic"


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


# --- re-coding lineage (Code Changes sheet) ---------------------------------------------------


def _lineage(pairs):
    """Run _attach_lineage over (key, old_code, raw_old_barcode[, changed_on[, old_ssc]]) rows."""
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _attach_lineage

    observations = {"mfr-gw-trade:99120202075": _obs()}
    stats = collections.defaultdict(int)
    _attach_lineage([tuple(p) + (None,) * (5 - len(p)) for p in pairs], observations, stats)
    return observations["mfr-gw-trade:99120202075"], stats


def test_code_change_records_predecessor_code_and_barcode():
    obs, stats = _lineage([("mfr-gw-trade:99120202075", "99120202012", "5011921062164")])
    assert obs.hints["supersedes"] == [{"productCode": "99120202012", "ean": "5011921062164"}]
    assert stats["lineage_links"] == 1
    assert stats["lineage_with_barcode"] == 1


def test_wh_colour_rebrand_row_yields_new_sku_plus_its_predecessor():
    """The WH Colour workbook is the rebrand register: `Original SKU` -> `New SKU` with the NEW
    barcode. Its rows used to die unread because none of the accepted code columns existed in it,
    silently losing 604 barcodes the catalog has never seen."""
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _first, _predecessor

    row = {
        "Original SKU": "99189960061",
        "Original Pack SKU": "9918996006106",
        "New SKU": "99189960262",
        "SSC": "27-19",
        "Product Description": "C:NIGHTHAUNT GLOOM 18ML ROW X6",
        "New Individual barcode": "501192126251-9",
        "Range": "BS:A",
    }
    assert _first(row, "Product Code", "New Product Code", "Unit Code", "Individual Code",
                  "New SKU") == "99189960262"
    assert _clean_ean(row["New Individual barcode"]) == "5011921262519"
    # no Old Barcode column in this workbook -> the link carries the code alone, never a guess
    assert _predecessor(row, "2026-07-30") == ("99189960061", None, None, None)


def test_row_hints_are_verbatim_and_carry_no_category_stamp():
    """The judgement that a `Paint -` range or a `Paint` tab means `paint` lives in
    data/catalog/taxonomy/category-rules/mfr-gw-trade.yaml since 2026-09-02, not here: a stamp
    written by a harvester is a `stated` claim no table can correct. The strategy records what the
    sheet says and nothing more."""
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _row_hints

    hints = _row_hints(
        {"SSC": "27-19", "Range": "BS:A", "SIZE": "18ml"}, "Paint", "C:NIGHTHAUNT GLOOM 18ML ROW X6"
    )
    assert hints == {"sscCode": "27-19", "tradeCategory": "BS:A", "sheets": ["Paint"], "volumeMl": 18}
    assert "category" not in _row_hints({"Trade range": "Paint - WH Colour - Base"}, "Sheet1", "X")
    assert "sheets" not in _row_hints({"Trade range": "Spray - Colour"}, "  ", "X")


def test_merge_unions_list_hints():
    """A product seen on the rebrand workbook's `Paint` tab and on the Trade Direct `Sheet1` keeps
    both tabs; scalar hints keep the first value as before."""
    merged = _merge(
        _obs(hints={"sheets": ["Sheet1"], "tradeCategory": "Paint - WH Colour - Base"}),
        _obs(hints={"sheets": ["Paint", "Sheet1"], "tradeCategory": "BS:A"}),
    )
    assert merged.hints == {"sheets": ["Sheet1", "Paint"], "tradeCategory": "Paint - WH Colour - Base"}


def test_cumulative_restatement_does_not_look_like_a_placeholder():
    """REGRESSION. The InsertDelete register is cumulative: each workbook generation restates every
    past code change, so a genuine old barcode is seen many times -- always against the SAME old
    code. An occurrence-count filter therefore rejects EVERY barcode (measured live: 2,729 rows for
    919 real edges, 0 barcodes surviving). The test is 'claimed by more than one distinct old
    code', not 'seen more than once'."""
    rows = [("mfr-gw-trade:99120202075", "99120202012", "5011921062164")] * 3
    obs, stats = _lineage(rows)
    assert obs.hints["supersedes"] == [{"productCode": "99120202012", "ean": "5011921062164"}]
    assert stats["lineage_with_barcode"] == 1
    assert stats["lineage_placeholder_barcodes"] == 0


def test_placeholder_old_barcode_is_dropped_but_the_code_link_survives():
    """GW reuses filler values in `Old Barcode` across unrelated products -- 14 of them, one on 29
    rows (measured 2026-07-22). Asserting those would invent barcode links between unrelated
    products; the renumbering itself is still real, so only the barcode is dropped."""
    filler = "5011921182312"
    obs, stats = _lineage(
        [
            ("mfr-gw-trade:99120202075", "99120202012", filler),
            ("mfr-gw-trade:99120202075", "99120202013", filler),
        ]
    )
    assert obs.hints["supersedes"] == [
        {"productCode": "99120202012"},
        {"productCode": "99120202013"},
    ]
    assert stats["lineage_placeholder_barcodes"] == 2
    assert stats["lineage_with_barcode"] == 0


def test_lineage_old_barcode_obeys_the_gs1_prefix_gate():
    """A 12-digit GW internal code parses as a valid UPC-A -- it must never become a barcode here
    either, exactly as on the primary column."""
    obs, _ = _lineage([("mfr-gw-trade:99120202075", "99120202012", "608899990183")])
    assert obs.hints["supersedes"] == [{"productCode": "99120202012"}]


def test_repeated_code_change_rows_dedup_and_prefer_the_one_with_a_barcode():
    obs, stats = _lineage(
        [
            ("mfr-gw-trade:99120202075", "99120202012", None),
            ("mfr-gw-trade:99120202075", "99120202012", "5011921062164"),
        ]
    )
    assert obs.hints["supersedes"] == [{"productCode": "99120202012", "ean": "5011921062164"}]
    assert stats["lineage_links"] == 1


def test_lineage_for_a_code_with_no_observation_is_counted_not_invented():
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _attach_lineage

    stats = collections.defaultdict(int)
    _attach_lineage([("mfr-gw-trade:missing", "99120202012", "5011921062164", None, None)], {}, stats)
    assert stats["lineage_unmatched"] == 1
    assert stats["lineage_links"] == 0


def test_predecessor_is_absent_on_sheets_without_old_columns():
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _predecessor

    assert _predecessor({"Product Code": "99120202075", "Barcode": "5011921252848"}) == (
        None,
        None,
        None,
        None,
    )
    # The real header, verified live against InsertDelete18.05.2026.xlsx sheet `Code Changes`:
    # New Product Code | Old Product Code | Description | New SS Code | Old SSC Code |
    # New Barcode | Old Barcode | Trade Range | Date
    assert _predecessor(
        {
            "New Product Code": "52170299004",
            "Old Product Code": " 5217 0299003 ",
            "Old Barcode": "5011921219254",
            "Date": dt.datetime(2026, 3, 30),
        },
        "2026-07-22",
    ) == ("52170299003", "5011921219254", "2026-03-30", None)


def test_future_dated_code_change_keeps_the_pair_but_drops_the_date():
    """Dates are ingestable EXCEPT forward-looking ones -- the same policy gate that excludes
    unreleased products. The renumbering itself is still a fact; only the date is withheld."""
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _predecessor

    code, barcode, changed, _ = _predecessor(
        {
            "Old Product Code": "52170299003",
            "Old Barcode": "5011921219254",
            "Date": dt.datetime(2026, 12, 25),
        },
        "2026-07-22",
    )
    assert (code, barcode) == ("52170299003", "5011921219254")
    assert changed is None


def test_change_date_lands_on_the_supersedes_entry():
    obs, _ = _lineage([("mfr-gw-trade:99120202075", "99120202012", "5011921062164", "2026-03-30")])
    assert obs.hints["supersedes"] == [
        {"productCode": "99120202012", "ean": "5011921062164", "changedOn": "2026-03-30"}
    ]


def test_select_workbooks_excludes_legacy_xls():
    """openpyxl cannot read BIFF .xls; excluding it at selection makes that a deliberate choice
    rather than a parse failure counted against the run."""
    assets = {"https://x/a/Pricelist UK.xls": {"file_name": "Pricelist UK.xls"}}
    assert _select_workbooks(assets, ["Pricelist"]) == []


# --- phase 6: the committed normalized extract -------------------------------------------------


def test_extract_keeps_only_consumed_columns_and_never_wholesale_pricing():
    """The snapshot is a NORMALIZED EXTRACT, not a copy of the workbook. GW's wholesale
    `Trade Price`/`Cost` columns sit next to the retail data we publish and must never reach git."""
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _extract

    row = {
        "Product Code": "99120204035", "Description": "SYLVANETH: DRYADS",
        "Barcode (Single)": "5011921179398", "UKR": 30.0, "Category (ENG)": "AOS - Sylvaneth",
        "Trade Price": 15.0, "Cost": 9.5, "Qty Per Case": 6, "": None, "Blank Column": "",
    }
    assert _extract(row) == {
        "Product Code": "99120204035",
        "Description": "SYLVANETH: DRYADS",
        "Barcode (Single)": "5011921179398",
        "UKR": 30.0,
        "Category (ENG)": "AOS - Sylvaneth",
    }


def test_extracted_dates_round_trip_through_the_same_date_reader():
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _as_date, _cell

    for value in (dt.datetime(2024, 6, 3, 9, 30), dt.date(2024, 6, 3)):
        assert _cell(value) == "2024-06-03"
        assert _as_date(_cell(value)) == dt.date(2024, 6, 3)


def _snapshot(tmp_path, rows):
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _write_snapshot

    path = tmp_path / "mfr-gw-trade" / "sheets.jsonl"
    _write_snapshot(path, rows)
    return path


def test_snapshot_round_trip_preserves_row_order(tmp_path):
    """Order is load-bearing: `_merge` resolves a code seen in several workbooks by first-wins
    rules, so a replay that reorders rows would not reproduce the live result."""
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _snapshot_rows

    rows = [
        ("InsertDelete.xlsx", "Deletions", {"Product Code": "1", "Description": "A"}),
        ("InsertDelete.xlsx", "Insertions", {"Product Code": "2", "Description": "B"}),
        ("China Order Form.xlsx", "Sheet1", {"Product Code": "3", "Description": "C"}),
    ]
    stats = collections.defaultdict(int)
    assert list(_snapshot_rows(_snapshot(tmp_path, rows), stats)) == rows
    assert stats["workbooks"] == 2


def test_missing_snapshot_says_how_to_create_one(tmp_path):
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _snapshot_rows

    with pytest.raises(FileNotFoundError, match="acquire --source mfr-gw-trade"):
        list(_snapshot_rows(tmp_path / "absent.jsonl", collections.defaultdict(int)))


def test_replay_from_snapshot_rebuilds_observations_and_lineage_with_no_network(tmp_path):
    """The whole point of phase 6: with the live source unreachable (no client at all), the
    committed extract still yields the same observations, barcodes and re-coding lineage."""
    from warhub_acquisition.acquire.runner import AcquireContext
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import gw_trade_sheets_strategy
    from warhub_acquisition.models.descriptor import SourceDescriptor
    from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

    snapshot = _snapshot(tmp_path, [
        ("InsertDelete.xlsx", "Code Changes", {
            "New Product Code": "99120204035", "Description": "SYLVANETH: DRYADS",
            "New Barcode": "5011921179398", "Old Product Code": "99120204012",
            "Old Barcode": "5011921062164", "Date": "2024-06-03", "UKR": 30.0,
        }),
        ("InsertDelete.xlsx", "Deletions", {
            "Product Code": "99120204012", "Description": "SYLVANETH DRYADS",
            "Barcode (Single)": "5011921062164",
        }),
    ])
    taxonomy = Taxonomy({"games-workshop": Manufacturer(
        slug="games-workshop", name="Games Workshop", codePattern=r"\d{11}")})
    descriptor = SourceDescriptor(
        id="mfr-gw-trade", kind="manufacturer", strategy="gw-trade-sheets",
        scope={"manufacturer": "Games Workshop", "filePatterns": ["InsertDelete"]},
    )
    context = AcquireContext(
        taxonomy=taxonomy, mappings={}, run_date="2026-07-30",
        snapshot_dir=snapshot.parent, from_snapshot=True,
    )

    result = gw_trade_sheets_strategy(descriptor, None, {}, context)

    by_key = {o.key: o for o in result.observations}
    assert set(by_key) == {"mfr-gw-trade:99120204035", "mfr-gw-trade:99120204012"}
    assert by_key["mfr-gw-trade:99120204035"].ean == "5011921179398"
    assert by_key["mfr-gw-trade:99120204035"].hints["supersedes"] == [
        {"productCode": "99120204012", "ean": "5011921062164", "changedOn": "2024-06-03"}
    ]
    # the retired code's own row still lands, still carrying its own barcode
    assert by_key["mfr-gw-trade:99120204012"].ean == "5011921062164"
    assert by_key["mfr-gw-trade:99120204012"].archived is True  # Deletions-only -> withdrawn
    assert result.stats["workbooks"] == 1
    # a replay must never rewrite the file it just read
    assert "snapshot_rows" not in result.stats


# --- Excel's dropped leading zero ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (1010299044, "01010299044"),   # EU-region code typed as a NUMBER: leading zero eaten
        ("1010299044", "01010299044"),
        (2120712002, "02120712002"),
        ("99120204035", "99120204035"),  # already 11 digits: untouched
        (" 99120204035 ", "99120204035"),
        ("101010004SP", "101010004SP"),  # non-numeric codes are never padded
    ],
)
def test_code_restores_a_leading_zero_excel_dropped(raw, expected):
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _code

    assert _code(raw) == expected


def test_predecessor_code_is_zero_padded_too():
    """A retired code that lost its zero would mint an archival record for a product code that
    never existed -- and would not match the surviving catalog's 11-digit codes."""
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _predecessor

    code, _, _, _ = _predecessor({"Old Product Code": 2120712002, "New Product Code": "60010299044"})
    assert code == "02120712002"


def test_short_code_that_is_a_truncated_real_code_is_left_alone():
    """GW's own sheets carry typos. `6024999960` is `60249999604` with its LAST digit lost -- the
    real code is asserted elsewhere with the same barcode. Padding it invented `06024999960`, a
    code that has never existed, and moved a real product's barcode onto it."""
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _code

    known = frozenset({"60249999604"})
    assert _code("6024999960", known) == "6024999960"       # truncation: left to fail the pattern
    assert _code("3050208002", known) == "03050208002"      # lost leading zero: padded


# --- minting archival records for retired codes nothing observes --------------------------------


def _mint(observations):
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _mint_lineage_records

    by_key = {o.key: o for o in observations}
    stats = collections.defaultdict(int)
    _mint_lineage_records(by_key, stats)
    return by_key, stats


def test_unobserved_retired_code_gets_its_own_archival_record():
    survivor = _obs(
        key="mfr-gw-trade:99120204035", sku="99120204035", ean="5011921179398", name="DRYADS",
        hints={"supersedes": [{"productCode": "99120204012", "ean": "5011921062164",
                               "changedOn": "2024-06-03"}]},
    )
    by_key, stats = _mint([survivor])

    minted = by_key["mfr-gw-trade:99120204012"]
    assert minted.sku == "99120204012"
    assert minted.ean == "5011921062164"      # the retired barcode becomes a real, scannable record
    assert minted.archived is True            # -> status: discontinued, from the existing rules
    assert minted.hints == {"lineageDerived": True, "retiredOn": "2024-06-03"}
    assert minted.name == "DRYADS"
    assert stats["lineage_records"] == 1
    assert stats["lineage_records_with_barcode"] == 1


def test_an_observed_retired_code_is_never_overwritten_by_a_minted_one():
    real = _obs(key="mfr-gw-trade:99120204012", sku="99120204012", ean="5011921062164",
                name="SYLVANETH DRYADS")
    survivor = _obs(key="mfr-gw-trade:99120204035", sku="99120204035", ean="5011921179398",
                    hints={"supersedes": [{"productCode": "99120204012"}]})
    by_key, stats = _mint([real, survivor])

    assert by_key["mfr-gw-trade:99120204012"] is real
    assert stats["lineage_records"] == 0


def test_a_retired_code_claimed_by_two_survivors_is_not_minted():
    # A fan-out is a regional split or a filler code -- neither is a 1:1 lineage fact, and minting
    # one record for it would pick a parent at random.
    a = _obs(key="mfr-gw-trade:52170206002", sku="52170206002", ean="5011921260195",
             hints={"supersedes": [{"productCode": "52170206001"}]})
    b = _obs(key="mfr-gw-trade:54170206002", sku="54170206002", ean="5011921260218",
             hints={"supersedes": [{"productCode": "52170206001"}]})
    by_key, stats = _mint([a, b])

    assert "mfr-gw-trade:52170206001" not in by_key
    assert stats["lineage_records_ambiguous"] == 1


def test_a_malformed_code_can_never_mint_a_product():
    survivor = _obs(key="mfr-gw-trade:99120204035", sku="99120204035",
                    hints={"supersedes": [{"productCode": "5011921062164"}]})  # a barcode, not a code
    by_key, stats = _mint([survivor])

    assert len(by_key) == 1
    assert stats["lineage_records_malformed"] == 1


def test_minted_record_without_a_barcode_still_preserves_the_code():
    survivor = _obs(key="mfr-gw-trade:99121499041", sku="99121499041",
                    hints={"supersedes": [{"productCode": "99061499084"}]})
    by_key, stats = _mint([survivor])

    minted = by_key["mfr-gw-trade:99061499084"]
    assert minted.ean is None
    assert minted.sku == "99061499084"
    assert stats["lineage_records"] == 1
    assert stats["lineage_records_with_barcode"] == 0


def test_slash_dates_in_the_register_are_read_day_first():
    """A text-typed date column arrives as `01/03/2021`, which `fromisoformat` rejects -- so the
    change date was silently dropped on 192 register rows. Day-first is unambiguous on this data:
    zero of those rows have both leading fields <= 12."""
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _as_date, _predecessor

    assert _as_date("01/03/2021") == dt.date(2021, 3, 1)   # day-first, not 2021-01-03
    assert _as_date("29/02/2024") == dt.date(2024, 2, 29)
    assert _as_date("2021-03-01") == dt.date(2021, 3, 1)   # ISO still wins
    assert _as_date("31/02/2021") is None                  # impossible date, not a silent shift
    assert _as_date("not a date") is None

    _, _, changed_on, _ = _predecessor(
        {"Old Product Code": "99120204012", "Date": "03/06/2024"}, run_date="2026-07-30"
    )
    assert changed_on == "2024-06-03"


def test_old_ssc_column_is_kept_in_the_extract_before_anything_reads_it():
    """GW's SS Code is the product's identity across a re-code, so `Old SSC Code` is what tells a
    real predecessor from a stale regional edition. A whitelist only keeps what it is told to, and
    a durable extract must not discard a column just because today's parser ignores it."""
    from warhub_acquisition.acquire.strategies.gw_trade_sheets import _extract

    row = {"Old Product Code": "99120204012", "Old SSC Code": "48-88", "New SS Code": "55-24",
           "Trade Price": 15.0}
    extracted = _extract(row)
    assert extracted["Old SSC Code"] == "48-88"
    assert extracted["New SS Code"] == "55-24"
    assert "Trade Price" not in extracted
