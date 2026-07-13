"""Polite HTTP client: the single place politeness (UA, pacing, retry) is enforced."""
import time
from typing import TYPE_CHECKING, Callable

import httpx

if TYPE_CHECKING:
    # Only for the `robots` type hint below -- a runtime import here would cycle (robots.py
    # already imports FetchError/PoliteClient from this module).
    from warhub_acquisition.acquire.robots import RobotsPolicy

UA = "warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)"

_MAX_ATTEMPTS = 3


def _parses_as_json(response: httpx.Response) -> bool:
    try:
        response.json()
    except ValueError:
        # Poison 2xx body (e.g. an empty response from a misbehaving edge/CDN): never let
        # json.JSONDecodeError escape the client's FetchError contract. Shared by every
        # JSON-accepting method (get_json_response, post_json) so there is exactly one
        # "does this 2xx body actually parse" check in the whole client.
        return False
    return True


class FetchError(Exception):
    """Raised when a URL could not be fetched after retries."""

    def __init__(self, url: str, status: int | None) -> None:
        self.url = url
        self.status = status
        super().__init__(f"failed to fetch {url} (status={status})")


class RobotsDisallowedError(Exception):
    """A robots.txt policy disallows fetching a URL. Carries machine-readable details, mirroring
    `SourceContractError`/`FetchError`'s `message, details: dict` shape.

    Raised from two places, deliberately:

    1. `runner.run_source`'s base-URL preflight (BEFORE any strategy runs, checking only
       `descriptor.baseUrl`) -- a fast, loud, early failure that gives a better error before any
       strategy-specific work happens. Its `details` includes `"source"` (the descriptor id),
       since `runner.py` knows which source it's checking.
    2. `PoliteClient._request` (below) -- the REAL guarantee this closes: EVERY outgoing request,
       for every strategy, is checked against whatever policy is attached to the client (see
       `PoliteClient.__init__`'s `robots` parameter), not just the base URL. A site that allows
       `/` but disallows some path a strategy actually fetches (e.g. `/products.json`) is caught
       HERE, even though the base-URL preflight alone would have missed it. Its `details` has no
       `"source"` key -- `PoliteClient` is a generic HTTP client with no notion of which
       descriptor it belongs to.
    """

    def __init__(self, message: str, details: dict) -> None:
        self.details = details
        super().__init__(message)


class PoliteClient:
    def __init__(
        self,
        base_url: str | None,
        rps: float = 0.5,
        user_agent: str = UA,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 30.0,
        robots: "RobotsPolicy | None" = None,
    ) -> None:
        # Explicit timeout, default 30s -- httpx's own default is 5s, which real slow-but-healthy
        # endpoints blow through: Wayback CDX data pages are 200KB+ and took 3-7s+ in live
        # controller probes (2026-07-13), so at 5s every CDX page fetch became three straight
        # transport timeouts -> FetchError(status=None), killing both arc-* sources' first
        # harvest. Descriptors can raise it further via `politeness.timeoutSeconds` (see
        # runner.run_source), e.g. 60 for the arc-* Wayback sources.
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._user_agent = user_agent
        # `None` (the default) means "no robots checking" -- used for tests, for the bare probe
        # client `runner.run_source` uses to fetch robots.txt itself (checking robots against the
        # robots.txt fetch would be nonsensical), and for `ignoreRobots: true` descriptors (see
        # acquire/robots.py's module docstring). When set, EVERY request this client makes is
        # checked in `_request` below -- the per-request guarantee, not just a base-URL preflight.
        self._robots = robots
        self._client = httpx.Client(
            base_url=base_url or "",
            headers={"User-Agent": user_agent},
            transport=transport,
            timeout=timeout,
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
        method: str = "GET",
        json_body: object | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        # Per-request robots.txt enforcement -- BEFORE pacing/sending, and before the retry loop
        # (the target URL doesn't change across retries, so there's nothing to re-check). This is
        # the real compliance guarantee: a base-URL-only preflight (see runner.run_source) can
        # miss a site that allows `/` but disallows a specific path a strategy actually fetches
        # (e.g. `/products.json`); checking HERE, at the single choke point every request already
        # passes through, means every fetched URL is checked, not just the base URL. Cheap: no
        # network call, `build_request` only resolves the final URL (relative `url` merged against
        # `self._client`'s `base_url`, exactly as the real request will resolve it) and
        # `RobotsPolicy.allows` is a pure in-memory check over the already-parsed policy.
        if self._robots is not None:
            full_url = str(self._client.build_request(method, url, params=params).url)
            if not self._robots.allows(full_url, self._user_agent):
                disallow = self._robots.disallowed_by(full_url, self._user_agent)
                token, rule = disallow if disallow is not None else (self._user_agent, None)
                rule_detail = f" ({rule})" if rule else ""
                raise RobotsDisallowedError(
                    f"robots.txt disallows fetching {full_url} for user-agent {token!r}{rule_detail}",
                    {"type": "robots-disallowed", "url": full_url, "userAgent": token, "rule": rule},
                )

        last_status: int | None = None
        for attempt in range(_MAX_ATTEMPTS):
            self._pace()
            try:
                response = self._client.request(method, url, params=params, json=json_body, headers=headers)
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
        response = self._request(url, params, accept=_parses_as_json)
        return response.json(), response.headers

    def get_json(self, url: str, params: dict | None = None) -> object:
        return self.get_json_response(url, params)[0]

    def get_text(self, url: str) -> str:
        return self.get_response(url).text

    def post_json(self, url: str, json_body: object, headers: dict | None = None) -> object:
        """POST a JSON body, return the parsed JSON response body.

        Added for the algolia strategy (Task 9): Algolia's search endpoint is a POST, and needs
        two auth headers per request (`x-algolia-application-id`/`x-algolia-api-key`) rather than
        the client-wide `User-Agent` default. Goes through the exact same `_request`
        retry/pacing/accept machinery every other method uses (same poison-2xx-body protection as
        `get_json_response`, via the shared `_parses_as_json` check) -- no separate request path,
        no separate httpx.Client instance.
        """
        response = self._request(url, method="POST", json_body=json_body, headers=headers, accept=_parses_as_json)
        return response.json()
