"""barcode-db strategy: inverted-flow candidate selection (reads the resolved catalog, not a
source enumeration), the two db queriers (upcitemdb JSON, Go-UPC HTML heading), the title-sanity
gate, and miss/error counting.

Fixture provenance (`tests/fixtures/barcode_db/`), all captured LIVE 2026-07-13 via curl at <=1
req/s (3 requests total) -- see `barcode_db.py`'s module docstring for full detail:

- `upcitemdb-hit.json`: real `GET https://api.upcitemdb.com/prod/trial/lookup?upc=5011921146000`
  response. Real title "Space Marines Stormraven Gunship Warhammer 40,000", brand
  "Citadel Miniatures", model "99120101088".
- `upcitemdb-miss.json`: real `GET .../lookup?upc=5011921194285` response -- `{"total": 0,
  "items": []}` (the probe doc's documented upcitemdb gap for this EAN).
- `goupc-hit.html`: real `GET https://go-upc.com/search?q=5011921146000` response, trimmed to the
  head `<title>` and the product-details block. Real `<h1 class="product-name">Games Workshop
  Warhammer 40K: Space Marines Stormraven Gunship</h1>` and a `Brand` metadata row of
  "Games Workshop".
"""
from pathlib import Path

import httpx
import pytest

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.barcode_db import (
    _select_provisional_candidates,
    _title_sanity_ok,
    barcode_db_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy
from warhub_acquisition.yamlio import write_yaml

FIXTURES = Path(__file__).parent / "fixtures" / "barcode_db"

STORMRAVEN_EAN = "5011921146000"  # probe-verified real GW EAN
NECRONS_EAN = "5011921194285"  # probe-verified real GW EAN (upcitemdb 0-item miss)


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "games-workshop": Manufacturer(
                slug="games-workshop",
                name="Games Workshop",
                gs1Prefixes=["5011921"],
                vendorNames=["Games Workshop", "Citadel", "Forge World"],
            ),
            "wyrd-games": Manufacturer(slug="wyrd-games", name="Wyrd Games", vendorNames=["Wyrd Games"]),
        }
    )


def write_catalog(catalog_dir: Path, manufacturer: str, products: list[dict]) -> None:
    write_yaml(catalog_dir / f"{manufacturer}.yaml", {"manufacturer": manufacturer, "products": products})


def product(
    entity_id: str,
    ean: str | None,
    ean_confidence: str | None,
    manufacturer: str = "games-workshop",
    name: str = "Stormraven Gunship",
) -> dict:
    record: dict = {"id": entity_id, "name": name, "manufacturer": manufacturer}
    if ean is not None:
        record["ean"] = ean
    if ean_confidence is not None:
        record["eanConfidence"] = ean_confidence
    return record


def context(
    catalog_dir: Path | None, budget: int | None = None, run_date: str = "2026-07-13"
) -> AcquireContext:
    return AcquireContext(taxonomy=taxonomy(), mappings={}, run_date=run_date, budget=budget, catalog_dir=catalog_dir)


def upcitemdb_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="bdb-upcitemdb", kind="barcode-db", strategy="barcode-db",
        baseUrl="https://api.upcitemdb.com", scope={"db": "upcitemdb"},
    )


def goupc_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="bdb-goupc", kind="barcode-db", strategy="barcode-db",
        baseUrl="https://go-upc.com", scope={"db": "go-upc"},
    )


def test_strategy_is_registered() -> None:
    assert STRATEGIES["barcode-db"] is barcode_db_strategy


# --- Inverted-flow candidate selection: provisional-only, sorted, budget-capped -----------------


