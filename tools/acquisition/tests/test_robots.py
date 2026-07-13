"""robots.txt compliance preflight: `acquire/robots.py` unit tests, plus `run_source` integration
(the preflight is wired in BEFORE any strategy runs -- see runner.py's module docstring additions
and robots.py's own module docstring for the full policy rationale, including why `ClaudeBot` is
checked as a third token alongside our own UA)."""
from pathlib import Path

import httpx
import pytest

from warhub_acquisition.acquire.client import UA, FetchError, PoliteClient
from warhub_acquisition.acquire.robots import (
    CLAUDEBOT_TOKEN,
    PRODUCT_TOKEN,
    RobotsFetchError,
    RobotsPolicy,
    fetch_policy,
)
from warhub_acquisition.acquire.runner import STRATEGIES, AcquireContext, RobotsDisallowedError, StrategyResult, run_source
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.descriptor import SourceDescriptor
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy


# --- test helpers ------------------------------------------------------------------------------


def client_for(handler, sleep=None) -> PoliteClient:
    return PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(handler),
        sleep=sleep or (lambda seconds: None),
    )


def robots_response(body: str) -> httpx.Response:
    return httpx.Response(200, text=body)


def obs(key: str, **kw: object) -> Observation:
    base: dict[str, object] = {
        "key": key,
        "name": f"Product {key}",
        "firstSeen": "2000-01-01",
        "lastSeen": "2000-01-01",
        "extractor": "toy@1",
    }
    base.update(kw)
    return Observation(**base)


def context(tmp_path: Path) -> AcquireContext:
    return AcquireContext(taxonomy=Taxonomy({}), mappings={}, run_date="2026-07-13")


