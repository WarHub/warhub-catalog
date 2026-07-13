"""Polite HTTP client: the single place politeness (UA, pacing, retry) is enforced."""
import time
from typing import Callable

import httpx

UA = "warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)"

_MAX_ATTEMPTS = 3


class FetchError(Exception):
    """Raised when a URL could not be fetched after retries."""

    def __init__(self, url: str, status: int | None) -> None:
        self.url = url
        self.status = status
        super().__init__(f"failed to fetch {url} (status={status})")


class PoliteClient:
    def __init__(
        self,
        base_url: str | None,
        rps: float = 0.5,
        user_agent: str = UA,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._client = httpx.Client(
            base_url=base_url or "",
            headers={"User-Agent": user_agent},
            transport=transport,
        )

    def _pace(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            wait = self._min_interval - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = time.monotonic()

    def _backoff_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return float(2**attempt)

    def _request(
        self,
        url: str,
        params: dict | None = None,
        accept: Callable[[httpx.Response], bool] | None = None,
    ) -> httpx.Response:
        last_status: int | None = None
        for attempt in range(_MAX_ATTEMPTS):
            self._pace()
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError:
                last_status = None
                if attempt < _MAX_ATTEMPTS - 1:
                    self._sleep(self._backoff_delay(attempt, None))
                    continue
                raise FetchError(url, None) from None

            if response.status_code == 429 or response.status_code >= 500:
                last_status = response.status_code
                if attempt < _MAX_ATTEMPTS - 1:
                    self._sleep(self._backoff_delay(attempt, response.headers.get("Retry-After")))
                    continue
                raise FetchError(url, last_status)

            if not (200 <= response.status_code < 300):
                # Any other non-2xx (404, and — per the goblingaming incident — a
                # 301 redirect with follow_redirects off) is not a politeness/transient
                # concern, so surface it immediately via the same FetchError contract
                # instead of leaking an empty/poison body or an httpx.HTTPStatusError
                # to callers. No retry: redirects and client errors won't fix themselves.
                raise FetchError(url, response.status_code)

            if accept is not None and not accept(response):
                # 2xx but the payload failed the caller's validation (e.g. get_json's
                # body doesn't parse as JSON). Observed live: Shopify's edge returning
                # empty-body 200s. Treat like any other transient failure and retry
                # with the same backoff loop before giving up.
                last_status = response.status_code
                if attempt < _MAX_ATTEMPTS - 1:
                    self._sleep(self._backoff_delay(attempt, None))
                    continue
                raise FetchError(url, last_status)

            return response

        raise FetchError(url, last_status)  # unreachable safeguard

    def get_response(self, url: str, params: dict | None = None) -> httpx.Response:
        """Like `get_json`/`get_text` but returns the full response (headers + body).

        `get_text` is a thin wrapper over this so there is exactly one request/retry/pacing
        code path for the raw-response case.

        No body validation happens at this layer: a 2xx response is returned as-is
        regardless of its content (e.g. non-JSON bodies are fine here — only
        `get_json`/`get_json_response` treat an unparseable body as transient).
        """
        return self._request(url, params)

    def get_json_response(self, url: str, params: dict | None = None) -> tuple[object, httpx.Headers]:
        """Like `get_json` but also exposes response headers.

        Added for the woo strategy (Task 8 fix wave 1): WooCommerce's Store API signals total
        result count via the `X-WP-Total` response header, not the JSON body, so pagination
        needs header access -- but `get_response` deliberately skips body validation, and
        enumeration was calling it and then unguarding `response.json()`, bypassing the very
        poison-2xx-body protection `get_json`'s `accept` hook exists to provide (an
        empty/malformed 200 body would crash the run instead of being retried). `get_json` is
        now a thin wrapper over this so there is exactly one retry+accept code path for the
        JSON case; its signature/behavior is unchanged.
        """
        def parses_as_json(response: httpx.Response) -> bool:
            try:
                response.json()
            except ValueError:
                # Poison 2xx body (e.g. an empty response from a misbehaving edge/CDN):
                # never let json.JSONDecodeError escape the client's FetchError contract.
                return False
            return True

        response = self._request(url, params, accept=parses_as_json)
        return response.json(), response.headers

    def get_json(self, url: str, params: dict | None = None) -> object:
        return self.get_json_response(url, params)[0]

    def get_text(self, url: str) -> str:
        return self.get_response(url).text
