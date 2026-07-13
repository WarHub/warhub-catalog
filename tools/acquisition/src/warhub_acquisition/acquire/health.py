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


def build_health_report(
    healths: list[SourceHealth],
    failures: list[SourceFailure],
    errors: list[SourceError],
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
