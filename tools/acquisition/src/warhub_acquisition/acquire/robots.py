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

- 301/302/303/307/308 -> FOLLOWED, up to `MAX_REDIRECTS` (5) consecutive hops, then the final
  response is classified by the rules below. See the redirect section immediately after this list.
- 404/410 -> permissive (`RobotsPolicy` wrapping `None`): "no restrictions published" is an
  explicit, positive outcome, not a fallback-on-error. Per RFC 9309 sec 2.3.1.3, these two codes
  are the ones a well-behaved crawler treats as "no robots.txt exists."
- Any other non-2xx (5xx after `PoliteClient`'s own retries, a transport failure, or anything else
  -- 401/403/etc.) -> `RobotsFetchError` (FAIL LOUD). We cannot prove we're allowed, and a site
  that is actively erroring on its own robots.txt is not the same thing as a site that has
  published "no restrictions" -- silently treating that as permission would defeat the entire
  point of this preflight.
- 200 -> parsed by `_parse_groups` into RFC 9309 user-agent groups.

**Redirects ARE followed, on robots.txt only (fix, 2026-08-12)**: until this date a 3xx on
robots.txt was lumped in with 401/403/5xx and raised `RobotsFetchError`, on the reasoning that
`PoliteClient` never follows redirects so we could not resolve one. That was a gap in this fetcher,
not a compliance stance: RFC 9309 sec 2.3.1.2 is explicit that a crawler "SHOULD follow at least
five consecutive redirects, even across authorities", and that a robots.txt reached within five
hops MUST be fetched, parsed, and its rules followed IN THE CONTEXT OF THE INITIAL AUTHORITY. An
apex host 301ing `/robots.txt` to its `www` canonical (or to a locale prefix like `/en/robots.txt`)
is the single most ordinary shape on the web; refusing it meant refusing to read rules a site was
publishing perfectly well, which is strictly worse for compliance than reading them.

It was also already costing us. Two committed descriptors existed to route around this fetcher
rather than around any site's actual wishes:

- `mfr-armypainter.yaml` pinned `baseUrl` to the apex host with the note "the www host 301s
  robots.txt (the robots fetcher refuses to assume permission on redirects)" -- a baseUrl chosen to
  dodge a client limitation.
