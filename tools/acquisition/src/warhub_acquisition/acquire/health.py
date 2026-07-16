"""Acquisition health report: per-source table + unmapped/skipped rollups (markdown)."""
from dataclasses import dataclass

from warhub_acquisition.acquire.runner import SourceHealth


@dataclass
class SourceFailure:
    """A source that raised SourceContractError during acquire.

    Rendered into the health report from the exception's `.details` -- SourceHealth itself is
    never constructed for a failed source (run_source raises instead of returning contract_ok=False).
    """

    source_id: str
    details: dict


@dataclass
class SourceError:
    """A source that raised some other (non-contract) exception during acquire.

    Distinct from SourceFailure: this is an unexpected error (e.g. FetchError after retry
    exhaustion) rather than a declared-contract violation, and is rendered differently in the
    health report so the two failure kinds stay distinguishable at a glance.
    """

    source_id: str
    exc_type: str
    message: str


@dataclass
class SourceRateLimited:
    """A source whose ONLY failure this run was upstream rate-limiting -- an HTTP 429, or a
    Cloudflare-style 403 anti-bot block -- after PoliteClient exhausted its bounded retry/backoff.

    Deliberately split out from SourceError: this is an *expected, environment-driven, transient*
    degradation (GitHub-runner IPs are throttled by Shopify/Cloudflare -- see catalog-acquire.yml's
    header), NOT a code or data fault. A source in this bucket made no progress tonight, but its
    cursor is intact and it converges on a later run. A run whose failures are ALL of this kind is
    reported as DEGRADED (a distinct exit code the workflow treats as success-with-annotation),
    not broken -- so a throttled night no longer paints the whole job red and hides real failures.
    Rendered with a `rate-limited` status so the sticky PR surfaces it at a glance.
    """

    source_id: str
    status: int | None
    message: str


def build_health_report(
    healths: list[SourceHealth],
    failures: list[SourceFailure],
    errors: list[SourceError],
    rate_limited: list[SourceRateLimited],
    skipped: list[str],
) -> str:
    lines = [
        "## Acquisition health",
        "",
        "| source | status | full sweep | observations | marked missed | stats |",
        "|---|---|---|---|---|---|",
    ]

    rows: list[tuple[str, str]] = []
    for health in healths:
        stats = ", ".join(f"{k}={v}" for k, v in sorted(health.stats.items()))
        rows.append(
            (
                health.source_id,
                f"| {health.source_id} | ok | {health.full_sweep} | {health.observation_count} "
                f"| {health.marked_missed} | {stats} |",
            )
        )
    for failure in failures:
        details = ", ".join(f"{k}={v}" for k, v in sorted(failure.details.items()))
        rows.append(
            (failure.source_id, f"| {failure.source_id} | CONTRACT VIOLATION |  |  |  | {details} |")
        )
    for error in errors:
        rows.append(
            (error.source_id, f"| {error.source_id} | ERROR |  |  |  | {error.exc_type}: {error.message} |")
        )
    for limited in rate_limited:
        detail = f"HTTP {limited.status}: {limited.message}" if limited.status is not None else limited.message
        rows.append(
            (limited.source_id, f"| {limited.source_id} | rate-limited |  |  |  | {detail} |")
        )
    for _, row in sorted(rows, key=lambda r: r[0]):
        lines.append(row)

    if skipped:
        lines += ["", "## Skipped (no registered strategy)", ""]
        for source_id in sorted(skipped):
            lines.append(f"- {source_id}")

    unmapped = [
        (health.source_id, health.stats["unmapped_hints"])
        for health in healths
        if health.stats.get("unmapped_hints")
    ]
    if unmapped:
        lines += ["", "## Unmapped hints", ""]
        for source_id, count in sorted(unmapped):
            lines.append(f"- {source_id}: {count}")

    return "\n".join(lines) + "\n"
