#!/usr/bin/env python
"""How often does each category rule agree with a source that STATED a category for the same product?

    uv run python tools/acquisition/scripts/measure_category_rules.py
    uv run python tools/acquisition/scripts/measure_category_rules.py --axis role

THE ROLE AXIS HAS A DIFFERENT CONTROL. No source states a role, so `--axis role` grades every
clause and every lexicon entry that names one against the PAINT ARCHIVE's own `role` for the
product's barcode (data/paints/brands/*.yaml, decided there from the maker's range and name and
held to the colourless invariant). That control covers only the joined pots -- about 1,350
products -- and none of the brushes, tools and basing materials, so an `applicator`, `tool`,
`basing` or `build` clause cannot be validated here and is judged the way a `miniatures` clause is:
on whether the store's word names the thing. The reach column counts the products still carrying
`roleBasis: unknown` that the clause or entry would decide.

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

THE BAR USED TO DEPEND ON THE FALLBACK, AND THE FALLBACK IS GONE. While `resolve` wrote
`miniatures` for anything undecided, a clause predicting `miniatures` added no answer -- only the
claim that the answer was evidence-backed -- and so had to be near-certain to be worth making,
while a clause predicting anything else replaced a value that was wrong whenever it fired and
earned its place at a much lower purity.

An undecided product now carries NO category at all, so both halves of that asymmetry are void: a
`miniatures` clause supplies a real answer exactly like any other, and no clause is displacing a
wrong value, because there is no value. Judge every clause by the same question -- is it right --
and read the disagreements below rather than a threshold.

A LOW SCORE IS NOT AUTOMATICALLY THE RULE'S FAULT. `Bases -> hobby-auxiliary` disagrees with 11
products legacy-catalog states as `terrain`, and categories.yaml settles that one against
legacy: "Bases sold on their own are `hobby-auxiliary`, not `miniatures`: a blank base is a
component of the hobby, not a model." Read the disagreements, then decide which side is wrong.
"""
import argparse
import collections
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools/acquisition/src"))

from warhub_acquisition.categorize.decide import _clause_hit, _product_hit, _signal  # noqa: E402
from warhub_acquisition.categorize.lexicon import load_lexicon  # noqa: E402
from warhub_acquisition.categorize.paints import load_paint_roles  # noqa: E402
from warhub_acquisition.categorize.rules import load_category_rules  # noqa: E402
from warhub_acquisition.models.catalog import CanonicalProduct  # noqa: E402
from warhub_acquisition.models.descriptor import load_descriptors  # noqa: E402
from warhub_acquisition.resolve.resolver import DataPaths, joined_evidence  # noqa: E402
from warhub_acquisition.yamlio import read_yaml  # noqa: E402


def measure_roles(paths: DataPaths) -> int:
    """Grade every role-naming clause and lexicon entry against the archive's role per barcode."""
    rules = load_category_rules(paths.category_rules)
    lexicon = load_lexicon(paths.taxonomy)
    archive = load_paint_roles(paths.paints)
    if not archive:
        print("the paint archive carries no `role` yet -- nothing to grade against")
        return 0
    joined = joined_evidence(paths)

    products: list[CanonicalProduct] = []
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        for row in (read_yaml(path) or {}).get("products") or []:
            products.append(CanonicalProduct.model_validate(row))
    control = {
        p.id: next(archive[c] for c in (p.ean, *p.additionalEans) if c in archive)
        for p in products
        if any(c in archive for c in (p.ean, *p.additionalEans))
    }
    open_ids = {p.id for p in products if p.roleBasis == "unknown"}
    print(f"control: {len(control)} products on an archive barcode that carries a role")
    print(f"  mix: {dict(collections.Counter(control.values()).most_common())}")
    print(f"open: {len(open_ids)} products carry roleBasis: unknown\n")

    score: dict[tuple[str, str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    reach: collections.Counter = collections.Counter()
    examples: dict[tuple[str, str, str], list[str]] = collections.defaultdict(list)
    by_id = {p.id: p for p in products}
    for product in products:
        code = product.productCode or product.sku or ""
        for member in joined.entities.get(product.id) or []:
            table = rules.get(member.source_id)
            if table is None or table.manufacturer is not None:
                continue
            for clause in table.clauses:
                if clause.role and _clause_hit(member, clause):
                    key = (member.source_id, _signal(clause), clause.role)
                    _grade(key, product.id, clause.role, control, open_ids, score, reach, examples)
                    break
        mtable = rules.get(product.manufacturer or "")
        if mtable is not None and mtable.manufacturer is not None:
            for clause in mtable.clauses:
                if clause.role and _product_hit(product.name, code, clause):
                    key = (product.manufacturer, _signal(clause), clause.role)
                    _grade(key, product.id, clause.role, control, open_ids, score, reach, examples)
                    break
        if lexicon is not None:
            for entry in lexicon.entries:
                if entry.role and re.search(entry.nameMatches, product.name or "", re.IGNORECASE):
                    key = ("lexicon", f"name~{entry.nameMatches}", entry.role)
                    _grade(key, product.id, entry.role, control, open_ids, score, reach, examples)
                    break

    print(f"{'source':18} {'clause -> says':60} {'n':>4} {'agree':>6} {'reach':>5}  disagreements")
    keys = sorted(set(score) | set(reach), key=lambda k: (-sum(score[k].values()), -reach[k]))
    for key in keys:
        counts = score[key]
        source, signal, said_value = key
        total = sum(counts.values())
        agree = counts.get(said_value, 0)
        pct = f"{agree / total:6.0%}" if total else "     -"
        others = ", ".join(f"{k}x{v}" for k, v in counts.most_common() if k != said_value)
        print(f"{source:18} {(signal + ' -> ' + said_value)[:60]:60} {total:4} {pct} {reach[key]:5}  {others[:40]}")
        for example in examples[key]:
            print(f"{'':18}   {example}")
    return 0


def _grade(key, product_id, said, control, open_ids, score, reach, examples) -> None:
    if product_id in open_ids:
        reach[key] += 1
    other = control.get(product_id)
    if other is None:
        return
    score[key][other] += 1
    if other != said and len(examples[key]) < 4:
        examples[key].append(f"{product_id} (archive {other})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--axis", choices=("category", "role"), default="category")
    args = parser.parse_args()
    paths = DataPaths(REPO_ROOT / "data")
    if args.axis == "role":
        return measure_roles(paths)
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
