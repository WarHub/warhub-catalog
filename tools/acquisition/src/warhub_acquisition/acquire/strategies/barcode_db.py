"""Barcode-db corroboration strategy: upcitemdb trial API + Go-UPC web lookup.

Registered as `STRATEGIES["barcode-db"]`. Unlike every other strategy in this package, the flow is
INVERTED: instead of enumerating a source's own product listing, this strategy reads the CURRENT
RESOLVED catalog (`data/catalog/products/*.yaml`, reached via `context.catalog_dir` -- see
`AcquireContext.catalog_dir` and `runner.run_source`, which populates it from
`paths.catalog_products` on every call) and looks for entities whose `eanConfidence` is exactly
`"provisional"` (a single non-barcode-db source asserted the ean; nothing has corroborated it yet).
For each such entity, up to `context.budget` of them (sorted by entity id for determinism), it
queries an independent barcode database for the SAME ean and, if the db's answer looks like the
same product, emits a CORROBORATING observation -- never an originating one. See
`docs/research/2026-07-12-source-probe-retailers-barcodedb.md` for the live probe this is built
from (both DBs' endpoints, hit-rate expectations, and the three known-good GW EANs).

**Two backends, one strategy function**, selected by `descriptor.scope["db"]` (mirrors
`cdx_archive.py`'s `scope.extractor` dispatch pattern):

- `"upcitemdb"`: `GET https://api.upcitemdb.com/prod/trial/lookup?upc=<ean>` (`baseUrl` +
  `/prod/trial/lookup`). Free trial, ~100 requests/day (probe-verified) -- `data/catalog/sources/
  bdb-upcitemdb.yaml` documents this as `budget.requestsPerRun: 80`, but that field is NEVER read
  by this module; `context.budget` (the CLI `--budget` flag) is the only thing that actually caps
  a run, exactly like every other strategy. Response JSON: `{"items": [...]}`; zero items is a
  miss. A single non-empty-title item's `title` becomes the emitted `name`; its `brand` feeds the
  title-sanity check below (see the live fixture: EAN `5011921146000`'s title is "Space Marines
  Stormraven Gunship Warhammer 40,000" -- it does NOT itself contain "Games Workshop"/"Citadel"/
  "Forge World", but `brand` is "Citadel Miniatures", which does. upcitemdb's `title` field alone
  is therefore an unreliable manufacturer signal for GW products; `brand` is real, upcitemdb-
  supplied text about the same item, not an inference from ean prefix or anything else, so folding
  it into the sanity check is still checking what the db itself claims about the product, just a
  second field of the same response).
- `"go-upc"`: `GET https://go-upc.com/search?q=<ean>` (HTML, guest/anonymous -- no auth). Live
  fixture (EAN `5011921146000`) confirms the product-name heading is
  `<h1 class="product-name">Games Workshop Warhammer 40K: Space Marines Stormraven Gunship</h1>`
  and a metadata table row `<td class="metadata-label">Brand</td><td>Games Workshop</td>` --
  `_GOUPC_HEADING_RE`/`_GOUPC_BRAND_RE` extract those two, HTML-unescaped and tag-stripped. No
  heading match (a "no results" page, or any markup change) is a miss.

**Title-sanity gate**: the db's `title` and `brand` (Go-UPC's heading text plus its own Brand
metadata row) are joined into one case-folded string and checked for a case-insensitive substring
match against the entity's manufacturer's `name` OR any `vendorNames` (from `context.taxonomy`,
loaded from `data/catalog/taxonomy/manufacturers.yaml`) -- a hit against a DIFFERENT product (same
ean prefix range, wrong item, a merchant's mislabeled listing, ...) must never corroborate. No
match: `stats["mismatched_title"] += 1`, nothing emitted for that ean -- the miss is silent by
design (a bad match is not evidence of anything, positive or negative, about the entity's real
ean).

**Observations**: `key = f"{descriptor.id}:{ean}"` (the SAME ean read from the catalog -- this
strategy can only ever assert an ean it was handed, never invent one), `ean` = that same ean,
`name` = the db's title, `manufacturer` = the ENTITY's manufacturer slug, PINNED from the catalog
record -- never derived from db text (the sanity check only gates emission; it never substitutes
for the pinned value). `archived` is always `False` (a barcode-db hit says nothing about archival
status). No `url`/prices: neither db reliably exposes a canonical PRODUCT url (upcitemdb's `offers`
link is a click-tracking redirect through upcitemdb's own domain, not the underlying retailer's
page; Go-UPC's own page isn't a retailer/manufacturer product page either) -- both are simply
omitted rather than populated with something misleading.

**Never mints entities**: every ean this strategy ever asserts was read directly from an existing
catalog entity's `ean` field (never derived, guessed, or parsed from db text) -- structurally, a
barcode-db observation's ean always matches SOME existing entity's ean for the same manufacturer.
`resolve/join.py` additionally enforces this defensively (a barcode-db observation whose
(manufacturer, ean) matches no OTHER source's assertion is dropped and reported, never name-joined
into a fresh entity) -- see `join_observations`'s `non_barcode_db_eans` guard and its
`"barcode-db-unjoined"` ambiguous-report type.

**Never confirms alone**: `kind: barcode-db` is already ranked below `retailer` in
`models.descriptor.KIND_PRIORITY` and `resolve/corroborate.py`'s `resolve_ean` already requires at
least one NON-barcode-db source among >=2 distinct sources before flipping `confirmed` (see
`test_corroborate.py::test_barcode_db_alone_never_confirms` /
`test_two_barcode_dbs_alone_stay_provisional`, both pre-existing) -- a barcode-db observation's
entire value is as a SECOND, independent source alongside whichever non-barcode-db source already
asserted the ean provisionally.

**`full_sweep` is hard-coded `False`, always** -- a budget-limited slice of "whichever entities are
currently provisional, sorted by id" is not a sweep of any population, live or archived; the
budgeted slice mechanism itself doubles as forward progress across runs (once an entity is
corroborated, its `eanConfidence` stops being `"provisional"` on the NEXT `resolve` -- it falls out
of this strategy's candidate list on its own, no cursor bookkeeping needed here at all; this
strategy is intentionally stateless, `cursor` is always `{}`).

Stats: `queried` (candidates selected within budget), `corroborated`, `misses` (0 items / no
heading match), `mismatched_title`, `fetch_errors` (a `FetchError` -- including a persistent 429
after `PoliteClient`'s own retry/backoff is exhausted -- is caught per-candidate, counted, and the
run continues with the next candidate; a persistent quota exhaustion therefore shows up as a run
where every candidate lands in `fetch_errors`, not as an uncaught `SOURCE ERROR`, since a partial
network outage saying nothing about any one candidate is not the same class of problem as
`cdx_archive.py`'s garbled-showNumPages case, which WOULD poison a cache if swallowed -- this
strategy has no cache to poison). `queried == corroborated + misses + mismatched_title +
fetch_errors` always.

Fixture provenance (`tests/fixtures/barcode_db/`), all captured LIVE 2026-07-13 via curl at <=1
req/s (3 requests total; EANs from the probe doc's verified GW cross-checks):
`upcitemdb-hit.json` (real `GET .../lookup?upc=5011921146000` response -- title "Space Marines
Stormraven Gunship Warhammer 40,000", brand "Citadel Miniatures", model "99120101088"),
`upcitemdb-miss.json` (real `GET .../lookup?upc=5011921194285` response -- `{"total": 0, "items":
[]}`, confirming the probe doc's documented upcitemdb gap for this EAN), `goupc-hit.html` (real
`GET https://go-upc.com/search?q=5011921146000` response, trimmed to the head title + the
product-details block containing the `h1.product-name` heading and the EAN/Brand/Category metadata
table -- everything else, e.g. nav chrome, description prose, the additional-attributes list,
scripts, was cut).
"""
import html as html_lib
import re
from pathlib import Path
from typing import Callable

