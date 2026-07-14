r"""Robots.txt compliance: fetch a source's published crawl policy and enforce it on EVERY request
a strategy makes, not just its `baseUrl`. This closes a real gap -- the pipeline harvested 13+
sources for two plans and never once checked robots.txt (a controller audit, 2026-07-13, found
every current source happens to permit us, but that was luck plus memory, not enforcement -- one
candidate source, fantasywelt.de, explicitly disallows our crawler by name).

**Two enforcement points, one policy (fix wave 1, 2026-07-13)**: the FIRST version of this module
only checked `descriptor.baseUrl` once, in `runner.run_source`, before any strategy ran -- a real
compliance hole, since a site can publish a robots.txt that allows `/` (the site root, i.e.
`baseUrl`) while disallowing a specific path a strategy actually fetches (e.g. `/products.json` or
`/search`). Nothing in this repo's current sources hit that hole (verified live), but nothing
structurally prevented a future one from doing so. The fix moved enforcement into
`PoliteClient._request` (`acquire/client.py`) -- the choke point every HTTPX-based request from
every strategy passes through -- so the guarantee became "every fetched URL is checked, base URL
or not" for those strategies. The two checks work together, not redundantly:

1. `runner.run_source`'s base-URL preflight (unchanged in spirit, still runs first): a fast, loud,
   early failure -- if `baseUrl` itself is disallowed, we know before any strategy-specific work
   (enumeration, pagination, detail fetches) starts, with a clear "this source's root is blocked"
   error rather than whatever the strategy's first fetch happens to be.
2. `PoliteClient._request`'s per-request check: the `RobotsPolicy` fetched by the preflight is
   attached to the strategy's `PoliteClient` (`robots=` constructor param) and re-checked against
   the fully-resolved URL of every single subsequent request made THROUGH that client, base URL or
   not.

**NOT every strategy fetches through `PoliteClient` (fix wave 3, Important #2 correction)**: point
2 above is not, in fact, a universal "every request from every strategy" guarantee -- it only
covers requests that go through `PoliteClient._request`. `strategies/playwright_wp.py` (CMON) is
the one exception: it fetches every URL via a Chromium `page.goto` (`_playwright_browser.py`),
which never calls `PoliteClient._request` at all (see that module's docstring -- CMON's
Cloudflare wall requires a real, JS-executing browser, not httpx). An earlier version of this
docstring claimed `PoliteClient` was "the single choke point EVERY request from EVERY strategy
already passes through," which was simply false for that strategy: point 1's base-URL preflight
still ran for it (so a disallowed `baseUrl` was still caught), but every subsequent sitemap/line/
product URL it fetched via `page.goto` went completely unchecked. Fixed by giving
`playwright_wp.py`'s own fetch helper (`_fetch`, wired through `_run`) the same check
`PoliteClient._request` does, reading the identical `RobotsPolicy` off `client.robots` /
`client.user_agent` (both public read-only properties on `PoliteClient`, added for exactly this
cross-transport reuse -- see that module's docstring's "Robots.txt THROUGH THE BROWSER too"
section) rather than re-fetching robots.txt a second time. The accurate claim, going forward: every
URL fetched by every strategy IS checked against the source's `RobotsPolicy` -- but the checkpoint
that does it is strategy-specific whenever a strategy's transport isn't `PoliteClient` itself, not
a single shared choke point.

**Why a self-contained matcher, not `urllib.robotparser` (fix wave 4, 2026-07-15)**: the first
implementation delegated the allow/disallow decision to stdlib's
`urllib.robotparser.RobotFileParser.can_fetch()`, and the diagnostic rule lookup to its private
`_find_entry`. That was a portability trap. CPython rewrote `robotparser` for RFC 9309 in 3.14: on
3.14+, `can_fetch` uses **longest-match-wins** (so `Allow: /` + `Disallow: /products.json` blocks
`/products.json`); on 3.12/3.13 the old parser used **first-matching-line-in-file-order** (so the
leading `Allow: /` won and `/products.json` was permitted). Our `requires-python` floor is 3.12,
CI runs 3.12.3, dev ran 3.14 -- so the identical policy silently enforced DIFFERENTLY depending on
interpreter, and the per-path hole this whole module exists to close was reopened on exactly the
version CI (and any 3.12 deployment) uses. `_find_entry` compounded it: it only exists on 3.14, so
the human-readable rule in every disallow error came back `None` on 3.12. This module now parses
robots.txt itself and applies RFC 9309 group selection + longest-match resolution directly, so the
decision is identical on every supported interpreter. See `_Group` / `_match_rule` below.

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
- 200 -> parsed by `_parse_groups` into RFC 9309 user-agent groups.

**Checked tokens (`RobotsPolicy.allows`)**: every call checks THREE user-agent tokens against the
parsed policy, and a `Disallow` under ANY of them makes the URL not-allowed:

1. The full outgoing `User-Agent` string this client actually sends (`client.UA` by default --
   `"warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)"`).
2. The bare product token (`"warhub-catalog-bot"`) -- robots.txt authors conventionally name the
   product, not a full UA-with-URL-comment string. Group selection reduces any UA to its pre-`/`
   token before matching (see `_select_group`), so in practice this is redundant with (1) today,
   but it's cheap, explicit, and future-proof against a UA format change.
3. `"ClaudeBot"` -- a DELIBERATE, CONSERVATIVE policy choice, not an accident. Cloudflare's AI
   Crawl Control and a growing set of publishers name `ClaudeBot` specifically as how they opt out
   of Anthropic-affiliated crawling (see Cloudflare's AI Crawl Control docs). This tool runs under
   Claude Code / the Claude Agent SDK; a site that has gone to the trouble of writing a
   `User-agent: ClaudeBot` block is expressing "no AI-agent crawling from Anthropic's stack" even
   though our own product string never says "Claude" anywhere. We treat that as disallowing
   OURSELVES too, rather than exploiting the UA-string mismatch as a loophole. This can only ever
   make the check MORE conservative (fewer allows, never more) -- it never grants access a plain
   product-token check would have denied.

**Crawl-delay (`RobotsPolicy.crawl_delay`)**: the most-conservative (largest) `Crawl-delay` across
the same three tokens `allows` checks. The runner honors it when it asks for SLOWER pacing than the
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
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

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


# --- RFC 9309 parsing + matching (self-contained, interpreter-independent) -----------------------


@dataclass
class _Rule:
    """One `Allow:`/`Disallow:` ruleline. `pattern` is the raw path text (kept verbatim for the
    human-readable error message); `regex` is its compiled RFC 9309 form (`*` = any run, trailing
    `$` = end-anchor); `specificity` is the pattern length -- the octet count RFC 9309 sec 2.2.2
    uses to pick the most specific matching rule."""

    allow: bool
    pattern: str
    regex: "re.Pattern[str]"
    specificity: int


@dataclass
class _Group:
    """One RFC 9309 group: the user-agent tokens that select it (lowercased, `*` = default group),
    its rulelines, and its crawl-delay if any."""

    agents: list[str] = field(default_factory=list)
    rules: list[_Rule] = field(default_factory=list)
    crawl_delay: float | None = None


def _compile_pattern(pattern: str) -> "re.Pattern[str]":
    """Compile an RFC 9309 path pattern to an anchored regex. `*` matches any run of characters; a
    trailing `$` anchors to the end of the path; everything else is a literal prefix. All literal
    runs are `re.escape`d so path text like `.json` or `(x)` can never be read as regex syntax."""
    anchored_end = pattern.endswith("$")
    core = pattern[:-1] if anchored_end else pattern
    body = ".*".join(re.escape(part) for part in core.split("*"))
    return re.compile("^" + body + ("$" if anchored_end else ""))


def _parse_groups(lines: list[str]) -> list[_Group]:
    """Parse robots.txt lines into RFC 9309 groups. Consecutive `User-agent:` lines with no
    intervening rule share one group; the first rule-type line (`Allow`/`Disallow`/`Crawl-delay`)
    after a user-agent line closes the group's agent list, so the next `User-agent:` starts a fresh
    group. Comments (`#`), blank lines, and unrecognized/valueless fields are skipped."""
    groups: list[_Group] = []
    current: _Group | None = None
    seen_rule = False
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        name = name.strip().lower()
        value = value.strip()
        if name == "user-agent":
            if current is None or seen_rule:
                current = _Group()
                groups.append(current)
                seen_rule = False
            current.agents.append(value.lower())
        elif name in ("allow", "disallow"):
            if current is None:
                continue
            seen_rule = True
            # An empty `Disallow:` imposes no restriction (RFC 9309 sec 2.2.2); an empty `Allow:` is
            # likewise inert. Skip either -- adding a zero-length rule would match every path.
            if not value:
                continue
            current.rules.append(
                _Rule(
                    allow=(name == "allow"),
                    pattern=value,
                    regex=_compile_pattern(value),
                    specificity=len(value),
                )
            )
        elif name == "crawl-delay":
            if current is None:
                continue
            seen_rule = True
            try:
                current.crawl_delay = float(value)
            except ValueError:
                continue
    return groups


def _select_group(groups: list[_Group], user_agent: str) -> _Group | None:
    """RFC 9309 group selection for one crawler token: the group whose user-agent line matches most
    specifically (longest matching agent string wins), falling back to the `*` group only when no
    specific group matches. Matching mirrors the long-standing convention: the crawler token is
    reduced to its pre-`/` product token, lowercased, and a group agent matches if it is a substring
    of that token. Returns `None` when nothing (not even `*`) applies -- i.e. no restrictions on us."""
    reduced = user_agent.split("/", 1)[0].strip().lower()
    best: _Group | None = None
    best_len = -1
    default: _Group | None = None
    for group in groups:
        for agent in group.agents:
            if agent == "*":
                if default is None:
                    default = group
            elif agent and agent in reduced and len(agent) > best_len:
                best_len = len(agent)
                best = group
    return best if best is not None else default


def _url_path(url: str) -> str:
    """The path (plus query, if any) an RFC 9309 rule matches against. Empty path becomes `/`."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path