- `mfr-corvus-belli.yaml` cited `store.corvusbelli.com/robots.txt` 301ing to `/en/robots.txt` as
  one of two reasons for `ignoreRobots: true`. That reason is now void; its OTHER reason (the
  strategy's real fetch target is a hardcoded AppSync host unrelated to the storefront baseUrl) is
  untouched and still carries the flag on its own.

Scope, deliberately narrow -- this changes how ROBOTS.TXT is fetched and nothing else.
`PoliteClient` still never follows redirects for anything a strategy fetches: a 301 on a product
URL is still an immediate `FetchError` (the goblingaming incident, see client.py), because a
strategy silently following a redirect could land on a path the policy disallows without being
re-checked. The robots.txt probe client is the one client that carries no policy at all (checking
robots against the robots.txt fetch would be nonsensical), so hop-by-hop re-checking is not a
question here.

What stops this being a loophole:

- Bounded at five consecutive hops, exactly the RFC floor. A sixth is `RobotsFetchError`, not an
  assumption of permission (the RFC permits treating it as "unavailable", i.e. permissive; we stay
  stricter).
- A loop (any hop revisiting an already-requested URL), a 3xx with a missing/empty `Location`, and
  a `Location` on a non-http(s) scheme are each `RobotsFetchError` -- unresolvable is unresolvable.
- The FINAL response is classified by exactly the same rules a first-hop response is: only 2xx
  parses, only 404/410 is permissive, everything else fails loud. A redirect ending in 403 fails
  just as it did before this change.
- Rules fetched from a redirect target bind requests to the ORIGINAL host, per the RFC's
  "context of the initial authority" -- so a canonical host publishing `Disallow: /` blocks the
  apex source that redirected to it. Pinned end-to-end in test_robots.py.

The honest cost: a host that 301s `/robots.txt` to an HTML page returning 200 now yields a policy
parsed from HTML, i.e. zero groups, i.e. no restrictions -- where before it failed loud. That is
not a new failure mode (a host serving that same HTML soft-404 directly on `/robots.txt` with a 200
already parses to zero groups today, and always has), but redirect-following does make it reachable
on redirecting hosts. Not guarded here: every available guard is a content-type or body heuristic
that would also reject the many sites serving a perfectly valid robots.txt under a sloppy
`Content-Type`, and asymmetric guards (applied to redirected 200s only) would be worse still.

**Checked tokens (`RobotsPolicy.allows`)**: every call checks TWO user-agent tokens against the
parsed policy, and a `Disallow` under EITHER of them makes the URL not-allowed:

1. The full outgoing `User-Agent` string this client actually sends (`client.UA` by default --
   `"warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)"`).
2. The bare product token (`"warhub-catalog-bot"`) -- robots.txt authors conventionally name the
   product, not a full UA-with-URL-comment string. Group selection reduces any UA to its pre-`/`
   token before matching (see `_select_group`), so in practice this is redundant with (1) today,
   but it's cheap, explicit, and future-proof against a UA format change.

Nothing else about enforcement is relaxed by that list being two long rather than three. The `*`
group still fully binds us -- it is the group `_select_group` falls back to whenever no specific
group names us, which is the overwhelmingly common case -- and a site that disallows
`warhub-catalog-bot` BY NAME still blocks us outright (fantasywelt.de, cited at the top of this
docstring, remains blocked on exactly that basis). robots.txt is still fetched, parsed and
enforced on every request at both enforcement points, and `RobotsFetchError` still fails loud.

**RETIRED third token: `ClaudeBot` (maintainer decision, 2026-08-05)**: until this date `allows`
and `crawl_delay` also evaluated the literal token `"ClaudeBot"`, so that a site publishing
Cloudflare's managed AI-crawler block (`User-agent: ClaudeBot` / `Disallow: /`) was treated as
disallowing US, even though our product string never says "Claude" anywhere and we never present
that UA. The maintainer retired it, verbatim: "ignore ClaudeBot when doing harvest - we harvest
via scripts, not via claude session direct."

The reasoning, and the evidence measured live on 2026-08-05 against www.reapermini.com/robots.txt:

- robots.txt is a PER-USER-AGENT protocol (RFC 9309 sec 2.2.1). A `User-agent: ClaudeBot` group
  addresses Anthropic's own web crawler. This harvester is a separate, honestly-identified,
  user-operated program that fetches on demand under its own name and never claims to be
  ClaudeBot; the group that actually addresses us is `*`, or a `warhub-catalog-bot` group.
- Under the group that does address us, that file explicitly permits us: its first `User-agent: *`
  group is `Allow: /`, with no crawl-delay. The `ClaudeBot / Disallow: /` line is one of NINE
  consecutive Cloudflare-managed AI-crawler blocks in a `# BEGIN Cloudflare Managed content`
  section -- Amazonbot, Applebot-Extended, Bytespider, CCBot, ClaudeBot,
  CloudflareBrowserRenderingCrawler, Google-Extended, GPTBot, meta-externalagent -- i.e. a
  vendor-supplied AI-crawler list toggled on at the edge, not a rule written about this pipeline.
- The same file carries `Content-Signal: search=yes,ai-train=no,use=reference` on its `*` group.
  This repo builds a REFERENCE catalog (identifiers, names, barcodes) and trains nothing, so
  `use=reference` is consistent with what we do and `ai-train=no` restricts something we were
  never doing.

**The counter-argument, stated plainly rather than buried**: a publisher who switches on a
ClaudeBot block may well intend it as "no AI-agent-operated crawling of any kind," not narrowly
"not Anthropic's crawler process." Under the previous policy we honored that broader reading; as
of 2026-08-05 we do not, and a site whose ONLY expression of that intent is a ClaudeBot group is
now fetched by this pipeline where it previously was not. That is a real change in whose wishes we
defer to, made deliberately by the maintainer on the reasoning above, and recorded here so a
future reader weighs the trade-off rather than rediscovering it. If a publisher names us, or
narrows `*`, we are still bound -- that is the line this change does not cross.

**Crawl-delay (`RobotsPolicy.crawl_delay`)**: the most-conservative (largest) `Crawl-delay` across
the same two tokens `allows` checks. The runner honors it when it asks for SLOWER pacing than the
descriptor's own `politeness.rps` -- a site publishing `Crawl-delay: 10` is asking us to back off,
and `politeness.rps` is a ceiling we impose on OURSELVES, never a floor we're entitled to regardless
of what the site asks for.

**Escape hatch**: `descriptor.politeness["ignoreRobots"]` (default `False`, wired in
`runner.run_source`) skips this preflight entirely for sources where `baseUrl` genuinely isn't the
real fetch target (e.g. an Algolia or AppSync API host reached via an absolute URL baked into the
strategy, unrelated to the marketing-site `baseUrl` the descriptor happens to declare) or where
robots.txt is otherwise not the right compliance mechanism. It must be set explicitly per
descriptor, with a comment citing why -- see `data/catalog/sources/mfr-gw-algolia.yaml`,
`mfr-corvus-belli.yaml` and `mfr-vallejo.yaml` for the THREE real cases this repo currently needs
it for. (This said "two" while four descriptors carried the flag; corrected 2026-08-05, when
retiring the ClaudeBot token let `mfr-reaper.yaml` drop its own.) If you add or remove one, fix
this line -- an undercount here reads as "the escape hatch is barely used" when auditing it.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from warhub_acquisition.acquire.client import FetchError, PoliteClient

# The bare product token robots.txt authors are most likely to write, independent of our UA
# string's exact format (see module docstring point 2).
PRODUCT_TOKEN = "warhub-catalog-bot"

# (There is deliberately no CLAUDEBOT_TOKEN here any more. It was removed outright rather than
# kept-but-unreferenced on 2026-08-05: a module-level constant is an interface statement -- "this
# codebase has a notion of the ClaudeBot token" -- and after the retirement described in the module
# docstring we have no such notion, so keeping one unused would read as an oversight or, worse, as
# a token something still checks. The full rationale, the maintainer's wording, the measured Reaper
# evidence and the counter-argument all live in the module docstring, which is where a policy
# decision belongs; the literal string survives only inside test fixtures, where it stands for
# SOMEONE ELSE'S robots.txt rather than for a token of ours.)

# 404/410 are the only statuses RFC 9309 sec 2.3.1.3 treats as "no robots.txt published" -- every
# other non-2xx is a FetchError that propagates uncaught (fail loud).
_PERMISSIVE_STATUSES = frozenset({404, 410})

# The redirect statuses `fetch_policy` follows (see the module docstring's redirect section). Passed
# to `PoliteClient.get_response`'s `allow_statuses` so the client hands the 3xx response back
# instead of raising -- PoliteClient itself still never follows a redirect for anything else.
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)

