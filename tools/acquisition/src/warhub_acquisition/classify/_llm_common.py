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
