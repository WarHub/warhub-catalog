# tools/acquisition/tests/test_repo_data.py
"""Loads the REAL committed data/catalog/* through the real models so a config typo fails CI.

Uses a repo-root fixture rather than a package-relative one: this package can be built and
tested outside the monorepo (sdist), where ../../../../data does not exist -- skip cleanly
in that case instead of failing.
"""
import json
import re
from pathlib import Path

import pytest

from warhub_acquisition.models.catalog import Overrides
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.resolve import crossover
from warhub_acquisition.resolve.join import Matches
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy, load_labels
from warhub_acquisition.yamlio import read_yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_DATA = REPO_ROOT / "data"
PAINT_HARVEST_BRIDGE = REPO_ROOT / "tools/acquisition/scripts/gen_paint_harvest.py"


def _require_repo_data() -> DataPaths:
    if not REPO_DATA.exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")
    return DataPaths(REPO_DATA)


def test_repo_taxonomy_loads() -> None:
    paths = _require_repo_data()
    taxonomy = Taxonomy.load(paths.taxonomy)
    assert taxonomy.manufacturers
    for slug, manufacturer in taxonomy.manufacturers.items():
        assert manufacturer.slug == slug


def test_repo_labels_load() -> None:
    paths = _require_repo_data()
    game_systems, factions = load_labels(paths.taxonomy)
    assert game_systems
    assert factions


def test_repo_source_descriptors_validate() -> None:
    paths = _require_repo_data()
    descriptors = load_descriptors(paths.sources)
    assert descriptors
    for source_id, descriptor in descriptors.items():
        assert descriptor.id == source_id


def test_repo_matches_and_overrides_parse_when_present() -> None:
    paths = _require_repo_data()
    if paths.matches.exists():
        Matches.model_validate(read_yaml(paths.matches))
    if paths.overrides.exists():
        Overrides.model_validate(read_yaml(paths.overrides))


