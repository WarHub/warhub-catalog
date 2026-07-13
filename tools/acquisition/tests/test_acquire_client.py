"""PoliteClient: pacing, retry-with-backoff, and error surfacing over an injected transport."""
import json
import urllib.robotparser

import httpx
import pytest

from warhub_acquisition.acquire.client import UA, FetchError, PoliteClient, RobotsDisallowedError
from warhub_acquisition.acquire.robots import RobotsPolicy


def _policy(robots_txt: str) -> RobotsPolicy:
    """Build a `RobotsPolicy` directly from robots.txt text, without a network fetch -- mirrors
    exactly what `robots.fetch_policy` does on a 200 response (`RobotFileParser().parse(...)`)."""
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(robots_txt.splitlines())
    return RobotsPolicy(parser)


def test_user_agent_constant() -> None:
    assert UA == "warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)"


def test_get_json_sends_user_agent_and_returns_parsed_body() -> None:
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers["user-agent"] = request.headers.get("user-agent")
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    assert client.get_json("/things.json") == {"ok": True}
    assert seen_headers["user-agent"] == UA


def test_get_response_exposes_headers_and_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, headers={"X-WP-Total": "42"})

    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    response = client.get_response("/things.json")
    assert response.json() == {"ok": True}
    assert response.headers["X-WP-Total"] == "42"


def test_get_text_returns_body_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="hello world")

    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    assert client.get_text("/page.html") == "hello world"


def test_pacing_sleeps_for_min_interval_between_requests() -> None:
    calls: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = PoliteClient(
        "https://example.test",
        rps=0.5,
        transport=httpx.MockTransport(handler),
        sleep=calls.append,
    )
    client.get_json("/a")
    client.get_json("/b")
    # first request paces nothing (no prior request); second must wait ~1/rps = 2s
    assert len(calls) == 1
    assert calls[0] == pytest.approx(2.0, abs=0.2)


def test_pacing_scales_with_rps() -> None:
    calls: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = PoliteClient(
        "https://example.test",
        rps=2.0,
        transport=httpx.MockTransport(handler),
        sleep=calls.append,
    )
    client.get_json("/a")
    client.get_json("/b")
    assert calls[0] == pytest.approx(0.5, abs=0.1)


def test_429_with_retry_after_is_retried_then_succeeds() -> None:
    attempts = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, text="slow down")
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        rps=1000,  # keep pacing delay negligible for this test
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert client.get_json("/retry-me") == {"ok": True}
    assert attempts["n"] == 2
    assert 3.0 in sleeps  # honored the Retry-After header value


def test_5xx_retried_with_exponential_backoff_then_succeeds() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    assert client.get_json("/flaky") == {"ok": True}
    assert attempts["n"] == 3


def test_persistent_failures_raise_fetch_error_after_retries() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(500, text="down")

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json("/always-down")
    assert attempts["n"] == 3
    assert excinfo.value.url.endswith("/always-down")
    assert excinfo.value.status == 500


def test_transport_error_retried_then_raises_fetch_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json("/unreachable")
    assert excinfo.value.status is None


def test_non_retryable_4xx_raises_fetch_error_without_retry() -> None:
    """A 404 is not a politeness/transient concern: it must surface as the single
    FetchError contract immediately, with no retry and no leaked httpx exception."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(404, text="not found")

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json("/missing")
    assert excinfo.value.status == 404
    assert excinfo.value.url.endswith("/missing")
    assert len(calls) == 1  # no retry for a non-retryable 4xx


def test_3xx_redirect_raises_fetch_error_without_retry() -> None:
    """The goblingaming incident: an apex host 301-redirected detail URLs with an
    empty body. follow_redirects stays off, so this must surface immediately as
    FetchError(url, 301) — never leak the empty body into json.loads."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(301, headers={"Location": "https://example.test/moved"}, text="")

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json("/detail")
    assert excinfo.value.status == 301
    assert len(calls) == 1  # no retry for a redirect


