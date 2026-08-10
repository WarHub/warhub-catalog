# tools/acquisition/src/warhub_acquisition/classify/supersessions.py
"""Deterministic supersession proposals from manufacturer-asserted re-coding lineage.

Phase 4 added the relation (`matches.supersessions`) and proved it on 13 hand-checked pairs.
This scales it: GW's own `Code Changes` register states, per surviving product code, which codes
it replaced -- captured as ``hints["supersedes"]`` by the gw-trade strategy.

Unlike `classify --propose-joins` there is NO LLM judgement here. "Are these the same product?"
is asserted at source by the manufacturer, so nothing needs adjudicating. What needs review is
whether each asserted edge is mechanically SAFE to declare, and that is exactly what the buckets
record:

  * ``ready``                  -- both sides resolve to their own distinct entity: a line to paste.
  * ``already-declared``       -- already in matches.yaml; re-runs are idempotent.
  * ``same-code``              -- the register restates a code that did not change (a re-barcode on
                                 the SAME code). That is an `additionalEans` case, never lineage --
                                 declaring it would point an entity at itself.
  * ``unobserved-retired-code``-- nothing observes the retired code, so it has no entity to link.
                                 The barcode and date are still reported: this is the population a
                                 future "mint archival records from lineage" step would serve, and
                                 leaving it silent is how old codes got lost in the first place.
  * ``merged-with-survivor``   -- the retired code IS observed but currently resolves INTO the
                                 surviving entity. Promoting these is real work (the union barrier
                                 has to split them), so they are kept separate from `ready`.
  * ``regional-variant``       -- the retired code fans out to the SAME product in several regional
                                 editions (GW's leading code pair is a region marker: 60 ROW, 56
                                 JUC, 52/54 language groups...). Only the edition sharing the
                                 retired code's own region is its successor; the others are other
                                 regions' products, which have their own retired codes. Measured
                                 2026-07-30: 299 of the 307 multi-survivor codes are exactly this,
                                 and in 299/299 precisely ONE survivor shares the retired prefix.
  * ``conflicting``            -- one retired code asserted against two different survivors that a
                                 regional split does NOT explain (a filler code reused across
                                 unrelated products), OR a pair the register asserts in BOTH
                                 directions -- which is the shape the bucket actually holds today.
                                 The filler-code illustration here used to name an ISBN-barcoded
                                 `03040199135` against two terrain kits; that pair moved to
                                 ``stale-register-row`` when that bucket was introduced, so read it
                                 as a shape to watch for, not a current instance. Never promote
                                 without a human.
  * ``contradicts-declared``   -- the exact reverse of an edge already in matches.yaml. The
                                 declaration wins (it was verified against evidence; the register
                                 restates old rows), but the contradiction is named, not dropped.

The file is a REVIEW ARTIFACT ONLY -- this module NEVER edits data/catalog/matches.yaml.
"""
from dataclasses import dataclass, field
from pathlib import Path

from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.resolve.join import Matches
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import dump_yaml, read_yaml

READY = "ready"
CONTRADICTS_DECLARED = "contradicts-declared"
RETIRED_ALREADY_DECLARED = "retired-already-declared"
ALREADY_DECLARED = "already-declared"
SAME_CODE = "same-code"
UNOBSERVED = "unobserved-retired-code"
MERGED = "merged-with-survivor"
REGIONAL = "regional-variant"
CONFLICTING = "conflicting"
STALE_REGISTER_ROW = "stale-register-row"
UNRESOLVED_CARRIER = "surviving-entity-unresolved"

_BUCKET_ORDER = (
    READY, MERGED, CONFLICTING, STALE_REGISTER_ROW, CONTRADICTS_DECLARED, RETIRED_ALREADY_DECLARED, UNOBSERVED,
    REGIONAL, SAME_CODE, ALREADY_DECLARED, UNRESOLVED_CARRIER,
)


def _cyclic_entities(graph: dict[str, str]) -> set[str]:
    """Entities lying on a cycle of a `retired -> surviving` map.

    Each entity has at most one successor, so the graph is functional and every component holds at
    most one cycle -- walk forward from each start and stop when the path revisits a node still on
    the current walk.
    """
    finished: set[str] = set()
    cyclic: set[str] = set()
    for start in graph:
        path: list[str] = []
        on_path: set[str] = set()
        node = start
        while node in graph and node not in finished and node not in on_path:
            path.append(node)
            on_path.add(node)
            node = graph[node]
        if node in on_path:
            cyclic.update(path[path.index(node):])
        finished.update(on_path)
    return cyclic


