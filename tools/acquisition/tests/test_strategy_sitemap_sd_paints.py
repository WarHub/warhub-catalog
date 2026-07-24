"""Sitemap-sd-paints strategy (Green Stuff World): sitemap filtering, Product-scoped microdata
extraction (mpn-as-sku, gtin13, EUR price, ml-from-title), budget/cursor/give-up flow.

Fixture provenance: every fixture under fixtures/sitemap_sd_paints/ is REAL markup captured
live from greenstuffworld.com on 2026-07-24 and trimmed (regions joined with `<!-- trimmed -->`
markers; values untouched) -- see the recon notes in
docs/research/2026-07-23-paint-manufacturer-harvest-design.md (Wave 3):

- `gsw-sitemap-en.xml`: real head + six real `<url>` entries from `1_en_0_sitemap.xml`
  (CDATA-wrapped locs, `<image:image><image:loc>` children), incl. the `/en/122-acrylic-paints`
  category landing page and a non-paint rolling-pin product.
- `gsw-product-1864.html`: Acrylic Color WONKA VIOLET (the known catalog-gap paint; mpn 3220,
  gtin13 8435646505800, discounted price content 2.592) -- breadcrumb block kept so the
  "first itemprop=name is 'Home'" trap stays live.
- `gsw-product-2417.html`: Dipping ink 60 ml - PAPYRUS DIP (mpn 3481, gtin13 8435646508412;
  the 60 ml and 17 ml papyrus variants are SEPARATE products on this store).
- `gsw-category-122.html`: real category page -- no schema.org/Product itemtype anywhere (the
  parse-miss / give-up-cap fixture).
"""
from pathlib import Path

import httpx

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext
from warhub_acquisition.acquire.strategies.sitemap_sd_paints import (
    _availability,
    _ml,
    _parse_product,
    sitemap_sd_paints_strategy,
)
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

FIXTURES = Path(__file__).parent / "fixtures" / "sitemap_sd_paints"

BASE = "https://www.greenstuffworld.com"
WONKA_PATH = "/en/acrylic-paints/1864-acrylic-color-wonka-violet.html"
PAPYRUS_PATH = "/en/dipping-inks/2417-dipping-ink-60-ml-papyrus-dip.html"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def gsw_taxonomy() -> Taxonomy:
    return Taxonomy(
        {
            "green-stuff-world": Manufacturer(
                slug="green-stuff-world",
                name="Green Stuff World",
                vendorNames=["Green Stuff World", "GSW"],
                gs1Prefixes=["8435646", "8436574"],
            )
        }
    )


def descriptor(**extra_scope: object) -> SourceDescriptor:
    return SourceDescriptor(
        id="mfr-greenstuffworld",
        kind="manufacturer",
        strategy="sitemap-sd-paints",
        baseUrl=BASE,
        scope={
            "manufacturer": "Green Stuff World",
            "sitemaps": [f"{BASE}/1_en_0_sitemap.xml"],
            # Deliberately LOOSER than the production descriptor's /\d+- anchored regex: this
            # also matches the real /en/122-acrylic-paints category landing page, so the
            # non-product-URL guard is exercised against a real sitemap entry.
            "urlInclude": r"(acrylic-paints|dipping-inks)",
            **extra_scope,
        },
    )


def context(taxonomy: Taxonomy | None = None, budget: int | None = None) -> AcquireContext:
    return AcquireContext(
        taxonomy=taxonomy or gsw_taxonomy(), mappings={}, run_date="2026-07-24", budget=budget
    )


