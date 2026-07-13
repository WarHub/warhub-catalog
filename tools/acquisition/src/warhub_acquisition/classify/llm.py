"""LLM classification of the parked queue (Task 5): proposes gameSystem/faction decisions for
`classify --emit-queue`'s output by batching queue items to an Anthropic model, validating every
answer against the queue's own candidate lists, and writing accepted decisions to
`data/catalog/classifications/products.yaml` -- the same file `classify --apply` (apply.py)
consumes. This module never touches overrides.yaml directly; apply.py is the only write path
there.

Hash-keyed cache (`data/review/classification-cache.jsonl`, append-only, sorted-key JSON lines)
guarantees an item is never re-queried while its inputs (including its candidate lists) are
unchanged: `compute_input_hash` hashes the ENTIRE queue item -- including `candidates` -- so a
taxonomy change that adds/removes a candidate slug naturally invalidates the cache entry (new
decision space = new hash = re-queried), with no separate versioning scheme required.

Batching, hashing, cache read/append, response parsing, and the SDK call wrapper are shared with
`classify/joins.py` (Task 6) via `classify/_llm_common.py` -- see that module's docstring. This
module owns only the classification-specific decision space: the candidate-validated prompt, the
`CacheEntry` schema, and the gameSystem/faction acceptance logic.
"""
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from warhub_acquisition.classify._llm_common import (
    ACCEPT_THRESHOLD,
    AnthropicClient,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    append_cache_lines,
    batch_pending,
    call_batch,
    compute_input_hash,
    extract_text,
    load_cache,
    parse_response,
)
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import load_labels
from warhub_acquisition.yamlio import read_yaml, write_yaml

DEFAULT_BUDGET = 500

__all__ = [
    "DEFAULT_BUDGET",
    "DEFAULT_MODEL",
    "AnthropicClient",
    "CacheEntry",
    "LlmRunSummary",
    "build_system_prompt",
    "compute_input_hash",
    "run_llm_classification",
]


class CacheEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputHash: str
    entity: str
    decision: Literal["classified", "unknown"]
    gameSystem: str | None = None
    faction: str | None = None
    confidence: float | None = None
    model: str
    date: str


@dataclass
class LlmRunSummary:
    queried: int
    cached_skips: int
    accepted: int
    unknown: int
    low_confidence: int
    requests: int

    def render(self) -> str:
        return (
            f"queried={self.queried} cached-skips={self.cached_skips} "
            f"accepted={self.accepted} unknown={self.unknown} low-confidence={self.low_confidence}"
        )


# --- prompt --------------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are classifying tabletop miniature wargaming products for a catalog. Each product below \
failed automatic classification and needs a gameSystem (and optionally a faction) assigned from \
name, source URL, and manufacturer evidence alone -- there is no description or category text.

TASK
For every product object in the user message, decide:
- gameSystem: pick EXACTLY ONE slug from the CANDIDATE GAME SYSTEMS list below, or the literal \
string "unknown" if no candidate confidently fits.
- faction: OPTIONAL. Pick a slug from that gameSystem's own faction list only if the product \
clearly and unambiguously names or implies that faction. Leave it null otherwise -- do not guess.
- confidence: a calibrated 0.0-1.0 estimate that your gameSystem choice is correct. A wrong \
gameSystem is worse than "unknown", so when unsure, answer "unknown" with a correspondingly low \
confidence rather than picking a plausible-looking slug.

EVIDENCE
name, url, and manufacturer are the only signal. A url often embeds the source's own slug for the \
product or game system (e.g. a "/kings-of-war-..." path segment). Use it.

