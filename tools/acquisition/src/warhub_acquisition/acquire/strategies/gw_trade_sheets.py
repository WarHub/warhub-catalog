"""GW trade-site spreadsheet strategy: manufacturer-authoritative EANs from trade.games-workshop.com.

Registered as `STRATEGIES["gw-trade-sheets"]`. Enumerates the PUBLIC media library on Games
Workshop's retailer-network site, downloads the barcode-bearing workbooks, and emits one
Observation per product row. See `docs/research/2026-07-22-gw-trade-barcode-retrieval.md` for the
live probe this is built from (endpoint mechanics, full file inventory, measured yield, and the
terms assessment).

**Why this source exists at all.** Every prior probe concluded GW publishes no EANs on its own web
properties (`docs/research/2026-07-12-source-probe-manufacturers.md`) and that its trade order
forms were auth-walled (`2026-07-16-trade-order-sheets.md`). Both are wrong: the trade site serves
spreadsheets carrying retail EAN-13s from `/assets/YYYY/MM/<name>`, listed by an unauthenticated
REST route. `robots.txt` is fully open (`User-agent: *` / empty `Disallow:`).

## Enumeration

`GET {baseUrl}/wp-json/gw/v2/media?fe=1&type=118&order=desc&per_page=100&page=N&lang=en&country=C`
with an `X-WP-Nonce` header. Three non-obvious mechanics, each of which independently makes the
endpoint look empty or gated if you get it wrong:

1. **`country` must be the NUMERIC id** (220 = United Kingdom). Passing the country *name* returns
   `total_items: 0` with HTTP 200 -- indistinguishable from "no such data" and the single reason
   the previous probe reported a login wall.
2. **The nonce is public**, printed into `/resources/` HTML as `var gwAssetData = {"nonce":"..."}`.
   It is NOT a credential (requests succeed with no cookie and no session) but it IS required, and
   it rotates -- hence `_scrape_nonce`, which re-reads it at the start of every run rather than
   pinning a value in the descriptor.
3. **`type=118`** ("Printable Materials") is the documents bucket: ~468 items per country versus
   5,270 unfiltered, and every barcode-bearing spreadsheet found carries it. Enumerating unfiltered
   costs 10x the requests for the same yield.

Asset visibility is country-scoped and the slices genuinely differ (totals range 5,109-5,927), so
`scope.countries` fans out. Several barcode files exist ONLY in non-UK slices.

## Rate limiting -- the failure mode that silently truncates

The host 429s under load, and (verified 2026-07-22) **the media API degrades to a HTTP 200 with an
empty `assets` array rather than returning 429**. A paginator that reads `len(assets)` therefore
concludes "end of results" and reports success having collected a fraction of the data. During the
investigation this was initially misdiagnosed as a hard 1,800-item pagination cap; it is not, and
pages 19-53 return data normally at >=8s spacing.

`_fetch_page` therefore treats "empty assets before `total_items` is satisfied" as a RETRYABLE
THROTTLE, not as end-of-results, and gives up loudly (FetchError) rather than quietly. This is the
single most important behaviour in this module -- without it the source under-reports and its
contract still passes.

## Rows -> Observations

`key = f"{descriptor.id}:{product_code}"`, `sku` = GW's 11-digit product code (the join key the
catalog already stores as `productCode`), `ean` = the row's barcode, `name` = the trade
description. `manufacturer` is PINNED to `scope.manufacturer` ("Games Workshop") -- trade sheets
carry no vendor column, same situation as `mfr-gw-algolia`/`arc-gw-webstore`, resolved through
`Taxonomy.manufacturer_for_vendor`.

**Deletions rows set `archived=True`.** That is the existing, code-free lever for discontinued
products: `resolve/attributes.py` derives `status="discontinued"` for an entity with no
non-archived member. It also means a Deletions row can never flip a fresh entity to `current`.

Three data hazards, each measured and gated (research doc SS4.2):

- **`_GS1_PREFIXES` allowlist is mandatory, not defensive.** ~85 rows carry 12-digit GW-INTERNAL
  codes (11-digit product code + check digit, e.g. `608899990183` for code `60889999018`).
  `ean.normalize_ean` zero-pads 12-digit input into EAN-13 as UPC-A, so these pass
  `canonical_ean` cleanly and would be stored as retail barcodes. Only `5011921` (GW's GS1 prefix)
  and `977`/`978`/`979` (Bookland, for Black Library ISBN-13s) are accepted.
- **14-digit `Barcode (6-Pack)` values are GTIN-14 case codes**, not retail barcodes. Never read
  that column; `Barcode (Single)` is the unit EAN.
- **Future-dated rows are dropped** (`_release_date_is_future`). GW's Trade Terms define
  Confidential Information to expressly include "product release dates" and unreleased product
  info; excluding not-yet-released rows keeps that class of data out of the catalog entirely. This
  is a deliberate policy gate, not a data-quality one -- see the research doc SS6.

Prices: only RRP columns are read. Measured against 822 overlapping catalog products, the regional
`UKR` column has median(sheet/catalog priceGbp) = 1.000, i.e. it IS the retail price. The separate
`Trade Price`/`Cost` columns are wholesale (~64-65% of RRP) and are never read.

`full_sweep` is always False: this is a budgeted slice of workbooks, not a population census of
GW's range, and must never drive miss-streak/liveness decisions for products it does not list.
"""
from __future__ import annotations

