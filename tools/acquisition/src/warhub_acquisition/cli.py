"""warhub-data CLI: resolve and report (acquire/migrate arrive in later plans)."""
import argparse
import sys
from pathlib import Path

from warhub_acquisition.report import build_report
from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import read_yaml


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="warhub-data")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("resolve", "report"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--data", type=Path, default=Path("data"))
    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("--data", type=Path, default=Path("data"))
    migrate.add_argument("--legacy-dir", type=Path, default=Path("data/products/manufacturers"))
    migrate.add_argument("--seed-dir", type=Path, default=Path("data/products/seed"))
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
        return 0

    print(build_report(paths), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