def test_selects_only_provisional_entities_sorted_by_id(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(
        catalog_dir, "games-workshop",
        [
            product("games-workshop/b-second", STORMRAVEN_EAN, "provisional"),
            product("games-workshop/a-first", NECRONS_EAN, "provisional"),
            product("games-workshop/c-confirmed", "5011921142361", "confirmed"),
            product("games-workshop/d-no-ean", None, None),
        ],
    )
    candidates = _select_provisional_candidates(catalog_dir)
    assert candidates == [
        ("games-workshop/a-first", NECRONS_EAN, "games-workshop"),
        ("games-workshop/b-second", STORMRAVEN_EAN, "games-workshop"),
    ]


def test_selects_across_multiple_manufacturer_files_sorted_globally(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(catalog_dir, "wyrd-games", [product("wyrd-games/z-item", "5060393709671", "provisional", manufacturer="wyrd-games")])
    write_catalog(catalog_dir, "games-workshop", [product("games-workshop/a-item", STORMRAVEN_EAN, "provisional")])
    candidates = _select_provisional_candidates(catalog_dir)
    assert [c[0] for c in candidates] == ["games-workshop/a-item", "wyrd-games/z-item"]


def test_missing_catalog_dir_returns_no_candidates(tmp_path: Path) -> None:
    assert _select_provisional_candidates(tmp_path / "nonexistent") == []


def test_budget_caps_candidates_queried(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(
        catalog_dir, "games-workshop",
        [
            product("games-workshop/a", STORMRAVEN_EAN, "provisional"),
            product("games-workshop/b", NECRONS_EAN, "provisional"),
        ],
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=load_text("upcitemdb-hit.json"))

    client = PoliteClient(
        "https://api.upcitemdb.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    result = barcode_db_strategy(upcitemdb_descriptor(), client, {}, context(catalog_dir, budget=1))
    assert result.stats["queried"] == 1
    assert len(calls) == 1
    assert "upc=5011921146000" in calls[0]  # the sorted-first candidate (a's ean), not b's


def test_no_catalog_dir_on_context_raises(tmp_path: Path) -> None:
    client = PoliteClient("https://api.upcitemdb.com", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ValueError, match="catalog_dir"):
        barcode_db_strategy(upcitemdb_descriptor(), client, {}, context(None))


def test_unknown_db_scope_raises(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    descriptor = SourceDescriptor(
        id="bdb-mystery", kind="barcode-db", strategy="barcode-db", baseUrl="https://example.test",
        scope={"db": "not-a-real-db"},
    )
    client = PoliteClient("https://example.test", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ValueError, match="not-a-real-db"):
        barcode_db_strategy(descriptor, client, {}, context(catalog_dir))


# --- upcitemdb: real fixture hit / miss ----------------------------------------------------------


def test_upcitemdb_real_fixture_hit_corroborates_with_pinned_manufacturer(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(catalog_dir, "games-workshop", [product("games-workshop/41-10", STORMRAVEN_EAN, "provisional")])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prod/trial/lookup"
        assert request.url.params["upc"] == STORMRAVEN_EAN
        return httpx.Response(200, text=load_text("upcitemdb-hit.json"))

    client = PoliteClient(
        "https://api.upcitemdb.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    result = barcode_db_strategy(upcitemdb_descriptor(), client, {}, context(catalog_dir))

    assert result.stats == {"queried": 1, "corroborated": 1, "misses": 0, "mismatched_title": 0, "fetch_errors": 0}
    assert len(result.observations) == 1
    obs = result.observations[0]
    assert obs.key == f"bdb-upcitemdb:{STORMRAVEN_EAN}"
    assert obs.ean == STORMRAVEN_EAN
    assert obs.name == "Space Marines Stormraven Gunship Warhammer 40,000"  # real db title, verbatim
    assert obs.manufacturer == "games-workshop"  # PINNED from the catalog entity, not derived from db text
    assert obs.archived is False
    assert obs.url is None  # upcitemdb doesn't reliably expose a canonical product url -- omitted
    assert obs.priceGbp is None and obs.priceUsd is None and obs.priceEur is None
    assert obs.extractor == "barcode-db@1"
    assert result.full_sweep is False
    assert result.cursor == {}


def test_upcitemdb_real_fixture_zero_items_is_a_miss(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(catalog_dir, "games-workshop", [product("games-workshop/49-04", NECRONS_EAN, "provisional")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=load_text("upcitemdb-miss.json"))

    client = PoliteClient(
        "https://api.upcitemdb.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    result = barcode_db_strategy(upcitemdb_descriptor(), client, {}, context(catalog_dir))

    assert result.observations == []
    assert result.stats == {"queried": 1, "corroborated": 0, "misses": 1, "mismatched_title": 0, "fetch_errors": 0}


# --- Go-UPC: real fixture hit + synthetic miss -----------------------------------------------


def test_goupc_real_fixture_hit_corroborates(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(catalog_dir, "games-workshop", [product("games-workshop/41-10", STORMRAVEN_EAN, "provisional")])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params["q"] == STORMRAVEN_EAN
        return httpx.Response(200, text=load_text("goupc-hit.html"))

    client = PoliteClient("https://go-upc.com", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = barcode_db_strategy(goupc_descriptor(), client, {}, context(catalog_dir))

    assert result.stats == {"queried": 1, "corroborated": 1, "misses": 0, "mismatched_title": 0, "fetch_errors": 0}
    obs = result.observations[0]
    assert obs.key == f"bdb-goupc:{STORMRAVEN_EAN}"
    assert obs.name == "Games Workshop Warhammer 40K: Space Marines Stormraven Gunship"  # real heading, verbatim
    assert obs.manufacturer == "games-workshop"
    assert obs.ean == STORMRAVEN_EAN
    assert obs.url is None


def test_goupc_no_heading_match_is_a_miss(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(catalog_dir, "games-workshop", [product("games-workshop/x", STORMRAVEN_EAN, "provisional")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body><p>No results found.</p></body></html>")

    client = PoliteClient("https://go-upc.com", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = barcode_db_strategy(goupc_descriptor(), client, {}, context(catalog_dir))

    assert result.observations == []
    assert result.stats["misses"] == 1


# --- Title-sanity gate ---------------------------------------------------------------------------


def test_title_sanity_matches_manufacturer_name() -> None:
    assert _title_sanity_ok({"title": "Games Workshop Widget", "brand": ""}, "games-workshop", taxonomy())


def test_title_sanity_matches_vendor_name_case_insensitively() -> None:
    assert _title_sanity_ok({"title": "some widget", "brand": "CITADEL miniatures"}, "games-workshop", taxonomy())


def test_title_sanity_rejects_unrelated_product_and_emits_nothing(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(catalog_dir, "games-workshop", [product("games-workshop/x", STORMRAVEN_EAN, "provisional")])

    unrelated = (
        '{"code":"OK","total":1,"offset":0,"items":[{"ean":"' + STORMRAVEN_EAN
        + '","title":"Totally Unrelated Garden Hose","brand":"Acme Hoses"}]}'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=unrelated)

    client = PoliteClient(
        "https://api.upcitemdb.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    result = barcode_db_strategy(upcitemdb_descriptor(), client, {}, context(catalog_dir))

    assert result.observations == []
    assert result.stats == {"queried": 1, "corroborated": 0, "misses": 0, "mismatched_title": 1, "fetch_errors": 0}


def test_title_sanity_unresolvable_manufacturer_slug_rejects() -> None:
    assert not _title_sanity_ok({"title": "Games Workshop Widget", "brand": ""}, "nonexistent-slug", taxonomy())


# --- FetchError handling ---------------------------------------------------------------------


def test_fetch_error_counted_and_run_continues(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(
        catalog_dir, "games-workshop",
        [
            product("games-workshop/a", STORMRAVEN_EAN, "provisional"),
            product("games-workshop/b", NECRONS_EAN, "provisional"),
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["upc"] == STORMRAVEN_EAN:
            return httpx.Response(500, text="down")  # retried 3x by PoliteClient, still fails
        return httpx.Response(200, text=load_text("upcitemdb-miss.json"))

    client = PoliteClient(
        "https://api.upcitemdb.com", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    result = barcode_db_strategy(upcitemdb_descriptor(), client, {}, context(catalog_dir))

    assert result.stats == {"queried": 2, "corroborated": 0, "misses": 1, "mismatched_title": 0, "fetch_errors": 1}
    assert result.observations == []


# --- full_sweep / cursor -----------------------------------------------------------------------


def test_full_sweep_always_false_and_cursor_stateless(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(catalog_dir, "games-workshop", [product("games-workshop/x", STORMRAVEN_EAN, "provisional")])

    client = PoliteClient(
        "https://api.upcitemdb.com",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=load_text("upcitemdb-hit.json"))),
        sleep=lambda s: None,
    )
    result = barcode_db_strategy(upcitemdb_descriptor(), client, {}, context(catalog_dir))
    assert result.full_sweep is False
    assert result.cursor == {}


def test_no_provisional_entities_queries_nothing(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog" / "products"
    catalog_dir.mkdir(parents=True)
    write_catalog(catalog_dir, "games-workshop", [product("games-workshop/x", "5011921142361", "confirmed")])

    client = PoliteClient(
        "https://api.upcitemdb.com",
        transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError("no request expected"))),
    )
    result = barcode_db_strategy(upcitemdb_descriptor(), client, {}, context(catalog_dir))
    assert result.observations == []
    assert result.stats["queried"] == 0
