"""Deterministic candidate-pair generation + LLM join adjudication (Task 6): scans the RESOLVED
catalog (`data/catalog/products/*.yaml`) and the parked entities in `data/review/conflicts.yaml`
(`type: unclassified-entity`) for same-manufacturer entity pairs that are suspiciously likely to be
the SAME real-world product living as two separate catalog entities -- a retailer-minted duplicate
the deterministic join machinery (`resolve/join.py`) did not (and structurally could not) merge on
its own, because the two sides never shared a code/ean anchor at join time.

Three deterministic rules generate candidates (no LLM involved yet):
  (a) ean    -- both entities assert the same GS1-validated EAN under the same manufacturer.
  (b) name   -- both entities normalize (via `resolve.identity.slugify`, the SAME normalizer the
                conservative name-join pass in `resolve/join.py` uses) to the identical, non-empty
                name slug under the same manufacturer. This is an EXACT normalized match, not a
                fuzzy one -- candidate generation stays fully deterministic.
  (c) legacy-code -- one entity's `legacyProductCode` hint (a migrated-legacy-catalog artifact,
                only ever present on PARKED entities -- resolved entities don't carry raw hints)
                digit-extracted equals another same-manufacturer entity's `sku` digit-extracted.

A pair matched by more than one rule appears ONCE, with `matchedRules` listing every rule that
fired (sorted). Candidates are sorted by (entityA, entityB) for determinism.

Each candidate is then sent to an LLM (batching/cache/threshold machinery shared with Task 5's
`classify/llm.py` via `classify/_llm_common.py`) for a same-product true/false verdict with
confidence, written to `data/review/join-proposals.yaml`. The cache
(`data/review/join-cache.jsonl`) is a SEPARATE file/namespace from classification's
`classification-cache.jsonl`: a classification decision and a join verdict are different input
spaces and must never be confused or invalidate one another.

PROMOTION IS OUT OF SCOPE FOR THIS MODULE. `classify --propose-joins` NEVER edits
`data/catalog/matches.yaml`. See the `join-proposals.yaml` header comment this module writes: a
human (or the controller, with spot-check gates like Task 5's LLM classification waves) must
manually copy the `entityA`/`entityB` pair of any `acceptedCandidate: true` entry (verdict
`same-product`, confidence >= 0.8) into `matches.yaml`'s `joins` map, then re-run `resolve` and
`report --ean-guard` (a join can change a confirmed EAN; guard findings are review items).
"""
import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from warhub_acquisition.classify._llm_common import (
    ACCEPT_THRESHOLD,
    AnthropicClient,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    append_cache_lines,
    batch_pending,
    call_batch,
    compute_input_hash,
    extract_text,
    load_cache,
    parse_response,
)
from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.resolve.corroborate import resolve_ean
from warhub_acquisition.resolve.identity import slugify
from warhub_acquisition.resolve.join import Matches, join_observations
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import dump_yaml, read_yaml

DEFAULT_BUDGET = 500

__all__ = [
    "DEFAULT_BUDGET",
    "DEFAULT_MODEL",
    "AnthropicClient",
    "EntityContext",
    "JoinCacheEntry",
    "JoinProposalSummary",
    "generate_candidates",
    "run_join_proposals",
]

_DIGITS_RE = re.compile(r"\D+")


def _digits(value: object | None) -> str:
    if not value:
        return ""
    return _DIGITS_RE.sub("", str(value))


# --- entity contexts ------------------------------------------------------------------------


@dataclass
class EntityContext:
    entity: str
    manufacturer: str
    name: str
    sku: str | None
    ean: str | None  # GS1-validated, or None
    url: str | None
    legacyProductCode: str | None
    evidence: list[str] = field(default_factory=list)

    def to_context_dict(self) -> dict:
        return {
            "entity": self.entity,
            "name": self.name,
            "sku": self.sku,
            "ean": self.ean,
            "url": self.url,
            "legacyProductCode": self.legacyProductCode,
            "evidence": self.evidence,
        }


def _resolved_entity_contexts(paths: DataPaths) -> dict[str, EntityContext]:
    """Read the already-resolved catalog files directly -- no need to re-run the resolver for
    entities it already successfully classified and wrote out.
    """
    contexts: dict[str, EntityContext] = {}
    if not paths.catalog_products.exists():
        return contexts
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        data = read_yaml(path) or {}
        for record in data.get("products") or []:
            contexts[record["id"]] = EntityContext(
                entity=record["id"],
                manufacturer=record["manufacturer"],
                name=record["name"],
                sku=record.get("sku") or None,
                # re-validate defensively -- catalog_products/*.yaml SHOULD only ever carry a
                # GS1-validated ean (resolve_ean's job), but candidate generation must not trust
                # an on-disk file blindly as the source of "validated" for rule (a).
                ean=canonical_ean(record.get("ean")),
                url=record.get("url"),
                legacyProductCode=None,  # resolved CanonicalProduct records drop raw hints
                evidence=sorted(record.get("evidence") or []),
            )
    return contexts