def _no_claimant_kept_ssc(retired_ssc: object, survivor_ssc: dict[str, str]) -> bool:
    """True when the retired SS Code is known and no surviving code carries it.

    Requires knowing BOTH sides -- an unknown retired SSC, or claimants whose own SSC we
    never captured, must stay `conflicting` rather than be convicted on absence.
    """
    wanted = str(retired_ssc).strip() if retired_ssc else ""
    known = {ssc for ssc in survivor_ssc.values() if ssc}
    return bool(wanted) and bool(known) and wanted not in known


def _ssc_successor(retired_ssc: object, survivor_ssc: dict[str, str]) -> str | None:
    """The one surviving code that kept the retired code's SS Code, or None.

    None when the retired SSC is unknown, when NO claimant kept it (the retired code is
    then a stale row parked in the register's Old columns, not a predecessor of any of
    them), or when SEVERAL did (regional editions share an SSC -- the region rule splits
    those). Returning None means 'this rule has nothing to say', never 'no successor'.
    """
    wanted = str(retired_ssc).strip() if retired_ssc else ""
    if not wanted:
        return None
    kept = [code for code, ssc in survivor_ssc.items() if ssc == wanted]
    return kept[0] if len(kept) == 1 else None


def _regional_successor(retired_code: str, surviving_codes: set[str]) -> str | None:
    """Which of several surviving codes actually succeeds `retired_code`, or None if unclear.

    A retired code is routinely restated against every REGIONAL edition of its replacement, because
    GW keys the register on the code body and the leading pair carries the region. Those editions
    are the same product for different markets -- each has its own retired code -- so only the one
    sharing this code's region is its successor. Requires the fan-out to be a clean regional split
    (identical body on every survivor) and exactly one survivor in the retired code's own region;
    anything else is left for a human.
    """
    codes = {code for code in surviving_codes if code and len(code) > 2}
    if len(codes) < 2 or len(retired_code) <= 2 or len({code[2:] for code in codes}) != 1:
        return None
    same_region = [code for code in codes if code[:2] == retired_code[:2]]
    return same_region[0] if len(same_region) == 1 else None


@dataclass
class SupersessionProposalSummary:
    edges: int = 0
    buckets: dict[str, int] = field(default_factory=dict)


def _proposals_path(paths: DataPaths) -> Path:
    return paths.root / "review" / "supersession-proposals.yaml"


_HEADER = """\
# data/review/supersession-proposals.yaml -- generated by
# `warhub-data classify --propose-supersessions`.
#
# Manufacturer-asserted product-code lineage (today: GW's `Code Changes` register, captured as
# hints["supersedes"]), classified by whether each edge can be declared in
# data/catalog/matches.yaml's `supersessions:` map. This file is a REVIEW ARTIFACT ONLY -- the
# generator NEVER edits matches.yaml.
#
# TO PROMOTE: paste the `readyToPromote` block below into matches.yaml under `supersessions:`
# (spot-check a sample first -- the register is the manufacturer's, but the entity ids are ours),
# then re-run `warhub-data resolve` and `warhub-data report --ean-guard`. A promoted edge splits
# one entity into two: expect `repackaged` guard findings (the retired barcode moving to the
# archival record) and NEVER `lost`.
#
# Buckets other than `ready` are NOT paste-ready, each for a specific reason -- see the module
# docstring in classify/supersessions.py. `unobserved-retired-code` is the population no mechanism
# reaches yet: the manufacturer says the code existed, but nothing in the evidence observes it, so
# there is no entity to link. Those rows carry the retired barcode and change date so the loss is
# at least visible and countable.
"""


def _catalog_index(paths: DataPaths) -> tuple[dict[str, str], dict[tuple[str, str], str], dict[str, dict]]:
    """`(evidence key -> entity id, (manufacturer, product code) -> entity id, entity id -> record)`.

    Read from the RESOLVED catalog rather than re-running the resolver's join: the published
    records already carry both their `evidence` keys and their `productCode`, so this stays a
    cheap read over data/catalog/products/*.yaml.
    """
    by_key: dict[str, str] = {}
    by_code: dict[tuple[str, str], str] = {}
    records: dict[str, dict] = {}
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        data = read_yaml(path) or {}
        for product in data.get("products", []):
            records[product["id"]] = product
            for key in product.get("evidence") or []:
                by_key[key] = product["id"]
            if product.get("productCode"):
                by_code[(product["manufacturer"], product["productCode"])] = product["id"]
    return by_key, by_code, records