def test_get_json_empty_body_200_retried_then_raises_fetch_error() -> None:
    """A 2xx with an unparseable (e.g. empty) body is transient, not an immediate
    failure: retry with the same backoff loop, then raise FetchError(url, 200)."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="")

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json("/empty")
    assert len(calls) == 3  # retried through all attempts
    assert excinfo.value.status == 200


def test_get_json_empty_body_then_valid_json_succeeds_on_retry() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(200, text="")
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    assert client.get_json("/flaky-body") == {"ok": True}
    assert attempts["n"] == 2


def test_get_response_does_not_validate_non_json_2xx_body() -> None:
    """get_response has no JSON-parsing concept: a 2xx with a non-JSON body (e.g.
    empty, or plain text) is returned as-is, unlike get_json."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="")

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    response = client.get_response("/not-json")
    assert response.status_code == 200
    assert response.text == ""
    assert len(calls) == 1  # no retry: get_response never inspects the body


def test_get_json_response_returns_parsed_body_and_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, headers={"X-WP-Total": "42"})

    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    body, headers = client.get_json_response("/things.json")
    assert body == {"ok": True}
    assert headers["X-WP-Total"] == "42"


def test_get_json_response_empty_body_200_retried_then_raises_fetch_error() -> None:
    """The woo strategy used to call get_response + unguarded response.json() for header
    access, bypassing get_json's poison-2xx-body protection entirely: an empty/malformed
    body on a real pagination endpoint would crash the run instead of being retried.
    get_json_response must share the exact same retry+accept path as get_json."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="", headers={"X-WP-Total": "2"})

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json_response("/wp-json/wc/store/products")
    assert len(calls) == 3  # retried through all attempts, same as get_json
    assert excinfo.value.status == 200


def test_post_json_sends_method_body_and_extra_headers() -> None:
    """Added for the algolia strategy (Task 9): Algolia's search endpoint is a POST with a JSON
    body and two auth headers that aren't part of the client's default headers."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        seen["x-algolia-application-id"] = request.headers.get("x-algolia-application-id")
        seen["x-algolia-api-key"] = request.headers.get("x-algolia-api-key")
        seen["user-agent"] = request.headers.get("user-agent")
        return httpx.Response(200, json={"hits": [], "nbPages": 1})

    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    body = client.post_json(
        "https://m5ziqznq2h-dsn.algolia.net/1/indexes/prod-lazarus-product-en-gb/query",
        {"query": "", "hitsPerPage": 100, "page": 0, "filters": "productType:miniatureKit"},
        headers={"x-algolia-application-id": "M5ZIQZNQ2H", "x-algolia-api-key": "secret"},
    )
    assert body == {"hits": [], "nbPages": 1}
    assert seen["method"] == "POST"
    assert seen["body"] == {"query": "", "hitsPerPage": 100, "page": 0, "filters": "productType:miniatureKit"}
    assert seen["x-algolia-application-id"] == "M5ZIQZNQ2H"
    assert seen["x-algolia-api-key"] == "secret"
    # per-request headers add to, not replace, the client's own default UA header
    assert seen["user-agent"] == UA


