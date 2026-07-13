r"""Robots.txt compliance preflight: fetch and enforce a source's published crawl policy BEFORE
any strategy runs. This closes a real gap -- the pipeline harvested 13+ sources for two plans and
never once checked robots.txt (a controller audit, 2026-07-13, found every current source happens
to permit us, but that was luck plus memory, not enforcement -- one candidate source,
fantasywelt.de, explicitly disallows our crawler by name).

**Fetching (`fetch_policy`)**: always goes THROUGH the caller's `PoliteClient` -- paced, retried,
UA-bearing, exactly like every other request this codebase makes. `GET <baseUrl>/robots.txt`:

- 404/410 -> permissive (`RobotsPolicy` wrapping `None`): "no restrictions published" is an
  explicit, positive outcome, not a fallback-on-error. Per RFC 9309 sec 2.3.1.3, these two codes
  are the ones a well-behaved crawler treats as "no robots.txt exists."
- Any other non-2xx (5xx after `PoliteClient`'s own retries, a transport failure, or anything else
  -- 401/403/3xx/etc.) -> `RobotsFetchError` (FAIL LOUD). We cannot prove we're allowed, and a
  site that is actively erroring or redirecting on its own robots.txt is not the same thing as a
  site that has published "no restrictions" -- silently treating that as permission would defeat
  the entire point of this preflight. `PoliteClient` never follows redirects (see client.py), so a
  3xx here is not resolved automatically; if a source's `baseUrl` genuinely isn't where its
  robots.txt lives (see `politeness.ignoreRobots` on `SourceDescriptor`), that's a descriptor-level
  fix, not something this module should paper over.
- 200 -> parsed via stdlib `urllib.robotparser.RobotFileParser.parse()`.

**Checked tokens (`RobotsPolicy.allows`)**: every call checks THREE user-agent tokens against the
parsed policy, and a `Disallow` under ANY of them makes the URL not-allowed:

1. The full outgoing `User-Agent` string this client actually sends (`client.UA` by default --
   `"warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)"`).
2. The bare product token (`"warhub-catalog-bot"`) -- robots.txt authors conventionally name the
   product, not a full UA-with-URL-comment string (stdlib's own `Entry.applies_to` already reduces
   any UA to its pre-`/` token before matching, so in practice this is redundant with (1) today,
   but it's cheap, explicit, and future-proof against a UA format change).
3. `"ClaudeBot"` -- a DELIBERATE, CONSERVATIVE policy choice, not an accident. Cloudflare's AI
   Crawl Control and a growing set of publishers name `ClaudeBot` specifically as how they opt out
   of Anthropic-affiliated crawling (see Cloudflare's AI Crawl Control docs). This tool runs under
   Claude Code / the Claude Agent SDK; a site that has gone to the trouble of writing a
   `User-agent: ClaudeBot` block is expressing "no AI-agent crawling from Anthropic's stack" even
   though our own product string never says "Claude" anywhere. We treat that as disallowing
   OURSELVES too, rather than exploiting the UA-string mismatch as a loophole. This can only ever
   make the check MORE conservative (fewer allows, never more) -- it never grants access a plain
   product-token check would have denied.

**Crawl-delay (`RobotsPolicy.crawl_delay`)**: a thin wrapper over
`RobotFileParser.crawl_delay(user_agent)` (stdlib already implements the same entries/default-entry
matching `can_fetch` uses). The runner honors it when it asks for SLOWER pacing than the
descriptor's own `politeness.rps` -- a site publishing `Crawl-delay: 10` is asking us to back off,
and `politeness.rps` is a ceiling we impose on OURSELVES, never a floor we're entitled to regardless
of what the site asks for.

**Escape hatch**: `descriptor.politeness["ignoreRobots"]` (default `False`, wired in
`runner.run_source`) skips this preflight entirely for sources where `baseUrl` genuinely isn't the
real fetch target (e.g. an Algolia or AppSync API host reached via an absolute URL baked into the
strategy, unrelated to the marketing-site `baseUrl` the descriptor happens to declare) or where
robots.txt is otherwise not the right compliance mechanism. It must be set explicitly per
descriptor, with a comment citing why -- see `data/catalog/sources/mfr-gw-algolia.yaml` and
`mfr-corvus-belli.yaml` for the two real cases this repo currently needs it for.
"""
import urllib.robotparser
from urllib.parse import quote, urlparse, urlunparse

from warhub_acquisition.acquire.client import FetchError, PoliteClient

# The bare product token robots.txt authors are most likely to write, independent of our UA
# string's exact format (see module docstring point 2).
PRODUCT_TOKEN = "warhub-catalog-bot"

# Deliberate policy choice -- see module docstring point 3.
CLAUDEBOT_TOKEN = "ClaudeBot"

# 404/410 are the only statuses RFC 9309 sec 2.3.1.3 treats as "no robots.txt published" -- every
# other non-2xx is a FetchError that propagates uncaught (fail loud).
_PERMISSIVE_STATUSES = frozenset({404, 410})

