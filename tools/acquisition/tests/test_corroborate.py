from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.corroborate import EanResolution, find_shared_eans, resolve_ean

KINDS = {"mfr-w": "manufacturer", "ret-a": "retailer", "ret-b": "retailer", "db-upc": "barcode-db"}


def obs(key: str, ean: str | None) -> Observation:
    return Observation(
        key=key, name="X", manufacturer="warlord-games",
        firstSeen="2026-07-12", lastSeen="2026-07-12", extractor="t@1", ean=ean,
    )


def test_manufacturer_assertion_confirms() -> None:
    resolution = resolve_ean("e", [obs("mfr-w:1", "5060393709671")], KINDS)
    assert resolution.ean == "5060393709671"
    assert resolution.confidence == "confirmed"


def test_two_retailers_confirm() -> None:
    resolution = resolve_ean("e", [obs("ret-a:1", "5060393709671"), obs("ret-b:1", "5060393709671")], KINDS)
    assert resolution.confidence == "confirmed"


def test_single_retailer_is_provisional() -> None:
    assert resolve_ean("e", [obs("ret-a:1", "5060393709671")], KINDS).confidence == "provisional"


def test_barcode_db_alone_never_confirms() -> None:
    resolution = resolve_ean("e", [obs("db-upc:1", "5060393709671")], KINDS)
    assert resolution.confidence == "provisional"
    resolution = resolve_ean("e", [obs("db-upc:1", "5060393709671"), obs("ret-a:1", "5060393709671")], KINDS)
    assert resolution.confidence == "confirmed"  # db + retailer = two independent sources


def test_invalid_ean_ignored() -> None:
    resolution = resolve_ean("e", [obs("ret-a:1", "5011921194286")], KINDS)  # bad checksum
    assert resolution.ean is None
    assert resolution.confidence is None


def test_mismatch_is_conflicted_and_reported() -> None:
    resolution = resolve_ean(
        "e", [obs("mfr-w:1", "5060393709671"), obs("ret-a:1", "5011921194285")], KINDS
    )
    assert resolution.confidence == "conflicted"
    assert resolution.ean == "5060393709671"  # manufacturer kind wins
    assert resolution.conflicts[0]["type"] == "ean-mismatch"


def test_shared_ean_across_entities_reported() -> None:
    resolutions = {
        "a": EanResolution("5060393709671", "confirmed", []),
        "b": EanResolution("5060393709671", "provisional", []),
        "c": EanResolution(None, None, []),
    }
    shared = find_shared_eans(resolutions)
    assert shared == [
        {"type": "ean-shared", "ean": "5060393709671", "entities": ["a", "b"]}
    ]
