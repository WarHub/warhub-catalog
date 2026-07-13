"""Contract-enforcing source runner: invoke a strategy, gate writes on its contract, persist."""
from dataclasses import dataclass, field
from typing import Callable

from warhub_acquisition.acquire.client import PoliteClient
from warhub_acquisition.acquire.cursor import CursorStore
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import Contract, SourceDescriptor
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.taxonomy import Taxonomy


class SourceContractError(Exception):
    """A source's fetched data failed its declared contract. Carries machine-readable details."""

    def __init__(self, message: str, details: dict) -> None:
        self.details = details
        super().__init__(message)


@dataclass
class StrategyResult:
    observations: list[Observation]
    full_sweep: bool
    stats: dict[str, int]
    cursor: dict


@dataclass
class AcquireContext:
    taxonomy: Taxonomy
    mappings: dict[str, dict]
    run_date: str
    budget: int | None = None


Strategy = Callable[[SourceDescriptor, PoliteClient, dict, AcquireContext], StrategyResult]

STRATEGIES: dict[str, Strategy] = {}


@dataclass
class SourceHealth:
    source_id: str
    full_sweep: bool
    contract_ok: bool
    observation_count: int
    stats: dict[str, int] = field(default_factory=dict)


def _check_contract(descriptor: SourceDescriptor, result: StrategyResult, cursor: dict) -> None:
    contract = descriptor.contract or Contract()
    actual = len(result.observations)

    if result.full_sweep:
        if actual < contract.minCount:
            raise SourceContractError(
                f"{descriptor.id}: fresh observation count {actual} below minCount {contract.minCount}",
                {"type": "min-count", "source": descriptor.id, "expected": contract.minCount, "actual": actual},
            )

        last_good_count = cursor.get("last_good_count")
        if last_good_count:
            drop_pct = (last_good_count - actual) / last_good_count * 100
            if drop_pct > contract.maxDropPct:
                raise SourceContractError(
                    f"{descriptor.id}: observation count dropped {drop_pct:.1f}% "
                    f"(from {last_good_count} to {actual}), exceeds maxDropPct {contract.maxDropPct}",
                    {
                        "type": "drop",
                        "source": descriptor.id,
                        "last_good_count": last_good_count,
                        "actual": actual,
                        "drop_pct": drop_pct,
                        "max_drop_pct": contract.maxDropPct,
                    },
                )

    # Field fill rates apply to whatever was fetched this run, full sweep or not: a partial,
    # budgeted run is still expected to extract its fields correctly (structured-data drift
    # must be loud even when the run itself is intentionally incomplete).
    if result.observations:
        for field_name, min_rate in sorted(contract.requiredFieldRates.items()):
            filled = sum(1 for observation in result.observations if getattr(observation, field_name, None))
            rate = filled / len(result.observations)
            if rate < min_rate:
                raise SourceContractError(
                    f"{descriptor.id}: field {field_name!r} fill rate {rate:.2f} below required {min_rate}",
                    {
                        "type": "field-fill-rate",
                        "source": descriptor.id,
                        "field": field_name,
                        "rate": rate,
                        "required": min_rate,
                    },
                )


def run_source(
    descriptor: SourceDescriptor,
    paths,
    context: AcquireContext,
    transport=None,
) -> SourceHealth:
    politeness = descriptor.politeness or {}
    client = PoliteClient(descriptor.baseUrl, rps=politeness.get("rps", 0.5), transport=transport)

    cursor_store = CursorStore(paths.evidence_products)
    cursor = cursor_store.load(descriptor.id)

    strategy = STRATEGIES[descriptor.strategy]
    result = strategy(descriptor, client, cursor, context)

    # All contract checks run BEFORE any evidence or cursor write: a failed source must never
    # delete or decay existing evidence, it can only fail to refresh it.
    _check_contract(descriptor, result, cursor)

    store = EvidenceStore(paths.evidence_products)
    seen_keys: set[str] = set()
    for observation in result.observations:
        fresh = observation.model_copy(update={"firstSeen": context.run_date, "lastSeen": context.run_date})
        store.upsert(descriptor.id, fresh)
        seen_keys.add(fresh.key)

    if result.full_sweep:
        store.mark_missed(descriptor.id, seen_keys)

    store.save(descriptor.id)

    new_cursor = dict(result.cursor)
    new_cursor["last_run_date"] = context.run_date
    new_cursor["last_good_count"] = len(result.observations) if result.full_sweep else cursor.get("last_good_count")
    cursor_store.save(descriptor.id, new_cursor)

    return SourceHealth(
        source_id=descriptor.id,
        full_sweep=result.full_sweep,
        contract_ok=True,
        observation_count=len(result.observations),
        stats=result.stats,
    )
