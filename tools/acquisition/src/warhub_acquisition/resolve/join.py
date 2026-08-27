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
    # Declared product lineage: `{retired entity id: surviving entity id}`. Unlike `joins` (which
    # merges observations that are ONE product) this is a LINK between two products that both keep
    # their own record -- the retired one keeps its own product code, barcode, name and firstSeen,
    # and gains `supersededBy`; the survivor gains `supersedes`. People own boxes for decades, so a
    # retired code/barcode must stay resolvable rather than being folded away. See resolve/resolver.py
    # for where the link is stamped, and the union barrier below for what stops the two sides
    # silently re-merging.
    supersessions: dict[str, str] = Field(default_factory=dict)
    # Hand corrections for a single observation whose retailer SKU carries the WRONG product code,
    # bridging two genuinely different products into one entity. Maps observation key -> the correct
    # normalized product code. Applied before union-find grouping so the mis-coded observation joins
    # the right entity and the other product splits back out. Use ONLY for a demonstrable retailer
    # mis-code (e.g. a single-miniature listing tagged with an army-set's code); it is not a general
    # re-slotting tool. See resolve/join.py where `code` is computed.
    reassignCodes: dict[str, str] = Field(default_factory=dict)


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
    sku_is_listing_id: dict[str, bool] | None = None,
) -> JoinResult:
    result = JoinResult()
    sku_is_listing_id = sku_is_listing_id or {}
    ordered = sorted(observations, key=lambda o: _priority(o, kinds))

    # barcode-db observations must never MINT an entity -- they exist only to corroborate an
    # ean some OTHER (non-barcode-db) source already asserted for the same manufacturer. Collect
    # every (manufacturer, ean) pair asserted by a non-barcode-db observation up front, so the
    # classify loop below can tell a barcode-db observation that is genuinely joining an existing
    # entity from one whose ean matches nothing -- the latter must be dropped, not name-joined.
    non_barcode_db_eans: dict[str, set[str]] = {}
    for observation in ordered:
        if not observation.manufacturer:
            continue
        if kinds.get(observation.source_id, "barcode-db") == "barcode-db":
            continue
        ean = canonical_ean(observation.ean)
        if ean is not None:
            non_barcode_db_eans.setdefault(observation.manufacturer, set()).add(ean)

    # classify: unattributed (no manufacturer), unjoined barcode-db (ean matches no other
    # source's assertion for this manufacturer -- see above), degenerate (no code/EAN/forced-join
    # and empty name slug -- would otherwise form a bogus "manufacturer/" entity), else attributed.
    attributed: list[Observation] = []
    codes: dict[str, str | None] = {}
    eans: dict[str, str | None] = {}
    for observation in ordered:
        if not observation.manufacturer:
            result.ambiguous.append({"type": "unattributed", "key": observation.key, "name": observation.name})
            continue
        code = matches.reassignCodes.get(observation.key) or taxonomy.normalize_code(
            observation.manufacturer, observation.sku
        )
        ean = canonical_ean(observation.ean)
        forced = matches.joins.get(observation.key)
        is_barcode_db = kinds.get(observation.source_id, "barcode-db") == "barcode-db"
        if (
            is_barcode_db
            and not forced
            and ean not in non_barcode_db_eans.get(observation.manufacturer, set())
        ):
            result.ambiguous.append(
                {
                    "type": "barcode-db-unjoined",
                    "key": observation.key,
                    "name": observation.name,
                    "ean": observation.ean,
                }
            )
            continue
        if code is None and ean is None and not forced and slugify(observation.name) == "":
            result.ambiguous.append(
                {"type": "degenerate-name", "key": observation.key, "name": observation.name}
            )
            continue
        codes[observation.key] = code
        eans[observation.key] = ean
        attributed.append(observation)

    # --- declared supersessions: the two sides must never end up in one group -------------------
    # A pair is expressed as entity ids; both sides of every pair in use today are
    # `manufacturer/<product code>`, so the pair reduces to two codes under one manufacturer (a
    # name-slug suffix simply never equals any observation's normalized code, and the pair is then
    # inert here -- nothing can bridge it by code anyway).
    barred_pairs: dict[str, list[tuple[str, str]]] = {}
    for retired, surviving in sorted(matches.supersessions.items()):
        retired = matches.aliases.get(retired, retired)
        surviving = matches.aliases.get(surviving, surviving)
        retired_manufacturer, _, retired_code = retired.partition("/")
        surviving_manufacturer, _, surviving_code = surviving.partition("/")
        if (
            retired_manufacturer == surviving_manufacturer
            and retired_code
            and surviving_code
            and retired_code != surviving_code
        ):
            barred_pairs.setdefault(retired_manufacturer, []).append((retired_code, surviving_code))

    # Which side of a declared pair OWNS a contested barcode: a barcode the MANUFACTURER asserts
    # under code C is C's own barcode. `(manufacturer, ean) -> (owning code, the other side)`.
    manufacturer_code_eans: dict[tuple[str, str], set[str]] = {}
    for observation in attributed:
        if kinds.get(observation.source_id) != "manufacturer":
            continue
        code, ean = codes[observation.key], eans[observation.key]
        if code is not None and ean is not None:
            manufacturer_code_eans.setdefault((observation.manufacturer, code), set()).add(ean)
    pair_owner: dict[tuple[str, str], tuple[str, str]] = {}
    for manufacturer, pairs in barred_pairs.items():
        for retired_code, surviving_code in pairs:
            retired_eans = manufacturer_code_eans.get((manufacturer, retired_code), set())
            surviving_eans = manufacturer_code_eans.get((manufacturer, surviving_code), set())
            for ean in retired_eans - surviving_eans:
                pair_owner.setdefault((manufacturer, ean), (retired_code, surviving_code))
            for ean in surviving_eans - retired_eans:
                pair_owner.setdefault((manufacturer, ean), (surviving_code, retired_code))

    uf = _UnionFind()
    code_index: dict[tuple[str, str], str] = {}
    # GS1 EANs are manufacturer-scoped, so joins are keyed by (manufacturer, ean): a
    # validated EAN shared by two DIFFERENT manufacturers is bad data to surface, not a
    # merge instruction -- ean_owners tracks the first manufacturer to claim each ean so a
    # second, different manufacturer asserting it is reported instead of unioned.
    ean_index: dict[tuple[str, str], str] = {}
    ean_owners: dict[str, str] = {}
    ean_conflicts: set[str] = set()
    # ean_claims tracks EVERY observation key that asserted a given validated ean, regardless
    # of manufacturer -- used to build cross-manufacturer-ean payloads with the complete set of
    # disputing keys (not just the owner's anchor + the other manufacturers' keys).
    ean_claims: dict[str, set[str]] = {}
    # Product codes present in each union-find group, maintained alongside the unions so the
    # supersession barrier can ask "would merging these two groups put both sides of a declared
    # pair in one entity?" -- the transitive question, not just "do these two observations
    # disagree". Keyed by group root; merged on every union.
    group_codes: dict[str, set[str]] = {}

    def union(a: str, b: str) -> None:
        root_a, root_b = uf.find(a), uf.find(b)
        if root_a == root_b:
            return
        uf.union(a, b)
        merged = group_codes.pop(root_a, set()) | group_codes.pop(root_b, set())
        if merged:
            group_codes[uf.find(a)] = merged

    def barred(a: str, b: str, manufacturer: str) -> tuple[str, str] | None:
        root_a, root_b = uf.find(a), uf.find(b)
        if root_a == root_b:
            return None  # already one group; nothing to bar and no union to report
        merged = group_codes.get(root_a, set()) | group_codes.get(root_b, set())
        return next(
            (
                pair
                for pair in barred_pairs.get(manufacturer, ())
                if pair[0] in merged and pair[1] in merged
            ),
            None,
        )

    blocked_bridges: dict[tuple[str, str, str], set[str]] = {}
    for observation in attributed:
        code = codes[observation.key]
        ean = eans[observation.key]
        # A bridging observation carrying one side of a declared pair as its SKU while scanning as
        # the other side's barcode is placed by BARCODE: the barcode identifies the box in hand,
        # the SKU is only the lister's catalogue number, and it goes stale across a re-code. This
        # is what puts a retailer's live price/url on the record a shopper can actually buy, and
        # leaves the retired record attested by its own (usually archived) manufacturer evidence.
        owner = pair_owner.get((observation.manufacturer, ean)) if ean is not None else None
        if owner is not None and code == owner[1]:
            result.ambiguous.append(
                {
                    "type": "supersession-stale-code",
                    "key": observation.key,
                    "ean": ean,
                    "listed_code": code,
                    "barcode_code": owner[0],
                    "manufacturer": observation.manufacturer,
                }
            )
            # Discard the stale code EVERYWHERE, not just for the unions below. `codes` is what
            # `group_entity_id` ranks to name a group, and it ranks by source kind -- so a re-homed
            # observation left holding its stale code can still NAME the group it was re-homed
            # into. Measured 2026-07-30 on Mortisan Boneshaper and Boingrot Bounderz: the retired
            # component is built correctly (the manufacturer's own retired code + barcode, plus the
            # re-homed bridges) and is then named `games-workshop/<SURVIVING code>` by a re-homed
            # `curated` observation, whose kind outranks the manufacturer's. The retired component
            # collides with the survivor's id and the final id-keyed merge folds the two back into
            # one entity -- undoing the split that the barrier and the re-homing just achieved, and
            # reporting the declared pair as `unresolved-supersession`. The three pairs declared
            # before this escaped only because their bridge was a `retailer`, which loses that rank.
            codes[observation.key] = None
            code = None
        if code is not None:
            group_codes.setdefault(uf.find(observation.key), set()).add(code)
            anchor = code_index.setdefault((observation.manufacturer, code), observation.key)
            union(anchor, observation.key)
        if ean is not None:
            ean_claims.setdefault(ean, set()).add(observation.key)
            owner_manufacturer = ean_owners.setdefault(ean, observation.manufacturer)
            if owner_manufacturer == observation.manufacturer:
                anchor = ean_index.setdefault((observation.manufacturer, ean), observation.key)
                pair = barred(anchor, observation.key, observation.manufacturer)
                if pair is None:
                    union(anchor, observation.key)
                else:
                    # THE union barrier. Without it a single bridging observation re-merges a
                    # declared pair through the shared barcode and the retired record disappears
                    # again -- measured on every GW repackaging pair, 2026-07-30.
                    blocked_bridges.setdefault(
                        (observation.manufacturer, pair[0], pair[1]), set()
                    ).update({anchor, observation.key})
            else:
                ean_conflicts.add(ean)

    # --- per-source listing identity: one store article number is one store listing -------------
    # For a source that declares `skuIsListingId`, two of ITS OWN observations carrying the same
    # non-empty `sku` are the same listing re-keyed, and are unioned as such. This runs AFTER the
    # code/ean unions above so it attaches an anchorless member to whatever its twin already
    # anchored on, rather than founding a group of its own.
    #
    # WHY A SOURCE NEEDS THIS. A source's observation key is a function of its strategy -- a
    # sitemap path under `sitemap-structured-data`, a handle under `shopify` -- so changing a
    # source's strategy re-keys every listing it has. `EvidenceStore.upsert` is keyed per
    # observation and a `full_sweep=False` source never prunes, so both generations stay in the
    # ledger and the store is represented twice. The store's own article number is the one
    # identity that survives the change.
    #
    # THE GUARD IS THE POINT, and it is why this is opt-in per source rather than a global rule.
    # A group whose members assert MORE THAN ONE distinct barcode is not one listing -- it is a
    # store reusing an article number, and unioning it would fabricate a product. Such a group is
    # reported and left alone. Measured 2026-08-26 over all 31 evidence sources: 4,323 groups of
    # >= 2 observations share a sku, and exactly 3 disagree on the barcode (2 `arc-tistaminis`,
    # 1 `arc-wargameportal`) -- none of which has an anchorless member, so none of them is a group
    # this pass would otherwise change. Nothing anywhere disagrees on the normalized product code
    # or on the manufacturer.
    sku_groups: dict[tuple[str, str], list[Observation]] = {}
    for observation in attributed:
        if not observation.sku or not sku_is_listing_id.get(observation.source_id):
            continue
        sku_groups.setdefault((observation.source_id, observation.sku), []).append(observation)
    for (source_id, sku), members in sorted(sku_groups.items()):
        if len(members) < 2:
            continue
        distinct_eans = {eans[m.key] for m in members} - {None}
        if len(distinct_eans) > 1:
            result.ambiguous.append(
                {
                    "type": "sku-group-ean-conflict",
                    "source": source_id,
                    "sku": sku,
                    "keys": sorted(m.key for m in members),
                    "eans": sorted(distinct_eans),
                }
            )
            continue
        anchor = min(members, key=lambda m: _priority(m, kinds)).key
        for member in members:
            pair = barred(anchor, member.key, member.manufacturer)
            if pair is None:
                union(anchor, member.key)
            else:
                blocked_bridges.setdefault((member.manufacturer, pair[0], pair[1]), set()).update(
                    {anchor, member.key}
                )

    for (manufacturer, retired_code, surviving_code), keys in sorted(blocked_bridges.items()):
        result.ambiguous.append(
            {
                "type": "supersession-blocked-merge",
                "retired": f"{manufacturer}/{retired_code}",
                "surviving": f"{manufacturer}/{surviving_code}",
                "keys": sorted(keys),
            }
        )

    for ean in sorted(ean_conflicts):
        result.ambiguous.append(
            {"type": "cross-manufacturer-ean", "ean": ean, "keys": sorted(ean_claims[ean])}
        )

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
    manufacturer_by_key = {observation.key: observation.manufacturer for observation in attributed}
    forced_entries = sorted(
        (key, target) for key, target in matches.joins.items() if key in manufacturer_by_key
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
                # A forced join that would collapse a declared supersession is a contradiction
                # between two hand-written instructions. The supersession wins (it is the whole
                # point of keeping the retired record) and the join is left unresolved -- the
                # existing `unresolved-forced-join` report below then names it for a human.
                if barred(root, match_root, manufacturer_by_key[key]) is not None:
                    continue
                union(root, match_root)
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
            union(candidates[0], root)
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

    # report supersessions whose ids resolve to no entity: entity ids fall back to name slugs, so
    # a code that stops being observed (or a typo) leaves the link pointing at nothing. A dangling
    # link publishes as silence, which is exactly what this whole phase exists to prevent.
    for retired, surviving in sorted(matches.supersessions.items()):
        missing = sorted(
            {
                eid
                for eid in (
                    matches.aliases.get(retired, retired),
                    matches.aliases.get(surviving, surviving),
                )
                if eid not in result.entities
            }
        )
        if missing:
            result.ambiguous.append(
                {
                    "type": "unresolved-supersession",
                    "retired": retired,
                    "surviving": surviving,
                    "missing": missing,
                }
            )

    return result