def _load_matches(paths: DataPaths) -> Matches:
    if paths.matches.exists():
        return Matches.model_validate(read_yaml(paths.matches))
    return Matches()


def _parked_entity_ids(paths: DataPaths) -> list[str]:
    if not paths.conflicts.exists():
        return []
    conflicts = read_yaml(paths.conflicts) or {}
    return sorted(
        {c["entity"] for c in conflicts.get("conflicts") or [] if c.get("type") == "unclassified-entity"}
    )


def _parked_entity_contexts(paths: DataPaths) -> dict[str, EntityContext]:
    """Parked entities never made it into `catalog_products/*.yaml` (the resolver drops them
    before writing), so their context is reconstructed by re-running the resolver's OWN join step
    over the current evidence -- the same approach `classify/queue.py` uses for the same reason
    (resolve_catalog does not expose joined member observations itself).
    """
    parked_ids = _parked_entity_ids(paths)
    if not parked_ids:
        return {}

    taxonomy = Taxonomy.load(paths.taxonomy)
    descriptors = load_descriptors(paths.sources)
    kinds = {sid: descriptor.kind for sid, descriptor in descriptors.items()}
    evidence = EvidenceStore(paths.evidence_products).load_all()
    observations = [observation for source in evidence.values() for observation in source.values()]
    joined = join_observations(observations, taxonomy, kinds, _load_matches(paths))

    contexts: dict[str, EntityContext] = {}
    for entity in parked_ids:
        members = joined.entities.get(entity)
        if not members:
            raise ValueError(f"unclassified-entity {entity!r} in conflicts.yaml has no matching evidence")
        # members are already sorted best-source-first by join_observations' final step.
        anchor = members[0]
        sku = next((m.sku for m in members if m.sku), None)
        url = next((m.url for m in members if m.url), None)
        legacy = next(
            (str(m.hints["legacyProductCode"]) for m in members if m.hints.get("legacyProductCode")), None
        )
        ean_resolution = resolve_ean(entity, members, kinds)
        contexts[entity] = EntityContext(
            entity=entity,
            manufacturer=anchor.manufacturer,
            name=anchor.name,
            sku=sku,
            ean=ean_resolution.ean,
            url=url,
            legacyProductCode=legacy,
            evidence=sorted(m.key for m in members),
        )
    return contexts


def _entity_contexts(paths: DataPaths) -> dict[str, EntityContext]:
    contexts = _resolved_entity_contexts(paths)
    contexts.update(_parked_entity_contexts(paths))
    return contexts


# --- deterministic candidate rules -----------------------------------------------------------


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _rule_ean(contexts: dict[str, EntityContext]) -> dict[tuple[str, str], set[str]]:
    groups: dict[tuple[str, str], list[str]] = {}
    for ctx in contexts.values():
        if ctx.ean:
            groups.setdefault((ctx.manufacturer, ctx.ean), []).append(ctx.entity)
    return _pairs_from_groups(groups, "ean")


def _rule_name(contexts: dict[str, EntityContext]) -> dict[tuple[str, str], set[str]]:
    groups: dict[tuple[str, str], list[str]] = {}
    for ctx in contexts.values():
        slug = slugify(ctx.name)
        if slug:
            groups.setdefault((ctx.manufacturer, slug), []).append(ctx.entity)
    return _pairs_from_groups(groups, "name")


def _pairs_from_groups(groups: dict[tuple[str, str], list[str]], rule: str) -> dict[tuple[str, str], set[str]]:
    pairs: dict[tuple[str, str], set[str]] = {}
    for entities in groups.values():
        unique = sorted(set(entities))
        if len(unique) < 2:
            continue
        for a, b in itertools.combinations(unique, 2):
            pairs.setdefault(_pair_key(a, b), set()).add(rule)
    return pairs


