"""Parity invariants for the legacy migration; violations are loud."""
from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.migrate.runner import MigrationSummary
from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import read_yaml


def verify_migration(paths: DataPaths, summary: MigrationSummary) -> tuple[list[str], str]:
    catalog = resolve_catalog(paths)
    violations: list[str] = []

    evidence = EvidenceStore(paths.evidence_products).load_all()
    all_keys = {key for source in evidence.values() for key in source}
    covered: dict[str, int] = {}
    products = [p for records in catalog.values() for p in records]
    for product in products:
        for key in product.evidence:
            covered[key] = covered.get(key, 0) + 1
    missing = sorted(all_keys - set(covered))
    if missing:
        violations.append(f"{len(missing)} observation keys not covered by any entity (first: {missing[:5]})")
    doubled = sorted(key for key, count in covered.items() if count > 1)
    if doubled:
        violations.append(f"{len(doubled)} observation keys covered by more than one entity (first: {doubled[:5]})")

    asserted = {
        ean for source in evidence.values() for obs in source.values()
        if (ean := canonical_ean(obs.ean)) is not None
    }
    catalog_eans = {p.ean for p in products if p.ean}
    conflicts = read_yaml(paths.conflicts)["conflicts"] if paths.conflicts.exists() else []
    conflict_eans = {
        value for c in conflicts
        for value in (
            [c.get("ean")] + [a.get("ean") for a in c.get("assertions", [])]
        )
        if value
    }
    lost = sorted(asserted - catalog_eans - conflict_eans)
    if lost:
        violations.append(f"{len(lost)} valid EANs lost (first: {lost[:5]})")

    total = sum(len(source) for source in evidence.values())
    expected = summary.legacy_count + summary.seed_count
    if total != expected:
        violations.append(f"evidence count {total} != migrated count {expected}")
    if summary.invalid_records:
        violations.append(f"{len(summary.invalid_records)} invalid legacy records skipped")

    invalid_ean_count = sum(
        1 for source in evidence.values() for obs in source.values()
        if obs.ean and canonical_ean(obs.ean) is None
    )

    # Count observations (records) by manufacturer
    records_by_manufacturer: dict[str, int] = {}
    for source in evidence.values():
        for obs in source.values():
            if obs.manufacturer:
                records_by_manufacturer[obs.manufacturer] = records_by_manufacturer.get(obs.manufacturer, 0) + 1

    lines = [
        "# Migration report", "",
        f"- observations: {total} (legacy {summary.legacy_count}, seed {summary.seed_count})",
        f"- entities: {len(products)}",
        f"- distinct valid EANs asserted: {len(asserted)}",
        f"- asserted EAN values failing validation: {invalid_ean_count}",
        f"- key collisions: {len(summary.key_collisions)}",
        f"- conflicts: {len(conflicts)}",
        f"- violations: {len(violations)}", "",
        "| manufacturer | records | entities | with EAN | confirmed |", "|---|---|---|---|---|",
    ]
    for manufacturer in sorted(catalog):
        records = catalog[manufacturer]
        with_ean = [p for p in records if p.ean]
        confirmed = [p for p in with_ean if p.eanConfidence == "confirmed"]
        record_count = records_by_manufacturer.get(manufacturer, 0)
        lines.append(f"| {manufacturer} | {record_count} | {len(records)} | {len(with_ean)} | {len(confirmed)} |")
    if violations:
        lines += ["", "## Violations", *[f"- {v}" for v in violations]]
    return violations, "\n".join(lines) + "\n"