def transport(
    calls: list[str] | None = None,
    drift_details: bool = False,
    not_found: set[str] | None = None,
    wonka_html: str | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        if path == "/1_en_0_sitemap.xml":
            return httpx.Response(200, text=load_fixture("gsw-sitemap-en.xml"))
        if path in (WONKA_PATH, PAPYRUS_PATH):
            product_id = "1864" if path == WONKA_PATH else "2417"
            if not_found is not None and product_id in not_found:
                return httpx.Response(404, text="not found")
            if drift_details:
                return httpx.Response(200, text=load_fixture("gsw-category-122.html"))
            if product_id == "1864":
                return httpx.Response(200, text=wonka_html or load_fixture("gsw-product-1864.html"))
            return httpx.Response(200, text=load_fixture("gsw-product-2417.html"))
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def run(
    budget: int | None = None,
    cursor: dict | None = None,
    calls: list[str] | None = None,
    taxonomy: Taxonomy | None = None,
    drift_details: bool = False,
    not_found: set[str] | None = None,
    wonka_html: str | None = None,
):
    client = PoliteClient(
        BASE,
        transport=transport(calls, drift_details, not_found, wonka_html),
        sleep=lambda s: None,
    )
    return sitemap_sd_paints_strategy(descriptor(), client, cursor or {}, context(taxonomy, budget))


def observation(result, product_id: str):
    return next(o for o in result.observations if o.key == f"mfr-greenstuffworld:{product_id}")


def test_strategy_is_registered() -> None:
    assert STRATEGIES["sitemap-sd-paints"] is sitemap_sd_paints_strategy


# --- Enumeration: urlInclude filter + product-URL shape guard -----------------------------------


def test_sitemap_filtering_and_product_url_parse() -> None:
    calls: list[str] = []
    result = run(calls=calls)

    assert result.stats["fetched_sitemaps"] == 1  # single urlset, no index nesting
    # 6 real locs; the <image:loc> CDATA grandchildren must never be collected as page locs.
    assert result.stats["sitemap_urls_total"] == 6
    # urlInclude keeps 122-acrylic-paints (category), wonka, papyrus; /en/, /en/best-sales and
    # the rolling-pin product are excluded before any fetch.
    assert result.stats["sitemap_urls_filtered"] == 3
    assert result.stats["skipped_non_product"] == 1  # the category landing page
    assert result.stats["products_enumerated"] == 2
    # Only the two product pages were fetched beyond the sitemap itself.
    assert {c for c in calls if "sitemap" not in c} == {f"{BASE}{WONKA_PATH}", f"{BASE}{PAPYRUS_PATH}"}


# --- Product-scoped microdata extraction --------------------------------------------------------


def test_wonka_violet_extraction_mpn_as_sku_and_reference_hint() -> None:
    result = run()
    wonka = observation(result, "1864")
    # The breadcrumb's first itemprop="name" is "Home" -- the Product-scoped slice must win.
    assert wonka.name == "Acrylic Color WONKA VIOLET"
    assert wonka.sku == "3220"  # meta itemprop=mpn: the true paint number
    assert wonka.ean == "8435646505800"  # meta itemprop=gtin13
    assert wonka.priceEur == 2.592  # discounted pre-rounding content value, EUR-confirmed
    assert wonka.availability == "in_stock"  # <link itemprop=availability href=.../InStock>
    assert wonka.imageUrl == f"{BASE}/29144-large_default/acrylic-color-wonka-violet.jpg"
    assert wonka.manufacturer == "green-stuff-world"
    assert wonka.url == f"{BASE}{WONKA_PATH}"
    assert wonka.extractor == "sitemap-sd-paints@1"
    assert wonka.hints["category"] == "paint"
    assert wonka.hints["categorySlug"] == "acrylic-paints"
    # The EAN+'ES' store reference differs from the mpn-derived sku -> rides along in hints.
    assert wonka.hints["reference"] == "8435646505800ES"
    assert "ml" not in wonka.hints  # no volume in this product name

    assert result.stats["eans_found"] == 2
    assert result.stats["prices_found"] == 2
    assert result.full_sweep is True


def test_papyrus_dip_extraction_parses_ml_from_title() -> None:
    result = run()
    papyrus = observation(result, "2417")
    assert papyrus.name == "Dipping ink 60 ml - PAPYRUS DIP"
    assert papyrus.sku == "3481"
    assert papyrus.ean == "8435646508412"
    assert papyrus.priceEur == 3.7375
    assert papyrus.hints["categorySlug"] == "dipping-inks"
    assert papyrus.hints["ml"] == 60
    assert papyrus.hints["reference"] == "8435646508412ES"
    assert result.stats["ml_parsed"] == 1


def test_reference_becomes_sku_when_mpn_is_absent() -> None:
    # Same real page minus its mpn meta -- the store reference is the sku fallback, and the
    # then-redundant hints.reference disappears.
    wonka_no_mpn = load_fixture("gsw-product-1864.html").replace(
        '<meta itemprop="mpn" content="3220" />', ""
    )
    result = run(wonka_html=wonka_no_mpn)
    wonka = observation(result, "1864")
    assert wonka.sku == "8435646505800ES"
    assert "reference" not in wonka.hints


def test_price_is_dropped_when_currency_is_not_eur() -> None:
    # Guard against a geo/currency-module drift: a non-EUR priceCurrency must never land in
    # priceEur.
    wonka_usd = load_fixture("gsw-product-1864.html").replace(
        '<meta itemprop="priceCurrency" content="EUR">',
        '<meta itemprop="priceCurrency" content="USD">',
    )
    result = run(wonka_html=wonka_usd)
    assert observation(result, "1864").priceEur is None
    assert result.stats["prices_found"] == 1  # papyrus (still EUR) keeps its price


def test_parse_product_unit_availability_and_ml_helpers() -> None:
    parsed = _parse_product(load_fixture("gsw-product-1864.html"))
    assert parsed == {
        "name": "Acrylic Color WONKA VIOLET",
        "reference": "8435646505800ES",
        "mpn": "3220",
        "ean": "8435646505800",
        "priceEur": 2.592,
        "availability": "in_stock",
        "imageUrl": f"{BASE}/29144-large_default/acrylic-color-wonka-violet.jpg",
    }
    assert _parse_product(load_fixture("gsw-category-122.html")) == {}  # no Product itemtype
    assert _availability('<link itemprop="availability" href="https://schema.org/OutOfStock"/>') == "out_of_stock"
    assert _ml("Dipping ink 17 ml - Papyrus Dip") == 17
    assert _ml("Chameleon colorshift 52ml") == 52  # no space before the unit
    assert _ml("Acrylic Color FANG WHITE") is None


# --- Budget / cursor discipline -----------------------------------------------------------------


def test_budget_zero_defers_all_details_and_observes_nothing() -> None:
    result = run(budget=0)
    assert result.stats["details_fetched"] == 0
    # A sitemap loc carries no fields -- unlike mr_hobby there is no listing tier, so an
    # unfetched id contributes NO observation.
    assert result.observations == []
    assert result.cursor["pending_details"] == ["1864", "2417"]
    assert result.full_sweep is False


def test_budget_one_fetches_lowest_new_id_first() -> None:
    calls: list[str] = []
    result = run(budget=1, calls=calls)
    assert result.stats["details_fetched"] == 1
    assert [c for c in calls if "sitemap" not in c] == [f"{BASE}{WONKA_PATH}"]  # 1864 < 2417
    assert [o.key for o in result.observations] == ["mfr-greenstuffworld:1864"]
    assert result.cursor["pending_details"] == ["2417"]
    assert result.full_sweep is False


def test_cursor_carries_parsed_details_forward_without_refetch() -> None:
    first = run()
    calls: list[str] = []
    second = run(cursor=first.cursor, calls=calls)
    assert not any(c.endswith(".html") for c in calls if "sitemap" not in c)
    assert second.stats["details_fetched"] == 0
    wonka = observation(second, "1864")
    assert wonka.sku == "3220"
    assert wonka.ean == "8435646505800"
    assert wonka.priceEur == 2.592
    assert wonka.hints["reference"] == "8435646505800ES"
    assert second.full_sweep is True


def test_partial_budget_resumes_from_pending_queue() -> None:
    first = run(budget=1)
    assert first.full_sweep is False
    calls: list[str] = []
    second = run(cursor=first.cursor, calls=calls)
    # Only the pending id is fetched -- 1864's parsed detail is carried, never re-fetched.
    assert [c for c in calls if "sitemap" not in c] == [f"{BASE}{PAPYRUS_PATH}"]
    assert second.stats["details_fetched"] == 1
    assert len(second.observations) == 2
    assert second.cursor["pending_details"] == []
    assert second.full_sweep is True


def test_cursor_prunes_ids_no_longer_in_the_filtered_sitemap() -> None:
    stale_cursor = {
        "details": {"9999": {"name": "Delisted Paint", "ean": "8435646500000"}},
        "pending_details": [],
    }
    result = run(cursor=stale_cursor)
    assert "9999" not in result.cursor["details"]
    assert not any(o.key.endswith(":9999") for o in result.observations)


# --- 404 / parse-miss give-up flow --------------------------------------------------------------


def test_404_detail_caps_immediately_and_never_blocks_full_sweep() -> None:
    result = run(not_found={"2417"})
    assert result.stats["detail_not_found"] == 1
    assert result.stats["detail_fetch_errors"] == 0
    assert result.cursor["details"]["2417"] == {"detailMisses": 3}
    assert result.cursor["pending_details"] == []
    assert result.full_sweep is True
    # No page, no fields, no observation -- but the sweep claim stands.
    assert [o.key for o in result.observations] == ["mfr-greenstuffworld:1864"]
    # And the dead loc is never fetched again once capped.
    calls: list[str] = []
    run(cursor=result.cursor, calls=calls, not_found={"2417"})
    assert not any("2417" in c for c in calls if "sitemap" not in c)


def test_transient_fetch_error_stays_pending_and_blocks_full_sweep() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/1_en_0_sitemap.xml":
            return httpx.Response(200, text=load_fixture("gsw-sitemap-en.xml"))
        if request.url.path == WONKA_PATH:
            return httpx.Response(200, text=load_fixture("gsw-product-1864.html"))
        return httpx.Response(500, text="down")  # papyrus: retried by PoliteClient, still fails

    client = PoliteClient(BASE, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = sitemap_sd_paints_strategy(descriptor(), client, {}, context())
    assert result.stats["detail_fetch_errors"] == 1
    assert result.cursor["pending_details"] == ["2417"]
    assert "2417" not in result.cursor["details"]  # errors never count against the miss cap
    assert result.full_sweep is False


def test_give_up_cap_stops_retrying_unparseable_pages() -> None:
    cursor: dict = {}
    for expected_misses in (1, 2, 3):
        result = run(cursor=cursor, drift_details=True)
        assert result.stats["details_fetched"] == 2
        assert result.stats["detail_parse_misses"] == 2
        assert result.cursor["details"]["1864"] == {"detailMisses": expected_misses}
        assert result.full_sweep is False  # still pending below the cap
        cursor = result.cursor
    final = run(cursor=cursor, drift_details=True)
    assert final.stats["details_fetched"] == 0
    assert final.cursor["pending_details"] == []
    assert final.full_sweep is True
    assert final.observations == []  # nothing ever parsed -- nothing observable


# --- Pinned manufacturer attribution ------------------------------------------------------------


def test_unknown_pinned_vendor_fetches_nothing_and_observes_nothing() -> None:
    # Taxonomy without green-stuff-world: the pinned scope.manufacturer cannot resolve. The
    # fixture pages DO carry brand microdata ("Green Stuff World") -- it must be ignored
    # (attribution is pinned via taxonomy, never read off a theme block), so nothing is
    # fetched and nothing is observed; the descriptor's minCount then fails the run loudly.
    other = Taxonomy(
        {"vallejo": Manufacturer(slug="vallejo", name="Vallejo", vendorNames=["Vallejo"])}
    )
    calls: list[str] = []
    result = run(taxonomy=other, calls=calls)
    assert result.stats["skipped_unknown_vendor"] == 2
    assert result.stats["details_fetched"] == 0
    assert [c for c in calls if "sitemap" not in c] == []
    assert result.observations == []
