"""warhub-data CLI: resolve, report, migrate, acquire, classify."""
import argparse
import datetime
import os
import sys
from pathlib import Path

from warhub_acquisition.classify.llm import DEFAULT_BUDGET, DEFAULT_MODEL
from warhub_acquisition.migrate.verify import verify_migration
from warhub_acquisition.report import build_report, check_ean_guard, render_ean_guard_section
from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import read_yaml, write_yaml


# Exit codes for the `acquire` verb (documented in .github/workflows/catalog-acquire.yml's header
# and enforced by its "Run acquire" step):
#   0                  -- every selected source succeeded.
#   EXIT_DEGRADED (3)  -- the ONLY failures were upstream rate-limits (HTTP 429 / Cloudflare 403);
#                         successful sources committed, rate-limited ones kept their cursors and
#                         retry next run. The workflow treats this as success-with-annotation, not
#                         a red job -- a throttled night is a DEGRADED run, not a broken one.
#   EXIT_SOURCE_FAILURE (4) -- at least one GENUINE failure (contract violation, parse error,
#                         unexpected exception). Rate-limits present alongside a real failure do
#                         NOT downgrade this: a real fault always wins.
#   1                  -- usage/validation error (bad --run-date, unknown source, missing data dir).
EXIT_DEGRADED = 3
EXIT_SOURCE_FAILURE = 4


def _run_acquire(args: argparse.Namespace, paths: DataPaths) -> int:
    import warhub_acquisition.acquire.strategies  # noqa: F401  (import registers STRATEGIES entries)
    from warhub_acquisition.acquire.client import FetchError
    from warhub_acquisition.acquire.health import (
        SourceError,
        SourceFailure,
        SourceRateLimited,
        build_health_report,
    )
    from warhub_acquisition.acquire.runner import (
        STRATEGIES,
        AcquireContext,
        SourceContractError,
        load_mappings,
        run_source,
    )
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
    mappings = load_mappings(paths.mappings)
    context = AcquireContext(taxonomy=taxonomy, mappings=mappings, run_date=args.run_date, budget=args.budget)

    healths = []
    failures = []
    errors = []
    rate_limited = []
    try:
        for source_id in source_ids:
            try:
                health = run_source(descriptors[source_id], paths, context)
            except SourceContractError as exc:
                failures.append(SourceFailure(source_id=source_id, details=exc.details))
                print(f"CONTRACT VIOLATION {source_id}: {exc.details}")
                continue
            except Exception as exc:
                # Per-source isolation: a source blowing up mid-run must not abort the whole
                # acquire command -- later sources still run, and already-collected results still
                # get flushed to the health report below. Rate-limits are split off here into their
                # OWN bucket: an upstream throttle (429 / Cloudflare 403, flagged on the FetchError
                # by PoliteClient) is an expected, transient, environment-driven degradation, not a
                # code/data fault, so it must NOT fail the run the way a genuine error does. The
                # source made no progress this run but its cursor is intact and it converges later.
                if isinstance(exc, FetchError) and exc.rate_limited:
                    rate_limited.append(
                        SourceRateLimited(source_id=source_id, status=exc.status, message=str(exc))
                    )
                    print(f"RATE LIMITED {source_id}: {exc}")
                    continue
                errors.append(SourceError(source_id=source_id, exc_type=type(exc).__name__, message=str(exc)))
                print(f"SOURCE ERROR {source_id}: {type(exc).__name__}: {exc}")
                continue
            healths.append(health)
            stats = " ".join(f"{k}={v}" for k, v in sorted(health.stats.items()))
            print(f"{source_id}: ok {stats}".rstrip())
    finally:
        # Always write the health report once the loop has run, even if every source failed --
        # successful sources' results must never be silently lost because a later source raised.
        report_text = build_health_report(healths, failures, errors, rate_limited, skipped)
        report_path = paths.root / "review" / "acquisition-health.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8", newline="\n")

    # A genuine failure always wins over a rate-limit; a run whose only failures are rate-limits is
    # DEGRADED (not broken) so the workflow can treat it as success-with-annotation.
    if failures or errors:
        return EXIT_SOURCE_FAILURE
    if rate_limited:
        return EXIT_DEGRADED
    return 0


