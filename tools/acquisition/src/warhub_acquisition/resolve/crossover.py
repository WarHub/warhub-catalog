"""Is this paint-source observation actually a boxed SET (i.e. a product)? One shared evaluator.

Two very different callers must agree EXACTLY, or a box publishes twice or not at all:

  * resolve/resolver.py admits the rows this selects into the product catalog, and
  * scripts/gen_paint_harvest.py refuses precisely the same rows from the paint bridge.

A SOURCE'S CROSSOVER PREDICATE IS EXACTLY WHAT ITS PAINT BRIDGE REFUSES -- which only holds if
there is one implementation. Before this, each bridge carried its own inline set test (three
different spellings of the same idea) and the resolver had none at all.

STDLIB ONLY, and deliberately so. This module's imports are `re` and `typing` and nothing else --
no pydantic, no yaml, no first-party module. `gen_paint_harvest.py` runs in CI as
`uv run --with pyyaml python ...` (.github/workflows/paint-catalog-update.yml:75) and imports this
via a sys.path bootstrap. The two package `__init__` files it traverses import nothing
third-party -- `resolve/__init__.py` is empty and `warhub_acquisition/__init__.py` holds only
`__version__ = "0.1.0"` -- so that import pulls in no dependency and the workflow line needs no
edit. (An earlier draft of this comment said both were empty; they are not, and the claim is
worth stating accurately because it is the one a future reader will check before adding an import
to either file. Verified: `uv run --with pyyaml --no-project python -c "...import matches"`
succeeds in an environment where `import pydantic` raises.)
Hence the plain-dict interface: the resolver passes `Observation.model_dump()` and a
`Crossover.model_dump()`, the script passes the raw JSONL row and the raw parsed YAML.
"""
import re
from typing import Mapping


def clause_matches(name: str, hints: Mapping[str, object], clause: Mapping) -> bool:
    """One CrossoverClause against one observation's name + hints (see models/descriptor.py)."""
    if clause.get("nameMatches"):
        return re.search(clause["nameMatches"], name or "", re.IGNORECASE) is not None
    if clause.get("hintEquals"):
        return all(hints.get(key) == value for key, value in clause["hintEquals"].items())
    if clause.get("hintContainsAny"):
        for key, values in clause["hintContainsAny"].items():
            got = hints.get(key)
            if got is None:
                return False  # a hint the store stopped emitting is not a match, and not an error
            # EXACT value membership, NEVER substring. Army Painter's four genuine airbrush paint
            # sets (AW8001P-AW8004P) carry the tags `Airbrush Warpaints` / `SDS Airbrush Sets`,
            # which contain the substring of the `brushset` exclusion; a substring test would veto
            # all four real sets to exclude 7 brush sets (measured 2026-08-05).
            if isinstance(got, (list, tuple, set)):
                if not (set(got) & set(values)):
                    return False
            elif got not in values:
                return False
        return True
    return False


def matches(observation: Mapping, rule: Mapping | None) -> bool:
    """True iff this observation is a SET under `rule` (a `Crossover.model_dump()`-shaped dict).

    `noneOf` is evaluated FIRST and vetoes unconditionally -- a vetoed row can never be rescued by
    an `anyOf` clause, which is what makes the exclusion lists readable as "not these, whatever
    else you concluded". No rule (a paint source that declares no carve-out) means nothing crosses.
    """
    return matched_clause(observation, rule) is not None


def matched_clause(observation: Mapping, rule: Mapping | None) -> Mapping | None:
    """The FIRST `anyOf` clause this observation satisfies, or None -- `matches` with a receipt.

    Exists because a crossed row's category is not always the block's: see `category_for`. Clause
    ORDER is therefore load-bearing where clauses overlap, which is why this returns the first
    match rather than any match, and why the descriptor lists the narrow clauses first.
    """
    if not rule:
        return None
    name = str(observation.get("name") or "")
    hints = observation.get("hints") or {}
    if any(clause_matches(name, hints, clause) for clause in rule.get("noneOf") or []):
        return None
    for clause in rule.get("anyOf") or []:
        if clause_matches(name, hints, clause):
            return clause
    return None


def category_for(observation: Mapping, rule: Mapping | None) -> str | None:
    """What to stamp on a crossed row: the matching clause's own `category`, else the block's.

    ONE SOURCE CAN CROSS TWO DIFFERENT KINDS OF THING. ak-interactive.com sells boxed sets (which
    are `paint-set` products) and auxiliary agents -- thinners, burnishing fluids, chipping fluids
    -- out of the same paint categories. Both belong in the product catalog and NEITHER belongs in
    the paint catalog, but stamping an agent `paint-set` would be the same structural lie the block
    was introduced to fix, one level down. A per-clause override says the true thing about each
    without needing a second block, so the four sources that cross exactly one kind are untouched.
    """
    clause = matched_clause(observation, rule)
    if clause is None:
        return None
    return str(clause.get("category") or (rule or {}).get("category") or "") or None
