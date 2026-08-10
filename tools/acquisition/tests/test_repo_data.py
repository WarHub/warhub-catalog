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
import yaml

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
        by_set_and_name: dict[tuple[str, str], list[str]] = {}
        for record in archive.get("paints") or []:
            key = _paint_identity_key(record)
            identities[key] = identities.get(key, 0) + 1
            details = record.get("details") or {}
            by_set_and_name.setdefault(
                (_normalize(str(details.get("set") or "")), _normalize(str(record["name"]))), []
            ).append(key)
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
                survivor for survivor in survivors
                if sum(1 for a, b in zip(authored_parts, survivor.split("|")) if a != b) == 1
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

    `Overrides.setRefs` is the one place a human may overrule a code a manufacturer printed, so it
    is also the one place a stale entry does real damage: silently rewriting a ref the source has
    since FIXED, or pointing at a paint that has since been retracted. Neither shows up anywhere
    else -- gen_set_contents.py applies a correction with `dict.get`, so an entry that matches
    nothing is a no-op and an entry pointing nowhere just re-refuses. Both look like success.

    Two halves, because the entry makes two claims:

      1. THE MISTYPED REF IS STILL PRINTED. If it is gone from that product's `contentSkus`, the
         manufacturer fixed its own prose (or the description changed shape) and the entry must be
         DELETED, not left behind where it can catch a future code that happens to collide.
      2. THE CORRECTED CODE STILL NAMES EXACTLY ONE PAINT. A correction resolving to zero paints
         is a refusal wearing a repair's clothes; one resolving to several would pick by archive
         order, which is the tie-break-by-luck this relation refuses everywhere else.

    Live today: ak-interactive/AK11781 prints `AK111424 Grey Green`, which is AK11424 with one
    extra digit -- the only 6-digit code in a box whose other nine are 5-digit AK11xxx.
    """
    _require_repo_data()
    overrides_path = REPO_DATA / "catalog" / "overrides.yaml"
    if not overrides_path.exists():
        pytest.skip("data/catalog/overrides.yaml not present")
    corrections = (read_yaml(overrides_path) or {}).get("setRefs") or {}
    if not corrections:
        pytest.skip("no setRefs corrections declared")

    products: dict[str, dict] = {}
    for path in sorted((REPO_DATA / "catalog" / "products").glob("*.yaml")):
        for product in (read_yaml(path) or {}).get("products") or []:
            products[str(product.get("id"))] = product

    paints_by_code: dict[str, list[str]] = {}
    for path in sorted((REPO_DATA / "paints" / "brands").glob("*.yaml")):
        archive = read_yaml(path) or {}
        for record in archive.get("paints") or []:
            code = str(record.get("productCode") or "")
            if code:
                paints_by_code.setdefault(code, []).append(f"{path.stem}/{record['name']}")

    stale, unresolvable = [], []
    for product_id, mapping in corrections.items():
        product = products.get(product_id)
        assert product is not None, (
            f"setRefs names {product_id!r}, which is not a committed product -- a correction "
            "scoped to a product that no longer exists can never fire"
        )
        stated = [str(code) for code in (product.get("contentSkus") or [])]
        for wrong, right in mapping.items():
            if str(wrong) not in stated:
                stale.append((product_id, wrong, right))
            hits = paints_by_code.get(str(right), [])
            if len(hits) != 1:
                unresolvable.append((product_id, wrong, right, hits))

    assert not stale, (
        "setRefs entries whose mistyped ref is NO LONGER in the product's contentSkus -- the "
        "source fixed its own prose, so the correction is dead weight that can only misfire on a "
        f"future code. Delete them: {stale}"
    )
    assert not unresolvable, (
        "setRefs entries whose corrected code does not name exactly one committed paint. Zero "
        "means the repair refuses just as loudly as the typo did; several means it would be "
        f"decided by archive order: {unresolvable}"
    )