ROBOTS_PATH = "/robots.txt"


class RobotsFetchError(Exception):
    """robots.txt could not be retrieved with enough confidence to proceed: a 5xx (after
    PoliteClient's own retries), a transport failure, or any other non-2xx status that isn't one of
    the two "no robots.txt published" codes (404/410). We cannot prove we're allowed to crawl, so
    this fails loud rather than silently defaulting to permissive."""

    def __init__(self, base_url: str, cause: FetchError) -> None:
        self.base_url = base_url
        self.cause = cause
        super().__init__(
            f"could not fetch {base_url.rstrip('/')}{ROBOTS_PATH} "
            f"(status={cause.status}): refusing to assume permission"
        )


def _disallowing_rule(parser: urllib.robotparser.RobotFileParser, user_agent: str, path: str) -> str | None:
    """Best-effort lookup of the specific rule that disallowed `path` for `user_agent`, for
    human-readable error messages only -- `RobotFileParser.can_fetch()` only ever returns a bool.
    Uses `RobotFileParser._find_entry` (the same group-lookup helper `can_fetch`/`crawl_delay`
    themselves call internally -- CPython's robotparser group-matching has changed shape across
    versions, e.g. 3.14 rewrote it entirely per RFC 9309, so this defers to stdlib's own canonical
    lookup rather than re-deriving it) to find the applicable rule group, then picks the
    longest-matching `Disallow` ruleline within it (RFC 9309's own "most specific rule wins" tie-
    break). Returns `None` if no specific textual rule could be identified, or on any stdlib
    version where `_find_entry` doesn't exist -- the URL is still disallowed either way; this is
    purely diagnostic detail for the exception message, never used for the allow/disallow decision
    itself (that's `RobotFileParser.can_fetch`, called directly in `allows`/`disallowed_by`)."""
    if getattr(parser, "disallow_all", False):
        return "Disallow: / (robots.txt signaled the entire site is off-limits)"

    find_entry = getattr(parser, "_find_entry", None)
    entry = find_entry(user_agent) if find_entry is not None else None
    if entry is None:
        return None

    best_match = 0
    best_rule: str | None = None
    for line in entry.rulelines:
        match_length = line.applies_to(path)
        if match_length and not line.allowance and match_length >= best_match:
            best_match = match_length
            best_rule = f"Disallow: {line.path}"
    return best_rule


class RobotsPolicy:
    """Wraps a parsed (or absent) `urllib.robotparser.RobotFileParser`. `parser is None` means
    "no robots.txt was published" (404/410) -- an explicit permissive policy, not a null object
    standing in for "unknown"."""

    def __init__(self, parser: urllib.robotparser.RobotFileParser | None) -> None:
        self._parser = parser

    @property
    def is_permissive(self) -> bool:
        """True when no robots.txt was published at all (see module docstring)."""
        return self._parser is None

    def _tokens(self, user_agent: str) -> tuple[str, ...]:
        # See module docstring: full UA string, bare product token, and ClaudeBot -- ANY
        # disallowing any of the three makes the URL not-allowed.
        return (user_agent, PRODUCT_TOKEN, CLAUDEBOT_TOKEN)

    def allows(self, url: str, user_agent: str) -> bool:
        if self._parser is None:
            return True
        return all(self._parser.can_fetch(token, url) for token in self._tokens(user_agent))

    def disallowed_by(self, url: str, user_agent: str) -> tuple[str, str | None] | None:
        """Returns `(token, rule_or_None)` for the FIRST checked token (in `allows`'s own order)
        that disallows `url`, or `None` if every token is allowed. Used by callers (`runner.py`) to
        build a specific `RobotsDisallowedError` message -- `allows()` alone only exposes the bool.
        """
        if self._parser is None:
            return None
        parsed = urlparse(url)
        path = quote(urlunparse(("", "", parsed.path, parsed.params, parsed.query, ""))) or "/"
        for token in self._tokens(user_agent):
            if not self._parser.can_fetch(token, url):
                return token, _disallowing_rule(self._parser, token, path)
        return None

    def crawl_delay(self, user_agent: str) -> float | None:
        if self._parser is None:
            return None
        delay = self._parser.crawl_delay(user_agent)
        return float(delay) if delay is not None else None


def fetch_policy(client: PoliteClient, base_url: str) -> RobotsPolicy:
    """Fetches `<baseUrl>/robots.txt` through `client` (paced/retried/UA-bearing) and returns the
    resulting policy. See module docstring for the 404/410 (permissive) vs. everything-else
    (`RobotsFetchError`, fail loud) vs. 200 (parse) split."""
    try:
        response = client.get_response(ROBOTS_PATH)
    except FetchError as exc:
        if exc.status in _PERMISSIVE_STATUSES:
            return RobotsPolicy(None)
        raise RobotsFetchError(base_url, exc) from exc

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(response.text.splitlines())
    return RobotsPolicy(parser)
