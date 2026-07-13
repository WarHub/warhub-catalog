"""Build the classification queue: parked ('unclassified-entity') conflicts awaiting a
gameSystem/faction decision, with enough context for an LLM (Task 5) to classify each one.
"""
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.join import Matches, join_observations
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy, load_labels
from warhub_acquisition.yamlio import read_yaml

_DESCRIPTION_LIMIT = 300
# gameSystem/faction are definitionally absent on a parked entity's members (that's *why* it's
# parked -- no source hinted a gameSystem the resolver could use); description gets its own
# dedicated, truncated field below, so it is excluded from the generic raw-hints list too.
_EXCLUDED_HINT_KEYS = {"gameSystem", "faction", "description"}


def _first(values: list[object | None]) -> object | None:
    return next((value for value in values if value is not None), None)


def _load_matches(paths: DataPaths) -> Matches:
    if paths.matches.exists():
        return Matches.model_validate(read_yaml(paths.matches))
    return Matches()


def _joined_entities(paths: DataPaths) -> dict[str, list[Observation]]:
    """Re-run the resolver's join step (evidence + taxonomy + matches -> entity -> members) so
    a parked entity's full member-observation set is available. resolve_catalog does not expose
    this itself (it only returns finished CanonicalProducts and writes conflicts.yaml), so the
    join is repeated here rather than duplicating queue-building into resolver.py.
    """
    taxonomy = Taxonomy.load(paths.taxonomy)
    descriptors = load_descriptors(paths.sources)
    kinds = {sid: descriptor.kind for sid, descriptor in descriptors.items()}
    evidence = EvidenceStore(paths.evidence_products).load_all()
    observations = [observation for source in evidence.values() for observation in source.values()]
    joined = join_observations(observations, taxonomy, kinds, _load_matches(paths))
    return joined.entities


def _parked_entity_ids(paths: DataPaths) -> list[str]:
    if not paths.conflicts.exists():
        return []
    conflicts = read_yaml(paths.conflicts) or {}
    return sorted(
        {c["entity"] for c in conflicts.get("conflicts") or [] if c.get("type") == "unclassified-entity"}
    )


def _observed_factions_by_game_system(paths: DataPaths, known_factions: set[str]) -> dict[str, list[str]]:
    """Derive gameSystem -> observed faction slugs from the already-resolved catalog.

    taxonomy/factions.yaml and taxonomy/game-systems.yaml are both flat, ungrouped slug/label
    lists -- there is no static gameSystem<->faction association anywhere in the taxonomy
    layer. The only place a real gameSystem+faction pairing exists today is the resolved
    data/catalog/products/*.yaml written by `resolve`. A game system with no resolved products
    yet gets no entry here at all, rather than being handed the full faction list as a
    misleading "these are all valid" signal.
    """
    by_game_system: dict[str, set[str]] = {}
    if paths.catalog_products.exists():
        for path in sorted(paths.catalog_products.glob("*.yaml")):
            data = read_yaml(path) or {}
            for record in data.get("products") or []:
                game_system = record.get("gameSystem")
                faction = record.get("faction")
                if game_system and faction and faction in known_factions:
                    by_game_system.setdefault(game_system, set()).add(faction)
    return {game_system: sorted(factions) for game_system, factions in sorted(by_game_system.items())}


def _raw_hints(members: list[Observation]) -> list[str]:
    values: set[str] = set()
    for member in members:
        for key, value in member.hints.items():
            if key not in _EXCLUDED_HINT_KEYS:
                values.add(f"{key}={value}")
    return sorted(values)


def build_queue(paths: DataPaths) -> list[dict]:
    """One queue item per unclassified-entity conflict, sorted by entity id for determinism."""
    parked = _parked_entity_ids(paths)
    if not parked:
        return []

    entities = _joined_entities(paths)
    game_system_labels, faction_labels = load_labels(paths.taxonomy)
    # a single shared dict, reused by reference in every item: yamlio's dump_yaml aliases
    # repeated-identity nodes, so this real-world-sized (~47 gameSystems / ~140 factions) block
    # is written once and referenced, not duplicated 2000+ times over.
    candidates = {
        "gameSystems": sorted(game_system_labels),
        "factions": _observed_factions_by_game_system(paths, set(faction_labels)),
    }

    queue: list[dict] = []
    for entity in parked:
        members = entities.get(entity)
        if not members:
            raise ValueError(f"unclassified-entity {entity!r} in conflicts.yaml has no matching evidence")
        description = _first([member.hints.get("description") for member in members])
        queue.append(
            {
                "entity": entity,
                "name": members[0].name,
                "manufacturer": members[0].manufacturer,
                "url": _first([member.url for member in members]),
                "description": str(description)[:_DESCRIPTION_LIMIT] if description else None,
                "hints": _raw_hints(members),
                "candidates": candidates,
            }
        )
    return queue
