"""Contract-enforcing source runner: invoke a strategy, gate writes on its contract, persist."""
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from warhub_acquisition.acquire.client import UA, PoliteClient
from warhub_acquisition.acquire.cursor import CursorStore
from warhub_acquisition.acquire.robots import fetch_policy
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import Contract, SourceDescriptor
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import read_yaml


def load_mappings(directory: Path) -> dict[str, dict]:
    """Load `data/catalog/mappings/<source-id>.yaml` files into `{source_id: {...}}`.

    A source with no mapping file (fine for most retailers) is simply absent from the returned
    dict -- callers already do `context.mappings.get(descriptor.id, {})`, so a missing key and an
    empty file behave identically. A missing directory (e.g. a repo that hasn't created any
    mappings yet) returns `{}`, not an error.
    """
    if not directory.exists():
        return {}
    return {path.stem: (read_yaml(path) or {}) for path in sorted(directory.glob("*.yaml"))}


class SourceContractError(Exception):
    """A source's fetched data failed its declared contract. Carries machine-readable details."""

    def __init__(self, message: str, details: dict) -> None:
        self.details = details
        super().__init__(message)


class RobotsDisallowedError(Exception):
    """A source's own published robots.txt (or ClaudeBot's, per acquire/robots.py's deliberate
    policy) disallows us from fetching its `baseUrl`. Carries machine-readable details, mirroring
    `SourceContractError` -- this is raised BEFORE the strategy runs (see `run_source`), so it hits
    the exact same per-source-isolation path (`cli.py`'s `except Exception`, `SOURCE ERROR`, exit
    code 4) as any other fetch failure, and never touches evidence or the cursor."""

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
    # Additive field (Task 4, barcode-db strategy): the resolved catalog directory
    # (`paths.catalog_products`), needed by INVERTED-flow strategies that read the current
    # catalog rather than a source's own listing. `None` unless `run_source` has populated it
    # (see below) -- callers constructing an AcquireContext directly (most existing strategy
    # tests) never need to set this.
    catalog_dir: Path | None = None


Strategy = Callable[[SourceDescriptor, PoliteClient, dict, AcquireContext], StrategyResult]

STRATEGIES: dict[str, Strategy] = {}


@dataclass
class SourceHealth:
    source_id: str
    full_sweep: bool
    contract_ok: bool
    observation_count: int
    stats: dict[str, int] = field(default_factory=dict)
    marked_missed: int = 0


