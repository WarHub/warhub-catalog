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


def test_manufacturer_barcode_is_authoritative_over_disagreeing_retailer() -> None:
    # A live manufacturer lists its own barcode; a retailer disagrees. The manufacturer is
    # authoritative for its OWN barcodes, so it wins the primary and the retailer's barcode is kept
    # as an additional (retired/variant) barcode -- the disagreement is resolved, not flagged.
    resolution = resolve_ean(
        "e", [obs("mfr-w:1", "5060393709671"), obs("ret-a:1", "5011921194285")], KINDS
    )
    assert resolution.ean == "5060393709671"
    assert resolution.additional == ["5011921194285"]
    assert resolution.confidence == "confirmed"
    assert resolution.conflicts == []


def test_two_barcode_dbs_alone_stay_provisional() -> None:
    resolution = resolve_ean(
        "e", [obs("db-upc:1", "5060393709671"), obs("db-goupc:1", "5060393709671")],
        {**KINDS, "db-goupc": "barcode-db"},
    )
    assert resolution.confidence == "provisional"


def test_mismatch_tiebreak_is_lexicographic_for_equal_strength() -> None:
    resolution = resolve_ean(
        "e", [obs("ret-a:1", "5060393709671"), obs("ret-b:1", "5011921194285")], KINDS
    )
    assert resolution.confidence == "conflicted"
    assert resolution.ean == "5011921194285"  # equal kind+count -> lexicographically smallest


def test_single_source_asserting_two_eans_is_conflicted() -> None:
    resolution = resolve_ean(
        "e", [obs("ret-a:1", "5060393709671"), obs("ret-a:2", "5011921194285")], KINDS
    )
    assert resolution.confidence == "conflicted"
    assert len(resolution.conflicts) == 1


# --- multi-EAN repackaging (a product joined across a new box/barcode) ------------------------

REPACK_KINDS = {"legacy-catalog": "curated", "mfr-m": "manufacturer", "ret-t": "retailer", "arc-x": "archive"}


def obsx(key: str, ean: str | None, *, archived: bool = False, missStreak: int = 0) -> Observation:
    return Observation(
        key=key, name="X", manufacturer="mantic-games",
        firstSeen="2026-07-12", lastSeen="2026-07-12", extractor="t@1",
        ean=ean, archived=archived, missStreak=missStreak,
    )


def test_repackaging_join_promotes_live_barcode_and_keeps_old_as_additional() -> None:
    # OLD barcode attested only by a superseded (folded-in old-code) curated obs; the NEW barcode by
    # a live manufacturer + retailer. Primary = NEW (confirmed); OLD retained in `additional`, never
    # dropped; no conflict (a legitimate repackaging, not a same-code disagreement).
    members = [
        obsx("legacy-catalog:old", "5060469664330"),   # superseded old-packaging barcode
        obsx("mfr-m:new", "5060924985581"),
        obsx("ret-t:new", "5060924985581"),
    ]
    r = resolve_ean("mantic-games/NEW", members, REPACK_KINDS, superseded=frozenset({"legacy-catalog:old"}))
    assert r.ean == "5060924985581"
    assert r.additional == ["5060469664330"]
    assert r.confidence == "confirmed"
    assert r.conflicts == []


def test_repackaging_prefers_live_barcode_over_stale_curated_in_primary_pool() -> None:
    # Both barcodes sit on the SURVIVING code (a disagreement -> still flagged conflicted), but the
    # primary must be the LIVE manufacturer barcode, not the archived curated one that outranks it
    # on kind alone. A folded-in old barcode puts this on the repackaging path.
    members = [
        obsx("legacy-catalog:surv", "5060469664330", archived=True),  # surviving, NOT live
        obsx("mfr-m:surv", "5060924985581"),                          # surviving, live
        obsx("arc-x:old", "5011921194285"),                           # superseded old barcode
    ]
    r = resolve_ean("e", members, REPACK_KINDS, superseded=frozenset({"arc-x:old"}))
    assert r.ean == "5060924985581"           # liveness beats curated kind-priority
    assert r.confidence == "conflicted"       # surviving code still carries two barcodes
    assert r.additional == ["5011921194285"]  # the folded-in old barcode is retained


def test_superseded_barcode_never_becomes_primary_even_if_higher_kind() -> None:
    # The folded-in (superseded) barcode is asserted by a manufacturer (kind 1) while the surviving
    # one is a lone retailer (kind 2). Supersession still keeps the surviving barcode primary and
    # the manufacturer's old barcode in `additional` -- a repackaging is code-anchored, not a kind
    # contest.
    members = [
        obsx("mfr-m:old", "5060469664330"),   # superseded, manufacturer -- but old packaging
        obsx("ret-t:new", "5060924985581"),   # surviving, retailer
    ]
    r = resolve_ean("e", members, REPACK_KINDS, superseded=frozenset({"mfr-m:old"}))
    assert r.ean == "5060924985581"
    assert r.additional == ["5060469664330"]
    assert r.confidence == "provisional"      # lone retailer -> provisional, from the primary alone


