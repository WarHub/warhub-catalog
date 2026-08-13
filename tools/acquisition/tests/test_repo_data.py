# tools/acquisition/tests/test_repo_data.py
"""Loads the REAL committed data/catalog/* through the real models so a config typo fails CI.

Uses a repo-root fixture rather than a package-relative one: this package can be built and
tested outside the monorepo (sdist), where ../../../../data does not exist -- skip cleanly
in that case instead of failing.
"""
import functools
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest
import yaml

from warhub_acquisition.models.catalog import Overrides, SetRefs
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.resolve import crossover
from warhub_acquisition.resolve.join import Matches
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy, load_labels
from warhub_acquisition.yamlio import read_yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_DATA = REPO_ROOT / "data"
PAINT_HARVEST_BRIDGE = REPO_ROOT / "tools/acquisition/scripts/gen_paint_harvest.py"
SET_CONTENTS_GENERATOR = REPO_ROOT / "tools/acquisition/scripts/gen_set_contents.py"


@functools.lru_cache(maxsize=1)
def _set_contents_generator():
    """The set-contents generator itself, so a guard over its inputs uses ITS rules, not a copy.

    Same importlib.util pattern nine other test modules use to reach a script that is not part of
    the installed package (tests/test_paint_harvest_gate.py is the canonical one; counted
    2026-08-11), each with a DISTINCT sys.modules name so no two of them collide. Safe to import:
    the script guards `main()` with `if __name__ == "__main__":`, and nothing at module scope
    touches the filesystem beyond a sys.path insert.

    Everything is read off THIS module object rather than re-imported from the package, so the
    objects the test asks questions of are byte-for-byte the ones the generator uses -- including
    under a non-editable install, where the script's own sys.path bootstrap could otherwise resolve
    `warhub_acquisition` to a different copy than pytest does.
    """
    if not SET_CONTENTS_GENERATOR.exists():
        pytest.skip("gen_set_contents.py not present (package built/tested outside the monorepo)")
    spec = importlib.util.spec_from_file_location(
        "gen_set_contents_for_repo_data", SET_CONTENTS_GENERATOR
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@functools.lru_cache(maxsize=None)
def _catalogs_for_manufacturer(manufacturer: str) -> tuple:
    """The paint archives gen_set_contents.py would search for this manufacturer -- and no others.

    `Catalog.__init__` is a pure constructor over one YAML read, so caching this is about not
    re-parsing a 200KB archive per assertion rather than about correctness.
    """
    generator = _set_contents_generator()
    brands = generator.MANUFACTURER_BRANDS.get(manufacturer) or []
    return tuple(generator.Catalog(brand, generator.BRANDS_DIR) for brand in brands)


def _codes_across_every_archive() -> dict[str, list[str]]:
    """Every productCode in data/paints/brands/, ignoring which brand it belongs to.

    THIS IS THE WRONG INDEX FOR DECIDING ANYTHING, and it is here only to prove that -- see the two
    divergence tests at the bottom of this file. A repo-wide index cannot answer the question this
    relation asks ("does this code name one paint in the brands THIS manufacturer's sets search?"),
    because the answer depends on the scope. It was, until 2026-08-11, how the setRefs guard
    answered it anyway.
    """
    codes: dict[str, list[str]] = {}
    for path in sorted((REPO_DATA / "paints" / "brands").glob("*.yaml")):
        for record in (read_yaml(path) or {}).get("paints") or []:
            code = str(record.get("productCode") or "")
            if code:
                codes.setdefault(code, []).append(f"{path.stem}/{record['name']}")
    return codes


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


# Anchored on purpose, and the anchoring is the whole point. A storefront's own test entry is
# named for a human scanning an admin list ("Test Product"), so it announces itself at the START of
# the title -- whereas the substring rule this replaces would delete Para Bellum's genuine Conquest
# expansion "Testing the Waters" (sku PBW1073, ean 5213009017671), a real product with a real
# barcode. `^test\b` spares it because "Testing" has no word boundary after "test"; also verified
# to spare "Contest Winner" and "Latest Arrivals". Measured 2026-08-12 over all 22,543 published
# products: these alternations flag exactly the three known store test entries and nothing else.
_STORE_TEST_ARTIFACT = re.compile(
    r"^test\b|\btest (product|item|sku|bundle)\b|^do not (buy|order|purchase)\b|^(dummy|placeholder)\b",
    re.IGNORECASE,
)


def test_no_published_product_looks_like_a_store_test_artifact() -> None:
    """A storefront's own test entry must never publish as a real product.

    Three did until 2026-08-12 -- `steamforged-games/test-product`,
    `steamforged-games/test-paint-f-f-bundle` and `mantic-games/test-product`, all `status:
    current` -- harvested straight off the live stores under two different strategies (`shopify`
    and `woo-store-api`). They are now declared in `SourceDescriptor.excludeKeys`, which drops and
    retracts them at the runner.

    That fix is exact-key, so it cannot catch the NEXT one a store adds. This tripwire is the part
    that generalises: it costs nothing, and it turns "someone eventually notices Test Product in
    the catalog" into a CI failure. On a hit, confirm it really is a test entry and add its key to
    the owning descriptor's `excludeKeys` -- do NOT widen the pattern into a substring match (see
    above), and do not add an allowlist here without a barcode-backed reason.
    """
    if not (REPO_DATA / "catalog" / "products").exists():
        pytest.skip("data/catalog/products/ not created yet")

    offenders = []
    for path in sorted((REPO_DATA / "catalog" / "products").glob("*.yaml")):
        for product in (read_yaml(path) or {}).get("products") or []:
            name = product.get("name") or ""
            if _STORE_TEST_ARTIFACT.search(name):
                offenders.append(f"{product.get('id')} ({name!r}) in {path.name}")

    assert not offenders, (
        "published products look like storefront test entries; declare each one's key under the "
        "owning source descriptor's excludeKeys:\n  " + "\n  ".join(offenders)
    )


def test_repo_matches_and_overrides_parse_when_present() -> None:
    paths = _require_repo_data()
    if paths.matches.exists():
        Matches.model_validate(read_yaml(paths.matches))
    if paths.overrides.exists():
        Overrides.model_validate(read_yaml(paths.overrides))
    # set-refs.yaml is hand-authored and read by a script that deliberately imports no pydantic
    # (gen_set_contents.py runs as `uv run --with pyyaml python ...`), so this is the ONLY place
    # its shape is checked. It also re-checks the split: `setRefs` back in overrides.yaml is now
    # an extra="forbid" ValidationError on the line above rather than a silent deletion.
    if paths.set_refs.exists():
        SetRefs.model_validate(read_yaml(paths.set_refs))


def test_every_paint_source_reaches_the_paint_catalog() -> None:
    """A harvested paint source that no bridge reads is evidence nobody consumes.

    Paint sources are deliberately excluded from the product catalog, so `gen_paint_harvest.py`
    is their ONLY route into anything published: if no bridge calls `paint_rows` for a source id,
    its committed observations reach neither catalog and the harvest was wasted politeness. This
    is a contract, not a report -- a new paint source must land with its bridge (or, if the
    bridge genuinely cannot be written yet, the evidence should not be committed).

    Looks for `paint_rows`, not `read_observations`: on 2026-08-05 the crossover gate moved into
    that reader, so a bridge reading the raw JSONL is a bridge with no set gate (see
    test_every_bridge_reads_through_the_crossover_gate below, which is the half of the contract
    that catches the wrong reader rather than a missing one).

    "Paint source" = most of its observations are paint-kind. The ratio matters: mfr-gw-trade
    (346 paints in a 6,914-row trade workbook) and legacy-catalog are product sources that
    happen to carry some paints, and they reach the paint catalog by a different bridge
    (gen_paint_barcodes.py); mfr-reaper is a paint source whose paint-set pages are not.

    IF mfr-warmachine EVER TRIPS THE RATIO, `catalog: paints` IS THE WRONG FIX. It is a
    manufacturer STOREFRONT that a bridge reads under a documented role exception (see
    gen_paint_harvest.py), and 387 of its 609 rows are models the product catalog must keep.
    Flagging it would pull all 609 out of the product catalog to stop 110 paints duplicating.
    Its margin is not comfortable -- a line moving between Steamforged storefronts already
    shifted 352 products once (PR #127) -- so if the non-paint side falls below the paint side,
    narrow this rule (exempt the source, or gate on the crossover declaration) rather than
    reclassifying a store that sells more than paint.
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
            if f'paint_rows("{source_dir.name}"' not in bridged:
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


# Every DECLARING source's `anyOf` name clause carries the same word list today (measured
# 2026-08-05: five sources, byte-identical 73-byte lines --
# `\b(SET|COLLECTION|FULL RANGE|BRIEFCASE|WOODEN BOX)\b` at mfr-ak-interactive.yaml:67,
# mfr-armypainter.yaml:71, mfr-greenstuffworld.yaml:73, mfr-monument.yaml:50, mfr-reaper.yaml:83).
# A sixth, DIFFERENT one lives at mfr-scale75.yaml:84 (`\bCASE\b`, in `noneOf`) -- divergence is
# not hypothetical here, it is already committed, which is why nothing below assumes one string.
# The predicate is per-source BY DESIGN -- see Crossover in models/descriptor.py, which justifies
# that with measurements where the direction of failure FLIPS between stores -- so divergence
# stays legal. It just has to be DECLARED, because the evaluator is shared while the predicate
# data is not, and an accidental divergence (a typo, a half-finished edit) is otherwise silent.
# The word list's own justification: models/descriptor.py, the `nameMatches` field comment.
CROSSOVER_NAME_CLAUSE_DIVERGES: dict[str, str] = {
    # source_id -> the MEASUREMENT that justifies a different `anyOf` word list for that source.
    # Empty today. Adding a line here is the second half of an intentional edit (the first is the
    # descriptor's own `reason` prose, which T1 already forces to be >= 80 chars); the test below
    # rejects a stale line, so re-converging later forces its deletion.
}
CROSSOVER_SOURCES_WITH_NO_NAME_CLAUSE = {
    # A declaring source may legitimately have no name clause at all. Listed so that SILENTLY
    # DROPPING one -- which a pure equality check cannot see, since it only compares what is
    # there -- fails here instead.
    "mfr-scale75": (
        "the title signal selects ZERO: scale75.com names its boxes 'BOREAL LIGHTS.COOL "
        "COLORS', 'CORE', 'PRIMARY', never 'set'. Its only nameMatches is the `\\bCASE\\b` VETO "
        "in noneOf (mfr-scale75.yaml:84), which is a per-source exclusion and out of scope here."
    ),
}


def _crossover_descriptors() -> dict:
    paths = _require_repo_data()
    descriptors = load_descriptors(paths.sources)
    return {sid: d for sid, d in descriptors.items() if d.crossoverToProducts is not None}


# The category vocabulary actually published today, counted over data/catalog/products/*.yaml on
# 2026-08-13: miniatures 21062, paint 957, paint-set 517, terrain 148, book 98, hobby-auxiliary 13.
# There is no enum on CanonicalProduct.category (it is a bare `str | None`), so a mapping typo --
# "paints", "Paint" -- would publish silently and split a category in the consumer catalogs.
_KNOWN_CATEGORIES = frozenset(
    {"miniatures", "paint", "paint-set", "terrain", "book", "hobby-auxiliary"}
)


def test_repo_mappings_use_only_known_categories() -> None:
    """`category` in a mapping file stamps hints.category straight onto every matching row.

    Added with mfr-warmachine, whose product_type vocabulary answers the FORMAT question ("Paint",
    "Miniatures") rather than the game-system one, so its 222 P3 rows can stop publishing as
    `miniatures`. It is checked here for the same reason gameSystem/faction slugs are: the value
    reaches the published catalog unvalidated otherwise.
    """
    paths = _require_repo_data()
    mappings_dir = REPO_DATA / "catalog" / "mappings"
    if not mappings_dir.exists():
        pytest.skip("data/catalog/mappings/ not created yet")
    assert paths.sources.exists()

    for path in sorted(mappings_dir.glob("*.yaml")):
        data = read_yaml(path) or {}
        for raw, category in (data.get("category") or {}).items():
            assert category in _KNOWN_CATEGORIES, (
                f"{path.name}: category[{raw!r}] -> {category!r} is not one of "
                f"{sorted(_KNOWN_CATEGORIES)}"
            )


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


def _anyof_name_clauses() -> dict[str, str]:
    """source_id -> its SET-WORD `anyOf` name-clause regex, for the sources that declare one.

    `anyOf` ONLY. scale75's `noneOf: \\bCASE\\b` is a per-source veto ("DR FLOWS PAINT CASE" is
    an empty carrying case, not a paint set) and has no business agreeing with anything.

    AND ONLY THE CLAUSES THAT STAMP THE BLOCK'S OWN CATEGORY. A clause carrying its own `category`
    selects a DIFFERENT KIND of thing and has no reason to agree with four other sources' set-word
    lists: mfr-ak-interactive's THINNER|CLEANER|BURNISHING|MICROFILLER|FLUID clause crosses
    auxiliary agents as `hobby-auxiliary`, which is not a boxed set and never was. Keying on the
    override -- rather than on clause position, or on inspecting the pattern text -- keeps the
    roster below about the one thing it was written to protect: five independent copies of the
    set-word list, which drift silently and which nothing else in the suite reads.
    """
    clauses: dict[str, str] = {}
    for source_id, descriptor in _crossover_descriptors().items():
        patterns = [c.nameMatches for c in descriptor.crossoverToProducts.anyOf
                    if c.nameMatches is not None and c.category is None]
        assert len(patterns) <= 1, f"{source_id}: {len(patterns)} anyOf name clauses, expected <=1"
        if patterns:
            clauses[source_id] = patterns[0]
    return clauses


def test_crossover_name_clauses_agree_unless_declared() -> None:
    """T5, Gap 1. The EVALUATOR is shared (resolve/crossover.py); the PREDICATE DATA is not.

    Five descriptors carry the same set-word regex as five independent literals, and T2 above
    only checks they compile -- `\\b(SET)\\b` and `\\bZZZ\\b` both pass it. T3 below is worse than
    silent on a narrowing: a narrowed pattern makes a row stop crossing and stop being refused in
    the same instant, so its join simply sees fewer rows and goes green. Nothing else in the suite
    reads these five strings at all.

    So: they must be EQUAL unless a maintainer says otherwise, in one of two rosters above. Not a
    shared constant -- that would undo the per-source design and hand the next bridge author an
    importable canonical word list, which is the module-level SET_WORDS this replaced. Not a
    semantics-over-corpus check either: measured 2026-08-05, `\\bWOODEN BOX\\b` matches 0 of the
    5,398 committed paint-source names, so deleting that token changes zero rows and a corpus
    check cannot see it.

    Three assertions, because a roster is only honest if it is checked both ways.
    """
    clauses = _anyof_name_clauses()
    assert clauses, "no crossover source declares an anyOf name clause -- did they all vanish?"

    # 1. The sources that are supposed to agree, agree.
    shared = {sid: p for sid, p in clauses.items() if sid not in CROSSOVER_NAME_CLAUSE_DIVERGES}
    distinct = sorted(set(shared.values()))
    assert len(distinct) == 1, (
        "crossover anyOf name clauses have diverged without a declaration:\n"
        + "\n".join(f"  data/catalog/sources/{sid}.yaml: {shared[sid]!r}" for sid in sorted(shared))
        + "\nIf that is intentional, extend the descriptor's `reason` AND add the source to "
          "CROSSOVER_NAME_CLAUSE_DIVERGES with the measurement. If it is a typo, fix the typo."
    )
    canonical = distinct[0]

    # 2. A declaring source with no name clause is a deliberate choice, and a silently DELETED
    #    clause looks exactly like one -- so both directions of that roster are pinned.
    missing = set(clauses) ^ set(_crossover_descriptors())
    assert missing == set(CROSSOVER_SOURCES_WITH_NO_NAME_CLAUSE), (
        f"declaring sources with no anyOf name clause: {sorted(missing)}, "
        f"declared: {sorted(CROSSOVER_SOURCES_WITH_NO_NAME_CLAUSE)} -- a clause was dropped or "
        "added without moving the source in/out of that roster"
    )

    # 3. Same discipline as T4: a stale exemption must fail, so re-converging forces the line out.
    for source_id, why in CROSSOVER_NAME_CLAUSE_DIVERGES.items():
        assert source_id in clauses, f"{source_id} declares no anyOf name clause to diverge with"
        assert clauses[source_id] != canonical, (
            f"{source_id} is listed in CROSSOVER_NAME_CLAUSE_DIVERGES ({why!r}) but its name "
            "clause matches the shared one again -- delete the roster line"
        )


def test_every_bridge_reads_through_the_crossover_gate() -> None:
    """T6, Gap 2. The invariant is stated universally, so the gate must be asked universally.

    Measured 2026-08-05 on the state this replaced: `is_set` was called at exactly 3 of the 9
    bridge sites (ak, gsw, reaper) while bridge_armypainter, bridge_monument and bridge_scale75
    each declared a `crossoverToProducts` block and never consulted it -- 76 crossed rows relying
    on inclusion whitelists that know nothing about sets. For monument and scale75 that held by
    coincidence; for armypainter it did NOT hold: 3 of its 49 crossed set rows (WP8017P, WP8042P,
    WP8012P, carrying real retail EANs the resolver publishes as products) pass its singles shape
    test and were stopped only by a failed catalog join.

    The fix was to move the gate into `paint_rows`, the one reader. This is what keeps it there:
    a bridge that calls `read_observations` directly is a bridge with no set gate, and that is now
    a test failure rather than a coincidence. Two call sites are legitimate -- the `def` and the
    one inside `paint_rows` -- and nothing else.
    """
    if not PAINT_HARVEST_BRIDGE.exists():
        pytest.skip("gen_paint_harvest.py not present (package tested outside the monorepo)")
    source = PAINT_HARVEST_BRIDGE.read_text(encoding="utf-8")

    assert "def paint_rows(" in source, "the gating reader is gone -- every bridge is now ungated"
    sites = [
        (n, line) for n, line in enumerate(source.splitlines(), 1)
        if "read_observations(" in line
    ]
    assert len(sites) == 2, (
        f"read_observations is referenced at {[n for n, _ in sites]}; exactly two are allowed "
        "(its own def, and the single call inside paint_rows). A bridge reading the raw JSONL "
        "skips the crossover gate: read paint_rows' docstring before adding a third."
    )
    assert sites[0][1].startswith("def read_observations("), sites[0]
    # The surviving call must be lexically inside paint_rows, not merely after its def line.
    definitions = [n for n, line in enumerate(source.splitlines(), 1)
                   if line.startswith("def ") or line.startswith("class ")]
    owner = max(n for n in definitions if n <= sites[1][0])
    assert source.splitlines()[owner - 1].startswith("def paint_rows("), (
        f"the one read_observations call (line {sites[1][0]}) sits in "
        f"{source.splitlines()[owner - 1]!r}, not in paint_rows"
    )

    # And every declaring source is actually routed through it, by id.
    for source_id in _crossover_descriptors():
        assert f'paint_rows("{source_id}"' in source, (
            f"{source_id} declares a crossover block but no bridge reads it through paint_rows"
        )


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


# --- retract: the one deletion in an append-only pipeline ------------------------------------

_WHITESPACE = re.compile(r"\s+")


def _normalize(value: str) -> str:
    """Port of `NameNormalizer.Normalize` (tools/WarHub.CatalogStore/NameNormalizer.cs:19-26).

    NFKC, collapse whitespace, trim, strip leading/trailing `'` and `"`, collapse and trim again,
    lowercase. Kept as a literal transcription rather than something tidier: the whole point of
    this test is that Python agrees with C# character-for-character, so any simplification here
    would be a second implementation to keep in sync rather than a mirror of the first.
    """
    text = unicodedata.normalize("NFKC", value or "")
    text = _WHITESPACE.sub(" ", text).strip()
    text = text.strip("'\"")
    text = _WHITESPACE.sub(" ", text).strip()
    return text.lower()


def _paint_identity_key(record: dict) -> str:
    """Port of `PaintRecordAdapter.IdentityKey` (Reconcile/PaintRecordAdapter.cs:10-14).

    NOT the same function as `_normalize` applied to the joined string: the adapter normalizes each
    of the four components SEPARATELY and joins with `|`, while `PaintOverrideAliases.Load` (:34)
    normalizes the authored key as ONE string. The two agree unless a component starts or ends with
    a quote or whitespace -- `'Ardcoat` and mr-hobby's `Dark Gray "Dunkel Grau"` are the real cases
    -- because a per-component pass strips a quote at a component boundary and a whole-string pass
    does not. Such a record cannot be named by a retract or alias key at all, and this test is
    where that would surface: the key would match zero records.
    """
    details = record.get("details") or {}
    return "|".join(
        _normalize(str(part if part is not None else ""))
        for part in (details.get("set"), record.get("name"),
                     record.get("productCode"), details.get("hex"))
    )


def test_every_alias_names_exactly_one_side_of_its_rename() -> None:
    """`aliases:` is the ONLY thing that turns a moved identity into a RENAME instead of a split,
    and like `retract:` it is matched with an ordinal `HashSet`/`Dictionary`
    (PaintOverrideAliases.cs:17-18) -- so a mistyped key produces no error, no warning and no log
    line. It is not even a no-op: the reconciler meets an unknown key, MINTS a second record with
    today's `firstSeen`, and leaves the original standing beside it. Silence looks identical to
    success while the archive quietly grows a duplicate.

    THE INVARIANT IS AN EXCLUSIVE OR, which is what makes it checkable from committed data alone.
    An alias names two identities, and exactly one of them can exist at rest:

      * the NEW key only -- the rename has been applied and the archive holds the corrected
        record. This is the steady state for every alias already merged.
      * the OLD key only -- the alias is authored but the catalog has not been regenerated yet.
        Legitimate mid-change; the next run consumes it.
      * BOTH -- the split this mechanism exists to prevent. Whatever the alias was supposed to
        stitch, it did not, and the archive now carries the record twice.
      * NEITHER -- a key mistyped on both sides, or aimed at a record whose components cannot be
        addressed at all (see `_paint_identity_key`: a component that begins or ends with a quote
        normalizes differently for the adapter than for the alias loader, so Citadel's `'Ardcoat`
        and mr-hobby's `Dark Gray "Dunkel Grau"` are unreachable by any alias or retract key).

    The `retract:` test below is the sibling of this one and they are deliberately different
    shapes: a retraction ends with its target ABSENT, so zero matches is the success case there
    and the near-miss heuristic has to do the work. A rename ends with its target PRESENT under a
    new name, so the count is decidable outright.
    """
    _require_repo_data()
    overrides_path = REPO_DATA / "paints/overrides.yaml"
    if not overrides_path.exists():
        pytest.skip("data/paints/overrides.yaml not present")
    aliases = (read_yaml(overrides_path) or {}).get("aliases") or {}
    if not aliases:
        pytest.skip("no aliases: block declared")

    both, neither = [], []
    for brand_slug, pairs in aliases.items():
        archive_path = REPO_DATA / "paints/brands" / f"{brand_slug}.yaml"
        assert archive_path.exists(), (
            f"aliases: names brand {brand_slug!r}, which has no data/paints/brands file -- "
            f"PaintOverrideAliases.Load is scoped by slug, so the whole block would be dead"
        )
        archive = read_yaml(archive_path) or {}
        identities: dict[str, int] = {}
        for record in archive.get("paints") or []:
            key = _paint_identity_key(record)
            identities[key] = identities.get(key, 0) + 1
        for new_key, old_key in (pairs or {}).items():
            new_n = identities.get(_normalize(str(new_key)), 0)
            old_n = identities.get(_normalize(str(old_key)), 0)
            if new_n and old_n:
                both.append((brand_slug, str(new_key), str(old_key)))
            elif not new_n and not old_n:
                neither.append((brand_slug, str(new_key), str(old_key)))

    assert not both, (
        f"{len(both)} alias(es) whose OLD and NEW identities are BOTH in the archive -- the "
        "rename split instead of stitching, and the record is now duplicated. Read the alias's "
        "own comment: a rename also needs whatever VACATES the old key before reconciliation (a "
        f"`productCode:`/`name:`/`set:` override, or an upstream generator change). {both}"
    )
    assert not neither, (
        f"{len(neither)} alias(es) naming NOTHING on either side -- a mistyped key is not a "
        "no-op, it mints a duplicate on the next run. Check the component order "
        "(`Set|Name|ProductCode|Hex`, which is NOT the `{Name}|{Set}` order the field-override "
        f"blocks use) and see `_paint_identity_key` for the quote trap. {neither}"
    )


#: Top-level keys of overrides.yaml that are not brand blocks.
_OVERRIDE_SECTIONS = {"additions", "aliases", "retract"}


def test_every_name_or_set_override_lands_as_a_rename_and_not_as_a_split() -> None:
    """The mirror of the test above, and it catches the omission that one CANNOT see.

    `test_every_alias_names_exactly_one_side_of_its_rename` starts from the alias and asks whether
    it names a live identity. Start from the OVERRIDE instead and a different failure appears: an
    override that moves a record with no alias at all. Nothing in that first test can notice,
    because there is no alias to iterate.

    It is the same split, reached from the other side. `OverrideApplier.Apply` rewrites the field
    before reconciliation (PaintCatalogApp.cs:256), so the fresh record arrives under a key the
    archive has never seen; step 1 misses, step 2 is disabled for paints (`PaintRecordAdapter.Url`
    returns null), step 3 finds no alias, and step 4 MINTS with today's `firstSeen` while the
    archived record -- never consumed, never retracted -- is emitted alongside it. Two records,
    history on neither, and no other guard fires: the barcode double-hold test needs a shared
    GTIN, and the retract test only reads `retract:`.

    THIS CHECKS THE OUTCOME, NOT THE MECHANISM, and an earlier draft that checked the mechanism is
    why. It demanded an alias whose OLD side carried the override key's spelling -- which is true
    only until the rename lands. An alias must always name the record's CURRENT archived identity,
    so once the correction is in `data/paints/brands/`, the old side carries the CORRECTED name and
    a later layer re-coding the record replaces the alias entirely. That draft passed at the layer
    that introduced it and failed three layers up, on a pairing that was completely correct.

    So the invariant is the same exclusive-or its sibling uses, over the ARCHIVE:

      * the CORRECTED identity only -- the rename landed. The steady state.
      * the BASE identity only -- authored, not yet regenerated. Legitimate mid-change, but ONLY
        with an alias to bridge it; without one the next run is the split described above.
      * BOTH -- the split already happened. The override minted its corrected record and the
        base-spelled one is still standing beside it.
      * NEITHER -- the override names nothing in this brand and rewrites nothing.

    WHY name/set AND NOT productCode/hex. All four components move a record, but only these two
    are routinely authored by hand against a name read off a source document -- they were added in
    PR #131 precisely so a base-sourced record could be corrected, and the requirement was stated
    three times in prose and guarded nowhere. The other two are written by generators.
    """
    _require_repo_data()
    overrides_path = REPO_DATA / "paints/overrides.yaml"
    if not overrides_path.exists():
        pytest.skip("data/paints/overrides.yaml not present")
    document = read_yaml(overrides_path) or {}
    aliases = document.get("aliases") or {}

    split, unpaired, dead = [], [], []
    for brand_slug, entries in document.items():
        if brand_slug in _OVERRIDE_SECTIONS or not isinstance(entries, dict):
            continue
        archive_path = REPO_DATA / "paints/brands" / f"{brand_slug}.yaml"
        if not archive_path.exists():
            continue
        live = {
            (_normalize(str((record.get("details") or {}).get("set") or "")),
             _normalize(str(record.get("name") or "")))
            for record in (read_yaml(archive_path) or {}).get("paints") or []
        }
        # (old set, old name) -> (new set, new name), as the brand's aliases state the move.
        moves = set()
        for new_key, old_key in (aliases.get(brand_slug) or {}).items():
            new_parts = [_normalize(part) for part in str(new_key).split("|")]
            old_parts = [_normalize(part) for part in str(old_key).split("|")]
            if len(new_parts) == 4 and len(old_parts) == 4:
                moves.add((old_parts[0], old_parts[1], new_parts[0], new_parts[1]))

        for key, fields in entries.items():
            if not isinstance(fields, dict) or not ({"name", "set"} & set(fields)):
                continue
            # The override key is `{Name}|{Set}` and stays the spelling the BASE emits.
            base_name, _, base_set = str(key).partition("|")
            base = (_normalize(base_set), _normalize(base_name))
            corrected = (
                _normalize(str(fields.get("set", base_set))),
                _normalize(str(fields.get("name", base_name))),
            )
            where = (brand_slug, str(key), "|".join(corrected))
            if base in live and corrected in live:
                split.append(where)
            elif base in live and base + corrected not in moves:
                unpaired.append(where)
            elif base not in live and corrected not in live:
                dead.append(where)

    assert not split, (
        f"{len(split)} `name:`/`set:` override(s) whose BASE and CORRECTED identities are BOTH in "
        "the archive -- the rename already split, and the record is now published twice with "
        f"history on neither. {split}"
    )
    assert not unpaired, (
        f"{len(unpaired)} `name:`/`set:` override(s) that will MINT rather than rename on the next "
        "run: the archive still holds the base spelling and no alias bridges the move. Add "
        "`aliases: <brand>:` mapping the NEW identity to the OLD one, keyed "
        "`Set|Name|ProductCode|Hex` (not the `{Name}|{Set}` order used here), with any leading "
        f"apostrophe stripped from both sides. {unpaired}"
    )
    assert not dead, (
        f"{len(dead)} `name:`/`set:` override(s) naming no record in their brand, under either "
        "spelling -- a field override is matched with an ordinal dictionary, so this rewrites "
        f"nothing and reports nothing. {dead}"
    )


def test_every_retract_key_names_exactly_one_committed_paint() -> None:
    """`retract:` is the ONLY code path in the pipeline that DELETES an archived record --
    `CatalogReconciler` subtracts exactly this set (:52-55 input side, :104 output side) and
    everything else is append-only. It is matched with an ordinal `HashSet<string>`
    (PaintOverrideAliases.cs:18), so a key that matches nothing produces no error, no warning and
    no log line: the record simply stays, and the run looks exactly like a successful retraction.

    That silent no-op is the failure mode this test exists for. A key must name exactly one
    committed record under the tool's own normalisation -- zero means the retraction misses,
    two would mean the identity key is not identifying.

    Deliberately checks against the ARCHIVE, not against the harvest: a retraction is a statement
    about what is published, and `data/paints/brands/*.yaml` is what is published.

    TWO LEGITIMATE STATES, and the assertion has to survive both. Before the paint tool runs, a
    key names exactly one record. After it runs it names ZERO -- the record is gone, which is the
    retraction working, and the block stays as the standing input-side guard. An earlier draft
    asserted `matches == 1` unconditionally and would have turned red the moment it succeeded.

    THE ALL-OR-NOTHING RULE THAT STOOD HERE WAS WRONG, and 2026-08-06 is when it broke: it read
    the whole file as one batch, so the first change to append a retraction beside an
    already-applied one failed with 20 keys "suspect" that were simply done. `retract:` is a
    standing declaration, not a queue -- entries accumulate and land in different runs, so a mixed
    resolved/missing count is the NORMAL steady state of any file with more than one batch in it.

    WHAT DISCRIMINATES INSTEAD, and it is sharper than counting. A key that names zero records is
    either applied or mistyped, and those two look different in the archive: an APPLIED key's
    record is gone entirely, while a MISTYPED key's record is still published under the (set,
    name) the author was aiming at -- the typo is in the productCode or the hex or a separator,
    which is precisely where these keys go wrong (`s Set - Colours`, the trailing empty-hex pipe).
    So a zero-match key whose (set, name) pair is STILL in the archive is the silent no-op; a
    zero-match key with no such record left is a retraction that worked. Measured on the committed
    file: 20 boxed sets + reaper's, all applied, 0 near-misses; the 3 green-stuff-world singles
    added today all resolve exactly.

    A SURVIVING (SET, NAME) IS NOT ENOUGH ON ITS OWN, and 2026-08-07 is when THAT broke. Retracting
    AK's category duplicates flagged `Naval|Wooden Deck|AK730|#AD9557` as mistyped because
    `Naval|Wooden Deck|AK5032|#D4B78B` survives it -- but those are two different paints that
    happen to share a name inside one set, and the retraction of the first was exactly right (it
    duplicated `General|Wooden Deck|AK730|#AD9557`, same code, same colour). The rule now asks how
    FAR the survivor is: a typo lands NEXT to its target, differing in the productCode or the hex
    but not both, because the author transcribed one record and got one field wrong. A survivor
    differing in BOTH is a different pot, and reading it as a near-miss blocks a correct deletion
    -- the worse of the two errors, since the false positive stops good data landing while the
    false negative merely fails to catch a key that is wrong in two places at once.

    A SURVIVOR THAT MERELY NORMALIZES ALIKE IS NOT ONE EITHER, and 2026-08-13 is when that broke:
    retracting P3's duplicate `Jack Bone` flagged the surviving `'Jack Bone` as a hex typo. Same
    conclusion as the Wooden Deck case, reached through the name rather than the code -- see the
    filter below.

    Residual blind spots, stated rather than papered over: a key whose SET or NAME component is
    itself mistyped names nothing and has no near-miss either, so it reads as applied; and by the
    same token neither does a key wrong in both code and hex. Nothing in the file can distinguish
    either from a real deletion -- only the record's absence proves it -- which is why the retract
    block's own comment insists the keys be GENERATED from the records rather than transcribed.
    """
    _require_repo_data()
    overrides_path = REPO_DATA / "paints/overrides.yaml"
    if not overrides_path.exists():
        pytest.skip("data/paints/overrides.yaml not present")
    retract = (read_yaml(overrides_path) or {}).get("retract") or {}
    if not retract:
        pytest.skip("no retract: block declared")

    ambiguous = []
    mistyped = []
    for brand_slug, keys in retract.items():
        archive_path = REPO_DATA / "paints/brands" / f"{brand_slug}.yaml"
        assert archive_path.exists(), (
            f"retract: names brand {brand_slug!r}, which has no data/paints/brands file -- "
            f"PaintOverrideAliases.Load is scoped by slug, so the whole list would be dead"
        )
        archive = read_yaml(archive_path) or {}
        identities: dict[str, int] = {}
        # (identity key, RAW name). The raw name is carried because the bucket is NORMALIZED and
        # therefore over-groups -- see the near-miss filter below.
        by_set_and_name: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for record in archive.get("paints") or []:
            key = _paint_identity_key(record)
            identities[key] = identities.get(key, 0) + 1
            details = record.get("details") or {}
            by_set_and_name.setdefault(
                (_normalize(str(details.get("set") or "")), _normalize(str(record["name"]))), []
            ).append((key, str(record["name"])))
        for authored in keys:
            # PaintOverrideAliases.Load normalizes the authored key as ONE string (:34).
            matches = identities.get(_normalize(str(authored)), 0)
            if matches > 1:
                ambiguous.append((brand_slug, authored, matches))
                continue
            if matches == 1:
                continue  # names its record; the retraction has not run yet
            # Zero matches: applied, or aimed at a record that is still published.
            parts = str(authored).split("|")
            survivors = by_set_and_name.get(
                (_normalize(parts[0]), _normalize(parts[1])), []) if len(parts) == 4 else []
            # NEAR-MISS ONLY. Survivors share the set and name by construction, so they can differ
            # from the authored key in the productCode, the hex, or both -- and only "one of the
            # two" reads as a transcription slip. Both differing means a genuinely different pot
            # sharing a name inside one set (AK's Naval Wooden Deck, AK730 vs AK5032), which the
            # retraction of its twin is supposed to leave standing.
            authored_parts = [_normalize(p) for p in parts]
            near = [
                survivor for survivor, raw_name in survivors
                if sum(1 for a, b in zip(authored_parts, survivor.split("|")) if a != b) == 1
                # AND the survivor is the record the author was LOOKING AT. The bucket is keyed
                # by the normalized name, and `_normalize` strips a leading or trailing quote
                # (NameNormalizer.Normalize:19-26), so two records whose names differ ONLY by
                # that quote land in one bucket -- P3's `'Jack Bone` (an elision of *warjack*)
                # and `Jack Bone`, both inherited from upstream P3.md. Retracting either twin
                # then reads as a hex typo against the other, because the name difference has
                # already been normalized away and the hex is all that is left to differ.
                #
                # This is the 2026-08-07 lesson in a third shape, and it resolves the same way:
                # a false positive blocks a correct deletion, which is the worse error. A real
                # typo is transcribed FROM the record it names, so the raw names match exactly;
                # a name that differs by a character only normalization can erase is a different
                # record. (Note the survivor here cannot be named by a retract key at all --
                # `_paint_identity_key` normalizes per component and `PaintOverrideAliases.Load`
                # normalizes the whole string, so an internal `|'Jack Bone|` survives one pass
                # and not the other. That asymmetry is documented on `_paint_identity_key`; it
                # is why the twin is safe from the very key that flags it.)
                and raw_name == parts[1]
            ]
            if near:
                mistyped.append((brand_slug, authored, near))

    assert not ambiguous, (
        "retract keys naming MORE than one committed record -- the identity key is not "
        f"identifying, and the retraction would delete several paints: {ambiguous}"
    )
    assert not mistyped, (
        f"{len(mistyped)} retract key(s) name NOTHING while the record they aim at is still "
        "published -- the productCode/hex/separator half of the key is wrong, and a mistyped key "
        "is a silent no-op that leaves the record in the catalog looking retired. "
        f"Authored key vs the identity keys still on file: {mistyped}"
    )


# One legitimate double-hold, pinned by hand because nothing can clear it: two REAL paints share
# this GTIN. Vallejo colour-corrected `Xpress Color Intense|Viking Grey|72.483` and kept the code
# and the barcode, so the archive carries both formulations (#374855 and #45515D) and
# PaintBuilder.cs:12-16 puts the hex in its natural key precisely so the second is published
# rather than silently dropped. Listed as (brand slug, barcode) so a NEW duplicate in vallejo is
# still caught.
_KNOWN_SHARED_BARCODES = {("vallejo", "8429551724838")}


def test_no_barcode_is_held_by_two_records_in_one_brand() -> None:
    """A barcode identifies ONE product. Two records in a brand holding the same GTIN is the
    catalogue asserting that one physical pot is two different paints, and every consumer that
    resolves a scan to a paint then has to pick one.

    THIS TEST EXISTS BECAUSE NOTHING ELSE CAN SEE IT, which is the only reason to spend an
    archive-wide sweep on something a guard should catch. `report --ean-guard` keys its holders on
    `(brand, role)` (report.py:229), not on the record, so a barcode sitting on two records of the
    same brand reads as perfectly held and the guard exits 0. It is blinder still on an
    overrides-only commit: `_head_yaml_files` intersects `git ls-tree` with
    `git diff --name-only HEAD` (report.py:180-195), enumerates zero brand files, and tracks
    nothing at all. Its green is vacuous, not reassuring.

    NOR does the harvest suite cover it any more. `test_paint_harvest_gsw_sets.py::
    test_every_displaced_barcode_is_retracted_or_listed` names the three green-stuff-world
    duplicates in a `deferred` dict and promises the list "can only shrink"; measured 2026-08-06 by
    emptying that dict, it reports 0 unanswered either way, because its ratchet-skip (:347) now
    treats the three `Acrylic Inks` records as prior mints once 240dc3d landed them in the archive.
    It can only ever see this on a pre-run tree. The invariant belongs against the ARCHIVE, which
    is what is published and what survives the tool run -- hence here, beside the retract test.

    THE ALLOWANCE IS DERIVED, NOT LISTED, and that is the whole design. A duplicate is tolerated
    only while one of its holders is already named by a `retract:` key for that brand -- i.e. while
    the repo has declared, in the one mechanism that deletes archived records, that this holder is
    going away. That ties the excuse to the fix: the moment the paint tool runs, the record is gone
    and the duplicate with it; if someone deletes the retract keys while the records remain, this
    turns red; and a duplicate introduced with no retraction behind it is red immediately. A
    hardcoded allow-list would instead have rotted into a permanent excuse, and asserting zero
    unconditionally would have been red on the committed tree for a defect that IS already answered.

    Membership is the faithful port of `CatalogReconciler` (:52-55, :104): it tests
    `retracted.Contains(adapter.IdentityKey(rec))`, so the RECORD is keyed per-component
    (`PaintRecordAdapter.IdentityKey`) while the AUTHORED key is normalized as one string
    (`PaintOverrideAliases.Load:34`). Reusing both helpers here rather than one of them.

    Brand-scoped deliberately. One barcode reaching two brands is a different claim -- rebrands and
    OEM relabels do share GTINs across catalogue brands -- and folding it in here would bury the
    within-brand case, which is unambiguously a defect, under judgement calls.

    Measured on the committed archive 2026-08-06: 4 duplicated barcodes catalogue-wide. Three are
    green-stuff-world `Fluor Metallic` records holding an `Acrylic Inks` GTIN via a matching bug
    fixed in 240dc3d, all three named by retract keys; the fourth is the vallejo pair pinned above.
    """
    _require_repo_data()
    brands_dir = REPO_DATA / "paints/brands"
    if not brands_dir.exists():
        pytest.skip("data/paints/brands not present")
    overrides_path = REPO_DATA / "paints/overrides.yaml"
    retract = {}
    if overrides_path.exists():
        retract = (read_yaml(overrides_path) or {}).get("retract") or {}

    offenders = []
    for archive_path in sorted(brands_dir.glob("*.yaml")):
        brand_slug = archive_path.stem
        retracted = {_normalize(str(k)) for k in (retract.get(brand_slug) or [])}
        holders: dict[str, list[tuple[str, str, bool]]] = {}
        for position, record in enumerate((read_yaml(archive_path) or {}).get("paints") or []):
            identity = _paint_identity_key(record)
            pending = identity in retracted
            barcodes = [(str(record["ean"]), "primary")] if record.get("ean") else []
            barcodes += [(str(e), "additional") for e in record.get("additionalEans") or []]
            # Per RECORD, not per listing: `OverrideApplier.cs:83` and `PaintRecordAdapter.
            # Merge:31-33` both union a record's old primary back into its own `additionalEans`,
            # so one record legitimately names a barcode twice. That is a record talking about
            # itself; this test is about TWO records claiming one product. Deduping on the
            # record's position keeps identity-colliding records (which the retract test hunts
            # separately) visible as the two holders they are.
            seen_here = set()
            for barcode, role in barcodes:
                if barcode in seen_here:
                    continue
                seen_here.add(barcode)
                holders.setdefault(barcode, []).append((f"[{position}] {identity}", role, pending))
        for barcode, held in sorted(holders.items()):
            if len(held) < 2:
                continue
            if (brand_slug, barcode) in _KNOWN_SHARED_BARCODES:
                continue
            # Tolerated only while the retractions leave EXACTLY ONE holder. Counting "some
            # leaving, some staying" is not enough: three holders with one retract key satisfies
            # that and still publishes a barcode on two records after the tool runs -- the very
            # defect this test exists for. Demonstrated by mutation, so it is a real hole rather
            # than a hypothetical one.
            leaving = sum(1 for *_, pending in held if pending)
            remaining = len(held) - leaving
            if remaining == 0:
                offenders.append((brand_slug, barcode, "EVERY holder retracted -- the barcode "
                                                       "would be left holding nothing", held))
            elif remaining > 1:
                offenders.append((
                    brand_slug, barcode,
                    f"{remaining} holders would REMAIN after the declared retractions "
                    f"({leaving} of {len(held)} named) -- a barcode identifies one product",
                    held,
                ))

    assert not offenders, (
        f"{len(offenders)} barcode(s) held by more than one record within a brand, with nothing "
        "declared to clear it. A GTIN identifies one product, so this publishes a scan that "
        "resolves to two different paints; `report --ean-guard` keys holders on (brand, role) and "
        "cannot see it. Either retract the wrong holder (the only mechanism that deletes an "
        "archived record) or, if both records are real paints sharing a code, pin the pair in "
        f"_KNOWN_SHARED_BARCODES with a citation: {offenders}"
    )


# YAML 1.2 core schema, verbatim from the spec's resolution table. NOT PyYAML's 1.1 resolver,
# which is the whole point of the test below.
_CORE_NULL = re.compile(r"^(~|null|Null|NULL|)$")
_CORE_BOOL = re.compile(r"^(true|True|TRUE|false|False|FALSE)$")
_CORE_INT = re.compile(r"^([-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$")
_CORE_FLOAT = re.compile(
    r"^([-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?"
    r"|[-+]?\.(inf|Inf|INF)|\.(nan|NaN|NAN))$"
)


def _reads_as_non_string_under_yaml_1_2(text: str) -> bool:
    return bool(
        _CORE_NULL.match(text)
        or _CORE_BOOL.match(text)
        or _CORE_INT.match(text)
        or _CORE_FLOAT.match(text)
    )


def test_no_committed_yaml_string_changes_type_between_readers() -> None:
    """A committed scalar must mean the same thing to every YAML reader, not just to ours.

    THE INVARIANT, and why it is decidable without knowing any schema: if PyYAML resolves a PLAIN
    (unquoted) scalar to a STRING, the writer meant a string -- nothing else could have produced
    that tag. So a YAML 1.2 core-schema reader disagreeing and calling it an int or a float is
    unambiguously a serialization bug, with no judgement call about whether the field is "supposed
    to be" numeric. The reverse case (a string field emitted as a genuine number) is NOT decidable
    from the text and is not tested here; it is closed on the write side instead, by
    yamlio._represent_str and QuotingEventEmitter force-quoting anything number-shaped.

    THIS IS THE TEST THAT SHOULD HAVE EXISTED FIRST. The same defect landed twice, in two
    languages, and neither writer's own tests could see it because both only ever read their own
    output back with the reader that produced it:

      - data/paints/equivalences.yaml built a local YamlDotNet serializer with no quoting rule at
        all. All 34,172 productCode scalars were plain; 13,112 ambiguous, 1,093 changing VALUE
        under PyYAML ('040' -> 32 as octal). 145 more were invisible to PyYAML entirely -- a
        leading-zero code containing an 8 or 9 is not valid octal, so PyYAML alone reads it as a
        string while a 1.2 reader takes it as an int. Exactly the case this test is shaped around.
      - data/paints/harvest/reaper.yaml called yaml.safe_dump directly instead of
        yamlio.dump_yaml. 115 of 487 `sku` scalars bare and 372 quoted -- one field contradicting
        itself, decided by nothing but which digits happened to appear.

    Both were silent: PyYAML round-trips its own output, so every in-repo consumer agreed with
    every other one, and the catalog was only wrong for somebody else.

    Scans every committed data/**/*.yaml -- generated and hand-edited alike, since a hand-edited
    file can carry the same mistake and overrides.yaml is full of zero-padded codes.
    """
    _require_repo_data()
    offenders: list[str] = []
    for path in sorted(REPO_DATA.rglob("*.yaml")):
        # CSafeLoader for speed (148 files, one of them 9 MB) -- it reports scalar style and
        # resolved tag just as the pure-Python loader does; see yamlio for the 7.5x measurement.
        node = yaml.compose(path.read_text(encoding="utf-8"), Loader=yaml.CSafeLoader)
        stack = [node] if node is not None else []
        while stack:
            current = stack.pop()
            if isinstance(current, yaml.ScalarNode):
                # style "" / None is plain; anything else was deliberately quoted or blocked.
                if (not current.style
                        and current.tag == "tag:yaml.org,2002:str"
                        and _reads_as_non_string_under_yaml_1_2(current.value)):
                    offenders.append(
                        f"{path.relative_to(REPO_DATA)}:{current.start_mark.line + 1} "
                        f"{current.value!r}"
                    )
            elif isinstance(current, yaml.SequenceNode):
                stack.extend(current.value)
            elif isinstance(current, yaml.MappingNode):
                for key, value in current.value:
                    stack.append(key)
                    stack.append(value)

    assert not offenders, (
        f"{len(offenders)} committed scalar(s) that PyYAML reads as a STRING but a YAML 1.2 "
        "core-schema reader reads as a number/bool/null. The writer meant a string, so the file "
        "is lying to every consumer that is not PyYAML -- and the join these values feed "
        "(productCode/sku/ean/ref) breaks silently rather than loudly. Fix the WRITER: Python "
        "generators must use warhub_acquisition.yamlio.dump_yaml, never yaml.safe_dump; C# "
        "writers must use CatalogSerializer.CreateSerializer(), never a local SerializerBuilder. "
        f"First 20: {offenders[:20]}"
    )


def test_every_set_ref_correction_is_live_and_resolvable() -> None:
    """A declared typo repair must still be repairing a typo, and must still land somewhere.

    `data/catalog/set-refs.yaml` (models/catalog.py::SetRefs) is the one place a human may overrule
    a code a manufacturer printed, so it is also the one place a stale entry does real damage:
    silently rewriting a ref the source has since FIXED, or pointing at a paint that has since been
    retracted. Neither shows up anywhere else -- gen_set_contents.py applies a correction with
    `dict.get`, so an entry that matches nothing is a no-op and an entry pointing nowhere just
    re-refuses. Both look like success.

    Two halves, because the entry makes two claims:

      1. THE MISTYPED REF IS STILL PRINTED. If it is gone from that product's `contentSkus`, the
         manufacturer fixed its own prose (or the description changed shape) and the entry must be
         DELETED, not left behind where it can catch a future code that happens to collide.
      2. THE CORRECTED CODE STILL NAMES EXACTLY ONE PAINT, in the brands this manufacturer's sets
         actually search. A correction resolving to zero paints is a refusal wearing a repair's
         clothes; one resolving to several would pick by archive order, which is the
         tie-break-by-luck this relation refuses everywhere else.

    RESOLVED THE WAY THE GENERATOR RESOLVES, which is the whole point of importing
    `paints_for_ref` and `MANUFACTURER_BRANDS` rather than restating them. This test used to glob
    every file in data/paints/brands/ and pass on a repo-wide unique hit, and that disagreed with
    gen_set_contents.py in both directions (measured 2026-08-11, and both are pinned by the two
    tests below so a future loosening fails rather than drifts):

      - It passed corrections the generator REFUSES. A code is only looked up in
        MANUFACTURER_BRANDS[manufacturer] -- ak-interactive searches only `ak-interactive` -- so
        correcting an AK ref to `RC078`, which exists exactly once repo-wide but in ak-real-color,
        was reported "live and resolvable" while the generator writes `unresolved`. 4,925 of the
        6,049 repo-wide-unique codes are outside ak-interactive's scope like that (warlord-games
        4,701, reaper 5,555, of 6,192 distinct codes across the 21 archives).
      - It failed corrections the generator RESOLVES. The generator falls back to
        `lstrip("0")`, so a reaper correction written in reaper's own printed vocabulary
        (`09412`) resolved there and produced hits=[] here. 345 of reaper's 403 distinct refs are
        zero-padded and its archive stores 0 of 494 codes with a leading zero, so that is the
        normal shape of a reaper code, not a corner.

    Live today: ak-interactive/AK11781 prints `AK111424 Grey Green`, which is AK11424 with one
    extra digit -- the only 6-digit code in a box whose other nine are 5-digit AK11xxx. Under the
    tightened rule it still resolves, to exactly one paint within `['ak-interactive']`:
    `Grey Green|Figures (3rd Gen)` (verified 2026-08-11; AK111424 itself names no paint anywhere).
    """
    _require_repo_data()
    generator = _set_contents_generator()
    set_refs_path = REPO_DATA / "catalog" / "set-refs.yaml"
    if not set_refs_path.exists():
        pytest.skip("data/catalog/set-refs.yaml not present")
    corrections = (read_yaml(set_refs_path) or {}).get("setRefs") or {}
    if not corrections:
        pytest.skip("no setRefs corrections declared")

    # Keyed by the products FILE STEM, because that is what gen_set_contents.py keys
    # MANUFACTURER_BRANDS by. Splitting the product id on "/" would agree today and would be a
    # second spelling of the same fact -- the thing this test was just fixed for.
    products: dict[str, tuple[str, dict]] = {}
    for path in sorted((REPO_DATA / "catalog" / "products").glob("*.yaml")):
        for product in (read_yaml(path) or {}).get("products") or []:
            products[str(product.get("id"))] = (path.stem, product)

    stale, unresolvable = [], []
    for product_id, mapping in corrections.items():
        entry = products.get(product_id)
        assert entry is not None, (
            f"setRefs names {product_id!r}, which is not a committed product -- a correction "
            "scoped to a product that no longer exists can never fire"
        )
        manufacturer, product = entry
        assert generator.MANUFACTURER_BRANDS.get(manufacturer), (
            f"setRefs corrects {product_id!r}, whose manufacturer {manufacturer!r} has no "
            "MANUFACTURER_BRANDS entry in gen_set_contents.py -- that manufacturer is refused "
            "wholesale and gets no set-contents file, so the correction can never fire"
        )
        catalogs = list(_catalogs_for_manufacturer(manufacturer))
        stated = [str(code) for code in (product.get("contentSkus") or [])]
        for wrong, right in mapping.items():
            if str(wrong) not in stated:
                stale.append((product_id, wrong, right))
            hits = generator.paints_for_ref(catalogs, str(right))
            if len(hits) != 1:
                unresolvable.append((
                    product_id, wrong, right,
                    sorted(f"{c.slug}/{c.key_of(p)}" for c, p in hits),
                    [c.slug for c in catalogs],
                ))

    assert not stale, (
        "setRefs entries whose mistyped ref is NO LONGER in the product's contentSkus -- the "
        "source fixed its own prose, so the correction is dead weight that can only misfire on a "
        f"future code. Delete them: {stale}"
    )
    assert not unresolvable, (
        "setRefs entries whose corrected code does not name exactly one paint IN THE BRANDS THAT "
        "MANUFACTURER'S SETS SEARCH (last field). Zero means the repair refuses just as loudly as "
        "the typo did -- and note a code that exists in some OTHER brand's archive still counts as "
        "zero here, because gen_set_contents.py never looks there. Several means it would be "
        f"decided by archive order: {unresolvable}"
    )


def test_a_setref_correction_may_not_reach_into_an_archive_the_generator_never_searches() -> None:
    """The FALSE PASS the guard above allowed until 2026-08-11, pinned so it cannot come back.

    gen_set_contents.py resolves a ref only against `MANUFACTURER_BRANDS[manufacturer]`. A guard
    that instead asks "is this code unique across all 21 brand archives?" answers a strictly easier
    question, and the gap is not marginal: measured 2026-08-11, 6,192 distinct product codes are
    committed, 6,049 of them unique repo-wide, and of those 4,925 name no paint at all inside
    ak-interactive's search space (warlord-games 4,701, reaper 5,555).

    `RC078` is the concrete shape -- exactly one paint repo-wide (ak-real-color, "Apc Interior
    Green Fs 24533") and zero inside `['ak-interactive']`. A correction pointing an AK ref there
    would have been called "live and resolvable" while the generator wrote `unresolved`, i.e. the
    guard's docstring promised precisely what it did not check.

    Asserted over the whole divergent population rather than on RC078 by name, so retracting one
    paint cannot turn this into a confusing failure -- but with a floor, so a scope change that
    quietly made the two indexes agree cannot turn it vacuous either.
    """
    _require_repo_data()
    generator = _set_contents_generator()
    repo_wide = _codes_across_every_archive()
    unique_repo_wide = [code for code, owners in repo_wide.items() if len(owners) == 1]
    assert len(unique_repo_wide) > 5000, (
        f"only {len(unique_repo_wide)} repo-wide-unique codes (6,049 measured 2026-08-11) -- the "
        "population this test reasons about has changed shape; re-derive before relaxing anything"
    )

    for manufacturer in sorted(generator.MANUFACTURER_BRANDS):
        catalogs = list(_catalogs_for_manufacturer(manufacturer))
        in_scope = {
            str(paint.get("productCode") or "") for catalog in catalogs for paint in catalog.paints
        }
        # Unique repo-wide -- so the OLD guard passed it -- but carried by no paint in any archive
        # this manufacturer searches. Every one must be refused, verbatim and after the zero-strip.
        outsiders = [code for code in unique_repo_wide
                     if code not in in_scope and (code.lstrip("0") or code) not in in_scope]
        assert len(outsiders) > 1000, (
            f"{manufacturer}: only {len(outsiders)} repo-wide-unique codes fall outside its "
            "search space (ak-interactive 4,925 / warlord-games 4,701 / reaper 5,555 measured "
            "2026-08-11) -- this test is close to vacuous, re-measure it"
        )
        for code in outsiders:
            assert generator.paints_for_ref(catalogs, code) == [], (
                f"{manufacturer}: {code!r} names no paint in "
                f"{generator.MANUFACTURER_BRANDS[manufacturer]} yet paints_for_ref returned a "
                f"hit -- the lookup has been widened past the brands the generator searches, so a "
                "setRefs correction could now be declared 'resolvable' against an archive this "
                "manufacturer's sets never draw from"
            )


def test_a_setref_correction_in_a_sources_zero_padded_vocabulary_still_resolves() -> None:
    """The FALSE FAIL of the same guard, and the reason the fix could not just be "scope it".

    A maintainer writing a reaper correction writes it the way reapermini.com prints the code --
    zero-padded, `09412` -- because that is the string sitting in `contentSkus` next to the typo.
    The generator resolves it (verbatim, then `lstrip("0")`); a guard without the strip returns
    zero hits and calls the correction unresolvable.

    Measured 2026-08-11 over the committed files: reaper's 29 sets state 802 refs, 403 distinct,
    ALL 5 characters, and 345 of the 403 are zero-padded -- while the archive stores 0 of its 494
    codes with a leading zero. So a padded correction is the ORDINARY case for this manufacturer,
    and the 345 below are each a correction that the pre-2026-08-11 guard would have rejected.
    """
    _require_repo_data()
    generator = _set_contents_generator()
    if "reaper" not in generator.MANUFACTURER_BRANDS:
        pytest.skip("reaper is no longer a set-contents manufacturer")
    catalogs = list(_catalogs_for_manufacturer("reaper"))
    repo_wide = _codes_across_every_archive()

    refs = sorted({
        str(ref)
        for product in (read_yaml(REPO_DATA / "catalog" / "products" / "reaper.yaml") or {})
        .get("products") or []
        for ref in (product.get("contentSkus") or [])
    })
    padded = [ref for ref in refs if ref.startswith("0")]
    # Padded, resolving to exactly one paint through the generator's rule, and invisible to a
    # verbatim index -- the exact combination the old guard mishandled.
    strip_only = [ref for ref in padded
                  if len(generator.paints_for_ref(catalogs, ref)) == 1 and ref not in repo_wide]
    assert len(strip_only) > 300, (
        f"{len(strip_only)} zero-padded reaper refs resolve only via the leading-zero strip (345 "
        f"of {len(refs)} distinct refs measured 2026-08-11, {len(padded)} padded today) -- if this "
        "collapsed, either the archive started storing padded codes or the strip was dropped, and "
        "in the second case every reaper correction a maintainer writes in the source's own "
        "vocabulary now silently fails"
    )
