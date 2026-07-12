"""warhub-data CLI: resolve and report (acquire/migrate arrive in later plans)."""
import argparse
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
    args = parser.parse_args(argv)
    paths = DataPaths(args.data)

    if args.command == "resolve":
        catalog = resolve_catalog(paths)
        total = sum(len(records) for records in catalog.values())
        conflicts = read_yaml(paths.conflicts)["conflicts"]
        print(f"resolved {total} products across {len(catalog)} manufacturers; {len(conflicts)} conflicts")
        return 2 if conflicts else 0

    print(build_report(paths), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