def _check_contract(descriptor: SourceDescriptor, result: StrategyResult, cursor: dict) -> None:
    contract = descriptor.contract or Contract()
    actual = len(result.observations)

    # minCount is checked on EVERY run, full sweep or not (final fix wave, item 3). Rationale: the
    # runner previously gated this on full_sweep, but shopify.py/woo.py sources can never reach
    # full_sweep at all (their barcode-less products re-queue into pending_details forever, so
    # `full_sweep = not pending_details` never goes True once a store has any barcode-less
    # product) -- their minCount floors were therefore permanently inert, and a partial
    # enumeration collapse (the bulk /products.json or Store API page listing itself shrinking,
    # e.g. from a broken store or a bad filter) would be silent. The assumption that makes this
    # safe: every current strategy's *enumeration* (the cheap bulk-listing pass) covers the full
    # product population on EVERY run, budgeted or not -- only per-item DETAIL fetches (barcodes,
    # gtins) are what the budget rations, and minCount is a floor on `len(result.observations)`
    # (one per enumerated+attributed product), not on detail-fetch completeness. sitemap_sd.py is
    # the one strategy that does NOT enumerate its full population every run (a sitemap page-fetch
    # budget rations the enumeration itself, not just per-item details) -- its minCount is 0 in
    # every descriptor, so this unconditional check stays a no-op for it by design.
    if actual < contract.minCount:
        raise SourceContractError(
            f"{descriptor.id}: fresh observation count {actual} below minCount {contract.minCount}",
            {"type": "min-count", "source": descriptor.id, "expected": contract.minCount, "actual": actual},
        )

    if result.full_sweep:
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
    sleep=None,
) -> SourceHealth:
    politeness = descriptor.politeness or {}
    configured_rps = politeness.get("rps", 0.5)
    timeout_seconds = float(politeness.get("timeoutSeconds", 30.0))
    # `sleep` is an optional pacing-injection seam (mirrors `transport`) -- `None` means "use
    # PoliteClient's own default (real time.sleep)"; tests inject a list-appending callable to
    # observe pacing decisions (e.g. a robots.txt Crawl-delay override) without a real wall-clock
    # wait. Threaded into every PoliteClient this function constructs, including the one rebuilt
    # below for a slower robots-driven rps.
    client_kwargs: dict[str, object] = {"timeout": timeout_seconds, "transport": transport}
    if sleep is not None:
        client_kwargs["sleep"] = sleep
    client = PoliteClient(descriptor.baseUrl, rps=configured_rps, **client_kwargs)

    # --- Robots.txt preflight (acquire/robots.py) -- BEFORE the strategy runs, never after. ---
    # Skipped entirely when there's no baseUrl to check (curated/no-strategy sources never reach
    # here via cli.py, but direct callers -- e.g. this module's own tests -- may still construct a
    # baseUrl-less descriptor) or when the descriptor explicitly opts out via
    # `politeness.ignoreRobots: true` (see robots.py's module docstring + the two real committed
    # cases in mfr-gw-algolia.yaml / mfr-corvus-belli.yaml: baseUrl there is a marketing site, not
    # the actual Algolia/AppSync API host the strategy fetches from, so checking baseUrl's
    # robots.txt would be checking the wrong thing entirely).
    ignore_robots = bool(politeness.get("ignoreRobots", False))
    robots_stats: dict[str, float] = {}
    if descriptor.baseUrl is not None and not ignore_robots:
        policy = fetch_policy(client, descriptor.baseUrl)
        disallow = policy.disallowed_by(descriptor.baseUrl, UA)
        if disallow is not None:
            token, rule = disallow
            rule_detail = f" ({rule})" if rule else ""
            raise RobotsDisallowedError(
                f"{descriptor.id}: robots.txt at {descriptor.baseUrl} disallows "
                f"user-agent {token!r}{rule_detail}",
                {
                    "type": "robots-disallowed",
                    "source": descriptor.id,
                    "url": descriptor.baseUrl,
                    "userAgent": token,
                    "rule": rule,
                },
            )

        robots_delay = policy.crawl_delay(UA)
        if robots_delay is not None:
            configured_interval = 1.0 / configured_rps if configured_rps > 0 else 0.0
            if robots_delay > configured_interval:
                # robots.txt asks for slower pacing than the descriptor configured for itself --
                # honor the slower one (a descriptor's politeness.rps is a ceiling we impose on
                # ourselves, never a floor we're entitled to regardless of what the site asks for).
                # Rebuild the client so every subsequent request (the strategy's, not the
                # robots.txt fetch that already happened above) goes out at the reduced rate.
                robots_stats["robots_crawl_delay_applied"] = robots_delay
                client = PoliteClient(descriptor.baseUrl, rps=1.0 / robots_delay, **client_kwargs)

    cursor_store = CursorStore(paths.evidence_products)
    cursor = cursor_store.load(descriptor.id)

    # `paths.catalog_products` is always available (it's a property, not a filesystem check) --
    # every strategy call gets a context carrying it, not just barcode-db's. `replace` (never
    # mutating the caller's context in place) so a single AcquireContext instance reused across
    # every source in a run (cli.py builds one) is never surprised by another source's call.
    strategy_context = replace(context, catalog_dir=paths.catalog_products)

    strategy = STRATEGIES[descriptor.strategy]
    result = strategy(descriptor, client, cursor, strategy_context)
    if robots_stats:
        result.stats.update(robots_stats)

    # All contract checks run BEFORE any evidence or cursor write: a failed source must never
    # delete or decay existing evidence, it can only fail to refresh it.
    _check_contract(descriptor, result, cursor)

    store = EvidenceStore(paths.evidence_products)
    seen_keys: set[str] = set()
    for observation in result.observations:
        fresh = observation.model_copy(update={"firstSeen": context.run_date, "lastSeen": context.run_date})
        store.upsert(descriptor.id, fresh)
        seen_keys.add(fresh.key)

    marked_missed = 0
    if result.full_sweep:
        marked_missed = store.mark_missed(descriptor.id, seen_keys)

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
        marked_missed=marked_missed,
    )