# RFC 9309 sec 2.3.1.2: a crawler SHOULD follow at least five consecutive redirects on robots.txt.
# Five is the floor a compliant client must reach, so it is also where we stop -- past it the RFC
# permits assuming the file is unavailable (permissive); we raise instead.
MAX_REDIRECTS = 5

ROBOTS_PATH = "/robots.txt"


class RobotsFetchError(Exception):
    """robots.txt could not be retrieved with enough confidence to proceed: a 5xx (after
    PoliteClient's own retries), a transport failure, any other non-2xx status that isn't one of
    the two "no robots.txt published" codes (404/410), or a redirect chain that could not be
    resolved (unfollowable `Location`, a loop, or more than `MAX_REDIRECTS` hops -- see the module
    docstring). We cannot prove we're allowed to crawl, so this fails loud rather than silently
    defaulting to permissive.

    `cause.url` is the URL actually being fetched when it failed, which differs from
    `<base_url>/robots.txt` once a redirect has been followed; `detail` says how we got there."""

    def __init__(self, base_url: str, cause: FetchError, *, detail: str | None = None) -> None:
        self.base_url = base_url
        self.cause = cause
        self.detail = detail
        context = f"; {detail}" if detail else ""
        super().__init__(
            f"could not fetch {base_url.rstrip('/')}{ROBOTS_PATH} "
            f"(status={cause.status}{context}): refusing to assume permission"
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
    """RFC 9309 group selection for one crawler token: pick the most specific matching user-agent
    (longest matching agent string wins), falling back to `*` only when no specific agent matches,
    then MERGE every group naming that agent. Matching mirrors the long-standing convention: the
    crawler token is reduced to its pre-`/` product token, lowercased, and a group agent matches if
    it is a substring of that token. Returns `None` when nothing (not even `*`) applies -- i.e. no
    restrictions on us.

    **Merging (fix, 2026-08-05)**: RFC 9309 sec 2.2.1 requires that groups repeating the same
    user-agent be combined into one. The previous implementation kept only the FIRST group per
    agent (`if default is None: default = group`) and silently discarded the rest. That is not
    hypothetical: www.reapermini.com/robots.txt publishes TWO `*` groups -- Cloudflare's managed
    block (`Allow: /`) near the top and a trailing site-authored one (`Disallow: /api`,
    `Disallow: /admin`) -- and the trailing group's rules evaluated as if absent, so
    `/api` and `/admin` both read as allowed. The bug predates the ClaudeBot-token retirement, but
    that retirement is what made it load-bearing: dropping `ignoreRobots: true` from
    mfr-reaper.yaml turned real per-request enforcement ON for the one source in this repo whose
    robots.txt exercises the gap. No path we fetch was ever affected (the Reaper strategy reads
    only /paints/*), but "the rule we ignored happened not to matter" is luck, not compliance.

    Crawl-delay across merged groups takes the MAX, consistent with `RobotsPolicy.crawl_delay`'s
    own most-conservative rule: a site that asks us to slow down anywhere gets the slower pace."""
    reduced = user_agent.split("/", 1)[0].strip().lower()
    selected: str | None = None
    for group in groups:
        for agent in group.agents:
            if agent and agent != "*" and agent in reduced:
                if selected is None or len(agent) > len(selected):
                    selected = agent
    if selected is None:
        selected = "*"

    matching = [group for group in groups if selected in group.agents]
    if not matching:
        return None
    if len(matching) == 1:
        return matching[0]

    merged = _Group(agents=[selected])
    for group in matching:
        merged.rules.extend(group.rules)
        if group.crawl_delay is not None:
            merged.crawl_delay = (
                group.crawl_delay if merged.crawl_delay is None
                else max(merged.crawl_delay, group.crawl_delay)
            )
    return merged


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
        # See module docstring: the full outgoing UA string and the bare product token -- EITHER
        # disallowing makes the URL not-allowed. `_select_group` falls back to the `*` group for
        # both when no group names us, so a site-wide `Disallow: /` under `*` still binds.
        return (user_agent, PRODUCT_TOKEN)

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
        """Most-conservative (largest) `Crawl-delay` across the same two tokens `allows` checks
        (fix wave 3, Minor #7): the outgoing UA and the bare product token. Taking the MAX across
        both (not the first hit, and not just the `user_agent` token) means a slower delay declared
        under a less-specific token always wins over a faster one declared under a more-specific
        token -- the more polite outcome, and the only one consistent with treating both tokens as
        "targeting us". Narrowed from three tokens on 2026-08-05 alongside `allows` -- see the
        module docstring's retired-ClaudeBot section; a `Crawl-delay` declared ONLY under a
        `ClaudeBot` group is no longer picked up, for the same reason its `Disallow` no longer
        binds."""
        if self._groups is None:
            return None
        delays: list[float] = []
        for token in self._tokens(user_agent):
            group = _select_group(self._groups, token)
            if group is not None and group.crawl_delay is not None:
                delays.append(group.crawl_delay)
        return max(delays) if delays else None


def _via(redirected: list[str]) -> str:
    """How we reached the hop that failed. Empty before any redirect has been followed, so a
    failure on the very first request keeps its original, redirect-free message."""
    if not redirected:
        return ""
    return f" via {len(redirected)} redirect(s) from {redirected[0]}"


def _redirect_target(response) -> str | None:
    """The absolute URL a 3xx robots.txt response points at, or `None` when it cannot be followed
    at all: no `Location` header, an empty one, or one resolving to a non-http(s) scheme. A
    relative `Location` (`/en/robots.txt`, the shape store.corvusbelli.com publishes) is resolved
    against the URL that was actually requested, not against `base_url` -- after a cross-host hop
    those differ."""
    location = response.headers.get("Location", "").strip()
    if not location:
        return None
    target = urljoin(str(response.request.url), location)
    if urlparse(target).scheme not in ("http", "https"):
        return None
    return target


def fetch_policy(client: PoliteClient, base_url: str) -> RobotsPolicy:
    """Fetches `<baseUrl>/robots.txt` through `client` (paced/retried/UA-bearing) and returns the
    resulting policy, following up to `MAX_REDIRECTS` consecutive redirects on the way. See the
    module docstring for the redirect rules and for the 404/410 (permissive) vs. everything-else
    (`RobotsFetchError`, fail loud) vs. 200 (parse) split the FINAL response is classified by.

    The rules returned bind requests to `base_url`'s host even when the file was fetched from
    another one -- RFC 9309 sec 2.3.1.2's "context of the initial authority"."""
    url = ROBOTS_PATH
    # Every URL we requested that answered with a redirect, in order: its length is the number of
    # hops followed so far, and membership is the loop check.
    redirected: list[str] = []

    while True:
        try:
            response = client.get_response(url, allow_statuses=_REDIRECT_STATUSES)
        except FetchError as exc:
            if exc.status in _PERMISSIVE_STATUSES:
                # A chain ending in 404/410 is still "no robots.txt published" -- the redirect just
                # told us where the site keeps the file it does not have.
                return RobotsPolicy(None)
            detail = f"failed at {exc.url}{_via(redirected)}" if redirected else None
            raise RobotsFetchError(base_url, exc, detail=detail) from exc

        if response.status_code not in _REDIRECT_STATUSES:
            return RobotsPolicy.from_lines(response.text.splitlines())

        current = str(response.request.url)
        redirected.append(current)
        failure = FetchError(current, response.status_code)
        target = _redirect_target(response)
        if target is None:
            location = response.headers.get("Location", "")
            raise RobotsFetchError(
                base_url, failure,
                detail=f"cannot follow redirect from {current} to {location!r}",
            )
        if target in redirected:
            raise RobotsFetchError(
                base_url, failure,
                detail=f"redirect loop: {current} -> {target}, already requested",
            )
        if len(redirected) > MAX_REDIRECTS:
            raise RobotsFetchError(
                base_url, failure,
                detail=f"more than {MAX_REDIRECTS} consecutive redirects (next would be {target})",
            )
        url = target
