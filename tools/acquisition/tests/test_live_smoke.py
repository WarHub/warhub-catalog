"""Live smoke test: one real, budgeted acquire run against mfr-warlord-store.

Opt-in only (`@pytest.mark.live`, excluded by default via pyproject's `addopts = "-m 'not
live'"`). Run explicitly with `uv run pytest -m live -q`. Makes real HTTP requests at the
descriptor's own politeness (rps 0.5) -- enumeration is always full (per the shopify strategy's
design, see task-5-report.md), so this is a couple dozen page-list requests plus `budget=3`
detail-page requests, all against a tmp data dir so nothing here touches the repo's real
evidence/cursor state.
"""
from pathlib import Path

import pytest

from warhub_acquisition.acquire.runner import AcquireContext, load_mappings, run_source
from warhub_acquisition.ean import is_valid_ean
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy

REPO_DATA = Path(__file__).resolve().parents[3] / "data"


@pytest.mark.live
def test_live_warlord_budgeted_acquire_yields_an_observation_with_a_valid_ean(tmp_path: Path) -> None:
    if not REPO_DATA.exists():
        pytest.skip("no repo data directory found (package built/tested outside the monorepo)")

    import warhub_acquisition.acquire.strategies  # noqa: F401  (registers STRATEGIES["shopify"])

    repo_paths = DataPaths(REPO_DATA)
    descriptor = load_descriptors(repo_paths.sources)["mfr-warlord-store"]
    taxonomy = Taxonomy.load(repo_paths.taxonomy)
    mappings = load_mappings(repo_paths.mappings)
    context = AcquireContext(taxonomy=taxonomy, mappings=mappings, run_date="2026-07-13", budget=3)

    tmp_paths = DataPaths(tmp_path)  # real network, but evidence/cursor land in a tmp dir
    health = run_source(descriptor, tmp_paths, context)

    assert health.observation_count >= 1

    observations = EvidenceStore(tmp_paths.evidence_products).load("mfr-warlord-store")
    valid_eans = [o.ean for o in observations.values() if o.ean and is_valid_ean(o.ean)]
    assert valid_eans, f"expected >=1 observation with a valid EAN among {health.observation_count}"