def register(name: str, strategy_fn, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(STRATEGIES, name, strategy_fn)


def toy_result(**kw: object) -> StrategyResult:
    base: dict[str, object] = {"observations": [], "full_sweep": False, "stats": {}, "cursor": {}}
    base.update(kw)
    return StrategyResult(**base)


# --- fetch_policy: 404/410 permissive, 5xx/transport fail loud, 200 parses ---------------------


def test_fetch_policy_404_is_permissive() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    policy = fetch_policy(client_for(handler), "https://example.test")
    assert policy.is_permissive is True
    assert policy.allows("https://example.test/anything", UA) is True
    assert policy.crawl_delay(UA) is None


def test_fetch_policy_410_is_permissive() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(410)

    policy = fetch_policy(client_for(handler), "https://example.test")
    assert policy.is_permissive is True
    assert policy.allows("https://example.test/anything", UA) is True


def test_fetch_policy_5xx_raises_robots_fetch_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(RobotsFetchError) as excinfo:
        fetch_policy(client_for(handler), "https://example.test")
    assert isinstance(excinfo.value.cause, FetchError)
    assert excinfo.value.cause.status == 503


def test_fetch_policy_transport_failure_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(RobotsFetchError) as excinfo:
        fetch_policy(client_for(handler), "https://example.test")
    assert excinfo.value.cause.status is None


def test_fetch_policy_non_permissive_4xx_raises() -> None:
    """A 301/401/403 on robots.txt itself is neither '2xx: parse' nor '404/410: no restrictions
    published' -- we cannot prove we're allowed, so this fails loud too, not just 5xx/transport."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"Location": "/en/robots.txt"})

    with pytest.raises(RobotsFetchError) as excinfo:
        fetch_policy(client_for(handler), "https://example.test")
    assert excinfo.value.cause.status == 301


def test_fetch_policy_200_parses_and_is_not_permissive() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response("User-agent: *\nDisallow: /private/\n")

    policy = fetch_policy(client_for(handler), "https://example.test")
    assert policy.is_permissive is False
    assert policy.allows("https://example.test/private/x", UA) is False
    assert policy.allows("https://example.test/public/x", UA) is True


def test_fetch_policy_requests_robots_txt_through_the_client() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return robots_response("User-agent: *\nAllow: /\n")

    fetch_policy(client_for(handler), "https://example.test")
    assert seen == ["/robots.txt"]


# --- RobotsPolicy.allows: full UA, bare product token, ClaudeBot -- ANY disallow => disallowed ---


def test_allows_true_when_robots_allows_everything() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response("User-agent: *\nAllow: /\n")

    policy = fetch_policy(client_for(handler), "https://example.test")
    assert policy.allows("https://example.test/", UA) is True


def test_allows_false_when_full_user_agent_string_is_disallowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response(f"User-agent: {PRODUCT_TOKEN}\nDisallow: /\n")

    policy = fetch_policy(client_for(handler), "https://example.test")
    # Our real outgoing UA string reduces to the same product token stdlib matches on.
    assert policy.allows("https://example.test/", UA) is False


def test_allows_false_when_bare_product_token_is_disallowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response(f"User-agent: *\nAllow: /\n\nUser-agent: {PRODUCT_TOKEN}\nDisallow: /\n")

    policy = fetch_policy(client_for(handler), "https://example.test")
    assert policy.allows("https://example.test/", UA) is False


def test_allows_false_when_claudebot_is_disallowed_even_if_our_own_ua_is_allowed() -> None:
    """The deliberate policy choice (robots.py module docstring, point 3): a site can disallow
    'ClaudeBot' by name without ever mentioning our real product string, and we still treat
    ourselves as disallowed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response(f"User-agent: *\nAllow: /\n\nUser-agent: {CLAUDEBOT_TOKEN}\nDisallow: /\n")

    policy = fetch_policy(client_for(handler), "https://example.test")
    assert policy.allows("https://example.test/", UA) is False


def test_allows_true_when_claudebot_disallowed_only_on_an_unrelated_path() -> None:
    """Sanity check: ClaudeBot being blocked from ONE path doesn't blanket-disallow the whole
    site -- only the checked URL matters, same as any other token."""

    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response(f"User-agent: *\nAllow: /\n\nUser-agent: {CLAUDEBOT_TOKEN}\nDisallow: /admin/\n")

    policy = fetch_policy(client_for(handler), "https://example.test")
    assert policy.allows("https://example.test/", UA) is True


def test_disallowed_by_reports_the_matching_token_and_rule() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response("User-agent: *\nDisallow: /\n")

    policy = fetch_policy(client_for(handler), "https://example.test")
    result = policy.disallowed_by("https://example.test/", UA)
    assert result is not None
    token, rule = result
    assert token == UA
    assert rule == "Disallow: /"


def test_disallowed_by_none_when_allowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response("User-agent: *\nAllow: /\n")

    policy = fetch_policy(client_for(handler), "https://example.test")
    assert policy.disallowed_by("https://example.test/", UA) is None


# --- crawl_delay -----------------------------------------------------------------------------


def test_crawl_delay_returns_declared_seconds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response("User-agent: *\nAllow: /\nCrawl-delay: 7\n")

    policy = fetch_policy(client_for(handler), "https://example.test")
    assert policy.crawl_delay(UA) == 7.0


def test_crawl_delay_none_when_not_declared() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response("User-agent: *\nAllow: /\n")

    policy = fetch_policy(client_for(handler), "https://example.test")
    assert policy.crawl_delay(UA) is None


def test_crawl_delay_none_when_permissive() -> None:
    policy = RobotsPolicy(None)
    assert policy.crawl_delay(UA) is None


# =================================================================================================
# run_source integration: the preflight is wired in BEFORE any strategy call.
# =================================================================================================


def _never_called_strategy(desc, client, cursor, ctx):
    raise AssertionError("strategy must not run when robots.txt disallows the source")


def test_run_source_disallowed_by_robots_raises_and_writes_no_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = DataPaths(tmp_path)
    store = EvidenceStore(paths.evidence_products)
    store.upsert("toy-robots", obs("toy-robots:existing"))
    store.save("toy-robots")
    before = (paths.evidence_products / "toy-robots" / "observations.jsonl").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/robots.txt"
        return robots_response("User-agent: *\nDisallow: /\n")

    register("toy-robots", _never_called_strategy, monkeypatch)
    desc = SourceDescriptor(
        id="toy-robots", kind="retailer", strategy="toy-robots", baseUrl="https://example.test"
    )

    with pytest.raises(RobotsDisallowedError) as excinfo:
        run_source(desc, paths, context(tmp_path), transport=httpx.MockTransport(handler))

    assert excinfo.value.details["type"] == "robots-disallowed"
    assert excinfo.value.details["source"] == "toy-robots"
    assert excinfo.value.details["url"] == "https://example.test"
    assert excinfo.value.details["rule"] == "Disallow: /"

    assert (paths.evidence_products / "toy-robots" / "observations.jsonl").read_bytes() == before
    assert not (paths.evidence_products / "toy-robots" / "cursor.yaml").exists()


def test_run_source_allowed_by_robots_proceeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response("User-agent: *\nAllow: /\n")

    register("toy-robots-ok", lambda desc, client, cursor, ctx: toy_result(), monkeypatch)
    desc = SourceDescriptor(
        id="toy-robots-ok", kind="retailer", strategy="toy-robots-ok", baseUrl="https://example.test"
    )

    health = run_source(desc, DataPaths(tmp_path), context(tmp_path), transport=httpx.MockTransport(handler))
    assert health.contract_ok is True


def test_run_source_permissive_404_robots_proceeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    register("toy-robots-404", lambda desc, client, cursor, ctx: toy_result(), monkeypatch)
    desc = SourceDescriptor(
        id="toy-robots-404", kind="retailer", strategy="toy-robots-404", baseUrl="https://example.test"
    )

    health = run_source(desc, DataPaths(tmp_path), context(tmp_path), transport=httpx.MockTransport(handler))
    assert health.contract_ok is True


def test_run_source_500_robots_raises_robots_fetch_error_and_writes_no_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = DataPaths(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    register("toy-robots-500", _never_called_strategy, monkeypatch)
    desc = SourceDescriptor(
        id="toy-robots-500", kind="retailer", strategy="toy-robots-500", baseUrl="https://example.test"
    )

    with pytest.raises(RobotsFetchError):
        run_source(desc, paths, context(tmp_path), transport=httpx.MockTransport(handler))

    assert not (paths.evidence_products / "toy-robots-500" / "observations.jsonl").exists()


def test_run_source_claudebot_disallowed_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_response(f"User-agent: *\nAllow: /\n\nUser-agent: {CLAUDEBOT_TOKEN}\nDisallow: /\n")

    register("toy-robots-claude", _never_called_strategy, monkeypatch)
    desc = SourceDescriptor(
        id="toy-robots-claude", kind="retailer", strategy="toy-robots-claude", baseUrl="https://example.test"
    )

    with pytest.raises(RobotsDisallowedError) as excinfo:
        run_source(desc, DataPaths(tmp_path), context(tmp_path), transport=httpx.MockTransport(handler))
    assert excinfo.value.details["userAgent"] == CLAUDEBOT_TOKEN


def test_run_source_ignore_robots_skips_the_check_entirely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"robots.txt must never be requested when ignoreRobots is set: {request.url}")

    register("toy-robots-ignore", lambda desc, client, cursor, ctx: toy_result(), monkeypatch)
    desc = SourceDescriptor(
        id="toy-robots-ignore",
        kind="manufacturer",
        strategy="toy-robots-ignore",
        baseUrl="https://example.test",
        politeness={"ignoreRobots": True},
    )

    health = run_source(desc, DataPaths(tmp_path), context(tmp_path), transport=httpx.MockTransport(handler))
    assert health.contract_ok is True


def test_run_source_no_base_url_skips_the_check_entirely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No baseUrl means nothing to check -- matches curated/no-strategy descriptors, which never
    reach run_source via cli.py anyway, but a direct caller (e.g. a test) with no baseUrl must not
    crash trying to fetch robots.txt against an empty base."""
    register("toy-no-baseurl", lambda desc, client, cursor, ctx: toy_result(), monkeypatch)
    desc = SourceDescriptor(id="toy-no-baseurl", kind="curated", strategy="toy-no-baseurl")

    health = run_source(desc, DataPaths(tmp_path), context(tmp_path))
    assert health.contract_ok is True


def test_run_source_strategy_fetch_of_disallowed_path_blocked_despite_permissive_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE HOLE THIS FIX CLOSES, end to end (fix wave 1, 2026-07-13): robots.txt allows '/' -- so
    the base-URL preflight (checking `descriptor.baseUrl`, i.e. the root) passes cleanly -- but
    specifically disallows '/products.json', a path the strategy itself fetches. Before this fix,
    only `descriptor.baseUrl` was ever checked, so this strategy fetch would have silently violated
    robots.txt on every run. Now `PoliteClient._request` checks every request the strategy's client
    makes (the policy fetched once by the preflight, attached to that client -- see runner.py), so
    this is caught."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_response("User-agent: *\nAllow: /\nDisallow: /products.json\n")
        return httpx.Response(200, json={"ok": True})

    def strategy(desc, client, cursor, ctx):
        client.get_json("/products.json")  # the disallowed path -- must raise before returning
        return toy_result()

    register("toy-robots-hole", strategy, monkeypatch)
    desc = SourceDescriptor(
        id="toy-robots-hole", kind="retailer", strategy="toy-robots-hole", baseUrl="https://example.test"
    )

    with pytest.raises(RobotsDisallowedError) as excinfo:
        run_source(desc, DataPaths(tmp_path), context(tmp_path), transport=httpx.MockTransport(handler))

    assert excinfo.value.details["type"] == "robots-disallowed"
    assert excinfo.value.details["url"] == "https://example.test/products.json"
    assert excinfo.value.details["rule"] == "Disallow: /products.json"
    # Raised by PoliteClient._request (the per-request check), not runner.py's base-URL preflight
    # -- which has no complaint about "/" -- so this has no "source" key (see client.py's
    # RobotsDisallowedError docstring).
    assert "source" not in excinfo.value.details


def test_run_source_strategy_fetch_of_allowed_path_proceeds_under_same_disallowing_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion to the hole-closing test above: the SAME policy (allows '/', disallows
    '/products.json') still lets the strategy fetch an unrelated, allowed path normally."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_response("User-agent: *\nAllow: /\nDisallow: /products.json\n")
        return httpx.Response(200, json={"ok": True})

    captured: dict = {}

    def strategy(desc, client, cursor, ctx):
        captured["result"] = client.get_json("/catalog.json")
        return toy_result()

    register("toy-robots-hole-ok", strategy, monkeypatch)
    desc = SourceDescriptor(
        id="toy-robots-hole-ok", kind="retailer", strategy="toy-robots-hole-ok", baseUrl="https://example.test"
    )

    health = run_source(desc, DataPaths(tmp_path), context(tmp_path), transport=httpx.MockTransport(handler))
    assert health.contract_ok is True
    assert captured["result"] == {"ok": True}


def test_run_source_honors_slower_robots_crawl_delay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Crawl-delay (5s) SLOWER than the descriptor's own politeness.rps (1.0 => 1s interval) must
    be honored: the client actually used by the strategy paces at the slower rate. Asserted via the
    injected sleep seam (real PoliteClient pacing, no wall-clock wait) -- not by introspecting a
    private attribute."""
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_response("User-agent: *\nAllow: /\nCrawl-delay: 5\n")
        return httpx.Response(200, text="ok")

    def strategy(desc, client, cursor, ctx):
        client.get_text("/a")
        client.get_text("/b")  # second real request on the (rebuilt) client -- this is what paces
        return toy_result()

    register("toy-crawl-delay", strategy, monkeypatch)
    desc = SourceDescriptor(
        id="toy-crawl-delay",
        kind="retailer",
        strategy="toy-crawl-delay",
        baseUrl="https://example.test",
        politeness={"rps": 1.0},
    )

    health = run_source(
        desc,
        DataPaths(tmp_path),
        context(tmp_path),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )

    assert health.stats["robots_crawl_delay_applied"] == 5.0
    assert sleeps == [pytest.approx(5.0, abs=0.2)]  # 1/5 rps, not the configured 1/1 rps


def test_run_source_does_not_slow_down_when_robots_crawl_delay_is_faster_than_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reverse case: robots asks for Crawl-delay: 5 (5s), but the descriptor already paces
    slower (rps=0.1 => 10s interval) -- our own, already-more-polite pace must win; nothing is
    rebuilt, and no robots_crawl_delay_applied stat is recorded."""
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_response("User-agent: *\nAllow: /\nCrawl-delay: 5\n")
        return httpx.Response(200, text="ok")

    def strategy(desc, client, cursor, ctx):
        client.get_text("/a")
        client.get_text("/b")
        return toy_result()

    register("toy-crawl-delay-faster", strategy, monkeypatch)
    desc = SourceDescriptor(
        id="toy-crawl-delay-faster",
        kind="retailer",
        strategy="toy-crawl-delay-faster",
        baseUrl="https://example.test",
        politeness={"rps": 0.1},
    )

    health = run_source(
        desc,
        DataPaths(tmp_path),
        context(tmp_path),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )

    assert "robots_crawl_delay_applied" not in health.stats
    # Fix wave 1 (per-request robots checking): the strategy always gets a freshly constructed
    # PoliteClient (with the robots policy attached) built AFTER the robots.txt probe fetch,
    # regardless of whether a crawl-delay override changed its rps -- so pacing starts fresh for
    # strategy requests, same as the slower-crawl-delay test above: /a (first request on the fresh
    # client) doesn't wait, then /b waits the full configured 10s interval.
    assert sleeps == [pytest.approx(10.0, abs=0.2)]