def test_every_paint_source_reaches_the_paint_catalog() -> None:
    """A harvested paint source that no bridge reads is evidence nobody consumes.

    Paint sources are deliberately excluded from the product catalog, so `gen_paint_harvest.py`
    is their ONLY route into anything published: if no bridge calls `read_observations` for a
    source id, its committed observations reach neither catalog and the harvest was wasted
    politeness. This is a contract, not a report -- a new paint source must land with its bridge
    (or, if the bridge genuinely cannot be written yet, the evidence should not be committed).

    "Paint source" = most of its observations are paint-kind. The ratio matters: mfr-gw-trade
    (346 paints in a 6,914-row trade workbook) and legacy-catalog are product sources that
    happen to carry some paints, and they reach the paint catalog by a different bridge
    (gen_paint_barcodes.py); mfr-reaper is a paint source whose paint-set pages are not.
    """
    paths = _require_repo_data()
    descriptors = load_descriptors(paths.sources)
    if not PAINT_HARVEST_BRIDGE.exists():
        pytest.skip("gen_paint_harvest.py not present (package tested outside the monorepo)")
    bridged = PAINT_HARVEST_BRIDGE.read_text(encoding="utf-8")

    evidence_dir = REPO_DATA / "evidence" / "products"
    unbridged = []
    for source_dir in sorted(p for p in evidence_dir.iterdir() if p.is_dir()):
        path = source_dir / "observations.jsonl"
        if not path.exists():
            continue
        categories = [
            (json.loads(line).get("hints") or {}).get("category")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        paints = sum(1 for category in categories if category and "paint" in str(category))
        if paints and paints * 2 >= len(categories):
            # It must ALSO be flagged `catalog: paints`, or the product resolver publishes every
            # one of its paints a SECOND time as a product -- the duplication that flag exists to
            # stop (measured once at 9 sources / 4,839 records).
            descriptor = descriptors.get(source_dir.name)
            assert descriptor is not None and descriptor.catalog == "paints", (
                f"{source_dir.name} is paint-majority evidence but is not `catalog: paints`, so "
                "the product resolver would publish its paints as products too."
            )
            if f'read_observations("{source_dir.name}")' not in bridged:
                unbridged.append(source_dir.name)

    assert not unbridged, (
        f"paint sources with no bridge in {PAINT_HARVEST_BRIDGE.name}: {unbridged} -- their "
        "observations reach neither the product catalog nor data/paints/"
    )


def test_repo_mappings_parse_when_present() -> None:
    _require_repo_data()
    # data/catalog/mappings/ does not exist yet (a later task creates it) -- tolerate its
    # absence today, but validate every file in it parses once it shows up.
    mappings_dir = REPO_DATA / "catalog" / "mappings"
    if not mappings_dir.exists():
        pytest.skip("data/catalog/mappings/ not created yet")
    files = sorted(mappings_dir.glob("*.yaml"))
    assert files
    for path in files:
        assert read_yaml(path) is not None


def test_repo_mappings_reference_only_known_taxonomy_slugs() -> None:
    """Every mapped gameSystem/faction slug must exist in the taxonomy label files -- strictly:
    a slug not yet in game-systems.yaml/factions.yaml is only tolerated if the mapping file
    explicitly lists it under a `newGameSystems:`/`newFactions:` allowlist key. No mapping file
    uses that escape hatch today (kept strict on purpose), but the mechanism exists so a future
    genuinely-new game system doesn't have to silently fail this check to get added.
    """
    paths = _require_repo_data()
    mappings_dir = REPO_DATA / "catalog" / "mappings"
    if not mappings_dir.exists():
        pytest.skip("data/catalog/mappings/ not created yet")

    game_systems, factions = load_labels(paths.taxonomy)

    for path in sorted(mappings_dir.glob("*.yaml")):
        data = read_yaml(path) or {}
        allowed_game_systems = set(data.get("newGameSystems", []))
        allowed_factions = set(data.get("newFactions", []))

        for raw, slug in (data.get("gameSystem") or {}).items():
            assert slug in game_systems or slug in allowed_game_systems, (
                f"{path.name}: gameSystem[{raw!r}] -> {slug!r} is not a known "
                f"taxonomy/game-systems.yaml slug and is not listed under newGameSystems"
            )

        for raw, slug in (data.get("faction") or {}).items():
            assert slug in factions or slug in allowed_factions, (
                f"{path.name}: faction[{raw!r}] -> {slug!r} is not a known "
                f"taxonomy/factions.yaml slug and is not listed under newFactions"
            )


# --- crossoverToProducts: the boxed sets that are products ----------------------------------
# Boxed multi-pot sets are products, not paints (maintainer decision 2026-08-05). Note that
# test_every_paint_source_reaches_the_paint_catalog above needs NO change and got none: the
# crossover carves rows OUT of a `catalog: paints` source without changing that flag, so its
# assertion (paint-majority evidence must be `catalog: paints`) still holds for all nine
# sources -- which is precisely why the flag was left byte-identical rather than turned into a
# mapping. A design that flipped a source to `catalog: products` would fail it immediately.

SOURCES_WITHOUT_A_CROSSOVER_BLOCK = [
    # Each records the measurement on its own descriptor; asserted here so a future block cannot
    # be added to one of them without someone deleting this line and reading why.
    "mfr-turbodork",  # 4 title hits, all junk: a display rack + three "_R" retailer trade packs
    "mfr-mr-hobby",  # SERIES-level evidence: `sku` is a range string ("C1~C189"), not an identity
    "mfr-vallejo",  # 0 of 1,194 titles match, and scope.urlInclude never fetched a sets endpoint
    "mfr-gw-webstore-paints",  # no committed evidence directory at all
]


def _crossover_descriptors() -> dict:
    paths = _require_repo_data()
    descriptors = load_descriptors(paths.sources)
    return {sid: d for sid, d in descriptors.items() if d.crossoverToProducts is not None}


def test_crossover_blocks_are_declared_on_paint_sources_with_a_reason() -> None:
    """T1. The block only makes sense on a `catalog: paints` source, and its `reason` is the
    only drift signal the mechanism has: `contract` measures the WHOLE source, so nothing fires
    if the PREDICATE collapses while the source stays healthy. A future reader diffing the
    recorded count against a fresh measurement is the mitigation, so the prose is mandatory."""
    blocks = _crossover_descriptors()
    assert blocks, "no source declares crossoverToProducts -- did the blocks get dropped?"
    for source_id, descriptor in blocks.items():
        rule = descriptor.crossoverToProducts
        assert descriptor.catalog == "paints", f"{source_id}: crossover on a non-paint source"
        assert len(rule.reason.strip()) >= 80, f"{source_id}: reason is too thin to audit"
        assert rule.category.strip(), f"{source_id}: no category to stamp"
        assert rule.anyOf, f"{source_id}: a block that selects nothing"


def test_crossover_name_patterns_compile() -> None:
    """T2. A regex lives in YAML here; a typo must fail in CI, not at resolve time."""
    for source_id, descriptor in _crossover_descriptors().items():
        rule = descriptor.crossoverToProducts
        for clause in [*rule.anyOf, *rule.noneOf]:
            if clause.nameMatches is not None:
                re.compile(clause.nameMatches)  # raises re.error on a bad pattern


def test_sources_without_a_crossover_block_declare_none() -> None:
    """T4. The deliberate absences, pinned. Each of these four was measured on 2026-08-05 and
    found to have nothing worth crossing; the comment on each descriptor says what."""
    paths = _require_repo_data()
    descriptors = load_descriptors(paths.sources)
    for source_id in SOURCES_WITHOUT_A_CROSSOVER_BLOCK:
        descriptor = descriptors.get(source_id)
        assert descriptor is not None, f"{source_id} descriptor vanished"
        assert descriptor.crossoverToProducts is None, (
            f"{source_id} grew a crossover block -- read the comment on its descriptor first"
        )


def test_no_crossed_set_also_reaches_the_paint_catalog() -> None:
    """T3, and the whole point: A SOURCE'S CROSSOVER PREDICATE IS EXACTLY WHAT ITS PAINT BRIDGE
    REFUSES. A row the product resolver admits must not also be published as an individual paint
    -- that is the double-publish `catalog: paints` exists to prevent, re-opened one carve-out at
    a time. Measured 2026-08-05: 0 of the 545 selected rows appear in any brand's harvest file.

    Joins on the BRIDGE's own code convention, not on `sourceUrl`: every Reaper single on a line
    page shares one URL, so a URL join reports false hits for all 115 Reaper sets.
    """
    paths = _require_repo_data()
    harvest_dir = REPO_DATA / "paints/harvest"
    if not harvest_dir.exists():
        pytest.skip("data/paints/harvest/ not generated")

    # source id -> (brand harvest slug, how that bridge spells a code)
    bridge_codes = {
        "mfr-ak-interactive": ("ak-interactive", lambda sku: sku),
        "mfr-armypainter": ("army-painter", lambda sku: sku),
        "mfr-greenstuffworld": ("green-stuff-world", lambda sku: sku),
        "mfr-monument": ("monument-pro-acryl", lambda sku: sku),
        "mfr-reaper": ("reaper", lambda sku: sku.lstrip("0")),  # site zero-pads, the base does not
        "mfr-scale75": ("scale75", lambda sku: sku),
    }

    offenders = []
    for source_id, descriptor in _crossover_descriptors().items():
        brand, spell = bridge_codes[source_id]
        harvest_path = harvest_dir / f"{brand}.yaml"
        if not harvest_path.exists():
            continue
        data = (read_yaml(harvest_path) or {}).get(brand) or {}
        published = {str(entry.get("sku")) for entry in (data.get("enrich") or {}).values()}
        published |= {str(entry.get("productCode")) for entry in data.get("additions") or []}
        published.discard("None")

        spec = descriptor.crossoverToProducts.model_dump()
        path = REPO_DATA / "evidence/products" / source_id / "observations.jsonl"
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            observation = json.loads(raw)
            if not crossover.matches(observation, spec):
                continue
            code = spell(str(observation.get("sku") or ""))
            if code and code in published:
                offenders.append((brand, code, observation.get("name")))

    assert not offenders, (
        f"rows that cross to the product catalog AND publish as paints: {offenders}"
    )
