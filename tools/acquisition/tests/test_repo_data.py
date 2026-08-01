# tools/acquisition/tests/test_repo_data.py
"""Loads the REAL committed data/catalog/* through the real models so a config typo fails CI.

Uses a repo-root fixture rather than a package-relative one: this package can be built and
tested outside the monorepo (sdist), where ../../../../data does not exist -- skip cleanly
in that case instead of failing.
"""
import json
from pathlib import Path

import pytest

from warhub_acquisition.models.catalog import Overrides
from warhub_acquisition.models.descriptor import load_descriptors
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
    _require_repo_data()
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


# Sources flagged `catalog: paints` are skipped by the product resolver, so the ONLY thing that
# consumes them is a bridge in scripts/gen_paint_harvest.py. A source with neither is acquired on a
# schedule and lands nowhere -- silently, because nothing errors. This pins that contract.
_PAINT_SOURCES_WITHOUT_A_BRIDGE = {
    # mfr-mr-hobby: 134 observations, and data/paints/brands/mr-hobby.yaml exists (imported by a
    # different route), but gen_paint_harvest.py has no mr-hobby bridge -- so nothing consumes this
    # source today. Pre-existing; recorded here so it is visible and so no NEW source joins it.
    "mfr-mr-hobby",
    # mfr-gw-webstore-paints: 331 Citadel paints with GW's own codes, pot sizes and launch dates.
    # Bridging it would add only 3 catalog paints today (gen_paint_barcodes.py already reaches 297),
    # so it is deliberately evidence-only for now. The Base/Layer codes it carries are the point.
    "mfr-gw-webstore-paints",
}


def test_every_paint_source_is_consumed_by_a_harvest_bridge() -> None:
    paths = _require_repo_data()
    script = Path(__file__).resolve().parents[1] / "scripts" / "gen_paint_harvest.py"
    if not script.exists():
        pytest.skip("gen_paint_harvest.py not present")
    text = script.read_text(encoding="utf-8")

    paint_sources = {
        source_id
        for source_id, descriptor in load_descriptors(paths.sources).items()
        if descriptor.catalog == "paints"
    }
    assert paint_sources, "expected at least one catalog: paints source"

    unconsumed = {s for s in paint_sources if f'"{s}"' not in text and f"'{s}'" not in text}
    assert unconsumed == _PAINT_SOURCES_WITHOUT_A_BRIDGE, (
        f"paint sources with no harvest bridge changed: {sorted(unconsumed)}. A `catalog: paints` "
        "source is skipped by the product resolver, so without a bridge its observations reach "
        "neither catalog. Add a bridge, or add it to _PAINT_SOURCES_WITHOUT_A_BRIDGE with a reason."
    )