def _rule_legacy_code(contexts: dict[str, EntityContext]) -> dict[tuple[str, str], set[str]]:
    by_legacy: dict[tuple[str, str], list[str]] = {}
    by_sku: dict[tuple[str, str], list[str]] = {}
    for ctx in contexts.values():
        legacy_digits = _digits(ctx.legacyProductCode)
        if legacy_digits:
            by_legacy.setdefault((ctx.manufacturer, legacy_digits), []).append(ctx.entity)
        sku_digits = _digits(ctx.sku)
        if sku_digits:
            by_sku.setdefault((ctx.manufacturer, sku_digits), []).append(ctx.entity)

    pairs: dict[tuple[str, str], set[str]] = {}
    for key, legacy_entities in by_legacy.items():
        for sku_entity in by_sku.get(key, []):
            for legacy_entity in legacy_entities:
                if legacy_entity == sku_entity:
                    continue
                pairs.setdefault(_pair_key(legacy_entity, sku_entity), set()).add("legacy-code")
    return pairs


def generate_candidates(paths: DataPaths) -> list[dict]:
    """Deterministic candidate generation -- no LLM. Returns sorted `{entityA, entityB,
    manufacturer, matchedRules}` dicts, each side's context a full `EntityContext.to_context_dict()`
    (name/sku/ean/url/legacyProductCode/evidence). A pair matched by multiple rules appears once with all rules
    listed.
    """
    contexts = _entity_contexts(paths)
    merged: dict[tuple[str, str], set[str]] = {}
    for rule_pairs in (_rule_ean(contexts), _rule_name(contexts), _rule_legacy_code(contexts)):
        for pair, rules in rule_pairs.items():
            merged.setdefault(pair, set()).update(rules)

    candidates: list[dict] = []
    for entity_a, entity_b in sorted(merged):
        ctx_a, ctx_b = contexts[entity_a], contexts[entity_b]
        candidates.append(
            {
                "entityA": ctx_a.to_context_dict(),
                "entityB": ctx_b.to_context_dict(),
                "manufacturer": ctx_a.manufacturer,
                "matchedRules": sorted(merged[(entity_a, entity_b)]),
            }
        )
    return candidates


# --- LLM adjudication -------------------------------------------------------------------------


class JoinCacheEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputHash: str
    entityA: str
    entityB: str
    verdict: Literal["same-product", "different-product", "unknown"]
    confidence: float | None = None
    model: str
    date: str


@dataclass
class JoinProposalSummary:
    candidates: int
    queried: int
    cached_skips: int
    accepted: int
    rejected: int
    unknown: int
    low_confidence: int
    requests: int

    def render(self) -> str:
        return (
            f"candidates={self.candidates} queried={self.queried} cached-skips={self.cached_skips} "
            f"accepted={self.accepted} rejected={self.rejected} unknown={self.unknown} "
            f"low-confidence={self.low_confidence}"
        )