def generate_supersession_proposals(paths: DataPaths) -> list[dict]:
    taxonomy = Taxonomy.load(paths.taxonomy)
    matches = (
        Matches.model_validate(read_yaml(paths.matches)) if paths.matches.exists() else Matches()
    )
    declared = {
        matches.aliases.get(retired, retired): matches.aliases.get(surviving, surviving)
        for retired, surviving in matches.supersessions.items()
    }
    entity_by_key, entity_by_code, records = _catalog_index(paths)

    # Collect edges first so a retired code asserted against two survivors can be spotted before
    # any of them is called `ready`. `observed_in` is built alongside: which entities hold an
    # observation carrying a given code. It is NOT the same question as `entity_by_code` (which
    # records who PUBLISHES the code) -- a folded retired code publishes nowhere while still being
    # observed, and phase 4's stale-code re-homing can legitimately put one code in two entities.
    edges: list[dict] = []
    observed_in: dict[tuple[str, str], set[str]] = {}
    for source in EvidenceStore(paths.evidence_products).load_all().values():
        for observation in source.values():
            if not observation.manufacturer:
                continue
            observed_code = taxonomy.normalize_code(observation.manufacturer, observation.sku)
            holder = entity_by_key.get(observation.key)
            if observed_code and holder:
                observed_in.setdefault((observation.manufacturer, observed_code), set()).add(holder)
            entries = observation.hints.get("supersedes")
            if not entries:
                continue
            surviving_entity = holder
            surviving_code = observed_code
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("productCode"):
                    continue
                raw_code = str(entry["productCode"])
                retired_code = taxonomy.normalize_code(observation.manufacturer, raw_code) or raw_code
                edges.append(
                    {
                        "manufacturer": observation.manufacturer,
                        "retiredCode": retired_code,
                        "retiredEan": entry.get("ean"),
                        "retiredSsc": entry.get("ssc"),
                        "survivingSsc": (observation.hints or {}).get("sscCode"),
                        "changedOn": entry.get("changedOn"),
                        "survivingCode": surviving_code,
                        "survivingEntity": surviving_entity,
                        "assertedBy": observation.key,
                    }
                )

    # Dedup identical assertions (the register is cumulative across workbook generations), then
    # find retired codes claimed by more than one surviving entity.
    unique: dict[tuple[str, str, str | None], dict] = {}
    for edge in edges:
        unique.setdefault(
            (edge["manufacturer"], edge["retiredCode"], edge["survivingEntity"]), edge
        )
    survivors_per_code: dict[tuple[str, str], set[str]] = {}
    survivor_codes_per_code: dict[tuple[str, str], set[str]] = {}
    survivor_ssc_per_code: dict[tuple[str, str], dict[str, str]] = {}
    for edge in unique.values():
        if edge["survivingEntity"]:
            pair = (edge["manufacturer"], edge["retiredCode"])
            survivors_per_code.setdefault(pair, set()).add(edge["survivingEntity"])
            if edge["survivingCode"]:
                survivor_codes_per_code.setdefault(pair, set()).add(edge["survivingCode"])
            if edge["survivingCode"] and edge.get("survivingSsc"):
                survivor_ssc_per_code.setdefault(pair, {})[edge["survivingCode"]] = str(
                    edge["survivingSsc"]).strip()

    proposals: list[dict] = []
    for edge in unique.values():
        manufacturer = edge["manufacturer"]
        retired_code = edge["retiredCode"]
        surviving = edge["survivingEntity"]
        # Which entity is the retired code's own? The record that PUBLISHES it wins; failing that,
        # any other entity observing it (its id is then a name slug, which still links fine).
        owner = entity_by_code.get((manufacturer, retired_code))
        observers = observed_in.get((manufacturer, retired_code), set())
        elsewhere = sorted(observers - {surviving})
        retired_entity = owner if owner is not None else (elsewhere[0] if elsewhere else None)

        fan_out = survivors_per_code.get((manufacturer, retired_code), set())
        pair_key = (manufacturer, retired_code)
        successor = None
        if len(fan_out) > 1:
            # GW's SS Code is the product's identity ACROSS a re-code -- the register keeps
            # it on the overwhelming majority of pairs -- so among COMPETING claimants the
            # one that kept the retired code's own SSC is the real successor and the rest
            # are stale rows. Only ever used between claimants, NEVER as a veto on a lone
            # edge: a real minority of already-declared pairs DO legitimately renumber their
            # SSC, so a lone edge that changes it is not thereby suspect. This comment used
            # to put that minority at 9; the committed artifact has never agreed, so count
            # `already-declared` rows whose retiredSsc and survivingSsc differ in
            # data/review/supersession-proposals.yaml rather than trusting a number here.
            successor = _ssc_successor(
                edge.get("retiredSsc"), survivor_ssc_per_code.get(pair_key, {}))
            # Regional editions SHARE their SSC, so a fan-out the SSC cannot split
            # falls through to the region rule, which is exactly what splits those.
            if successor is None:
                successor = _regional_successor(
                    retired_code, survivor_codes_per_code.get(pair_key, set()))

        if retired_entity is not None and declared.get(retired_entity) == surviving:
            # Checked FIRST: an edge a maintainer has already declared is settled, and
            # re-reporting it as `conflicting` because its fan-out is unresolved hides that.
            # Its unresolved RIVALS still surface, which is the part worth a human's time.
            bucket = ALREADY_DECLARED
        elif surviving is None:
            bucket = UNRESOLVED_CARRIER
        elif retired_code == edge["survivingCode"]:
            bucket = SAME_CODE
        elif len(fan_out) > 1 and successor is None and _no_claimant_kept_ssc(
            edge.get("retiredSsc"), survivor_ssc_per_code.get(pair_key, {})
        ):
            # The retired code's OWN SS Code is known and NOT ONE claimant kept it. GW's
            # SSC is the product's identity across a re-code, so this code is not the
            # predecessor of any of them -- it is a stale row the register parked in the
            # `Old ...` columns while a batch of genuinely new products was registered.
            # A verdict, not an unknown: every one is a real product (mostly non-English
            # regional editions), just not THESE products' ancestor.
            bucket = STALE_REGISTER_ROW
        elif len(fan_out) > 1 and successor is None:
            bucket = CONFLICTING
        elif successor is not None and edge["survivingCode"] != successor:
            # another region's edition of the same product; its own retired code covers it
            bucket = REGIONAL
        elif retired_entity is not None and retired_entity in declared:
            # `supersessions` is keyed by the RETIRED id, so promoting this would not add a link --
            # it would REPLACE the existing, hand-verified one. Marking it `ready` (as this did
            # until 2026-07-31) means any "paste readyToPromote" step silently rewrites a
            # declaration. Surfaced by a real case: a newly minted archival record made
            # `99070207010 -> 99070207021` proposable while `99070207010 -> 99120207208` was
            # already declared.
            bucket = RETIRED_ALREADY_DECLARED
        elif retired_entity is not None and retired_entity != surviving:
            bucket = READY
        elif surviving in observers:
            # observed, but every observation of it currently lands INSIDE the survivor
            bucket = MERGED
            retired_entity = None
        else:
            bucket = UNOBSERVED
            retired_entity = None

        record = records.get(surviving or "", {})
        proposals.append(
            {
                "bucket": bucket,
                "manufacturer": manufacturer,
                "retiredCode": retired_code,
                "retiredEan": edge["retiredEan"],
                "retiredSsc": edge.get("retiredSsc"),
                "survivingSsc": edge.get("survivingSsc"),
                "retiredEntity": retired_entity,
                "survivingEntity": surviving,
                "survivingCode": edge["survivingCode"],
                "survivingName": record.get("name"),
                "survivingEan": record.get("ean"),
                "changedOn": edge["changedOn"],
                "assertedBy": edge["assertedBy"],
            }
        )

    # Cycle guard. The register contradicts ITSELF across workbook generations (a pair asserted in
    # both directions) and can contradict an existing hand-verified declaration. resolve/resolver.py
    # rejects cycles outright, so neither may reach `ready`. Measured 2026-07-30 over 693 otherwise
    # ready edges: 3 two-cycles, one of them the exact reverse of phase 4's evidence-verified Dryads
    # declaration -- which is why a declared edge always wins over the register.
    for proposal in proposals:
        if proposal["bucket"] != READY:
            continue
        if declared.get(proposal["survivingEntity"]) == proposal["retiredEntity"]:
            proposal["bucket"] = CONTRADICTS_DECLARED

    candidate_graph = dict(declared)
    for proposal in proposals:
        if proposal["bucket"] == READY:
            candidate_graph.setdefault(proposal["retiredEntity"], proposal["survivingEntity"])
    cyclic = _cyclic_entities(candidate_graph)
    for proposal in proposals:
        # Demote BOTH directions: the register asserting a pair each way says nothing about which
        # way is right, so a human has to look.
        if proposal["bucket"] == READY and proposal["retiredEntity"] in cyclic:
            proposal["bucket"] = CONFLICTING

    proposals.sort(
        key=lambda p: (
            _BUCKET_ORDER.index(p["bucket"]),
            p["manufacturer"],
            p["retiredCode"],
            p["survivingEntity"] or "",
        )
    )
    return proposals


def run_supersession_proposals(paths: DataPaths) -> SupersessionProposalSummary:
    proposals = generate_supersession_proposals(paths)

    buckets: dict[str, int] = {}
    for proposal in proposals:
        buckets[proposal["bucket"]] = buckets.get(proposal["bucket"], 0) + 1

    ready = {p["retiredEntity"]: p["survivingEntity"] for p in proposals if p["bucket"] == READY}

    document = {
        "summary": {bucket: buckets.get(bucket, 0) for bucket in _BUCKET_ORDER},
        "readyToPromote": dict(sorted(ready.items())),
        "proposals": proposals,
    }
    path = _proposals_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_HEADER + dump_yaml(document), encoding="utf-8", newline="\n")

    return SupersessionProposalSummary(edges=len(proposals), buckets=buckets)