from warhub_acquisition.acquire.client import FetchError, PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, StrategyResult
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import read_yaml

EXTRACTOR = "barcode-db@1"

UPCITEMDB_LOOKUP_PATH = "/prod/trial/lookup"
GOUPC_SEARCH_PATH = "/search"

_TAG_RE = re.compile(r"<[^>]+>")
_GOUPC_HEADING_RE = re.compile(r'<h1[^>]*class="product-name"[^>]*>(.*?)</h1>', re.S)
_GOUPC_BRAND_RE = re.compile(
    r'<td[^>]*class="metadata-label"[^>]*>\s*Brand\s*</td>\s*<td[^>]*>(.*?)</td>', re.S | re.I
)


def _clean_text(raw: str) -> str:
    return html_lib.unescape(_TAG_RE.sub("", raw)).strip()


# --- DB queriers -------------------------------------------------------------------------------
# Each returns `{"title": str, "brand": str}` on a hit (brand may be "" if the db carries none) or
# `None` on a miss. Neither raises on a miss -- only `FetchError` (network/politeness failure)
# propagates, caught once by the shared loop in `barcode_db_strategy`.


def _query_upcitemdb(client: PoliteClient, ean: str) -> dict[str, str] | None:
    payload = client.get_json(UPCITEMDB_LOOKUP_PATH, params={"upc": ean})
    items = payload.get("items") if isinstance(payload, dict) else None
    if not items:
        return None
    item = items[0]
    if not isinstance(item, dict):
        return None
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    return {"title": title, "brand": str(item.get("brand") or "").strip()}


