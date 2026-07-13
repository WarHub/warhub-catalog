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
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import load_labels
from warhub_acquisition.yamlio import read_yaml, write_yaml

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_BUDGET = 500
_BATCH_SIZE = 20
_ACCEPT_THRESHOLD = 0.8
_MAX_TOKENS = 4096


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


class _MessagesResource(Protocol):
    def create(self, **kwargs: object) -> object: ...


class AnthropicClient(Protocol):
    """The one SDK surface this module calls -- `client.messages.create(...)`. This is the mock
    boundary for tests: inject any object with a `.messages.create(**kwargs)` callable.
    """

    messages: _MessagesResource


# --- input hash --------------------------------------------------------------------------------


def compute_input_hash(item: dict) -> str:
    """sha256 of the canonical queue-item JSON: sorted keys, compact separators, over the WHOLE
    item -- entity/name/manufacturer/url/description/hints AND candidates. Including candidates
    is deliberate: a new candidate gameSystem/faction slug is a new decision space, so it must
    produce a new hash and force a re-query rather than silently reusing a stale cached decision.
    """
    canonical = json.dumps(item, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


# --- response parsing (defensive) -----------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines)
    return stripped


def _extract_text(response: object) -> str:
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _parse_response(text: str, entities: list[str]) -> dict[str, dict | None]:
    """Per-item salvage: returns entity -> raw dict (possibly malformed) for every entity found
    in a parseable response array, entity -> None for everything else (missing from the response,
    or the response wasn't a parseable JSON array at all -- in which case every entity maps to
    None, since there is nothing to salvage from unparseable text).
    """
    results: dict[str, dict | None] = {entity: None for entity in entities}
    try:
        data = json.loads(_strip_code_fences(text))
    except (json.JSONDecodeError, TypeError):
        return results
    if not isinstance(data, list):
        return results
    for raw in data:
        if not isinstance(raw, dict):
            continue
        entity = raw.get("entity")
        if entity in results:
            results[entity] = raw
    return results


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


def _cache_path(paths: DataPaths) -> Path:
    return paths.root / "review" / "classification-cache.jsonl"


def _load_cache(path: Path) -> dict[str, CacheEntry]:
    cache: dict[str, CacheEntry] = {}
    if not path.exists():
        return cache
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entry = CacheEntry.model_validate(json.loads(line))
        cache[entry.inputHash] = entry
    return cache


def _append_cache_lines(path: Path, entries: list[CacheEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
            handle.write("\n")
        handle.flush()


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
    cache = _load_cache(cache_path)

    pending: list[tuple[dict, str]] = []
    cached_skips = 0
    for item in queue:
        input_hash = compute_input_hash(item)
        if input_hash in cache:
            cached_skips += 1
            continue
        pending.append((item, input_hash))

    system_prompt = None
    if pending:
        system_prompt = build_system_prompt(pending[0][0]["candidates"], game_system_labels, faction_labels)

    queried = 0
    accepted = 0
    unknown = 0
    low_confidence = 0
    requests_made = 0
    new_decisions: dict[str, dict] = {}

    for batch_start in range(0, len(pending), _BATCH_SIZE):
        if requests_made >= budget:
            break
        batch = pending[batch_start : batch_start + _BATCH_SIZE]
        entities = [item["entity"] for item, _ in batch]
        candidates = batch[0][0]["candidates"]

        user_content = json.dumps(
            [_item_for_prompt(item) for item, _ in batch], sort_keys=True, separators=(",", ":")
        )
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        requests_made += 1
        queried += len(batch)

        parsed = _parse_response(_extract_text(response), entities)

        entries: list[CacheEntry] = []
        for item, input_hash in batch:
            entity = item["entity"]
            entry = _decide(parsed.get(entity), candidates, model, run_date, input_hash, entity)
            entries.append(entry)
            cache[entry.inputHash] = entry
            if entry.decision == "unknown":
                unknown += 1
            elif entry.confidence is not None and entry.confidence >= _ACCEPT_THRESHOLD:
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
        _append_cache_lines(cache_path, entries)

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
