"""Pure resolver: evidence + taxonomy + matches + overrides -> canonical catalog."""
from dataclasses import dataclass
from pathlib import Path

from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.catalog import CanonicalProduct, Overrides
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.resolve.attributes import apply_overrides, resolve_attributes
from warhub_acquisition.resolve.corroborate import find_shared_eans, resolve_ean
from warhub_acquisition.resolve.join import Matches, join_observations
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import read_yaml, write_yaml


@dataclass
class DataPaths:
    root: Path

    @property
    def evidence_products(self) -> Path:
        return self.root / "evidence" / "products"

    @property
    def catalog_products(self) -> Path:
        return self.root / "catalog" / "products"

    @property
    def sources(self) -> Path:
        return self.root / "catalog" / "sources"

    @property
    def taxonomy(self) -> Path:
        return self.root / "catalog" / "taxonomy"

    @property
    def matches(self) -> Path:
        return self.root / "catalog" / "matches.yaml"

    @property
    def overrides(self) -> Path:
        return self.root / "catalog" / "overrides.yaml"

    @property
    def conflicts(self) -> Path:
        return self.root / "review" / "conflicts.yaml"


def _load_optional(path: Path, model: type, default: object) -> object:
    if path.exists():
        return model.model_validate(read_yaml(path))
    return default


def resolve_catalog(paths: DataPaths) -> dict[str, list[CanonicalProduct]]:
    taxonomy = Taxonomy.load(paths.taxonomy)
    descriptors = load_descriptors(paths.sources)
    kinds = {sid: descriptor.kind for sid, descriptor in descriptors.items()}

    evidence = EvidenceStore(paths.evidence_products).load_all()
    unknown = set(evidence) - set(descriptors)
    if unknown:
        raise ValueError(f"evidence sources without a descriptor: {sorted(unknown)}")

    matches: Matches = _load_optional(paths.matches, Matches, Matches())
    overrides: Overrides = _load_optional(paths.overrides, Overrides, Overrides())

    retracted = set(overrides.retract)
    for alias_target in matches.aliases.values():
        if alias_target in retracted:
            raise ValueError(f"matches.yaml alias targets retracted entity {alias_target!r}")
    for join_target in matches.joins.values():
        if join_target in retracted:
            raise ValueError(f"matches.yaml join targets retracted entity {join_target!r}")

    observations = [observation for source in evidence.values() for observation in source.values()]

    if not observations and any(paths.catalog_products.glob("*.yaml")):
        raise ValueError("no evidence loaded but catalog files exist; refusing to wipe the catalog")

    joined = join_observations(observations, taxonomy, kinds, matches)

    conflicts: list[dict] = list(joined.ambiguous)
    ean_resolutions = {}
    products: dict[str, list[CanonicalProduct]] = {}
    for entity, members in joined.entities.items():
        # retracted entities are fully suppressed -- including from the ean-shared check below
        if entity in retracted:
            continue
        ean = resolve_ean(entity, members, kinds)
        ean_resolutions[entity] = ean
        conflicts.extend(ean.conflicts)
        code = entity.split("/", 1)[1] if any(
            taxonomy.normalize_code(m.manufacturer, m.sku) == entity.split("/", 1)[1] for m in members
        ) else None
        product = apply_overrides(resolve_attributes(entity, members, kinds, ean, code), overrides)
        if product.gameSystem is None:
            # the publisher throws on a null gameSystem -- park the entity out of the
            # written catalog instead, surfaced via the review queue for mapping.
            conflicts.append(
                {"type": "unclassified-entity", "entity": entity, "names": [members[0].name]}
            )
            continue
        products.setdefault(product.manufacturer, []).append(product)

    conflicts.extend(find_shared_eans(ean_resolutions))

    paths.catalog_products.mkdir(parents=True, exist_ok=True)
    produced = set()
    for manufacturer in sorted(products):
        records = sorted(products[manufacturer], key=lambda p: p.id)
        write_yaml(
            paths.catalog_products / f"{manufacturer}.yaml",
            {
                "manufacturer": manufacturer,
                "products": [record.model_dump(mode="json", exclude_none=True) for record in records],
            },
        )
        produced.add(f"{manufacturer}.yaml")
    for stale in sorted(paths.catalog_products.glob("*.yaml")):
        if stale.name not in produced:
            stale.unlink()

    write_yaml(paths.conflicts, {"conflicts": sorted(conflicts, key=lambda c: str(sorted(c.items())))})
    return {manufacturer: sorted(records, key=lambda p: p.id) for manufacturer, records in sorted(products.items())}
