# tools/acquisition/src/warhub_acquisition/resolve/join.py
"""Deterministic entity resolution: group observations via union-find."""
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.models.descriptor import KIND_PRIORITY
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.identity import entity_id, slugify
from warhub_acquisition.taxonomy import Taxonomy


class Matches(BaseModel):
    model_config = ConfigDict(extra="forbid")
    joins: dict[str, str] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)


@dataclass
class JoinResult:
    entities: dict[str, list[Observation]] = field(default_factory=dict)
    ambiguous: list[dict] = field(default_factory=list)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)  # deterministic root choice


def _priority(observation: Observation, kinds: dict[str, str]) -> tuple[int, str]:
    return (KIND_PRIORITY.get(kinds.get(observation.source_id, "barcode-db"), 9), observation.key)


def join_observations(
    observations: list[Observation],
    taxonomy: Taxonomy,
    kinds: dict[str, str],
    matches: Matches,
) -> JoinResult:
    result = JoinResult()
    ordered = sorted(observations, key=lambda o: _priority(o, kinds))

    # classify: unattributed (no manufacturer), degenerate (no code/EAN/forced-join and empty
    # name slug -- would otherwise form a bogus "manufacturer/" entity), else attributed.
    attributed: list[Observation] = []
    codes: dict[str, str | None] = {}
    eans: dict[str, str | None] = {}
    for observation in ordered:
        if not observation.manufacturer:
            result.ambiguous.append({"type": "unattributed", "key": observation.key, "name": observation.name})
            continue
        code = taxonomy.normalize_code(observation.manufacturer, observation.sku)
        ean = canonical_ean(observation.ean)
        forced = matches.joins.get(observation.key)
        if code is None and ean is None and not forced and slugify(observation.name) == "":
            result.ambiguous.append(
                {"type": "degenerate-name", "key": observation.key, "name": observation.name}
            )
            continue
        codes[observation.key] = code
        eans[observation.key] = ean
        attributed.append(observation)

    uf = _UnionFind()
    code_index: dict[tuple[str, str], str] = {}
    ean_index: dict[str, str] = {}
    for observation in attributed:
        code = codes[observation.key]
        ean = eans[observation.key]
        if code is not None:
            anchor = code_index.setdefault((observation.manufacturer, code), observation.key)
            uf.union(anchor, observation.key)
        if ean is not None:
            anchor = ean_index.setdefault(ean, observation.key)
            uf.union(anchor, observation.key)

    # forced joins from matches.yaml: union with any member already carrying that entity id target
    forced_targets: dict[str, str] = {}  # entity id -> anchor key
    for observation in attributed:
        target = matches.joins.get(observation.key)
        if target:
            forced_targets.setdefault(target, observation.key)

    groups: dict[str, list[Observation]] = {}
    for observation in attributed:
        groups.setdefault(uf.find(observation.key), []).append(observation)

    # provisional entity id per group
    def group_entity_id(members: list[Observation]) -> str:
        best_code = min(
            (
                (_priority(m, kinds), codes[m.key])
                for m in members
                if codes[m.key] is not None
            ),
            default=None,
        )
        anchor = min(members, key=lambda m: _priority(m, kinds))
        raw = entity_id(anchor.manufacturer, best_code[1] if best_code else None, anchor.name)
        return matches.aliases.get(raw, raw)

    provisional: dict[str, str] = {root: group_entity_id(members) for root, members in groups.items()}

    # apply forced joins: merge groups whose provisional id equals a forced target
    for target, anchor_key in sorted(forced_targets.items()):
        for root, eid in sorted(provisional.items()):
            if eid == target:
                uf.union(root, anchor_key)

    # name-join pass for anchorless observations (no code, no valid EAN, not forced)
    groups = {}
    for observation in attributed:
        groups.setdefault(uf.find(observation.key), []).append(observation)
    provisional = {root: group_entity_id(members) for root, members in groups.items()}

    slug_index: dict[tuple[str, str], list[str]] = {}
    for root, members in groups.items():
        if any(codes[m.key] is not None for m in members):
            for slug in sorted({slugify(m.name) for m in members}):
                slug_index.setdefault((members[0].manufacturer, slug), []).append(root)

    for root, members in sorted(groups.items()):
        if any(codes[m.key] is not None or eans[m.key] is not None for m in members):
            continue
        if any(matches.joins.get(m.key) for m in members):
            continue
        candidates = sorted(
            {r for m in members for r in slug_index.get((m.manufacturer, slugify(m.name)), [])}
        )
        if len(candidates) == 1:
            uf.union(candidates[0], root)
        elif len(candidates) > 1:
            result.ambiguous.append(
                {
                    "type": "ambiguous-join",
                    "keys": sorted(m.key for m in members),
                    "name": members[0].name,
                    "candidates": sorted(provisional[c] for c in candidates),
                }
            )

    # final grouping + ids
    final_groups: dict[str, list[Observation]] = {}
    for observation in attributed:
        final_groups.setdefault(uf.find(observation.key), []).append(observation)
    for members in final_groups.values():
        members.sort(key=lambda m: _priority(m, kinds))
    entities = {group_entity_id(members): members for members in final_groups.values()}
    result.entities = dict(sorted(entities.items()))
    return result