CANDIDATE GAME SYSTEMS (slug: label; indented factions are that system's only valid faction slugs)
{candidates}

EXAMPLES
1. {{"entity": "mantic-games/mgkwc01", "name": "Kings of War: Northern Alliance Clansmen Regiment", \
"url": "https://www.manticgames.com/products/kings-of-war-northern-alliance-clansmen-regiment", \
"manufacturer": "mantic-games"}}
   -> {{"entity": "mantic-games/mgkwc01", "gameSystem": "kings-of-war", "faction": null, "confidence": 0.95}}
   The url slug names the system explicitly; no faction is named, so faction stays null.

2. {{"entity": "games-workshop/99189902012", "name": "Age of Sigmar: Skaven Paint Set", "url": null, \
"manufacturer": "games-workshop"}}
   -> {{"entity": "games-workshop/99189902012", "gameSystem": "age-of-sigmar", "faction": "skaven", \
"confidence": 0.9}}
   A paint bundle that explicitly names a system (and here, a faction) in its title IS a legitimate \
classification -- the bundled contents don't change that the box names the system.

3. {{"entity": "games-workshop/60122099045", "name": "Citadel Paints & Tools Starter Set", "url": null, \
"manufacturer": "games-workshop"}}
   -> {{"entity": "games-workshop/60122099045", "gameSystem": "unknown", "faction": null, "confidence": 0.95}}
   A generic paints-and-tools bundle names no specific game system anywhere -- do not guess one.

OUTPUT
Respond with ONLY a strict JSON array, no prose, no markdown code fences, one object per input \
product in the exact shape shown in the examples above, using the exact "entity" value from the \
input for each. Every product in the input must appear exactly once in the output.
"""


def _format_candidates(candidates: dict, game_system_labels: dict[str, str], faction_labels: dict[str, str]) -> str:
    lines: list[str] = []
    factions_by_gs = candidates.get("factions", {})
    for slug in candidates["gameSystems"]:
        label = game_system_labels.get(slug, slug)
        lines.append(f"- {slug}: {label}")
        faction_slugs = factions_by_gs.get(slug)
        if faction_slugs:
            faction_bits = ", ".join(f"{f} ({faction_labels.get(f, f)})" for f in faction_slugs)
            lines.append(f"    factions: {faction_bits}")
    return "\n".join(lines)


def build_system_prompt(candidates: dict, game_system_labels: dict[str, str], faction_labels: dict[str, str]) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(candidates=_format_candidates(candidates, game_system_labels, faction_labels))


def _item_for_prompt(item: dict) -> dict:
    return {key: value for key, value in item.items() if key != "candidates"}


def _decide(
    raw: dict | None, candidates: dict, model: str, run_date: str, input_hash: str, entity: str
) -> CacheEntry:
    if raw is not None:
        game_system = raw.get("gameSystem")
        faction = raw.get("faction")
        confidence = raw.get("confidence")
        valid_faction = faction is None or (
            isinstance(faction, str) and faction in candidates.get("factions", {}).get(game_system, [])
        )
        valid = (
            isinstance(game_system, str)
            and game_system != "unknown"
            and game_system in candidates["gameSystems"]
            and valid_faction
            and isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
        )
        if valid:
            return CacheEntry(
                inputHash=input_hash,
                entity=entity,
                decision="classified",
                gameSystem=game_system,
                faction=faction,
                confidence=float(confidence),
                model=model,
                date=run_date,
            )
    return CacheEntry(inputHash=input_hash, entity=entity, decision="unknown", model=model, date=run_date)


# --- cache -----------------------------------------------------------------------------------


def _cache_path(paths: DataPaths):
    return paths.root / "review" / "classification-cache.jsonl"


# --- classifications/products.yaml -----------------------------------------------------------


def _write_classifications(paths: DataPaths, new_decisions: dict[str, dict]) -> None:
    existing = read_yaml(paths.classifications) if paths.classifications.exists() else {}
    merged = {**(existing or {}), **new_decisions}
    write_yaml(paths.classifications, {entity: merged[entity] for entity in sorted(merged)})


# --- main entry point --------------------------------------------------------------------------


def run_llm_classification(
    paths: DataPaths,
    *,
    run_date: str,
    client: AnthropicClient,
    budget: int = DEFAULT_BUDGET,
    model: str = DEFAULT_MODEL,
) -> LlmRunSummary:
    queue_path = paths.root / "review" / "classification-queue.yaml"
    queue = (read_yaml(queue_path) or {}).get("queue") or []

    game_system_labels, faction_labels = load_labels(paths.taxonomy)
    cache_path = _cache_path(paths)
    cache = load_cache(cache_path, CacheEntry)

    pending: list[tuple[dict, str]] = []
    cached_skips = 0
    new_decisions: dict[str, dict] = {}
    for item in queue:
        input_hash = compute_input_hash(item)
        cached_entry = cache.get(input_hash)
        if cached_entry is not None:
            cached_skips += 1
            # A cache hit for a PREVIOUSLY accepted classification must still land in
            # products.yaml on every run -- mirrors joins.py's `decided` fold-in (see that
            # module's cache-hit branch). Without this, a run that crashed after flushing the
            # cache but before `_write_classifications` stranded the accepted decision forever:
            # every later run would hit the cache and `continue`, never re-materializing it.
            if (
                cached_entry.decision == "classified"
                and cached_entry.confidence is not None
                and cached_entry.confidence >= ACCEPT_THRESHOLD
            ):
                new_decisions[cached_entry.entity] = {
                    "gameSystem": cached_entry.gameSystem,
                    "faction": cached_entry.faction,
                    "decidedBy": "llm",
                    "model": cached_entry.model,
                    "inputHash": cached_entry.inputHash,
                    "date": cached_entry.date,
                }
            continue
        pending.append((item, input_hash))

    system_prompt = None
    if pending:
        base_candidates = pending[0][0]["candidates"]
        mismatched = [item["entity"] for item, _ in pending if item["candidates"] != base_candidates]
        if mismatched:
            # The system prompt is built ONCE from the first pending item's candidates and reused
            # for every batch's request. queue.py currently guarantees one shared candidates
            # object for the whole queue, but a queue.py change or a hand-edited queue file could
            # silently violate that -- and a mismatched item would then be judged against a
            # system prompt describing the WRONG candidate set. Fail loud instead of guessing.
            raise ValueError(
                "classification queue items do not share one candidates set; the system prompt "
                "would misdescribe candidates for: " + ", ".join(mismatched)
            )
        system_prompt = build_system_prompt(base_candidates, game_system_labels, faction_labels)

    queried = 0
    accepted = 0
    unknown = 0
    low_confidence = 0
    requests_made = 0

    batches = batch_pending(pending, DEFAULT_BATCH_SIZE, budget)
    for batch in batches:
        entities = [item["entity"] for item, _ in batch]

        response = call_batch(
            client,
            model=model,
            system_prompt=system_prompt,
            items=[_item_for_prompt(item) for item, _ in batch],
            max_tokens=DEFAULT_MAX_TOKENS,
        )
        requests_made += 1
        queried += len(batch)

        parsed = parse_response(extract_text(response), entities)

        entries: list[CacheEntry] = []
        for item, input_hash in batch:
            entity = item["entity"]
            # Validate against THIS item's own candidates, not a batch-wide/shared reference --
            # see the homogeneity guard above for why the two are expected to be equal but must
            # never be assumed identical.
            entry = _decide(parsed.get(entity), item["candidates"], model, run_date, input_hash, entity)
            entries.append(entry)
            cache[entry.inputHash] = entry
            if entry.decision == "unknown":
                unknown += 1
            elif entry.confidence is not None and entry.confidence >= ACCEPT_THRESHOLD:
                accepted += 1
                new_decisions[entry.entity] = {
                    "gameSystem": entry.gameSystem,
                    "faction": entry.faction,
                    "decidedBy": "llm",
                    "model": entry.model,
                    "inputHash": entry.inputHash,
                    "date": entry.date,
                }
            else:
                low_confidence += 1

        # incremental flush -- a crash on the NEXT request must not lose this batch's decisions.
        append_cache_lines(cache_path, entries)

    if new_decisions:
        _write_classifications(paths, new_decisions)

    return LlmRunSummary(
        queried=queried,
        cached_skips=cached_skips,
        accepted=accepted,
        unknown=unknown,
        low_confidence=low_confidence,
        requests=requests_made,
    )
