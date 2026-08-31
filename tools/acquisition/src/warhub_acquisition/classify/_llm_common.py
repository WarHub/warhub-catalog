"""Shared LLM machinery for Task 5 (`classify/llm.py`, gameSystem/faction classification) and
Task 6 (`classify/joins.py`, duplicate-entity join adjudication). Both modules send batched JSON
prompts to an Anthropic model, defensively parse a strict-JSON-array response keyed by an id field,
and persist decisions in a hash-keyed append-only cache so an unchanged input is never re-queried.
The MECHANICS are identical between the two; the DECISION SPACES (and cache files) are not, so this
module holds only the input-agnostic plumbing -- hashing, cache read/append, response parsing, the
SDK call wrapper, and the request-budget batch splitter. Each caller owns its own cache entry model,
prompt text, and acceptance/decision logic.
"""
import hashlib
import json
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_BATCH_SIZE = 20
DEFAULT_MAX_TOKENS = 4096
ACCEPT_THRESHOLD = 0.8

_CacheEntryT = TypeVar("_CacheEntryT", bound=BaseModel)


class _MessagesResource(Protocol):
    def create(self, **kwargs: object) -> object: ...


class AnthropicClient(Protocol):
    """The one SDK surface this module calls -- `client.messages.create(...)`. This is the mock
    boundary for tests: inject any object with a `.messages.create(**kwargs)` callable.
    """

    messages: _MessagesResource


# --- input hash --------------------------------------------------------------------------------


def compute_input_hash(item: dict) -> str:
    """sha256 of the canonical item JSON: sorted keys, compact separators, over the WHOLE item.
    Any field that is part of the decision space (including nested context objects) must be
    included -- a change there is a new decision space and must force a re-query, never a silent
    stale-cache reuse.
    """
    canonical = json.dumps(item, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- response parsing (defensive) ----------------------------------------------------------


def strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines)
    return stripped


def extract_text(response: object) -> str:
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def parse_response(text: str, ids: list[str], id_key: str = "entity") -> dict[str, dict | None]:
    """Per-item salvage: returns id -> raw dict (possibly malformed) for every id found in a
    parseable response array, id -> None for everything else (missing from the response, or the
    response wasn't a parseable JSON array at all -- in which case every id maps to None, since
    there is nothing to salvage from unparseable text).
    """
    results: dict[str, dict | None] = {item_id: None for item_id in ids}
    try:
        data = json.loads(strip_code_fences(text))
    except (json.JSONDecodeError, TypeError):
        return results
    if not isinstance(data, list):
        return results
    for raw in data:
        if not isinstance(raw, dict):
            continue
        item_id = raw.get(id_key)
        if item_id in results:
            results[item_id] = raw
    return results


# --- cache -----------------------------------------------------------------------------------


def load_cache(path: Path, model: type[_CacheEntryT]) -> dict[str, _CacheEntryT]:
    """Read the append-only cache into a dict keyed by `inputHash`. LAST LINE WINS: a second entry
    under an existing hash overrules the first, which is the only way to overrule a decision
    without changing its input, and is used as such (see `joins.py`'s cache-horizon note). Both
    callers' docstrings state what their file costs to prune; the rules are not the same.
    """
    cache: dict[str, _CacheEntryT] = {}
    if not path.exists():
        return cache
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entry = model.model_validate(json.loads(line))
        cache[entry.inputHash] = entry
    return cache


def cache_reachability(items: list[dict], cache: dict[str, BaseModel]) -> tuple[int, int]:
    """How much of `cache` today's queue can still reach: `(reachable, orphaned)`.

    A cache entry is only worth its disk if some CURRENT item hashes to its key, and nothing
    reported that until this function existed. The counts that were reported instead -- lines,
    distinct hashes, distinct entities -- cannot detect the failure this measures: a cache can
    hold a line per entity, one line each, no duplicates at all, and still answer nothing.

    That is not hypothetical. Measured 2026-08-31, all 6,223 classification cache lines were
    unreachable, and had been since the 2026-08-10 queue rebuild, because `compute_input_hash`
    hashes the WHOLE item including the shared `candidates` block (queue.py builds one and reuses
    it by reference for every item). One faction slug leaving one game system's observed list
    re-keys the entire corpus. That is the intended semantics -- a changed decision space is a new
    question -- but it is a cliff, and a cliff nobody can see is one everybody walks off: the wave
    that would have re-asked 6,223 items at full price to be told what the file already knew was
    priced as if the cache still worked.
    """
    live = {compute_input_hash(item) for item in items}
    reachable = sum(1 for input_hash in cache if input_hash in live)
    return reachable, len(cache) - reachable


def append_cache_lines(path: Path, entries: list[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
            handle.write("\n")
        handle.flush()


# --- batching / budget -------------------------------------------------------------------------


def batch_pending(pending: list, batch_size: int, budget: int) -> list[list]:
    """Slice `pending` into `batch_size`-sized batches, capped at the first `budget` batches --
    `budget` counts REQUESTS (batches), not items. Items beyond the cap are simply left out of the
    result (uncached, unqueried) for a future run to pick up.

    THE CAP IS POSITIONAL, SO THE QUEUE'S ORDER DECIDES WHAT A PARTIAL BUDGET BUYS, and that order
    is entity id -- which means alphabetical by manufacturer, a sequence chosen for determinism and
    carrying no relation whatever to where the answers are. A budget is not spread across the
    corpus; it is spent from the front of the alphabet until it runs out.

    For the classification queue that is actively perverse, measured 2026-08-31 over 14,265 items:
    the first 176 batches are entirely `ak-interactive` (2,409) and `army-painter` (1,119), two
    brands that are 99.6-99.8% paint and hobby supplies, where a null gameSystem is the CORRECT
    answer and the model will rightly say `unknown`. `games-workshop` -- 5,077 items and the
    largest real yield in the file -- does not begin until batch 229. So a budget under ~230 buys
    almost nothing but confirmation, and one under ~483 never finishes GW.

    Left positional rather than "fixed" by sorting on some yield heuristic: which manufacturer is
    worth asking about is a judgement, it changes as the catalog grows, and burying it here would
    make the spend depend on a guess nobody reviewed. The operator picks the budget; this docstring
    exists so they can pick it knowing what the front of the queue is.
    """
    batches = [pending[i : i + batch_size] for i in range(0, len(pending), batch_size)]
    return batches[:budget]


# --- SDK call wrapper --------------------------------------------------------------------------


def call_batch(
    client: AnthropicClient,
    *,
    model: str,
    system_prompt: str | None,
    items: list[dict],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> object:
    user_content = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
