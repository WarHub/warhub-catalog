"""EAN corroboration: confidence from independent source agreement.

An entity normally carries one barcode. A product genuinely REPACKAGED over time (same
contents, new box/barcode -- joined into one entity via matches.yaml) carries several: the
resolver folds the old product-code's observations in as `superseded` members. When that
happens this module:

  * chooses the PRIMARY `ean` from the surviving product code's observations, preferring a
    barcode LIVE-corroborated by a manufacturer/retailer currently listing it over one attested
    only by curated/legacy/archive evidence (a stale legacy barcode must not displace the live
    one -- see resolve/attributes.py for the parallel attribute rule), and
  * keeps every DISPLACED barcode in `additional` rather than dropping it silently.

A same-product-code disagreement (different barcodes on the SAME 11-digit code, with no folded
old code) is resolved by authority: a manufacturer is authoritative for its own barcodes, so when
exactly ONE of the competing barcodes is currently listed by a LIVE manufacturer feed, that is the
current retail barcode and the others are its retired versions (GW routinely reuses a code across a
repackage without changing it) -- the live-manufacturer barcode becomes primary and the rest drop
to `additional`, clearing the conflict. Otherwise -- no live manufacturer barcode, the manufacturer
itself listing two live barcodes for one code, or only retailers disagreeing (retailers make
barcode-entry errors) -- the historical `conflicted` semantics are kept and no `additional` list is
produced, though the PRIMARY is still the least-stale (most live-corroborated) barcode.
"""
from dataclasses import dataclass, field

from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.models.descriptor import KIND_PRIORITY
from warhub_acquisition.models.observation import Observation

# A barcode is LIVE-corroborated when a scraped manufacturer/retailer source currently lists it
# (present, not archived, not miss-decayed). Curated/legacy imports and archive snapshots never
# count as live -- they attest history, not the current shelf. Deliberately STRICTER than
# attributes.py's `scraped_live` (which admits kind `archive`): an archive-recovered observation
# may drive lifecycle, but it must never confer barcode primacy.
_LIVE_KINDS = ("manufacturer", "retailer")


@dataclass
class EanResolution:
    ean: str | None
    confidence: str | None
    conflicts: list[dict]
    additional: list[str] = field(default_factory=list)


def _confidence(sources: dict[str, str]) -> str:
    trusted = {sid for sid, kind in sources.items() if kind != "barcode-db"}
    has_authoritative = any(kind in ("manufacturer", "curated") for kind in sources.values())
    if has_authoritative or len(sources) >= 2 and len(trusted) >= 1:
        return "confirmed"
    return "provisional"


