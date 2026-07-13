"""warhub-data CLI: resolve, report, migrate, acquire."""
import argparse
import datetime
import sys
from pathlib import Path

from warhub_acquisition.migrate.verify import verify_migration
from warhub_acquisition.report import build_report, check_ean_guard, render_ean_guard_section
from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import read_yaml


def _run_acquire(args: argparse.Namespace, paths: DataPaths) -> int:
    from warhub_acquisition.acquire.health import SourceError, SourceFailure, build_health_report
    from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, SourceContractError, run_source
    from warhub_acquisition.models.descriptor import load_descriptors
    from warhub_acquisition.taxonomy import Taxonomy

    try:
        datetime.date.fromisoformat(args.run_date)
    except ValueError:
        print(f"error: --run-date must be YYYY-MM-DD, got {args.run_date!r}", file=sys.stderr)
        return 1

    descriptors = load_descriptors(paths.sources)

    if args.source:
        source_ids = sorted(set(args.source))
        unknown = [sid for sid in source_ids if sid not in descriptors]
        if unknown:
            print(f"error: unknown source(s): {', '.join(unknown)}", file=sys.stderr)
            return 1
        unregistered = [sid for sid in source_ids if descriptors[sid].strategy not in STRATEGIES]
        if unregistered:
            print(f"error: source(s) with no registered strategy: {', '.join(unregistered)}", file=sys.stderr)
            return 1
        skipped: list[str] = []
    else:
        source_ids = sorted(sid for sid, descriptor in descriptors.items() if descriptor.strategy in STRATEGIES)
        skipped = sorted(sid for sid, descriptor in descriptors.items() if descriptor.strategy not in STRATEGIES)

    taxonomy = Taxonomy.load(paths.taxonomy)
    context = AcquireContext(taxonomy=taxonomy, mappings={}, run_date=args.run_date, budget=args.budget)

    healths = []
    failures = []
    errors = []
    try:
        for source_id in source_ids:
            try:
                health = run_source(descriptors[source_id], paths, context)
            except SourceContractError as exc:
                failures.append(SourceFailure(source_id=source_id, details=exc.details))
                print(f"CONTRACT VIOLATION {source_id}: {exc.details}")
                continue
            except Exception as exc:
                # Per-source isolation: a source blowing up mid-run (e.g. FetchError after retry
                # exhaustion) must not abort the whole acquire command -- later sources still run,
                # and already-collected results still get flushed to the health report below.
                errors.append(SourceError(source_id=source_id, exc_type=type(exc).__name__, message=str(exc)))
                print(f"SOURCE ERROR {source_id}: {type(exc).__name__}: {exc}")
                continue
            healths.append(health)
            stats = " ".join(f"{k}={v}" for k, v in sorted(health.stats.items()))
            print(f"{source_id}: ok {stats}".rstrip())
    finally:
        # Always write the health report once the loop has run, even if every source failed --
        # successful sources' results must never be silently lost because a later source raised.
        report_text = build_health_report(healths, failures, errors, skipped)
        report_path = paths.root / "review" / "acquisition-health.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8", newline="\n")

    return 4 if (failures or errors) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="warhub-data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_sub = subparsers.add_parser("resolve")
    resolve_sub.add_argument("--data", type=Path, default=Path("data"))

    report_sub = subparsers.add_parser("report")
    report_sub.add_argument("--data", type=Path, default=Path("data"))
    report_sub.add_argument("--ean-guard", action="store_true")

    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("--data", type=Path, default=Path("data"))
    migrate.add_argument("--legacy-dir", type=Path, default=Path("data/products/manufacturers"))
    migrate.add_argument("--seed-dir", type=Path, default=Path("data/products/seed"))
    migrate.add_argument("--report", type=Path, default=None)

    acquire = subparsers.add_parser("acquire")
    acquire.add_argument("--data", type=Path, default=Path("data"))
    acquire.add_argument("--source", action="append", default=None)
    acquire.add_argument("--budget", type=int, default=None)
    acquire.add_argument("--run-date", required=True)

    args = parser.parse_args(argv)
    paths = DataPaths(args.data)
    if not paths.root.is_dir():
        print(f"error: data directory not found: {paths.root}", file=sys.stderr)
        return 1

    if args.command == "resolve":
        catalog = resolve_catalog(paths)
        total = sum(len(records) for records in catalog.values())
        conflicts = read_yaml(paths.conflicts)["conflicts"]
        print(f"resolved {total} products across {len(catalog)} manufacturers; {len(conflicts)} conflicts")
        return 2 if conflicts else 0

    if args.command == "migrate":
        from warhub_acquisition.migrate.runner import run_migration

        summary = run_migration(paths, args.legacy_dir, args.seed_dir)
        print(
            f"migrated {summary.legacy_count} legacy + {summary.seed_count} seed observations; "
            f"{len(summary.key_collisions)} key collisions; {len(summary.invalid_records)} invalid records"
        )
        violations, report = verify_migration(paths, summary)
        report_path = args.report or (args.data / "review" / "migration-report.md")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8", newline="\n")
        if violations:
            for violation in violations:
                print(f"VIOLATION: {violation}")
            return 3
        print("verification: OK")
        return 0

    if args.command == "acquire":
        return _run_acquire(args, paths)

    report_text = build_report(paths)
    exit_code = 0
    if args.ean_guard:
        findings = check_ean_guard(paths)
        if findings:
            report_text += render_ean_guard_section(findings)
            exit_code = 5
    print(report_text, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