import datetime as _dt
import io
import re
from typing import Iterator

from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation

# GW's own GS1 company prefix, plus the Bookland prefixes that carry Black Library ISBN-13s.
# Anything else in a Barcode column is not a retail barcode -- see the module docstring.
_GS1_PREFIXES: tuple[str, ...] = ("5011921", "977", "978", "979")

_NONCE_RE = re.compile(r"gwAssetData\s*=\s*\{\s*\"nonce\"\s*:\s*\"([0-9a-f]+)\"")

# The media API's documents bucket ("Printable Materials").
_DOC_TYPE = 118

_SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm")


def _scrape_nonce(client: PoliteClient, base_url: str, resources_path: str) -> str:
    """Read the public REST nonce out of the /resources/ HTML.

    Not a credential: the endpoint serves the same data to an anonymous client with no cookie. It
    does rotate, so it is re-read every run rather than pinned in the descriptor.
    """
    html = client.get_text(f"{base_url.rstrip('/')}{resources_path}")
    match = _NONCE_RE.search(html)
    if match is None:
        raise FetchError(
            f"{base_url}{resources_path}: no gwAssetData nonce in page HTML -- the resources page "
            "changed shape, or the response was an edge block rather than the real page",
            status=None,
        )
    return match.group(1)


def _fetch_page(
    client: PoliteClient,
    base_url: str,
    nonce: str,
    country: int,
    page: int,
    *,
    expect_more: bool,
) -> dict:
    """One media-API page, distinguishing a real empty page from a silent throttle.

    `expect_more` is True while the caller still has items outstanding per `total_items`. In that
    state an empty `assets` array CANNOT be end-of-results, so it is treated as a throttle and
    raised as a rate-limited FetchError (the runner's degraded-run path) rather than being accepted
    as "no more data". See the module docstring -- this is the difference between a short run that
    reports failure and a short run that reports success.
    """
    payload, _headers = client.get_json_response(
        f"{base_url.rstrip('/')}/wp-json/gw/v2/media",
        params={
            "fe": 1,
            "type": _DOC_TYPE,
            "order": "desc",
            "per_page": 100,
            "page": page,
            "lang": "en",
            "country": country,
        },
        headers={"X-WP-Nonce": nonce},
    )
    if not isinstance(payload, dict):
        raise FetchError(f"media page {page} (country {country}): non-object payload", status=None)
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise FetchError(f"media page {page} (country {country}): no assets array", status=None)
    if not assets and expect_more:
        raise FetchError(
            f"media page {page} (country {country}): empty assets array while items remain "
            "outstanding -- GW's edge degrades to an empty 200 under load instead of 429; "
            "treating as a throttle rather than end-of-results",
            status=200,
            rate_limited=True,
        )
    return payload


