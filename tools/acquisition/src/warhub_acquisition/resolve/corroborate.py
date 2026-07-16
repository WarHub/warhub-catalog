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

A plain same-product-code disagreement (two live sources asserting different barcodes for the
SAME code -- a data error, not a repackaging) is NOT a repackaging: it keeps the historical
`conflicted` semantics untouched, and produces no `additional` list.
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
) -> EanResolution:
    assertions: dict[str, dict[str, str]] = {}  # ean -> {source_id: kind}
    asserted_by: dict[str, set[str]] = {}       # ean -> {observation key, ...}
    live_eans: set[str] = set()
    for member in members:
        ean = canonical_ean(member.ean)
        if ean is None:
            continue
        kind = kinds.get(member.source_id, "barcode-db")
        assertions.setdefault(ean, {})[member.source_id] = kind
        asserted_by.setdefault(ean, set()).add(member.key)
        if not member.archived and kind in _LIVE_KINDS and member.missStreak < miss_threshold:
            live_eans.add(ean)

    if not assertions:
        return EanResolution(None, None, [])

    def strength(ean: str) -> tuple[int, int, str]:
        sources = assertions[ean]
        best_kind = min(KIND_PRIORITY.get(kind, 9) for kind in sources.values())
        return (best_kind, -len(sources), ean)

    # A barcode attested ONLY through superseded (folded-in old-packaging) observations is a
    # displaced repackaging barcode: it belongs in `additional`, never as the primary. Its
    # presence -- alongside at least one surviving-code barcode to be primary -- is what marks
    # this entity a genuine repackaging (as opposed to a same-code source disagreement).
    superseded_only = {ean for ean, keys in asserted_by.items() if keys <= superseded}
    primary_candidates = [ean for ean in assertions if ean not in superseded_only]
    repackaging = bool(superseded_only) and bool(primary_candidates)

    if repackaging:
        # Primary from the surviving product code, preferring a LIVE-corroborated barcode over a
        # curated/legacy/archive-only one, then the usual kind/count/lexicographic strength.
        primary = min(
            primary_candidates,
            key=lambda ean: (0 if ean in live_eans else 1, *strength(ean)),
        )
        additional = sorted(superseded_only)
        conflicts: list[dict] = []
        confidence = _confidence(assertions[primary])
        if len(primary_candidates) > 1:
            # Surviving code itself carries disagreeing barcodes -- a real conflict layered on top
            # of the repackaging; flag it loudly. The displaced repackaging barcodes still stand.
            confidence = "conflicted"
            conflicts.append(_mismatch(entity, primary, {e: assertions[e] for e in primary_candidates}))
        return EanResolution(primary, confidence, conflicts, additional)

    # --- single barcode, or a same-product-code disagreement: historical behaviour, unchanged ---
    ranked = sorted(assertions, key=strength)
    primary = ranked[0]
    conflicts = []
    if len(assertions) > 1:
        confidence = "conflicted"
        conflicts.append(_mismatch(entity, primary, assertions))
    else:
        confidence = _confidence(assertions[primary])
    return EanResolution(primary, confidence, conflicts)


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
