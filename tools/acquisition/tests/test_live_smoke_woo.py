"""Live smoke test: real, budgeted acquire runs against mfr-manticgames and mfr-para-bellum.

Opt-in only (`@pytest.mark.live`, excluded by default via pyproject's `addopts = "-m 'not
live'"`). Run explicitly with `uv run pytest -m live -q`. Enumeration is always full (per the
woo strategy's design, mirroring shopify's -- see task-8-report.md), so each run is dozens of
page-list requests at the descriptor's own politeness (rps 0.5) plus a small budget of detail
requests, all against a tmp data dir so nothing here touches the repo's real evidence/cursor
state (data/evidence/ and data/review/ are off-limits for this task -- see task-8-report.md).

Per this task's explicit scope cut, this is a SMOKE test only (small budget, tmp_path evidence,
no data/evidence or data/review writes) -- it is not the task's EXECUTE step (full harvest,
resolve, report, data commit), which the controller runs separately.
"""
from pathlib import Path

import pytest

from warhub_acquisition.acquire.runner import AcquireContext, load_mappings, run_source
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy

REPO_DATA = Path(__file__).resolve().parents[3] / "data"


@pytest.mark.live
def test_live_mantic_budgeted_acquire_fetches_details_and_extracts_valid_gtins_when_present(
    tmp_path: Path,
) -> None:
    """Real end-to-end pipeline check: enumeration + detail-page fetch + JSON-LD parsing against
    the live site. Does NOT assert a gtin is found within the small budget -- live evidence
    (task-8-report.md) shows gtin fill is sparse in this catalog (most Mantic products, e.g.
    miniatures kits and events, have none; only some retail-distributed books do), so requiring
    one within an arbitrary 5-product budget would be flaky. Real-fixture-exact gtin extraction
    (including @graph unwrapping) is already covered, offline and deterministically, by
    test_strategy_woo.py::test_gtin_extraction_handles_at_graph_nesting_from_real_fixture.
    """
    if not REPO_DATA.exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")

    import warhub_acquisition.acquire.strategies  # noqa: F401  (registers STRATEGIES["woo-store-api"])

    repo_paths = DataPaths(REPO_DATA)
    descriptor = load_descriptors(repo_paths.sources)["mfr-manticgames"]
    taxonomy = Taxonomy.load(repo_paths.taxonomy)
    mappings = load_mappings(repo_paths.mappings)
    context = AcquireContext(taxonomy=taxonomy, mappings=mappings, run_date="2026-07-13", budget=5)

    tmp_paths = DataPaths(tmp_path)  # real network, but evidence/cursor land in a tmp dir
    health = run_source(descriptor, tmp_paths, context)

    assert health.observation_count >= 1
    assert health.stats["details_fetched"] == 5  # the declared budget, spent on real HTTP fetches
    assert health.stats["detail_fetch_errors"] == 0

    observations = EvidenceStore(tmp_paths.evidence_products).load("mfr-manticgames")
    assert any(o.priceGbp for o in observations.values())
    # any gtin that WAS found (not guaranteed within this small a budget) must be digits-only.
    for observation in observations.values():
        if observation.ean:
            assert observation.ean.isdigit()


@pytest.mark.live
def test_live_para_bellum_budgeted_acquire_yields_observations_without_details(tmp_path: Path) -> None:
    if not REPO_DATA.exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")

    import warhub_acquisition.acquire.strategies  # noqa: F401

    repo_paths = DataPaths(REPO_DATA)
    descriptor = load_descriptors(repo_paths.sources)["mfr-para-bellum"]
    taxonomy = Taxonomy.load(repo_paths.taxonomy)
    mappings = load_mappings(repo_paths.mappings)
    context = AcquireContext(taxonomy=taxonomy, mappings=mappings, run_date="2026-07-13", budget=5)

    tmp_paths = DataPaths(tmp_path)
    health = run_source(descriptor, tmp_paths, context)

    assert health.observation_count >= 1
    assert health.stats["details_fetched"] == 0  # no gtinFromJsonLd -- never fetches details

    observations = EvidenceStore(tmp_paths.evidence_products).load("mfr-para-bellum")
    assert any(o.priceUsd for o in observations.values())