def _enumerate_assets(
    client: PoliteClient, base_url: str, nonce: str, countries: list[int]
) -> dict[str, dict]:
    """Union of type-118 documents across every configured country slice, keyed by file_url."""
    found: dict[str, dict] = {}
    for country in countries:
        page = 1
        seen = 0
        total: int | None = None
        while True:
            payload = _fetch_page(
                client,
                base_url,
                nonce,
                country,
                page,
                expect_more=total is not None and seen < total,
            )
            if total is None:
                raw_total = payload.get("total_items")
                total = int(raw_total) if isinstance(raw_total, int) else 0
            assets = payload.get("assets") or []
            if not assets:
                break
            for asset in assets:
                url = asset.get("file_url")
                if isinstance(url, str) and url:
                    found.setdefault(url, asset)
            seen += len(assets)
            if seen >= total:
                break
            page += 1
    return found


def _select_workbooks(assets: dict[str, dict], patterns: list[str]) -> list[tuple[str, dict]]:
    """Assets whose file name matches a configured pattern and is a readable workbook.

    Patterns are matched case-insensitively against the file name. Legacy `.xls` (BIFF) is
    deliberately NOT selected: openpyxl cannot read it, the only such file on the site is a
    price-change list with no unique barcodes, and silently skipping it inside the parser would
    look like a parse failure rather than a deliberate exclusion.
    """
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    out: list[tuple[str, dict]] = []
    for url, asset in sorted(assets.items()):
        name = str(asset.get("file_name") or url.rsplit("/", 1)[-1])
        if not name.lower().endswith(_SPREADSHEET_SUFFIXES):
            continue
        if any(rx.search(name) for rx in compiled):
            out.append((url, asset))
    return out


def _rows(sheet) -> Iterator[dict]:
    """Header-keyed rows, tolerating the leading note/banner rows some GW sheets carry.

    The AU/NZ price files put a paragraph of RRP small print in row 1 and the real header in row 2,
    so the header is taken to be the first row with >=3 non-empty cells rather than simply row 1.
    """
    header: list[str] | None = None
    for raw in sheet.iter_rows(values_only=True):
        cells = ["" if c is None else str(c).strip() for c in raw]
        if header is None:
            if sum(1 for c in cells if c) >= 3:
                header = cells
            continue
        if not any(cells):
            continue
        yield dict(zip(header, raw))


