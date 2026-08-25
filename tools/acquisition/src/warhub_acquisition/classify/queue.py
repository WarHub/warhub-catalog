"""Build the classification queue: published products with a null gameSystem (gameSystem is
optional -- a product genuinely belonging to no game system, e.g. a base, gaming mat, paint/tool
bundle, dice, or advent calendar, publishes with gameSystem: null rather than being parked out of
the catalog) awaiting an OPTIONAL gameSystem/faction decision, with enough context for an LLM
(Task 5) to classify each one.
"""
import html as html_lib
import re

from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.join import Matches, join_observations
from warhub_acquisition.resolve.resolver import DataPaths, select_product_observations
from warhub_acquisition.taxonomy import Taxonomy, load_labels
from warhub_acquisition.yamlio import read_yaml

_DESCRIPTION_LIMIT = 300
# gameSystem/faction are excluded here because a null-gameSystem entity's members typically
# never carried a gameSystem hint in the first place (that's why it resolved to null); description
# gets its own dedicated, truncated field below, so it is excluded from the generic raw-hints
# list too.
# `contentSkus` is excluded for size, not for relevance: EVERY paint-set product has a null
# gameSystem, so all of them reach this queue, and reaper/09956 alone carries 216 codes. A contents
# list tells an LLM nothing about a game system and would crowd the prompt.
_EXCLUDED_HINT_KEYS = {"gameSystem", "faction", "description", "contentSkus"}


_TAG = re.compile(r"<[^>]+>")


def _prompt_description(raw: object) -> str:
    """The description an LLM actually reads: markup flattened, THEN truncated to 300 chars.

    ORDER IS THE WHOLE POINT. Sources store their words verbatim, which for a WooCommerce store
    means raw HTML, and a 300-char window taken off the front of that is mostly angle brackets.
    Measured 2026-08-07 over the 999 live rows of AK's `paints-acrylics` category: the raw window
    is 45% prose on average (median 49%, worst 5%), 512 of the 999 rows are under half prose, and
    the leading run of markup alone averages 61 chars (max 115). EVERY one of AK's boxed sets has a
    null gameSystem, so all of them reach this queue -- they would have arrived spending a third of
    their budget on `<span class="collapseomatic ...>`.

    THIS IS THE RIGHT LAYER FOR IT, and it is why acquire/strategies/woo_paints.py stores
    `short_description` unsliced: a retune of a PROMPT costs nothing, while a retune of what was
    stored costs a full re-fetch. Flattening is skipped entirely when there is no tag, so it is
    byte-identical for the `legacy-catalog` descriptions, which are the bulk of the corpus and
    almost never carry markup.

    THE WOOCOMMERCE CASE IS NOT HYPOTHETICAL, and an earlier version of this note read as though it
    were: it said only four committed descriptions contained a tag, which was true before AK was
    acquired and is now wrong by three orders of magnitude. `mfr-ak-interactive`'s descriptions are
    committed HTML and essentially every one carries a tag, so they are the population this function
    exists for rather than a future one. Re-derive by grepping `"description":` and then for a tag
    across data/evidence/products/*/observations.jsonl.
    """
    text = str(raw)
    if _TAG.search(text):
        text = re.sub(r"\s+", " ", html_lib.unescape(_TAG.sub(" ", text))).strip()
    return text[:_DESCRIPTION_LIMIT]


def _first(values: list[object | None]) -> object | None:
    return next((value for value in values if value is not None), None)


def _load_matches(paths: DataPaths) -> Matches:
    if paths.matches.exists():
        return Matches.model_validate(read_yaml(paths.matches))
    return Matches()


def _joined_entities(paths: DataPaths) -> dict[str, list[Observation]]:
    """Re-run the resolver's join step (evidence + taxonomy + matches -> entity -> members) so a
    null-gameSystem entity's full member-observation set is available. The resolved
    CanonicalProduct only keeps a handful of folded hint fields (category/packaging/quantity/
    description), not the raw per-source hints dict this queue's "hints" field needs, and
    resolve_catalog does not expose joined members itself (it only returns finished
    CanonicalProducts and writes conflicts.yaml) -- so the join is repeated here rather than
    duplicating queue-building into resolver.py.

    REPEATING THE JOIN MEANS REPEATING ITS INPUT, and that is what `select_product_observations`
    is for. This function used to flatten the whole evidence store instead, which silently added
    the paint-source rows the product catalog deliberately excludes; the extra members changed
    which product code won the identity ordering, so the join produced ids the catalog does not
    have and `build_queue` raised on a product that exists. See ProductObservations for the
    measured case (`army-painter/CP3001` -> `army-painter/CP3001S`).
    """
    taxonomy = Taxonomy.load(paths.taxonomy)
    descriptors = load_descriptors(paths.sources)
    kinds = {sid: descriptor.kind for sid, descriptor in descriptors.items()}
    evidence = EvidenceStore(paths.evidence_products).load_all()
    selected = select_product_observations(evidence, descriptors, taxonomy)
    joined = join_observations(selected.observations, taxonomy, kinds, _load_matches(paths))
    return joined.entities


def _unclassified_entity_ids(paths: DataPaths) -> list[str]:
    """Every product id in the RESOLVED catalog (data/catalog/products/*.yaml) whose gameSystem
    is null. gameSystem is optional now -- the resolver publishes these products instead of
    parking them -- but they still await an OPTIONAL classification decision.
    """
    if not paths.catalog_products.exists():
        return []
    ids: set[str] = set()
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        data = read_yaml(path) or {}
        for record in data.get("products") or []:
            if record.get("gameSystem") is None:
                ids.add(record["id"])
    return sorted(ids)


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
    """One queue item per null-gameSystem product in the resolved catalog, sorted by entity id
    for determinism."""
    unclassified = _unclassified_entity_ids(paths)
    if not unclassified:
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
    for entity in unclassified:
        members = entities.get(entity)
        if not members:
            raise ValueError(f"null-gameSystem product {entity!r} has no matching evidence")
        description = _first([member.hints.get("description") for member in members])
        queue.append(
            {
                "entity": entity,
                "name": members[0].name,
                "manufacturer": members[0].manufacturer,
                "url": _first([member.url for member in members]),
                "description": _prompt_description(description) if description else None,
                "hints": _raw_hints(members),
                "candidates": candidates,
            }
        )
    return queue
