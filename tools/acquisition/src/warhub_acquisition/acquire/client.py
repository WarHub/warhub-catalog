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

    def _request(self, url: str, params: dict | None = None) -> httpx.Response:
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

            if response.status_code >= 400:
                # Non-retryable 4xx (e.g. 404): not a politeness/transient concern,
                # so surface it immediately via the same FetchError contract instead
                # of leaking httpx.HTTPStatusError to callers.
                raise FetchError(url, response.status_code)

            return response

        raise FetchError(url, last_status)  # unreachable safeguard

    def get_response(self, url: str, params: dict | None = None) -> httpx.Response:
        """Like `get_json`/`get_text` but returns the full response (headers + body).

        Added for the woo strategy (Task 8): WooCommerce's Store API signals total result count
        via the `X-WP-Total` response header, not the JSON body, so pagination needs header
        access that `get_json`'s `object`-only return can't provide. `get_json`/`get_text` are
        now thin wrappers over this so there is exactly one request/retry/pacing code path;
        neither existing method's signature or behavior changed.
        """
        return self._request(url, params)

    def get_json(self, url: str, params: dict | None = None) -> object:
        return self.get_response(url, params).json()

    def get_text(self, url: str) -> str:
        return self.get_response(url).text
