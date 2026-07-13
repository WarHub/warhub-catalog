"""PoliteClient: pacing, retry-with-backoff, and error surfacing over an injected transport."""
import httpx
import pytest

from warhub_acquisition.acquire.client import UA, FetchError, PoliteClient


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