def _first(row: dict, *names: str):
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _clean_ean(raw) -> str | None:
    """Canonical EAN-13, gated on GW's GS1 prefixes.

    The prefix gate is what stops GW's 12-digit internal codes -- which `canonical_ean` happily
    zero-pads into a valid-looking EAN-13 -- from being stored as retail barcodes.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) != 13:
        # 14-digit GTIN-14 case codes and 11/12-digit internal codes are not retail barcodes.
        return None
    ean = canonical_ean(digits)
    if ean is None or not ean.startswith(_GS1_PREFIXES):
        return None
    return ean


def _as_date(value) -> _dt.date | None:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _release_date_is_future(row: dict, run_date: str) -> bool:
    """True when the row describes a product not yet released as of the run date.

    Policy gate, not a data-quality one: GW's Trade Terms name "product release dates" and
    unreleased product information as Confidential Information, so unreleased rows are excluded
    from the catalog entirely. Rows with no release-date column are never excluded by this.
    """
    released = _as_date(_first(row, "Release Date (Global)", "Release Date", "Release Date (China)"))
    if released is None:
        return False
    try:
        today = _dt.date.fromisoformat(run_date)
    except ValueError:
        return False
    return released > today


def _price(row: dict, *names: str) -> float | None:
    """An RRP column, or None. Never reads `Trade Price`/`Cost` -- those are wholesale."""
    value = _first(row, *names)
    if value is None:
        return None
    try:
        price = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return price if price > 0 else None


def _merge(existing: Observation, fresh: Observation) -> Observation:
    """Fold a second row for the same product code into the observation already built for it.

    The same code legitimately appears in several workbooks -- the InsertDelete register lists it,
    and the current Trade Direct Range prices it -- and the naive last-wins dict assignment threw
    data away in both directions: `priceGbp` only exists on the Trade Direct Range rows, so
    whichever workbook happened to sort last (InsertDelete, having no price column) blanked it.

    Rules:
    - **Scalars: first non-null wins.** A later row must never overwrite a populated field with
      `None`. Where both are populated the earlier value is kept, so behaviour does not depend on
      filename sort order.
    - **`hints` merge**, so an SSC code from one sheet and a trade category from another both
      survive.

    `archived` is deliberately NOT decided here -- see `_is_discontinued`. It cannot be a pairwise
    fold: the correct answer depends on which KIND of sheet each sighting came from, which a
    two-observation merge cannot see.
    """
    merged = existing.model_copy(deep=True)
    for field in ("name", "sku", "ean", "priceGbp", "priceUsd", "priceEur", "url", "imageUrl"):
        if getattr(merged, field, None) is None:
            setattr(merged, field, getattr(fresh, field, None))
    for key, value in fresh.hints.items():
        merged.hints.setdefault(key, value)
    return merged


def _sheet_role(sheet_title: str) -> str:
    """Classify a sheet as evidence of withdrawal, of current availability, or neither.

    This distinction is load-bearing and easy to get wrong. The InsertDelete workbook is a
    HISTORICAL REGISTER, not a snapshot of today's range:

    - `Deletions` -- the product left the trade range on the row's date. Evidence of withdrawal.
    - `Insertions` -- the product ENTERED the range on the row's date. This says nothing about
      whether it is still sold: 1,683 codes (measured, 2026-07-22) appear in BOTH Insertions and
      Deletions, i.e. they were added and later withdrawn, and are genuinely discontinued. Treating
      an Insertions row as evidence of currency wrongly revives every one of them.
    - `Code Changes` -- a renumbering record; likewise says nothing about current availability.
    - Everything else (Trade Direct Range `Sheet1`, the paint/brush sheets) is a CURRENT range
      listing: presence there means GW sells it today, which legitimately overrides a stale
      Deletions row for a re-introduced product.
    """
    title = sheet_title.strip().lower()
    if title == "deletions":
        return "withdrawn"
    if title in ("insertions", "code changes"):
        return "historical"
    return "current"


def _is_discontinued(roles: set[str]) -> bool:
    """A product is discontinued iff something withdrew it and nothing current still lists it."""
    return "withdrawn" in roles and "current" not in roles


def gw_trade_sheets_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
        raise RuntimeError(
            f"{descriptor.id}: openpyxl is required to parse GW trade workbooks "
            "(`uv sync` in tools/acquisition)"
        ) from exc

    stats = {
        "workbooks": 0,
        "rows": 0,
        "emitted": 0,
        "skipped_no_ean": 0,
        "skipped_bad_prefix": 0,
        "skipped_unreleased": 0,
        "parse_errors": 0,
    }

    base_url = descriptor.baseUrl or "https://trade.games-workshop.com"
    scope = descriptor.scope
    # scope.manufacturer is the vendor NAME ("Games Workshop"); observations must carry the
    # taxonomy SLUG ("games-workshop"). Resolving through manufacturer_for_vendor is what makes
    # these rows join the existing GW entities -- emitting the raw name instead silently mints a
    # parallel 10th manufacturer and duplicates the whole GW catalog (measured: +7,999 products
    # and +7,157 conflicts on a resolve). Same mechanism as algolia.py/woo.py's pinned sources.
    manufacturer_name = str(scope.get("manufacturer") or "Games Workshop")
    manufacturer = context.taxonomy.manufacturer_for_vendor(manufacturer_name)
    if manufacturer is None:
        raise ValueError(
            f"{descriptor.id}: scope.manufacturer {manufacturer_name!r} is not a known vendor name "
            "in data/catalog/taxonomy/manufacturers.yaml (it must be a name/vendorName, not a slug)"
        )
    resources_path = str(scope.get("resourcesPath") or "/resources/")
    countries = [int(c) for c in (scope.get("countries") or [220])]  # type: ignore[union-attr]
    patterns = [str(p) for p in (scope.get("filePatterns") or [])]  # type: ignore[union-attr]
    if not patterns:
        raise ValueError(f"{descriptor.id}: scope.filePatterns is required")

    nonce = _scrape_nonce(client, base_url, resources_path)
    assets = _enumerate_assets(client, base_url, nonce, countries)
    workbooks = _select_workbooks(assets, patterns)
    if context.budget is not None:
        workbooks = workbooks[: context.budget]

    observations: dict[str, Observation] = {}
    # Per-product provenance across every sheet of every workbook, resolved into `archived` once
    # the whole harvest is in -- see _sheet_role / _is_discontinued.
    roles: dict[str, set[str]] = {}
    run_date = context.run_date

    for url, asset in workbooks:
        try:
            payload = client.get_response(url).content
            book = openpyxl.load_workbook(io.BytesIO(payload), data_only=True, read_only=True)
        except (FetchError, Exception):  # noqa: BLE001 - a bad workbook must not fail the run
            stats["parse_errors"] += 1
            continue
        stats["workbooks"] += 1

        try:
            for sheet in book.worksheets:
                role = _sheet_role(sheet.title)
                for row in _rows(sheet):
                    stats["rows"] += 1
                    code = _first(row, "Product Code", "New Product Code", "Unit Code", "Individual Code")
                    name = _first(row, "Description", "Description (ENG)", "PRODUCT NAME",
                                  "Product Description", "Product Name")
                    if code is None or name is None:
                        continue
                    if _release_date_is_future(row, run_date):
                        stats["skipped_unreleased"] += 1
                        continue

                    raw_barcode = _first(row, "Barcode (Single)", "New Individual barcode",
                                         "Barcode", "New Barcode")
                    ean = _clean_ean(raw_barcode)
                    if ean is None:
                        if raw_barcode is None:
                            stats["skipped_no_ean"] += 1
                        else:
                            stats["skipped_bad_prefix"] += 1
                        continue

                    sku = re.sub(r"\s+", "", str(code))
                    key = f"{descriptor.id}:{sku}"
                    hints: dict[str, object] = {}
                    ssc = _first(row, "SS Code", "SSC", "New SS Code", "Short Code")
                    if ssc is not None:
                        hints["sscCode"] = str(ssc).strip()
                    category = _first(row, "Category (ENG)", "Range", "Trade range")
                    if category is not None:
                        hints["tradeCategory"] = str(category).strip()

                    fresh = Observation(
                        key=key,
                        manufacturer=manufacturer,
                        name=str(name).strip(),
                        sku=sku,
                        ean=ean,
                        priceGbp=_price(row, "UKR"),
                        hints=hints,
                        firstSeen=run_date,
                        lastSeen=run_date,
                        # Provisional; finalised from `roles` once every workbook is parsed.
                        archived=False,
                        extractor="gw-trade-sheets",
                    )
                    existing = observations.get(key)
                    observations[key] = fresh if existing is None else _merge(existing, fresh)
                    roles.setdefault(key, set()).add(role)
                    stats["emitted"] += 1
        finally:
            book.close()

    for key, observation in observations.items():
        observation.archived = _is_discontinued(roles.get(key, set()))
    stats["discontinued"] = sum(1 for o in observations.values() if o.archived)

    return StrategyResult(
        observations=list(observations.values()),
        # Never a population census: a budgeted slice of workbooks must not drive liveness.
        full_sweep=False,
        stats=stats,
        cursor=cursor,
    )


STRATEGIES["gw-trade-sheets"] = gw_trade_sheets_strategy
