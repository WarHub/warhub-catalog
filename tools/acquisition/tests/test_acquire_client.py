"""PoliteClient: pacing, retry-with-backoff, and error surfacing over an injected transport."""
import json

import httpx
import pytest

from warhub_acquisition.acquire.client import UA, FetchError, PoliteClient, RobotsDisallowedError
from warhub_acquisition.acquire.robots import RobotsPolicy


def _policy(robots_txt: str) -> RobotsPolicy:
    """Build a `RobotsPolicy` directly from robots.txt text, without a network fetch -- mirrors
    exactly what `robots.fetch_policy` does on a 200 response."""
    return RobotsPolicy.from_lines(robots_txt.splitlines())


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


# =================================================================================================
# Rate-limit classification + bounded backoff (fix/nightly-429-degradation): a FetchError carries a
# `rate_limited` flag so the CLI can treat an upstream throttle as DEGRADED (exit 3) rather than a
# genuine failure (exit 4). 429 is always rate-limited; a 403 only when it carries a Cloudflare-
# style edge signature; every other status stays a real error. A Retry-After longer than the cap
# makes the client give up (degrade next run) instead of blocking the whole job's timeout.
# =================================================================================================


def test_429_after_retry_exhaustion_is_flagged_rate_limited() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(429, text="slow down")

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json("/products.json")
    assert excinfo.value.status == 429
    assert excinfo.value.rate_limited is True
    assert len(calls) == 3  # retried through all attempts before giving up


def test_5xx_after_retry_exhaustion_is_not_rate_limited() -> None:
    """A persistent 5xx is a genuine upstream fault, not a throttle -- it must NOT be flagged
    rate_limited (so the CLI still fails the run on it), unlike a 429."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json("/flaky")
    assert excinfo.value.status == 503
    assert excinfo.value.rate_limited is False


def test_cloudflare_403_is_flagged_rate_limited() -> None:
    """A 403 fronted by a Cloudflare edge (cf-ray / Server: cloudflare) is a bot/rate block on a
    keyless public endpoint, so it degrades rather than fails. No retry (403 is not in the retry
    set) -- the flag is what matters."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(403, text="Attention Required!", headers={"cf-ray": "8a1b", "Server": "cloudflare"})

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json("/products.json")
    assert excinfo.value.status == 403
    assert excinfo.value.rate_limited is True
    assert len(calls) == 1  # 403 is surfaced immediately, no retry


def test_plain_403_without_edge_signature_is_not_rate_limited() -> None:
    """A 403 with no edge signature is a genuine authorization/origin decision, not a throttle --
    it must stay a real error so a real misconfiguration still fails loudly."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json("/private")
    assert excinfo.value.status == 403
    assert excinfo.value.rate_limited is False


def test_429_retry_after_beyond_cap_gives_up_without_long_sleep() -> None:
    """A Retry-After longer than _MAX_BACKOFF_SECONDS must NOT be slept literally (it would eat the
    job's timeout-minutes and risk a mid-run cancellation with the cursor unsaved). The client
    gives up immediately, flagged rate_limited, so the source degrades and retries next run."""
    calls: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(429, headers={"Retry-After": "3600"}, text="slow down")

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    with pytest.raises(FetchError) as excinfo:
        client.get_json("/products.json")
    assert excinfo.value.status == 429
    assert excinfo.value.rate_limited is True
    assert len(calls) == 1  # gave up after the first attempt -- never retried
    assert sleeps == []  # never slept the hour-long Retry-After, nor any backoff at all


def test_5xx_retry_after_beyond_cap_still_sleeps_and_retries() -> None:
    """The give-up-on-long-Retry-After cap is scoped to 429 ONLY: a 5xx is a genuine upstream
    fault, not a throttle (its FetchError isn't flagged rate_limited, so it would FAIL the run,
    not degrade it) -- it must keep the pre-existing behavior of honoring Retry-After and
    retrying, however long the server asked for. Sleep is injected, so no real wait happens."""
    attempts = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503, headers={"Retry-After": "3600"}, text="unavailable")
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert client.get_json("/flaky") == {"ok": True}
    assert attempts["n"] == 2  # retried despite the hour-long Retry-After -- no early give-up
    assert 3600.0 in sleeps  # and honored the server's requested delay exactly, as before


def test_429_retry_after_within_cap_is_still_honored() -> None:
    """The cap only bites for pathologically long waits: a Retry-After at/under the cap is still
    honored and retried, exactly as before."""
    attempts = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "30"}, text="slow down")
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test",
        rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert client.get_json("/retry-me") == {"ok": True}
    assert attempts["n"] == 2
    assert 30.0 in sleeps  # honored a Retry-After equal to the cap


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


def test_http_cache_serves_second_get_from_disk(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WARHUB_HTTP_CACHE_DIR", str(tmp_path / "cache"))
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"hit": calls["n"]}, headers={"X-WP-Total": "7"})

    client = PoliteClient(
        "https://example.test", transport=httpx.MockTransport(handler), sleep=lambda s: None,
    )
    # first call hits the transport and populates the cache; the second is served from disk --
    # same body AND headers, transport untouched.
    first, h1 = client.get_json_response("/media?page=1")
    second, h2 = client.get_json_response("/media?page=1")
    assert first == second == {"hit": 1}
    assert h1["X-WP-Total"] == h2["X-WP-Total"] == "7"
    assert calls["n"] == 1  # transport called exactly once

    # a DIFFERENT url is a cache miss -> transport called again
    client.get_json_response("/media?page=2")
    assert calls["n"] == 2


def test_http_cache_replays_gzipped_response_without_double_decode(tmp_path, monkeypatch) -> None:
    # httpx hands the client a DECODED body; replaying the origin's Content-Encoding header
    # over it from the cache makes httpx decompress a second time (DecodingError "incorrect
    # header check" -- live-hit 2026-07-23 on Shopify /products.json). The framing headers
    # must be stripped, and a cache written BEFORE the fix (poisoned headers on disk) must
    # also replay cleanly thanks to the read-side strip.
    import gzip as gzip_lib

    monkeypatch.setenv("WARHUB_HTTP_CACHE_DIR", str(tmp_path / "cache"))
    body = json.dumps({"products": [1, 2, 3]}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=gzip_lib.compress(body),
            headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
        )

    client = PoliteClient(
        "https://example.test", transport=httpx.MockTransport(handler), sleep=lambda s: None,
    )
    assert client.get_json("/products.json") == {"products": [1, 2, 3]}  # writes cache
    assert client.get_json("/products.json") == {"products": [1, 2, 3]}  # replays from disk

    # Pre-fix poisoned cache entry: decoded body on disk + content-encoding still in headers.
    cache_dir = tmp_path / "cache"
    for headers_file in cache_dir.glob("*.headers"):
        stored = json.loads(headers_file.read_text("utf-8"))
        stored["content-encoding"] = "gzip"
        headers_file.write_text(json.dumps(stored), "utf-8")
    assert client.get_json("/products.json") == {"products": [1, 2, 3]}


def test_http_cache_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("WARHUB_HTTP_CACHE_DIR", raising=False)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "https://example.test", transport=httpx.MockTransport(handler), sleep=lambda s: None,
    )
    client.get_json("/x")
    client.get_json("/x")
    assert calls["n"] == 2  # no caching -> both calls hit the transport