_SYSTEM_PROMPT = """\
You are auditing a tabletop miniature wargaming product catalog for DUPLICATE entities: the same \
real-world product that ended up as two separate catalog entries because different sources \
(manufacturer site, retailers, archived pages, barcode databases) described it under different \
SKUs, spellings, or barcodes and a deterministic matching pass could not safely merge them.

Each pair below was flagged by an automated rule (matchedRules) as a SUSPECTED duplicate within \
the SAME manufacturer -- but the rule is only a hint, not proof. Some flagged pairs are genuinely \
the same product listed twice (a reissue, a retailer's own SKU, a legacy product code carried over \
from an old catalog); others are two DIFFERENT products that happen to share a barcode/code \
pattern or a near-identical name (a rulebook reprint vs. an unrelated box that recycled a similar \
numeric code, a "Battleforce" bundle vs. the standalone unit it contains, a different \
scale/edition of a similarly named model).

TASK
For every pair object in the user message, decide:
- sameProduct: true if entityA and entityB describe the SAME real-world product (the same box, \
model, or bundle a customer would consider identical), false otherwise.
- confidence: a calibrated 0.0-1.0 estimate that your sameProduct answer is correct.

EVIDENCE
name, sku, ean, url, legacyProductCode, and which rule(s) flagged the pair (matchedRules) are the \
only signal -- there is no description or image. A shared validated ean ("ean" in matchedRules) is \
strong evidence of sameness. A shared normalized name ("name" in matchedRules) is good evidence, but \
a box and the standalone unit inside it can still share a name and be legitimately different \
products. A legacy-code-to-sku digit match ("legacy-code" in matchedRules) is the WEAKEST signal \
-- numeric codes can coincide between unrelated products -- and must not be trusted without \
corroborating name or ean similarity; the legacyProductCode field shows the actual value that \
triggered the match so you can judge whether it plausibly corresponds to the other side's sku or \
looks coincidental.

COST ASYMMETRY
A wrong merge (declaring two different products the same) is worse than a missed merge (declaring \
the same product different): a false merge silently corrupts the catalog, while a missed merge just \
leaves a duplicate for a later pass to catch. When the evidence is genuinely ambiguous, prefer \
sameProduct: false or a lower confidence over a confident true.

EXAMPLES
1. {"pairId": "games-workshop/AAA::games-workshop/BBB", "manufacturer": "games-workshop", \
"matchedRules": ["ean"], "entityA": {"entity": "games-workshop/AAA", "name": "Combat Patrol: Necrons", \
"sku": "99120106339", "ean": "5011921063765", "url": null, "legacyProductCode": null}, \
"entityB": {"entity": "games-workshop/BBB", \
"name": "Combat Patrol - Necrons (Archived Listing)", "sku": "OLD-CP-NEC", "ean": "5011921063765", \
"url": "https://web.archive.org/.../combat-patrol-necrons", "legacyProductCode": null}}
   -> {"pairId": "games-workshop/AAA::games-workshop/BBB", "sameProduct": true, "confidence": 0.95}
   Identical validated ean under the same manufacturer, with a name variant consistent with an \
archived retailer listing -- the same physical product.

2. {"pairId": "mantic-games/CCC::mantic-games/DDD", "manufacturer": "mantic-games", \
"matchedRules": ["name"], "entityA": {"entity": "mantic-games/CCC", "name": "Kings of War: Ogre Battleforce", \
"sku": "MGKWO01", "ean": null, "url": null, "legacyProductCode": null}, \
"entityB": {"entity": "mantic-games/DDD", \
"name": "Kings of War: Ogre Battleforce", "sku": "MGKWO01-EU", "ean": null, "url": null, \
"legacyProductCode": null}}
   -> {"pairId": "mantic-games/CCC::mantic-games/DDD", "sameProduct": true, "confidence": 0.85}
   Identical normalized name and a sku differing only by a regional suffix -- the same product \
listed under two regional codes.

3. {"pairId": "games-workshop/EEE::games-workshop/FFF", "manufacturer": "games-workshop", \
"matchedRules": ["legacy-code"], "entityA": {"entity": "games-workshop/EEE", \
"name": "Warhammer 40,000: Core Rulebook", "sku": null, "ean": null, "url": null, \
"legacyProductCode": "400108001"}, \
"entityB": {"entity": "games-workshop/FFF", "name": "Warhammer Underworlds: Direchasm", \
"sku": "40-0108001", "ean": null, "url": null, "legacyProductCode": null}}
   -> {"pairId": "games-workshop/EEE::games-workshop/FFF", "sameProduct": false, "confidence": 0.9}
   The legacyProductCode digit-matches the sku, but that is a coincidental numeric overlap; the \
names describe two unrelated products, so the rule's hint does not hold up.

OUTPUT
Respond with ONLY a strict JSON array, no prose, no markdown code fences, one object per input \
pair in the exact shape shown in the examples above, using the exact "pairId" value from the \
input for each. Every pair in the input must appear exactly once in the output.
"""


def _pair_id(candidate: dict) -> str:
    return f"{candidate['entityA']['entity']}::{candidate['entityB']['entity']}"


def _item_for_prompt(item: dict) -> dict:
    def _ctx(context: dict) -> dict:
        return {key: value for key, value in context.items() if key != "evidence"}

    return {
        "pairId": item["pairId"],
        "manufacturer": item["manufacturer"],
        "matchedRules": item["matchedRules"],
        "entityA": _ctx(item["entityA"]),
        "entityB": _ctx(item["entityB"]),
    }


def _decide(
    raw: dict | None, model: str, run_date: str, input_hash: str, entity_a: str, entity_b: str
) -> JoinCacheEntry:
    if raw is not None:
        same_product = raw.get("sameProduct")
        confidence = raw.get("confidence")
        valid = (
            isinstance(same_product, bool)
            and isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
        )
        if valid:
            return JoinCacheEntry(
                inputHash=input_hash,
                entityA=entity_a,
                entityB=entity_b,
                verdict="same-product" if same_product else "different-product",
                confidence=float(confidence),
                model=model,
                date=run_date,
            )
    return JoinCacheEntry(
        inputHash=input_hash, entityA=entity_a, entityB=entity_b, verdict="unknown", model=model, date=run_date
    )


def _cache_path(paths: DataPaths) -> Path:
    return paths.root / "review" / "join-cache.jsonl"


def _proposals_path(paths: DataPaths) -> Path:
    return paths.root / "review" / "join-proposals.yaml"