def test_retailer_only_disagreement_stays_conflicted_with_no_additional() -> None:
    # No manufacturer barcode -- just two retailers disagreeing (retailers make barcode-entry
    # errors). The historical `conflicted` semantics are preserved and NO additionalEans are
    # produced: the resolver must not silently pick a winner or invent a repackaging from retailer
    # noise. The primary is still the least-stale/lexicographic choice, but the flag stays up.
    members = [obsx("ret-t:1", "5060393709671"), obsx("ret-x:1", "5011921194285")]
    r = resolve_ean("e", members, {**REPACK_KINDS, "ret-x": "retailer"})
    assert r.confidence == "conflicted"
    assert r.additional == []


def test_live_manufacturer_barcode_beats_stale_legacy_and_retires_it() -> None:
    # The stale-primary bug this fix targets: legacy (curated) lists an OLD barcode on the code and
    # a live manufacturer lists the CURRENT one. Manufacturer is authoritative -> current is primary,
    # the stale legacy barcode is retired to additionalEans, and the conflict clears. Before the fix
    # the curated kind (priority 0) would have won the primary and kept the entity conflicted.
    members = [obsx("legacy-catalog:1", "5060469664330"), obsx("mfr-m:1", "5060924985581")]
    r = resolve_ean("e", members, REPACK_KINDS)
    assert r.ean == "5060924985581"
    assert r.additional == ["5060469664330"]
    assert r.confidence == "confirmed"
    assert r.conflicts == []


def test_manufacturer_barcode_under_other_code_is_not_authoritative() -> None:
    # Akhelian-shape: a repackage brought an OLD code into this entity, so the manufacturer's OLD
    # barcode arrives under a DIFFERENT code than the surviving one. Only the manufacturer barcode on
    # the SURVIVING code is authoritative; the old-code manufacturer barcode is retired, not treated
    # as a second live-manufacturer barcode that would keep the entity conflicted.
    members = [
        obsx("mfr-m:new", "5060924985581"),   # surviving code
        obsx("mfr-m:old", "5060469664330"),   # old code, still a live (non-archived) trade row
        obsx("ret-t:old", "5060469664330"),
    ]
    member_codes = {"mfr-m:new": "CUR", "mfr-m:old": "OLD", "ret-t:old": "CUR"}
    r = resolve_ean("e", members, REPACK_KINDS, surviving_code="CUR", member_codes=member_codes)
    assert r.ean == "5060924985581"
    assert r.additional == ["5060469664330"]
    assert r.confidence == "confirmed"


def test_bridged_different_product_barcode_keeps_conflict_visible() -> None:
    # A retailer mis-coded a DIFFERENT product's barcode onto this entity: it is only ever carried
    # under a foreign code, never the surviving one (the Zodgrod-vs-Beast-Snagga-army-set shape).
    # The authoritative manufacturer barcode is still the primary, but the bridged barcode must NOT
    # be silently absorbed as a retired version -- keep it conflicted and visible so a human can
    # split it, rather than hiding the bad merge.
    members = [
        obsx("mfr-m:surv", "5060924985581"),                          # surviving code, authoritative
        obsx("mfr-m:foreign", "5060469664330", archived=True),        # a different product's code
    ]
    member_codes = {"mfr-m:surv": "CUR", "mfr-m:foreign": "FOREIGN"}
    r = resolve_ean("e", members, REPACK_KINDS, surviving_code="CUR", member_codes=member_codes)
    assert r.ean == "5060924985581"
    assert r.confidence == "conflicted"
    assert r.additional == []


def test_two_live_manufacturer_barcodes_on_surviving_code_stay_conflicted() -> None:
    # The manufacturer itself lists two live barcodes for the SAME surviving code -> genuinely
    # ambiguous, so it stays flagged rather than one silently retiring the other.
    members = [obsx("mfr-m:1", "5060924985581"), obsx("mfr-m:2", "5060469664330")]
    member_codes = {"mfr-m:1": "CUR", "mfr-m:2": "CUR"}
    r = resolve_ean("e", members, REPACK_KINDS, surviving_code="CUR", member_codes=member_codes)
    assert r.confidence == "conflicted"
    assert r.additional == []


def test_single_barcode_entity_has_empty_additional() -> None:
    r = resolve_ean("e", [obsx("mfr-m:1", "5060393709671")], REPACK_KINDS)
    assert r.ean == "5060393709671"
    assert r.additional == []
    assert r.confidence == "confirmed"


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


def test_additional_ean_colliding_with_another_entitys_primary_reported() -> None:
    # A repackaged product's retired barcode (in additionalEans) colliding with another entity's
    # primary is a data error just like a primary/primary collision -- it must surface, with the
    # additional-side holder named under `additionalIn`. A non-colliding additional barcode ("c")
    # raises nothing.
    resolutions = {
        "a": EanResolution("5060393709671", "confirmed", []),
        "b": EanResolution("5011921194285", "confirmed", [], ["5060393709671"]),
        "c": EanResolution("5060924985581", "confirmed", [], ["5060469664330"]),
    }
    shared = find_shared_eans(resolutions)
    assert shared == [
        {
            "type": "ean-shared",
            "ean": "5060393709671",
            "entities": ["a", "b"],
            "additionalIn": ["b"],
        }
    ]
