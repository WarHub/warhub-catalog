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

    def current_groups_and_ids() -> tuple[dict[str, list[Observation]], dict[str, str]]:
        current: dict[str, list[Observation]] = {}
        for observation in attributed:
            current.setdefault(uf.find(observation.key), []).append(observation)
        return current, {root: group_entity_id(members) for root, members in current.items()}

    # forced joins from matches.yaml: resolve targets through aliases (targets written as old
    # ids follow the alias like everything else), then apply as a fixpoint -- unioning a forced
    # key's group into whichever group currently carries the resolved target id, recomputing
    # groups/provisional ids after each successful union so chained forced joins (where one
    # union changes another group's provisional id) still resolve. Bounded by len(entries) + 1
    # full passes.
    attributed_keys = {observation.key for observation in attributed}
    forced_entries = sorted(
        (key, target) for key, target in matches.joins.items() if key in attributed_keys
    )

    groups, provisional = current_groups_and_ids()
    for _ in range(len(forced_entries) + 1):
        pass_changed = False
        for key, target in forced_entries:
            resolved_target = matches.aliases.get(target, target)
            root = uf.find(key)
            if provisional.get(root) == resolved_target:
                continue
            match_root = next(
                (
                    other_root
                    for other_root, eid in sorted(provisional.items())
                    if eid == resolved_target and other_root != root
                ),
                None,
            )
            if match_root is not None:
                uf.union(root, match_root)
                pass_changed = True
                groups, provisional = current_groups_and_ids()
        if not pass_changed:
            break

    # a forced join has "resolved" once its observation's group carries the (alias-resolved)
    # target id -- record which group roots that applies to, so the name-join pass below only
    # skips groups whose forced join actually took effect (an unresolved forced join must not
    # suppress the name-join fallback).
    resolved_forced_roots: set[str] = set()
    for key, target in forced_entries:
        resolved_target = matches.aliases.get(target, target)
        root = uf.find(key)
        if provisional.get(root) == resolved_target:
            resolved_forced_roots.add(root)

    # name-join pass for anchorless observations (no code, no valid EAN, no resolved forced join)
    slug_index: dict[tuple[str, str], list[str]] = {}
    for root, members in groups.items():
        if any(codes[m.key] is not None for m in members):
            for slug in sorted({slugify(m.name) for m in members}):
                slug_index.setdefault((members[0].manufacturer, slug), []).append(root)

    for root, members in sorted(groups.items()):
        if any(codes[m.key] is not None or eans[m.key] is not None for m in members):
            continue
        if root in resolved_forced_roots:
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

    # final grouping + ids -- distinct union-find components can still resolve to the same
    # final id (alias collapsing two coded groups, or two anchorless groups sharing a
    # manufacturer+name-slug that name-join never merges since it only joins anchorless INTO
    # coded groups). Merge member lists on collision instead of silently dropping one group.
    final_groups: dict[str, list[Observation]] = {}
    for observation in attributed:
        final_groups.setdefault(uf.find(observation.key), []).append(observation)
    entities: dict[str, list[Observation]] = {}
    for members in final_groups.values():
        entities.setdefault(group_entity_id(members), []).extend(members)
    for members in entities.values():
        members.sort(key=lambda m: _priority(m, kinds))
    result.entities = dict(sorted(entities.items()))

    # report matches.joins entries that never resolved: the observation exists but did not end
    # up in an entity whose id equals the (alias-resolved) target.
    observation_by_key = {observation.key: observation for observation in observations}
    key_to_entity = {
        member.key: eid for eid, members in result.entities.items() for member in members
    }
    for key, target in sorted(matches.joins.items()):
        if key not in observation_by_key:
            continue
        resolved_target = matches.aliases.get(target, target)
        if key_to_entity.get(key) != resolved_target:
            result.ambiguous.append({"type": "unresolved-forced-join", "key": key, "target": target})

    return result