_PROPOSALS_HEADER = """\
# data/review/join-proposals.yaml -- generated by `warhub-data classify --propose-joins`.
#
# Each entry is an LLM same-product verdict for a candidate pair a deterministic rule
# (matchedRules: ean / name / legacy-code) flagged as a SUSPECTED duplicate within one
# manufacturer. This file is a REVIEW ARTIFACT ONLY -- `classify --propose-joins` NEVER edits
# data/catalog/matches.yaml. A human (or the controller, with spot-check gates like Task 5's LLM
# classification waves) must manually copy the entityA/entityB pair of any entry with
# `acceptedCandidate: true` (verdict same-product, confidence >= 0.8) into matches.yaml's `joins`
# map -- spot-checking, not blindly trusting the threshold -- then re-run `resolve` and
# `report --ean-guard` (a join can change a confirmed EAN; guard findings are review items).
"""


def run_join_proposals(
    paths: DataPaths,
    *,
    run_date: str,
    client: AnthropicClient,
    budget: int = DEFAULT_BUDGET,
    model: str = DEFAULT_MODEL,
) -> JoinProposalSummary:
    candidates = generate_candidates(paths)

    cache_path = _cache_path(paths)
    cache = load_cache(cache_path, JoinCacheEntry)

    items: list[dict] = []
    for candidate in candidates:
        items.append({**candidate, "pairId": _pair_id(candidate)})

    pending: list[tuple[dict, str]] = []
    decided: dict[str, JoinCacheEntry] = {}
    cached_skips = 0
    for item in items:
        input_hash = compute_input_hash(item)
        cache_hit = cache.get(input_hash)
        if cache_hit is not None:
            cached_skips += 1
            decided[item["pairId"]] = cache_hit
            continue
        pending.append((item, input_hash))

    queried = 0
    requests_made = 0
    batches = batch_pending(pending, DEFAULT_BATCH_SIZE, budget)
    for batch in batches:
        pair_ids = [item["pairId"] for item, _ in batch]

        response = call_batch(
            client,
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            items=[_item_for_prompt(item) for item, _ in batch],
            max_tokens=DEFAULT_MAX_TOKENS,
        )
        requests_made += 1
        queried += len(batch)

        parsed = parse_response(extract_text(response), pair_ids, id_key="pairId")

        entries: list[JoinCacheEntry] = []
        for item, input_hash in batch:
            pair_id = item["pairId"]
            entry = _decide(
                parsed.get(pair_id), model, run_date, input_hash, item["entityA"]["entity"], item["entityB"]["entity"]
            )
            entries.append(entry)
            cache[entry.inputHash] = entry
            decided[pair_id] = entry

        # incremental flush -- a crash on the NEXT request must not lose this batch's decisions.
        append_cache_lines(cache_path, entries)

    accepted = 0
    rejected = 0
    unknown = 0
    low_confidence = 0
    proposals: list[dict] = []
    for candidate in candidates:
        pair_id = _pair_id(candidate)
        entry = decided.get(pair_id)
        if entry is None:
            continue  # budget-limited: neither cached nor queried this run
        is_accepted = (
            entry.verdict == "same-product" and entry.confidence is not None and entry.confidence >= ACCEPT_THRESHOLD
        )
        if entry.verdict == "unknown":
            unknown += 1
        elif entry.verdict == "different-product":
            rejected += 1
        elif is_accepted:
            accepted += 1
        else:
            low_confidence += 1
        proposals.append(
            {
                "entityA": candidate["entityA"],
                "entityB": candidate["entityB"],
                "manufacturer": candidate["manufacturer"],
                "matchedRules": candidate["matchedRules"],
                "verdict": entry.verdict,
                "confidence": entry.confidence,
                "acceptedCandidate": is_accepted,
                "model": entry.model,
                "date": entry.date,
                "inputHash": entry.inputHash,
            }
        )
    proposals.sort(key=lambda p: (p["entityA"]["entity"], p["entityB"]["entity"]))

    proposals_path = _proposals_path(paths)
    proposals_path.parent.mkdir(parents=True, exist_ok=True)
    proposals_path.write_text(
        _PROPOSALS_HEADER + dump_yaml({"proposals": proposals}), encoding="utf-8", newline="\n"
    )

    return JoinProposalSummary(
        candidates=len(candidates),
        queried=queried,
        cached_skips=cached_skips,
        accepted=accepted,
        rejected=rejected,
        unknown=unknown,
        low_confidence=low_confidence,
        requests=requests_made,
    )
