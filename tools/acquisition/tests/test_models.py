"""Model round-trip: priceCad (and its currency siblings) survive dump/validate untouched."""
from warhub_acquisition.models.catalog import CanonicalProduct
from warhub_acquisition.models.observation import Observation


def test_observation_price_cad_round_trips() -> None:
    observation = Observation(
        key="ret-tistaminis:necrons", name="Combat Patrol: Necrons", manufacturer="games-workshop",
        priceGbp=76.5, priceUsd=99.0, priceEur=89.0, priceCad=105.0,
        firstSeen="2026-07-13", lastSeen="2026-07-13", extractor="shopify@1",
    )
    dumped = observation.model_dump(mode="json")
    assert dumped["priceCad"] == 105.0
    restored = Observation.model_validate(dumped)
    assert restored == observation


def test_observation_price_cad_defaults_to_none() -> None:
    observation = Observation(
        key="ret-tistaminis:necrons", name="Combat Patrol: Necrons", manufacturer="games-workshop",
        firstSeen="2026-07-13", lastSeen="2026-07-13", extractor="shopify@1",
    )
    assert observation.priceCad is None


def test_canonical_product_price_cad_round_trips() -> None:
    product = CanonicalProduct(
        id="games-workshop/99120110052", name="Combat Patrol: Necrons", manufacturer="games-workshop",
        status="current", firstSeen="2026-07-13", priceGbp=76.5, priceUsd=99.0, priceEur=89.0, priceCad=105.0,
    )
    dumped = product.model_dump(mode="json", exclude_none=True)
    assert dumped["priceCad"] == 105.0
    # field order: priceCad must sit immediately after priceEur, like the other currency
    # fields declared before it -- this is what keeps the canonical YAML writer's output
    # ordering stable across the cross-stack golden fixture.
    keys = list(dumped.keys())
    assert keys.index("priceCad") == keys.index("priceEur") + 1
    restored = CanonicalProduct.model_validate(dumped)
    assert restored == product
