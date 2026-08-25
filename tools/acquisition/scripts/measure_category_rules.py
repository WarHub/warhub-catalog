#!/usr/bin/env python
"""How often does each category rule agree with a source that STATED a category for the same product?

    uv run python tools/acquisition/scripts/measure_category_rules.py

WHY THIS EXISTS. A rule table is a claim about a store's vocabulary, and the only way to know
whether the claim holds is to check it against products some OTHER source independently made a
statement about. Reading a sample by eye finds the errors that happen to be in the sample; this
finds the ones that are not. Both of the errors that shipped in the first draft of these tables --
gamenerdz's `Supplies` department holding GW paint six-packs, Mantic's `terraincrate-battlefields`
holding neoprene mats -- were found here and not by reading.

THE CONTROL IS `stated` ONLY, AND NEVER A `defaultHints` FILL. Three earlier versions of this
measurement were wrong in ways worth recording, because each looks reasonable:

  * Including every source's `hints.category` made `legacy-catalog`'s blanket `miniatures` the
    control for 8,197 products, so every specific clause (`Poster -> merch`, `Fate Deck ->
    game-accessory`) scored 0%.
  * Including this stage's OWN output made the tables score against each other, which is circular
    and inflated `Rules Supplements -> book`'s error rate from 6% to 45%.
  * The control contains almost no `miniatures` at all -- `legacy-catalog` states only terrain,
    book and paint, and manufacturers state paint and paint-set -- so a clause predicting
    `miniatures` scores 0% BY CONSTRUCTION and its number here means nothing.

THE BAR IS NOT THE SAME FOR EVERY CLAUSE, for a reason that follows from the fallback. The
resolver already writes `miniatures` for anything undecided, so a clause predicting `miniatures`
adds no answer -- only the claim that the answer is evidence-backed. It has to be near-certain to
be worth making. A clause predicting anything else replaces a value that is wrong whenever it
fires, so it earns its place at a much lower purity.

A LOW SCORE IS NOT AUTOMATICALLY THE RULE'S FAULT. `Bases -> hobby-auxiliary` disagrees with 11
products legacy-catalog states as `terrain`, and categories.yaml settles that one against
legacy: "Bases sold on their own are `hobby-auxiliary`, not `miniatures`: a blank base is a
component of the hobby, not a model." Read the disagreements, then decide which side is wrong.
"""
import collections
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools/acquisition/src"))

from warhub_acquisition.categorize.decide import _clause_hit, _signal  # noqa: E402
from warhub_acquisition.categorize.rules import load_category_rules  # noqa: E402
from warhub_acquisition.models.catalog import CanonicalProduct  # noqa: E402
from warhub_acquisition.models.descriptor import load_descriptors  # noqa: E402
from warhub_acquisition.resolve.resolver import DataPaths, joined_evidence  # noqa: E402
from warhub_acquisition.yamlio import read_yaml  # noqa: E402


def main() -> int:
    paths = DataPaths(REPO_ROOT / "data")
    rules = load_category_rules(paths.category_rules)
    if not rules:
        print("no rule tables to measure")
        return 0
    joined = joined_evidence(paths)
    defaults = {
        sid: (descriptor.defaultHints or {}).get("category")
        for sid, descriptor in load_descriptors(paths.sources).items()
    }

    control: dict[str, dict[str, str]] = {}
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        for row in (read_yaml(path) or {}).get("products") or []:
            product = CanonicalProduct.model_validate(row)
            said = {}
            for member in joined.entities.get(product.id) or []:
                value = member.hints.get("category")
                if value and str(value) != defaults.get(member.source_id):
                    said[member.source_id] = str(value)
            if said:
                control[product.id] = said

    mix = collections.Counter(v for said in control.values() for v in said.values())
    print(f"control: {len(control)} products with a stated (non-default) category")
    print(f"  mix: {dict(mix.most_common())}\n")

    score: dict[tuple[str, str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    examples: dict[tuple[str, str, str], list[str]] = collections.defaultdict(list)
    for product_id, said in control.items():
        for member in joined.entities.get(product_id) or []:
            table = rules.get(member.source_id)
            if table is None or member.source_id in said:
                continue  # a source is never its own control
            for clause in table.clauses:
                if not _clause_hit(member, clause):
                    continue
                if clause.category:
                    key = (member.source_id, _signal(clause), clause.category)
                    for other in said.values():
                        score[key][other] += 1
                        if other != clause.category and len(examples[key]) < 4:
                            examples[key].append(f"{product_id} (stated {other})")
                break

    print(f"{'source':18} {'clause -> says':52} {'n':>4} {'agree':>6}  disagreements")
    for key, counts in sorted(score.items(), key=lambda kv: -sum(kv[1].values())):
        source, signal, said_value = key
        total = sum(counts.values())
        agree = counts.get(said_value, 0)
        others = ", ".join(f"{k}x{v}" for k, v in counts.most_common() if k != said_value)
        print(f"{source:18} {(signal + ' -> ' + said_value)[:52]:52} {total:4} {agree / total:6.0%}  {others[:46]}")
        for example in examples[key]:
            print(f"{'':18}   {example}")
    print(
        "\nA clause predicting `miniatures` cannot be validated here (see the module docstring); "
        "judge those on whether the store's value names a FORMAT rather than a department."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
