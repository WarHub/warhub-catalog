"""Polite HTTP client: the single place politeness (UA, pacing, retry) is enforced."""
import hashlib
import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import httpx

if TYPE_CHECKING:
    # Only for the `robots` type hint below -- a runtime import here would cycle (robots.py
    # already imports FetchError/PoliteClient from this module).
    from warhub_acquisition.acquire.robots import RobotsPolicy

UA = "warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)"

_MAX_ATTEMPTS = 3

# Ceiling on how long a single request will block on a RATE-LIMIT (429) backoff -- and 429 ONLY.
# A 429 can carry a `Retry-After` of minutes; sleeping that literally would let ONE throttled
# endpoint consume the whole job's `timeout-minutes` budget and -- on a GitHub runner -- get the
# source cancelled mid-run with its cursor never saved (the exact July-2026 group-A1 degradation).
# When the honored delay would exceed this cap we stop retrying rather than sleep for minutes or
# retry sooner than the site asked (both would be wrong): the request fails, the source is
# recorded as rate-limited/degraded, and it retries cleanly on the next run. A 5xx is deliberately
# NOT subject to this cap: it's a genuine upstream fault, not a throttle -- its FetchError isn't
# flagged rate_limited (it would fail the run, not degrade it), so giving up early there would
# only narrow the pre-existing 5xx honor-Retry-After-and-retry resilience for no benefit. Pacing
# (`_pace`) still governs how fast we ever send -- this only bounds how long we WAIT before giving
# up. The exponential fallback (`2**attempt`) tops out at 2s and never trips this cap; only a
# server-supplied `Retry-After` can.
_MAX_BACKOFF_SECONDS = 30.0


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


def _looks_like_edge_rate_block(response: httpx.Response) -> bool:
    """True when a non-2xx response looks like a Cloudflare-style edge/anti-bot block rather than
    an origin decision. Used only to classify a 403: the public product endpoints this bot fetches
    never require authentication, so a 403 fronted by Cloudflare is a bot-detection/rate wall
    (throttle us -> treat as rate-limited/degraded, retry next run), whereas a 403 with no edge
    signature is left as a genuine error so a real misconfiguration still fails loudly. `cf-ray`
    is present on every Cloudflare-served response (including its challenge/block pages), and a
    `Server: cloudflare` header is the other unambiguous tell."""
    if "cloudflare" in response.headers.get("Server", "").lower():
        return True
    return "cf-ray" in response.headers