def _query_goupc(client: PoliteClient, ean: str) -> dict[str, str] | None:
    html = client.get_response(GOUPC_SEARCH_PATH, params={"q": ean}).text
    heading_match = _GOUPC_HEADING_RE.search(html)
    if not heading_match:
        return None
    title = _clean_text(heading_match.group(1))
    if not title:
        return None
    brand_match = _GOUPC_BRAND_RE.search(html)
    brand = _clean_text(brand_match.group(1)) if brand_match else ""
    return {"title": title, "brand": brand}


_QUERIERS: dict[str, Callable[[PoliteClient, str], dict[str, str] | None]] = {
    "upcitemdb": _query_upcitemdb,
    "go-upc": _query_goupc,
}


# --- Title-sanity gate ---------------------------------------------------------------------------


def _title_sanity_ok(record: dict[str, str], manufacturer_slug: str, taxonomy: Taxonomy) -> bool:
    spec = taxonomy.manufacturers.get(manufacturer_slug)
    if spec is None:
        return False
    folded = f"{record['title']} {record['brand']}".casefold()
    return any(candidate and candidate.casefold() in folded for candidate in (spec.name, *spec.vendorNames))


# --- Inverted-flow candidate selection: read the resolved catalog, not a source enumeration ------


def _select_provisional_candidates(catalog_dir: Path) -> list[tuple[str, str, str]]:
    """`(entity_id, ean, manufacturer_slug)` for every catalog entity with `eanConfidence:
    provisional`, sorted by entity id. Reads `paths.catalog_products/*.yaml` (the resolved
    catalog written by `resolve/resolver.py`) directly -- this strategy's entire input is the
    OUTPUT of a prior resolve, not any source's raw listing."""
    candidates: list[tuple[str, str, str]] = []
    if not catalog_dir.exists():
        return candidates
    for path in sorted(catalog_dir.glob("*.yaml")):
        data = read_yaml(path) or {}
        for product in data.get("products", []) or []:
            if product.get("eanConfidence") != "provisional":
                continue
            entity_id = product.get("id")
            ean = product.get("ean")
            manufacturer = product.get("manufacturer")
            if not entity_id or not ean or not manufacturer:
                continue
            candidates.append((str(entity_id), str(ean), str(manufacturer)))
    candidates.sort(key=lambda c: c[0])
    return candidates


# --- Strategy --------------------------------------------------------------------------------


def barcode_db_strategy(
    descriptor: SourceDescriptor,
    client: PoliteClient,
    cursor: dict,
    context: AcquireContext,
) -> StrategyResult:
    stats = {"queried": 0, "corroborated": 0, "misses": 0, "mismatched_title": 0, "fetch_errors": 0}

    db_name = str(descriptor.scope.get("db"))
    querier = _QUERIERS.get(db_name)
    if querier is None:
        raise ValueError(f"{descriptor.id}: unknown barcode-db source {db_name!r}")

    if context.catalog_dir is None:
        raise ValueError(
            f"{descriptor.id}: AcquireContext.catalog_dir is not set -- the barcode-db strategy "
            "reads the resolved catalog and cannot run without it (run_source populates this "
            "automatically; direct strategy calls in tests must set it explicitly)"
        )

    candidates = _select_provisional_candidates(context.catalog_dir)
    budget = context.budget
    to_query = candidates if budget is None else candidates[: max(budget, 0)]
    stats["queried"] = len(to_query)

    observations: list[Observation] = []
    for _entity_id, ean, manufacturer_slug in to_query:
        try:
            record = querier(client, ean)
        except FetchError:
            stats["fetch_errors"] += 1
            continue

        if record is None:
            stats["misses"] += 1
            continue

        if not _title_sanity_ok(record, manufacturer_slug, context.taxonomy):
            stats["mismatched_title"] += 1
            continue

        stats["corroborated"] += 1
        observations.append(
            Observation(
                key=f"{descriptor.id}:{ean}",
                manufacturer=manufacturer_slug,
                name=record["title"],
                ean=ean,
                archived=False,
                firstSeen=context.run_date,
                lastSeen=context.run_date,
                extractor=EXTRACTOR,
            )
        )

    return StrategyResult(
        observations=observations,
        # ALWAYS False -- see module docstring: the budgeted "still provisional" slice is not a
        # sweep of any population, and forward progress across runs comes from entities falling
        # out of the provisional candidate list once corroborated, not from missStreak decay.
        full_sweep=False,
        stats=stats,
        # Stateless by design -- see module docstring. Nothing to cache across runs.
        cursor={},
    )


STRATEGIES["barcode-db"] = barcode_db_strategy