def _match_rule(group: _Group | None, path: str) -> _Rule | None:
    """The rule that governs `path` in `group` under RFC 9309: the longest-matching ruleline wins,
    and on a tie an `Allow` beats a `Disallow`. Returns the winning `_Rule`, or `None` when the
    group is `None` or no ruleline matches (either case = allowed)."""
    if group is None:
        return None
    winner: _Rule | None = None
    for rule in group.rules:
        if not rule.regex.match(path):
            continue
        if winner is None or rule.specificity > winner.specificity or (
            rule.specificity == winner.specificity and rule.allow and not winner.allow
        ):
            winner = rule
    return winner


class RobotsPolicy:
    """Wraps parsed RFC 9309 groups (or `None`). `groups is None` means "no robots.txt was
    published" (404/410) -- an explicit permissive policy, not a null object standing in for
    "unknown". Build one from robots.txt text with `RobotsPolicy.from_lines`."""

    def __init__(self, groups: list[_Group] | None) -> None:
        self._groups = groups

    @classmethod
    def from_lines(cls, lines: list[str]) -> "RobotsPolicy":
        """Parse robots.txt body lines (as from `response.text.splitlines()`) into a policy."""
        return cls(_parse_groups(lines))

    @property
    def is_permissive(self) -> bool:
        """True when no robots.txt was published at all (see module docstring)."""
        return self._groups is None

    def _tokens(self, user_agent: str) -> tuple[str, ...]:
        # See module docstring: full UA string, bare product token, and ClaudeBot -- ANY
        # disallowing any of the three makes the URL not-allowed.
        return (user_agent, PRODUCT_TOKEN, CLAUDEBOT_TOKEN)

    def _token_disallows(self, url: str, token: str) -> _Rule | bool | None:
        """The disallowing `_Rule` for `token` on `url`, or `None` if `token` is allowed. Kept
        private; `allows`/`disallowed_by` are the public surface."""
        if self._groups is None:
            return None
        group = _select_group(self._groups, token)
        rule = _match_rule(group, _url_path(url))
        return rule if (rule is not None and not rule.allow) else None

    def allows(self, url: str, user_agent: str) -> bool:
        if self._groups is None:
            return True
        return all(self._token_disallows(url, token) is None for token in self._tokens(user_agent))

    def disallowed_by(self, url: str, user_agent: str) -> tuple[str, str | None] | None:
        """Returns `(token, rule_or_None)` for the FIRST checked token (in `allows`'s own order)
        that disallows `url`, or `None` if every token is allowed. Used by both enforcement points
        (see module docstring) to build a specific `RobotsDisallowedError` message once `allows()`
        has already said no -- `runner.run_source`'s base-URL preflight, and `PoliteClient._request`
        for every other request -- `allows()` alone only exposes the bool. `rule` is the human-
        readable `"Disallow: <path>"` of the winning rule."""
        if self._groups is None:
            return None
        for token in self._tokens(user_agent):
            rule = self._token_disallows(url, token)
            if rule is not None:
                return token, f"Disallow: {rule.pattern}"
        return None

    def crawl_delay(self, user_agent: str) -> float | None:
        """Most-conservative (largest) `Crawl-delay` across the same three tokens `allows` checks
        (fix wave 3, Minor #7): the outgoing UA, the bare product token, and ClaudeBot. Taking the
        MAX across all three (not the first hit, and not just the `user_agent` token) means a slower
        delay declared under a less-specific token always wins over a faster one declared under a
        more-specific token -- the more polite outcome, and the only one consistent with treating
        all three tokens as "targeting us"."""
        if self._groups is None:
            return None
        delays: list[float] = []
        for token in self._tokens(user_agent):
            group = _select_group(self._groups, token)
            if group is not None and group.crawl_delay is not None:
                delays.append(group.crawl_delay)
        return max(delays) if delays else None


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

    return RobotsPolicy.from_lines(response.text.splitlines())
