"""Live smoke test: one real, budgeted acquire run against mfr-gw-webstore-paints.

Opt-in only (`@pytest.mark.live`, excluded by default via pyproject's `addopts = "-m 'not
live'"`). Run explicitly with `uv run pytest -m live -q`. Makes real HTTP requests at the
descriptor's own politeness (rps 0.5): four Algolia roster POSTs, one buildId probe and
`budget=2` detail fetches, all against a tmp data dir so nothing here touches the repo's real
evidence/cursor state.

What this is really guarding, and why it is worth a live test at all: the two access mechanics
that no fixture can catch drifting. (1) GW's Next.js `buildId` ROTATES, and the only way to read
it is the 404 page a deliberately-invalid buildId returns -- if GW ever starts serving a
buildId-less 404, every detail fetch silently stops. (2) `_next/data` is reachable by plain httpx
while every HTML route on the same host is bot-walled; if that ever flips, this fails loudly here
rather than degrading in production.
"""
from pathlib import Path

import pytest

from warhub_acquisition.acquire.runner import AcquireContext, load_mappings, run_source
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy

REPO_DATA = Path(__file__).resolve().parents[3] / "data"
SOURCE_ID = "mfr-gw-webstore-paints"


@pytest.mark.live
def test_live_gw_webstore_paints_budgeted_acquire_yields_coded_paints(tmp_path: Path) -> None:
    if not REPO_DATA.exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")

    import warhub_acquisition.acquire.strategies  # noqa: F401  (registers the strategy)

    repo_paths = DataPaths(REPO_DATA)
    descriptor = load_descriptors(repo_paths.sources)[SOURCE_ID]
    context = AcquireContext(
        taxonomy=Taxonomy.load(repo_paths.taxonomy),
        mappings=load_mappings(repo_paths.mappings),
        run_date="2026-08-01",
        budget=2,
    )

    tmp_paths = DataPaths(tmp_path)  # real network, but evidence/cursor land in a tmp dir
    health = run_source(descriptor, tmp_paths, context)

    # The roster is never budgeted: a budgeted run still enumerates the full paint population.
    assert health.observation_count >= descriptor.contract.minCount

    observations = list(EvidenceStore(tmp_paths.evidence_products).load(SOURCE_ID).values())

    # The whole point of the source: every paint carries GW's own 11-digit product code, which
    # is what lets the Citadel barcode bridge stop fuzzy-matching names.
    assert all(o.sku and o.sku.isdigit() and len(o.sku) == 11 for o in observations)
    assert all(o.hints.get("category") == "paint" for o in observations)

    # Ranges come from GW's own paintType facet; Base/Layer/Contrast are its largest and have
    # existed for the whole life of the line.
    lines = {str(o.hints.get("line")) for o in observations}
    assert {"Base", "Layer", "Contrast"} <= lines

    # Sizes: most come from GW's CDN filenames, a minority from the spec block. Both are GW's own
    # assertions; measured union was 90% on 2026-08-01, so a floor of 80% catches a real collapse
    # (e.g. a CDN filename convention change) without tripping on GW retiring a few tiles.
    with_volume = [o for o in observations if o.hints.get("volumeMl")]
    assert len(with_volume) >= 0.8 * len(observations)

    # The buildId probe worked and the budgeted detail fetches landed: `launchDate` exists ONLY on
    # the _next/data record, so its presence proves the rotating buildId was discovered live.
    assert [o for o in observations if o.hints.get("launchDate")]