def test_post_json_empty_body_200_retried_then_raises_fetch_error() -> None:
    """post_json shares the same poison-2xx-body retry/accept path as get_json_response."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="")

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.post_json("/query", {"query": ""})
    assert len(calls) == 3
    assert excinfo.value.status == 200


def test_5xx_backoff_durations_follow_exponential_formula() -> None:
    """The backoff delay per attempt is 2**attempt (no Retry-After header present)."""
    attempts = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        rps=0,  # disable pacing sleeps so only backoff sleeps are captured
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert client.get_json("/flaky") == {"ok": True}
    assert attempts["n"] == 3
    assert sleeps == [1.0, 2.0]  # 2**0, 2**1 for the first two (failed) attempts


def test_default_timeout_is_30_seconds() -> None:
    """Fix wave 2 (live-run defect, 2026-07-13): httpx's own 5s default timed out on real Wayback
    CDX data pages (200KB+, 3-7s+ observed live in controller probes) -- three straight transport
    timeouts produced the observed `FetchError(status=None)` and killed both arc-* sources'
    first harvest. PoliteClient now sets an explicit 30s default on its httpx.Client."""
    client = PoliteClient("https://example.test", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert client._client.timeout == httpx.Timeout(30.0)


def test_timeout_constructor_param_overrides_default() -> None:
    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        timeout=60.0,
    )
    assert client._client.timeout == httpx.Timeout(60.0)


# =================================================================================================
# Per-request robots enforcement (fix wave 1, 2026-07-13): `PoliteClient._request` is the single
# choke point every request passes through, so this is where robots.txt is actually enforced now --
# not just once against `descriptor.baseUrl` (see runner.py's preflight, which stays as a fast
# early check but is no longer the real guarantee). See acquire/robots.py's module docstring for
# the full rationale.
# =================================================================================================


def test_robots_disallowed_path_blocked_even_though_root_is_allowed() -> None:
    """THE HOLE THIS FIX CLOSES (headline test): a base-URL-only preflight checking just '/' would
    see this policy as fully permissive -- '/' is explicitly allowed -- but '/products.json' is
    specifically disallowed. A client carrying this policy must still refuse to fetch it."""
    policy = _policy("User-agent: *\nAllow: /\nDisallow: /products.json\n")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
        robots=policy,
    )

    with pytest.raises(RobotsDisallowedError) as excinfo:
        client.get_json("/products.json")

    assert excinfo.value.details["type"] == "robots-disallowed"
    assert excinfo.value.details["url"] == "https://example.test/products.json"
    assert excinfo.value.details["userAgent"] == UA
    assert excinfo.value.details["rule"] == "Disallow: /products.json"
    # PoliteClient has no notion of which descriptor/source it belongs to -- unlike the base-URL
    # preflight's RobotsDisallowedError (raised in runner.py), this one never has a "source" key.
    assert "source" not in excinfo.value.details
    assert calls == []  # never reached the network -- checked BEFORE pacing/sending


def test_robots_allowed_path_succeeds_under_the_same_disallowing_policy() -> None:
    """Sanity check paired with the headline test above: the SAME policy that blocks
    '/products.json' still lets an allowed path through normally -- the check is per-URL, not a
    blanket block once any policy is attached."""
    policy = _policy("User-agent: *\nAllow: /\nDisallow: /products.json\n")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
        robots=policy,
    )
    assert client.get_json("/catalog.json") == {"ok": True}


def test_robots_none_default_means_no_per_request_checking() -> None:
    """`robots=None` (the default -- used for tests and for `ignoreRobots: true` descriptors, see
    runner.run_source) means every request proceeds regardless of any policy content: no policy is
    ever consulted."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    assert client.get_json("/anything") == {"ok": True}


def test_robots_explicit_none_also_means_no_per_request_checking() -> None:
    """Same as above but passing `robots=None` explicitly -- distinguishes 'default omitted' from
    'explicitly no policy' at the call site, both must behave identically."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
        robots=None,
    )
    assert client.get_json("/anything") == {"ok": True}


def test_robots_check_uses_the_clients_own_user_agent() -> None:
    """The per-request check is run against `self._user_agent` (the UA this client actually
    sends), not a hardcoded module constant -- matches robots.py's module docstring point 1."""
    policy = _policy("User-agent: custom-bot\nDisallow: /blocked\n")

    client = PoliteClient(
        "https://example.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})),
        sleep=lambda seconds: None,
        user_agent="custom-bot",
        robots=policy,
    )
    with pytest.raises(RobotsDisallowedError) as excinfo:
        client.get_json("/blocked")
    assert excinfo.value.details["userAgent"] == "custom-bot"