class FetchError(Exception):
    """Raised when a URL could not be fetched after retries.

    `rate_limited` distinguishes an upstream throttle/anti-bot block (which the pipeline treats as
    a DEGRADED, retry-next-run condition -- see cli._run_acquire / acquire/health.py) from a
    genuine fault. A 429 is ALWAYS a rate-limit; a 403 only counts as one when the caller passes
    `rate_limited=True` (PoliteClient._request does so on an edge-block signature -- see
    `_looks_like_edge_rate_block`); every other status defaults to a real error.
    """

    def __init__(self, url: str, status: int | None, *, rate_limited: bool | None = None) -> None:
        self.url = url
        self.status = status
        self.rate_limited = (status == 429) if rate_limited is None else rate_limited
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
        # Opt-in on-disk GET cache for LOCAL iteration: set WARHUB_HTTP_CACHE_DIR to a directory and
        # every 200 GET (media-API pages, the ~10 MB of trade workbooks, ...) is served from disk on
        # re-runs instead of re-downloaded. Keyed by the fully-resolved URL (params included, request
        # headers -- e.g. the rotating X-WP-Nonce -- excluded, since they don't change the response
        # body). Never expires: delete the directory to refresh. CI never sets the var, so CI always
        # fetches live. Off by default -- a no-op unless the env var is present.
        cache_dir = os.environ.get("WARHUB_HTTP_CACHE_DIR") or None
        self._cache_dir = Path(cache_dir) if cache_dir else None
        if self._cache_dir is not None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_paths(self, method: str, url: str, params: dict | None) -> tuple[Path, Path]:
        full = str(self._client.build_request(method, url, params=params).url)
        digest = hashlib.sha256(f"{method} {full}".encode()).hexdigest()
        assert self._cache_dir is not None
        base = self._cache_dir / digest
        return base, base.with_suffix(".headers")

    def _cache_read(self, method: str, url: str, params: dict | None) -> "httpx.Response | None":
        if self._cache_dir is None:
            return None
        body_path, headers_path = self._cache_paths(method, url, params)
        if not body_path.exists():
            return None
        headers = json.loads(headers_path.read_text("utf-8")) if headers_path.exists() else {}
        return httpx.Response(
            200, content=body_path.read_bytes(), headers=headers,
            request=self._client.build_request(method, url, params=params),
        )

    def _cache_write(self, method: str, url: str, params: dict | None, response: httpx.Response) -> None:
        if self._cache_dir is None or response.status_code != 200:
            return
        body_path, headers_path = self._cache_paths(method, url, params)
        body_path.write_bytes(response.content)
        headers_path.write_text(json.dumps(dict(response.headers)), "utf-8")

    @property
    def robots(self) -> "RobotsPolicy | None":
        """The `RobotsPolicy` attached to this client (`None` when robots checking is off -- see
        the constructor's `robots` parameter docs). Public on purpose: `_request` below is the
        checkpoint for every request THIS client makes via httpx, but a strategy that fetches
        through a different transport entirely (`playwright_wp.py`'s Chromium `page.goto`, which
        never calls `_request` -- see `acquire/robots.py`'s module docstring for the full story)
        still receives this same `PoliteClient` per the `Strategy` call signature and needs a way
        to enforce the identical policy itself, without a second robots.txt fetch."""
        return self._robots

    @property
    def user_agent(self) -> str:
        """Public counterpart to `robots` above -- a non-httpx strategy checking `robots.allows`
        itself needs the exact UA string this client would have sent, not a hardcoded guess."""
        return self._user_agent

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
                    delay = self._backoff_delay(attempt, response.headers.get("Retry-After"))
                    if response.status_code == 429 and delay > _MAX_BACKOFF_SECONDS:
                        # The rate-limiter asked us to wait longer than we're willing to block the
                        # whole run for (see _MAX_BACKOFF_SECONDS): stop now rather than sleep for
                        # minutes. FetchError(429) is flagged rate_limited, so the source degrades
                        # cleanly and retries next run instead of eating the job timeout. 429-only
                        # ON PURPOSE: a 5xx keeps its pre-existing honor-Retry-After-and-retry
                        # behavior -- see the _MAX_BACKOFF_SECONDS comment above.
                        raise FetchError(url, last_status)
                    self._sleep(delay)
                    continue
                raise FetchError(url, last_status)

            if not (200 <= response.status_code < 300):
                # Any other non-2xx (404, and — per the goblingaming incident — a
                # 301 redirect with follow_redirects off) is not a politeness/transient
                # concern, so surface it immediately via the same FetchError contract
                # instead of leaking an empty/poison body or an httpx.HTTPStatusError
                # to callers. No retry: redirects and client errors won't fix themselves.
                # Exception: a Cloudflare-style 403 is an edge rate/anti-bot block, not an origin
                # decision, so flag it rate_limited (-> degraded, retry next run) -- but only when
                # the response actually carries an edge signature, so a genuine 403 still fails.
                rate_limited = response.status_code == 403 and _looks_like_edge_rate_block(response)
                raise FetchError(url, response.status_code, rate_limited=rate_limited)

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

    def get_response(
        self, url: str, params: dict | None = None, headers: dict | None = None
    ) -> httpx.Response:
        """Like `get_json`/`get_text` but returns the full response (headers + body).

        `get_text` is a thin wrapper over this so there is exactly one request/retry/pacing
        code path for the raw-response case.

        No body validation happens at this layer: a 2xx response is returned as-is
        regardless of its content (e.g. non-JSON bodies are fine here — only
        `get_json`/`get_json_response` treat an unparseable body as transient).

        `headers` mirrors `post_json`'s parameter of the same name: per-request extra headers
        merged over the client's own (added for the gw-trade-sheets strategy, whose media API
        requires a public, rotating `X-WP-Nonce` header on GET -- see that module's docstring).
        """
        cached = self._cache_read("GET", url, params)
        if cached is not None:
            return cached
        response = self._request(url, params, headers=headers)
        self._cache_write("GET", url, params, response)
        return response

    def get_json_response(
        self, url: str, params: dict | None = None, headers: dict | None = None
    ) -> tuple[object, httpx.Headers]:
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
        cached = self._cache_read("GET", url, params)
        if cached is not None:
            return cached.json(), cached.headers
        response = self._request(url, params, accept=_parses_as_json, headers=headers)
        self._cache_write("GET", url, params, response)
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
