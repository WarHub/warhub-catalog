# tools/acquisition/tests/test_repo_data.py
"""Loads the REAL committed data/catalog/* through the real models so a config typo fails CI.

Uses a repo-root fixture rather than a package-relative one: this package can be built and
tested outside the monorepo (sdist), where ../../../../data does not exist -- skip cleanly
in that case instead of failing.
"""
import json
import re
import unicodedata
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
    """source_id -> its `anyOf` name-clause regex, for the sources that declare one.

    `anyOf` ONLY. scale75's `noneOf: \\bCASE\\b` is a per-source veto ("DR FLOWS PAINT CASE" is
    an empty carrying case, not a paint set) and has no business agreeing with anything.
    """
    clauses: dict[str, str] = {}
    for source_id, descriptor in _crossover_descriptors().items():
        patterns = [c.nameMatches for c in descriptor.crossoverToProducts.anyOf
                    if c.nameMatches is not None]
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

    TWO LEGITIMATE STATES, and the assertion has to survive both. Before the paint tool runs,
    every key names exactly one record. After it runs, every key names ZERO -- the records are
    gone, which is the retraction working, and the block stays as the standing input-side guard.
    An earlier draft asserted `matches == 1` unconditionally and would have turned red the moment
    it succeeded.

    So: no key may EVER name more than one record (that means the identity key is not
    identifying), and the resolved count must be all-or-nothing. A MIXED state is the typo
    signature -- 19 keys naming their record while the 20th names nothing is exactly the silent
    no-op this exists to catch, and it is indistinguishable from success if you only count zeros.
    """
    _require_repo_data()
    overrides_path = REPO_DATA / "paints/overrides.yaml"
    if not overrides_path.exists():
        pytest.skip("data/paints/overrides.yaml not present")
    retract = (read_yaml(overrides_path) or {}).get("retract") or {}
    if not retract:
        pytest.skip("no retract: block declared")

    ambiguous = []
    resolved = []
    missing = []
    for brand_slug, keys in retract.items():
        archive_path = REPO_DATA / "paints/brands" / f"{brand_slug}.yaml"
        assert archive_path.exists(), (
            f"retract: names brand {brand_slug!r}, which has no data/paints/brands file -- "
            f"PaintOverrideAliases.Load is scoped by slug, so the whole list would be dead"
        )
        archive = read_yaml(archive_path) or {}
        identities: dict[str, int] = {}
        for record in archive.get("paints") or []:
            key = _paint_identity_key(record)
            identities[key] = identities.get(key, 0) + 1
        for authored in keys:
            # PaintOverrideAliases.Load normalizes the authored key as ONE string (:34).
            matches = identities.get(_normalize(str(authored)), 0)
            (ambiguous if matches > 1 else resolved if matches == 1 else missing).append(
                (brand_slug, authored, matches)
            )

    assert not ambiguous, (
        "retract keys naming MORE than one committed record -- the identity key is not "
        f"identifying, and the retraction would delete several paints: {ambiguous}"
    )
    assert not (resolved and missing), (
        f"{len(resolved)} retract key(s) name their record while {len(missing)} name nothing. "
        "All-or-nothing is the only honest state: before the paint tool every key resolves, "
        "after it none does. A mix means the ones naming nothing are MISTYPED, and a mistyped "
        f"key is a silent no-op that leaves the record published. Suspect: {missing}"
    )
