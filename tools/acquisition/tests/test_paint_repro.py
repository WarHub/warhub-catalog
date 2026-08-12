# tools/acquisition/tests/test_paint_repro.py
"""The two paint generators whose OUTPUT is committed, checked against their committed INPUTS.

WHAT BREAKS WITHOUT THIS: data/paints/harvest/*.yaml and data/paints/barcodes/citadel-colour.yaml
are read by the C# tool as fact -- `--harvest` fills blank ean/imageUrl/price on paint records and
`--barcodes` supplies both barcodes and GW's own `volumeMl`. Nothing downstream re-derives them, so
a file that has drifted from the evidence it claims to project publishes a barcode, a photo or a
pot size that no committed source states any more, and it does it silently: PyYAML round-trips its
own output, the C# does an exact lookup, and paint-catalog-update.yml regenerates both files at the
top of the run without ever comparing them to what was committed. The drift is only visible as a
surprise diff on a PR nobody expected to touch data/paints.

Five scripts under tools/acquisition/scripts/ write committed data. THREE of them are offline and
deterministic -- they read only committed evidence -- and until now exactly one was gated:
data/catalog/set-contents has had this test since the relation itself landed in c272aa2
(test_set_contents.py::test_the_committed_relation_is_reproducible_from_committed_inputs). These
are the other two. (The remaining pair, gen_paint_store_barcodes.py -> data/paints/stores and
gen_paint_swatches.py -> data/paints/swatches, fetch through PoliteClient and are run on demand
against a live storefront, so they cannot be gated this way and are not.)

Both files are byte-identical to a regeneration today (2026-08-11), so these tests land green --
they exist to keep it that way.

IN-PROCESS, NOT SUBPROCESS, and that is not a style preference. Both scripts take their output path
from a module constant with no CLI override, so the subprocess shape test_set_contents.py uses
would write into the WORKING TREE -- a failing reproducibility gate would leave the tree dirty,
which is the opposite of what a gate should do (and on a generator whose additions are ratcheted
from its own prior output, a half-run tree is not trivially recoverable with `git checkout`).
Loading the script by path and redirecting the output constant writes only into tmp_path, and is
faster besides: no interpreter start, no re-import of the package.

Imported by path with a UNIQUE module name, like every other loader in this suite: the scripts are
not part of the installed package (they run standalone under `uv run --with pyyaml`), and
test_paint_harvest_gate.py, test_paint_harvest_price.py and friends each hold their own instance
of gen_paint_harvest.py with its own monkeypatched constants.
"""
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HARVEST_SCRIPT = REPO_ROOT / "tools/acquisition/scripts/gen_paint_harvest.py"
BARCODE_SCRIPT = REPO_ROOT / "tools/acquisition/scripts/gen_paint_barcodes.py"
HARVEST_DIR = REPO_ROOT / "data/paints/harvest"
BARCODE_FILE = REPO_ROOT / "data/paints/barcodes/citadel-colour.yaml"