def _run_classify_llm(args: argparse.Namespace, paths: DataPaths) -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "error: ANTHROPIC_API_KEY environment variable is required for `classify --llm`",
            file=sys.stderr,
        )
        return 1

    if not args.run_date:
        print("error: --run-date is required for `classify --llm`", file=sys.stderr)
        return 1
    try:
        datetime.date.fromisoformat(args.run_date)
    except ValueError:
        print(f"error: --run-date must be YYYY-MM-DD, got {args.run_date!r}", file=sys.stderr)
        return 1

    queue_path = paths.root / "review" / "classification-queue.yaml"
    if not queue_path.exists():
        print(
            f"error: queue file not found: {queue_path}; run `warhub-data classify --emit-queue` first",
            file=sys.stderr,
        )
        return 1

    import anthropic

    from warhub_acquisition.classify.llm import run_llm_classification

    client = anthropic.Anthropic(api_key=api_key)
    summary = run_llm_classification(
        paths, run_date=args.run_date, client=client, budget=args.budget, model=args.model
    )
    print(summary.render())
    return 0


def _run_classify_propose_joins(args: argparse.Namespace, paths: DataPaths) -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "error: ANTHROPIC_API_KEY environment variable is required for `classify --propose-joins`",
            file=sys.stderr,
        )
        return 1

    if not args.run_date:
        print("error: --run-date is required for `classify --propose-joins`", file=sys.stderr)
        return 1
    try:
        datetime.date.fromisoformat(args.run_date)
    except ValueError:
        print(f"error: --run-date must be YYYY-MM-DD, got {args.run_date!r}", file=sys.stderr)
        return 1

    import anthropic

    from warhub_acquisition.classify.joins import run_join_proposals

    client = anthropic.Anthropic(api_key=api_key)
    summary = run_join_proposals(
        paths, run_date=args.run_date, client=client, budget=args.budget, model=args.model
    )
    print(summary.render())
    return 0


def _run_classify(args: argparse.Namespace, paths: DataPaths) -> int:
    from warhub_acquisition.classify.apply import apply_classifications
    from warhub_acquisition.classify.queue import build_queue

    try:
        if args.emit_queue:
            queue = build_queue(paths)
            queue_path = paths.root / "review" / "classification-queue.yaml"
            write_yaml(queue_path, {"queue": queue})
            print(f"wrote {len(queue)} queue items to {queue_path}")
            return 0

        if args.llm:
            return _run_classify_llm(args, paths)

        if args.propose_joins:
            return _run_classify_propose_joins(args, paths)

        count = apply_classifications(paths)
        print(
            f"applied {count} classification{'s' if count != 1 else ''} to catalog/overrides.yaml; "
            "run `warhub-data resolve` to un-park the classified entities"
        )
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


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

    classify = subparsers.add_parser(
        "classify",
        description=(
            "Classification pipeline for published products with a null gameSystem (optional -- "
            "these publish as-is, but a decision here gives one a gameSystem/faction). "
            "--emit-queue writes data/review/classification-queue.yaml for a classifier "
            "(human or LLM) to work through; --apply reads committed decisions from "
            "data/catalog/classifications/products.yaml and merges them into "
            "data/catalog/overrides.yaml. --llm sends the emitted queue to an Anthropic model for "
            "gameSystem/faction decisions. --propose-joins deterministically finds suspected "
            "duplicate-entity pairs (shared EAN / normalized name / legacy-code-to-sku match), "
            "sends each to an Anthropic model for a same-product verdict, and writes "
            "data/review/join-proposals.yaml for human/controller review -- it NEVER edits "
            "matches.yaml itself. Neither --emit-queue/--apply/--llm nor --propose-joins re-runs "
            "`resolve` itself -- run `warhub-data resolve` afterwards for classified gameSystem/"
            "faction decisions or promoted joins to actually appear on the published catalog."
        ),
    )
    classify.add_argument("--data", type=Path, default=Path("data"))
    classify_mode = classify.add_mutually_exclusive_group(required=True)
    classify_mode.add_argument("--emit-queue", action="store_true")
    classify_mode.add_argument("--apply", action="store_true")
    classify_mode.add_argument("--llm", action="store_true")
    classify_mode.add_argument("--propose-joins", action="store_true")
    classify.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    classify.add_argument("--model", default=DEFAULT_MODEL)
    classify.add_argument("--run-date", default=None)

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

    if args.command == "classify":
        return _run_classify(args, paths)

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