def resolve_ean(
    entity: str,
    members: list[Observation],
    kinds: dict[str, str],
    superseded: frozenset[str] = frozenset(),
    miss_threshold: int = 3,
    surviving_code: str | None = None,
    member_codes: dict[str, str | None] | None = None,
) -> EanResolution:
    assertions: dict[str, dict[str, str]] = {}  # ean -> {source_id: kind}
    asserted_by: dict[str, set[str]] = {}       # ean -> {observation key, ...}
    ean_codes: dict[str, set[str | None]] = {}  # ean -> {product code each asserting member carries}
    live_eans: set[str] = set()
    # A barcode a live manufacturer lists under the SURVIVING product code is the authoritative
    # current retail barcode. Scoping to the surviving code matters: a repackage that folded/joined
    # an OLD code into this entity also drags the manufacturer's OLD barcode in (under that old
    # code) -- that old barcode is authoritative for the *old* code, not the current one, so it must
    # not count here. `member_codes` maps each member key to its normalized code; when it is absent
    # (direct unit-test calls), fall back to "a barcode any live manufacturer lists".
    live_mfr_eans: set[str] = set()
    for member in members:
        ean = canonical_ean(member.ean)
        if ean is None:
            continue
        kind = kinds.get(member.source_id, "barcode-db")
        assertions.setdefault(ean, {})[member.source_id] = kind
        asserted_by.setdefault(ean, set()).add(member.key)
        if member_codes is not None:
            ean_codes.setdefault(ean, set()).add(member_codes.get(member.key))
        if not member.archived and kind in _LIVE_KINDS and member.missStreak < miss_threshold:
            live_eans.add(ean)
            if kind == "manufacturer":
                on_surviving = (
                    member_codes is None
                    or surviving_code is None
                    or member_codes.get(member.key) == surviving_code
                )
                if on_surviving:
                    live_mfr_eans.add(ean)

    if not assertions:
        return EanResolution(None, None, [])

    def strength(ean: str) -> tuple[int, int, int, int, str]:
        # Primary-selection ordering, best (smallest) first:
        #   1. live-corroborated beats not (a barcode a manufacturer/retailer currently lists beats
        #      one attested only by curated/legacy/archive evidence -- the `corroborate` docstring's
        #      stated intent, now applied to plain disagreements too, not just repackaging).
        #   2. best kind among the barcode's LIVE assertions (manufacturer < retailer): a live
        #      manufacturer barcode outranks a live retailer one even when a stale curated/legacy
        #      source also backs the retailer's barcode and would otherwise drag its kind to 0.
        #   3. best kind over ALL assertions, then source count, then lexicographic -- unchanged
        #      tie-breakers, and the sole ordering when nothing is live (historical behaviour).
        sources = assertions[ean]
        overall_kind = min(KIND_PRIORITY.get(kind, 9) for kind in sources.values())
        live_kind = KIND_PRIORITY["manufacturer"] if ean in live_mfr_eans else (
            KIND_PRIORITY["retailer"] if ean in live_eans else 9
        )
        return (0 if ean in live_eans else 1, live_kind, overall_kind, -len(sources), ean)

    # A barcode attested ONLY through superseded (folded-in old-packaging) observations is a
    # displaced repackaging barcode: it belongs in `additional`, never as the primary. Its
    # presence -- alongside at least one surviving-code barcode to be primary -- is what marks
    # this entity a genuine repackaging (as opposed to a same-code source disagreement).
    superseded_only = {ean for ean, keys in asserted_by.items() if keys <= superseded}
    primary_candidates = [ean for ean in assertions if ean not in superseded_only]
    repackaging = bool(superseded_only) and bool(primary_candidates)

    if repackaging:
        # Primary from the surviving product code; `strength` already prefers a LIVE-corroborated
        # barcode (and a live manufacturer over a live retailer) before kind/count/lexicographic.
        primary = min(primary_candidates, key=strength)
        additional = sorted(superseded_only)
        conflicts: list[dict] = []
        confidence = _confidence(assertions[primary])
        if len(primary_candidates) > 1:
            # Surviving code itself carries disagreeing barcodes -- a real conflict layered on top
            # of the repackaging; flag it loudly. The displaced repackaging barcodes still stand.
            confidence = "conflicted"
            conflicts.append(_mismatch(entity, primary, {e: assertions[e] for e in primary_candidates}))
        return EanResolution(primary, confidence, conflicts, additional)

    if len(assertions) == 1:
        primary = next(iter(assertions))
        return EanResolution(primary, _confidence(assertions[primary]), [])

    # --- same product code, disagreeing barcodes ---
    # GW (and every manufacturer here) is authoritative for its OWN barcodes. When exactly one of
    # the competing barcodes is currently listed by a LIVE manufacturer feed, that is the current
    # retail barcode; the others on this code are its retired/superseded versions (GW routinely
    # reuses an 11-digit code across a repackage without a code change). So the live-manufacturer
    # barcode becomes the primary and the rest drop to `additionalEans` -- kept, never dropped --
    # which CLEARS the conflict. A stale legacy/curated barcode no longer displaces the live one.
    if len(live_mfr_eans) == 1:
        primary = next(iter(live_mfr_eans))
        losers = [e for e in assertions if e != primary]
        # A loser is a retired version of THIS product only if it was ever carried on the surviving
        # code. A barcode seen ONLY under a foreign code is a different product accidentally bridged
        # in (a retailer mis-coded listing sharing a name/EAN, not a deliberate repackaging join) --
        # absorbing it as `additional` would hide the bad merge, so keep the entity conflicted and
        # visible instead. When per-member codes are unknown (direct unit calls), treat all losers
        # as retired versions (the historical, code-blind behaviour).
        bridged = [
            e for e in losers
            if surviving_code is not None and ean_codes.get(e) and surviving_code not in ean_codes[e]
        ]
        if not bridged:
            return EanResolution(primary, _confidence(assertions[primary]), [], sorted(losers))
        return EanResolution(primary, "conflicted", [_mismatch(entity, primary, assertions)])

    # No single authoritative manufacturer barcode (none live-manufacturer, or the manufacturer
    # itself lists two live barcodes for one code, or only retailers disagree -- retailers do make
    # barcode-entry errors): keep the historical conflicted semantics. `strength` still puts the
    # best live-corroborated barcode first, so the PRIMARY is the least-stale choice even while the
    # disagreement is flagged for a human. No `additional` list is produced here.
    ranked = sorted(assertions, key=strength)
    primary = ranked[0]
    return EanResolution(primary, "conflicted", [_mismatch(entity, primary, assertions)])


def _mismatch(entity: str, chosen: str, assertions: dict[str, dict[str, str]]) -> dict:
    return {
        "type": "ean-mismatch",
        "entity": entity,
        "chosen": chosen,
        "assertions": [
            {"ean": e, "sources": sorted(s)} for e, s in sorted(assertions.items())
        ],
    }


def find_shared_eans(resolutions: dict[str, EanResolution]) -> list[dict]:
    """Report every barcode held by more than one entity -- as a primary `ean` OR an
    `additionalEans` entry (a repackaged product's retired barcode colliding with another entity's
    barcode is just as much a data error as two primaries colliding). When any holder carries the
    barcode as an additional one, the conflict names those holders under `additionalIn`."""
    by_ean: dict[str, list[str]] = {}
    additional_in: dict[str, list[str]] = {}
    for entity, resolution in sorted(resolutions.items()):
        if resolution.ean is not None:
            by_ean.setdefault(resolution.ean, []).append(entity)
        for extra in resolution.additional:
            by_ean.setdefault(extra, []).append(entity)
            additional_in.setdefault(extra, []).append(entity)
    conflicts: list[dict] = []
    for ean, entities in sorted(by_ean.items()):
        if len(entities) <= 1:
            continue
        conflict = {"type": "ean-shared", "ean": ean, "entities": entities}
        if ean in additional_in:
            conflict["additionalIn"] = additional_in[ean]
        conflicts.append(conflict)
    return conflicts