def _load(script: Path, module_name: str):
    """Same skip guard as _require_repo_data() in test_repo_data.py and _load() in
    test_paint_harvest_gate.py: this package can be built and tested outside the monorepo (sdist),
    where neither the scripts nor data/ exist. Skip cleanly rather than fail."""
    if not script.exists():
        pytest.skip(f"{script.name} not present (package tested outside the monorepo)")
    spec = importlib.util.spec_from_file_location(module_name, script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_harvest_is_reproducible_from_committed_evidence(tmp_path: Path) -> None:
    """The nine harvest files must still be what the committed evidence projects onto the catalog.

    They are a JOIN of two things that move independently: manufacturer observations under
    data/evidence/products/mfr-* (written by catalog-acquire, on demand -- paint sources are
    one-off snapshot harvests) and data/paints/brands/*.yaml (written by paint-catalog-update,
    weekly). Either side can move without the harvest being regenerated, and then the file asserts
    an enrichment neither side supports -- a barcode or a price filed under a `{Name}|{Set}`
    identity that has since been renamed, retracted or re-coded.

    THE OUTPUT DIRECTORY IS SEEDED WITH THE COMMITTED FILES, NOT LEFT EMPTY, because
    `previous_addition_codes` reads OUT_DIR: an addition is a paint that exists NOWHERE but this
    file, so once the C# absorbs one, the bridge code-matches it and would emit it as enrich-only,
    and the next merge would drop it entirely. The ratchet re-emits prior additions to stop that.
    A real run therefore reads the committed file before overwriting it, and this reproduces that
    exactly. Measured 2026-08-11, a run against an EMPTY output directory instead changes 8 of the
    9 files and drops 883 of the 1,094 addition codes (ak-interactive 242, vallejo 220,
    green-stuff-world 168, scale75 59, reaper 56, army-painter 72, turbo-dork 40,
    monument-pro-acryl 26) -- so an unseeded comparison would fail on the ratchet rather than on
    drift, and prove nothing.

    Measured 2026-08-11: all 9 files byte-identical, 13 s for the regeneration.
    """
    if not HARVEST_DIR.exists():
        pytest.skip("data/paints/harvest/ not present")
    committed = sorted(HARVEST_DIR.glob("*.yaml"))
    if not committed:
        pytest.skip("no harvest files committed yet")

    harvest = _load(HARVEST_SCRIPT, "gen_paint_harvest_repro")
    fresh = tmp_path / "harvest"
    shutil.copytree(HARVEST_DIR, fresh)
    # Assigned rather than monkeypatched: this module object belongs to this test alone (unique
    # sys.modules name), so there is nothing to leak into. Same shape as test_gen_paint_barcodes.
    harvest.OUT_DIR = fresh
    harvest.main()

    # One-directional on purpose: the seeded copies mean a brand can only ever be ADDED here, and
    # that is the whole detectable case -- a brand whose evidence went away keeps its file, because
    # main() leaves an existing file untouched rather than deleting a harvest nothing can rebuild.
    extra = sorted({p.name for p in fresh.glob("*.yaml")} - {p.name for p in committed})
    assert not extra, (
        f"the generator emits brand files the tree does not carry: {extra} -- a paint source was "
        "acquired and nobody regenerated the harvest"
    )
    stale = [p.name for p in committed if p.read_bytes() != (fresh / p.name).read_bytes()]
    assert not stale, (
        f"committed harvest files are not reproducible from committed evidence: {stale}. "
        "Regenerate with `uv run --with pyyaml python tools/acquisition/scripts/gen_paint_harvest.py`."
    )


def test_the_committed_citadel_barcodes_are_reproducible_from_the_gw_trade_evidence(
    tmp_path: Path,
) -> None:
    """The Citadel barcode bridge is a FUZZY match frozen at generation time, so it must be re-run.

    `resolve_key` falls back to difflib at a 0.86 cutoff within a set, and the C# BarcodeEnricher
    only ever does an exact `{Name}|{Set}` lookup against the result -- the match itself is never
    re-checked downstream. Rename a Citadel paint, retract one, or land another GW trade workbook,
    and the committed file keeps asserting the join the OLD catalog produced: a barcode and a
    `volumeMl` (which OVERRIDES the tool's per-set VolumeTable) sitting on an identity the archive
    no longer spells that way, or missing from one it now does.

    OFFLINE, verified rather than assumed: the script reads exactly two paths, both committed --
    data/evidence/products/mfr-gw-trade/observations.jsonl and data/paints/brands/citadel-colour.yaml
    -- and imports only difflib/json/re/sys/pathlib/yaml plus `norm` from the package. No network,
    no clock, no environment. Its workflow step (paint-catalog-update.yml, "Regenerate Citadel
    paint barcodes from GW trade evidence") runs it before the C# tool with no arguments at all.

    Measured 2026-08-11: byte-identical, 302 entries from 312 range-stated matches plus 526
    rebrand rows joined on SSC, 0.8 s.
    """
    if not BARCODE_FILE.exists():
        pytest.skip("data/paints/barcodes/citadel-colour.yaml not present")

    barcodes = _load(BARCODE_SCRIPT, "gen_paint_barcodes_repro")
    if not barcodes.EVIDENCE.exists():
        # main() itself skips here and leaves the committed file alone (fresh clone, or a run
        # before the first mfr-gw-trade acquisition), so there is nothing to compare.
        pytest.skip("no committed mfr-gw-trade evidence")

    fresh = tmp_path / "citadel-colour.yaml"
    barcodes.OUT = fresh
    barcodes.main()

    assert fresh.exists(), "the bridge wrote nothing despite the trade evidence being present"
    assert fresh.read_bytes() == BARCODE_FILE.read_bytes(), (
        "data/paints/barcodes/citadel-colour.yaml is not reproducible from the committed GW trade "
        "evidence and the committed Citadel archive. Regenerate with `uv run --with pyyaml python "
        "tools/acquisition/scripts/gen_paint_barcodes.py`."
    )
