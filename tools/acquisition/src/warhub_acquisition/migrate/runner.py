"""Orchestrate the one-time legacy migration into the evidence store."""
from dataclasses import dataclass, field
from pathlib import Path

from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.migrate.labels import write_label_files
from warhub_acquisition.migrate.legacy import read_legacy_products
from warhub_acquisition.migrate.seed import read_seed_products
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy


@dataclass
class MigrationSummary:
    legacy_count: int = 0
    seed_count: int = 0
    key_collisions: list[dict] = field(default_factory=list)
    invalid_records: list[dict] = field(default_factory=list)


def run_migration(paths: DataPaths, legacy_dir: Path, seed_dir: Path) -> MigrationSummary:
    taxonomy = Taxonomy.load(paths.taxonomy)
    extraction = read_legacy_products(legacy_dir)
    seed_observations = read_seed_products(
        seed_dir, taxonomy, extraction.label_to_game_system, extraction.label_to_faction
    )
    store = EvidenceStore(paths.evidence_products)
    for observation in extraction.observations:
        store.upsert("legacy-catalog", observation)
    for observation in seed_observations:
        store.upsert("seed-curated", observation)
    store.save("legacy-catalog")
    store.save("seed-curated")
    write_label_files(paths.taxonomy, extraction.game_system_labels, extraction.faction_labels)
    return MigrationSummary(
        legacy_count=len(extraction.observations),
        seed_count=len(seed_observations),
        key_collisions=extraction.key_collisions,
        invalid_records=extraction.invalid_records,
    )
