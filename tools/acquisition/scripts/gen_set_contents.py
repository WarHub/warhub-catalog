"""Generate data/catalog/set-contents/<manufacturer>.yaml — the boxed-set membership relation.

CanonicalProduct.contentSkus holds the manufacturer's own RAW product codes for what a boxed set
contains. Resolving them needs the PAINT catalog, which the product resolver deliberately never
loads (see models/catalog.py:56-78), so the join happens ONCE, here, and the committed YAML is
the audit trail — same architecture as gen_paint_barcodes.py and gen_paint_harvest.py, and the
same posture: reads only committed files, no network, deterministic, byte-identical on re-run.

WHY THE JOIN CANNOT BE DEFERRED TO A PUBLISHER. It is fuzzy in exactly one place — Reaper's site
zero-pads product codes (`09412`) and the paint archive does not (`9412`) — and it is refusable
in two more (a code naming zero paints, a code naming several). A publisher doing this inline
would have to embed the normalisation rule and would have nowhere to put a refusal. Here both
are visible in a diff.

IDENTITY, and why each side is named the way it is:

- The SET is keyed by `CanonicalProduct.id` (`reaper/09901`). It is stable and committed. Paint
  ids are minted at publish time and so cannot appear on either side of this file.
- A MEMBER is named by `paint` ("{Name}|{Set}", the C# paint catalog's own lookup key) PLUS
  `productCode`. Both are required because {Name}|{Set} is NOT unique — paint identity is
  set|name|productCode|hex — and `productCode` is the exact tie-break HarvestApplier
  .ApplyEnrichment performs (`r.ProductCode == entry.Sku`, ordinal case-insensitive). Measured
  2026-08-07: reaper has 491 keys over 492 paints, the one collision being
  `Rose Gold|Master Series Paints Core Colors` (9337, 9608), which none of the 802 refs lands
  on. So `productCode` is inert today and mandatory anyway — a member shape without it breaks
  the first time a box contains one of a same-name pair.
- `ref` is the source's own code VERBATIM, before normalisation. It is the audit link back to
  the product record's `contentSkus`, and it is the only field showing both sides of the join.
- `name` on a set is a REVIEW LABEL copied off the product record — 29 opaque ids is not a
  reviewable relation. Never join on it; it is regenerated wholesale with the rest of the file.

REFUSALS ARE RECORDED, NEVER GUESSED. A ref naming zero or several paints goes to `unresolved:`
with its raw code and a reason (Catalog.pins, BrandHarvest.add_enrich,
HarvestApplier.ApplyEnrichment — "guessing which of two paints a photo belongs to is worse than
leaving both blank"). A file that reported 100% by dropping the misses would be the failure mode
this whole exercise is about.

THE ONE THING THAT MAY OVERRULE A PRINTED CODE IS A HUMAN, and the distinction is worth stating
precisely because this file elsewhere says a generator rewriting a source's claim is worse than
one that refuses. That prohibition is on INFERENCE: nothing here computes an edit distance, looks
for a nearest code, or fuzzy-matches a name to make its own output look complete.
`data/catalog/set-refs.yaml` (models/catalog.py::SetRefs) is the other thing — a maintainer states,
in a committed file, scoped to one product, with the evidence beside it, that a manufacturer
mistyped a code in its own prose. It is the same separation `overrides.yaml` draws everywhere else
in this repo, and it is reviewable in a diff. The corrected code changes only what is LOOKED UP:
`ref:` keeps the string the source printed and the member carries `resolvedBy: correction`, so
nothing is laundered. It is a FILE OF ITS OWN and not a key in overrides.yaml because
`classify --apply` rewrites that file wholesale and deleted this block once already (2026-08-11).

WHERE IT RUNS. Downstream of BOTH pipelines, which is the structural difference from its two
siblings: they run BEFORE the C# paint tool because they FEED it, this one runs AFTER because it
CONSUMES data/paints/brands/*.yaml. Its other input, data/catalog/products/*.yaml, is written by
`warhub-data resolve` in a different workflow. So it is wired into both
(.github/workflows/paint-catalog-update.yml after the tool step, catalog-acquire.yml after
"Resolve catalog"), and what actually stops it going stale is the byte-compare test in
tests/test_set_contents.py, not the workflow placement.

TWO PROVENANCES, ONE RELATION. `contentSkus` now reaches a product record two ways -- a source's
own contents array, or resolve/set_refs.py reading the codes out of the source's prose -- and a set
records which via `from:`. Prose is the weaker claim (not guaranteed exhaustive) and the relation
must not launder that away; see CanonicalProduct.contentSkusFrom for the measurements.

Runnable directly: `uv run --with pyyaml python tools/acquisition/scripts/gen_set_contents.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
PRODUCTS_DIR = REPO / "data/catalog/products"
BRANDS_DIR = REPO / "data/paints/brands"
OUT_DIR = REPO / "data/catalog/set-contents"
SET_REFS = REPO / "data/catalog/set-refs.yaml"

# Same pure-pyyaml sys.path bootstrap gen_paint_harvest.py documents at length: this script runs
# as `uv run --with pyyaml python ...` in CI, and both modules below import only stdlib + yaml.
sys.path.insert(0, str(REPO / "tools/acquisition/src"))
from warhub_acquisition.paints.catalog import Catalog  # noqa: E402
from warhub_acquisition.resolve.set_refs import enumerated_members  # noqa: E402
from warhub_acquisition.yamlio import dump_yaml  # noqa: E402

# MANUFACTURER slug (data/catalog/products/) -> the PAINT BRAND slugs (data/paints/brands/) whose
# archives its sets may draw members from, in search order.
#
# EXPLICIT BECAUSE THE FILENAME CANNOT IMPLY IT. The two directories are keyed by different
# namespaces and they already disagree: monument-hobbies/monument-pro-acryl,
# games-workshop/citadel-colour, mantic-games/army-painter. `reaper` matching `reaper` is a
# coincidence, and inferring from it would silently resolve the next manufacturer's set against
# the wrong catalog (or, worse, against a same-named file that happens to exist).
#
# A LIST, NOT ONE SLUG, and that is a correction rather than speculation. The first draft mapped
# one manufacturer to one brand, which cannot express a fact this catalog already contains:
# measured 2026-08-07, 40 product rows carry an Army Painter product code (WP/TL/ST/BR/GM/BF)
# under a DIFFERENT manufacturer -- mantic-games 17, warlord-games 23 -- plus
# `warlord-games/AK17522` (an AK Interactive box) and
# `mantic-games/vallejo-hellboy-paint-set-discontinued` (Vallejo). So warlord-games needs both
# `army-painter` and `ak-interactive`, and mantic-games both `army-painter` and `vallejo`. Under
# the 1:1 shape the second brand was simply unsayable.
#
# It is inert today: reaper is the only manufacturer stating contentSkus (29 products), and one
# brand answers all 802 of its refs. Landed now anyway, because the alternative is discovering
# it while writing the change that needs it and being tempted to "just pick one".
#
# RESOLUTION ACROSS BRANDS IS REFUSE-ON-AMBIGUITY, like everything else here: a ref naming
# exactly one paint in exactly one listed brand is a member; a ref naming a paint in SEVERAL
# brands is unresolved with all the candidates named. It is never decided by list order -- the
# order only bounds the search, never breaks a tie.
#
# A manufacturer with contentSkus and no entry here is REFUSED loudly and gets no file, which
# tests/test_set_contents.py::test_the_relation_covers_exactly_the_products_that_state_contents
# turns into a CI failure -- its `declared` side scans the product records, so a refused
# manufacturer shows up as `missing`. (This comment previously named a
# tests/test_gen_set_contents.py::test_file_roster_matches_manufacturers_with_contentskus that has
# never existed in this repo; the property held, the citation did not.) That is deliberate: a new
# set-shipping manufacturer needs a human to state its paint brands, not a heuristic to pick one.
MANUFACTURER_BRANDS = {
    "reaper": ["reaper"],
    # No longer inert. resolve/set_refs.py derives contentSkus from a set's own description, and
    # measured 2026-08-07 that selects the warlord-games products which are AK "Quick Gen" boxes
    # Warlord resells. `ak-interactive` answers nearly all of their refs; `army-painter` is listed
    # beside it because some warlord product rows do carry an Army Painter code, and measured, NONE
    # of these refs resolve there -- so naming both brands introduces no ambiguity today and states
    # the real search space rather than a lucky one.
    "warlord-games": ["army-painter", "ak-interactive"],
    # NO LONGER PRE-DECLARED, AND NO LONGER INERT -- this entry was written BEFORE the acquire that
    # made it live, and the note it carried has been overtaken. The refusal rule above exists so a
    # heuristic never picks a brand; the human it demands was the author of the commit that added
    # this line, who had already measured which archive answers these refs. That acquire has since
    # landed: `mfr-ak-interactive` now captures `short_description`, AK's boxed-set rows carry
    # descriptions, and resolve/set_refs.py reads their contents out of that prose.
    #
    # AK IS NOW THE LARGEST POPULATION IN THIS RELATION, by a wide margin -- more sets and more refs
    # than warlord-games and reaper combined -- so anything that changes the description parse is
    # felt here first. A small number of its refs land in `unresolved`; that is the rule working,
    # not failing. Re-derive from data/catalog/set-contents/ak-interactive.yaml's own `counts`.
    "ak-interactive": ["ak-interactive"],
    # The one manufacturer here whose memberships come from a SKU rather than from prose: a P3
    # case pack's own code is its colour's code minus the `-S` single suffix
    # (resolve/set_refs.py::content_skus_from_case_sku). `p3` is the only paint brand Steamforged
    # has in this archive, and the refs are `SFP3-N###-S`, which is exactly the `productCode` on
    # the relaunched `P3 Paints` records -- so every ref resolves by code with nothing to guess.
    #
    # These sets are one member each, which is unlike every other entry above and is the honest
    # shape: a pack of six of one colour contains one distinct paint. It is also why they clear
    # the >=2-code bar that `content_skus_from_description` imposes -- that bar exists to stop a
    # prose cross-reference being read as a set of one, and a SKU pairing is not prose.
    "steamforged-games": ["p3"],
}

HEADER = """\
# GENERATED by tools/acquisition/scripts/gen_set_contents.py -- do not hand-edit.
#
# WHAT IS IN EACH BOXED SET, resolved: every `contentSkus` ref on a CanonicalProduct
# (data/catalog/products/) joined ONCE, here, against the paint archive
# (data/paints/brands/), so a publisher only ever does an exact lookup. Reads only committed
# files, no network, deterministic.
#
# A member names a paint by `paint` ({Name}|{Set}) PLUS `productCode`: {Name}|{Set} is not
# unique (paint identity is set|name|productCode|hex) and `productCode` is the exact tie-break
# HarvestApplier.ApplyEnrichment does. Paint ids are minted at publish time and cannot be used
# here. `ref` is the source's own code VERBATIM, before normalisation -- the audit link back to
# the product record. `name` on a set is a REVIEW LABEL off the product record; never join on
# it. `brand` is the paint archive that was searched, and it is NOT derivable from this file's
# name: data/catalog/products/ is keyed by manufacturer and data/paints/brands/ by brand, and
# the two namespaces already disagree (monument-hobbies/monument-pro-acryl,
# games-workshop/citadel-colour).
#
# CODE NORMALISATION: a ref is tried verbatim, then with leading zeros stripped. Reaper's site
# zero-pads (09412) and its archive does not (9412). Re-measured over the committed files
# 2026-08-11: all 403 distinct reaper refs are 5 chars, the archive stores NO code with a leading
# zero (0 of 494), and 345 of the 403 match only after stripping. The 58 that match VERBATIM are
# 89501-89556 -- a contiguous block, listed by reaper/09967 and reaper/09968 ("Pathfinder Colors of
# Golarion" sets #1 and #2), every one resolving into `Master Series Paints Pathfinder` -- plus the
# 29xxx pair the site names only inside a box (29107 Gutter Grime, 29815 HD Dragon Blue; both since
# acquired, so they now resolve rather than refuse).
#
# THAT SENTENCE USED TO CALL THE 89xxx BLOCK "Bones Ultra-Coverage", and it was wrong in a way
# worth recording because it inverted the very thing this paragraph is about. The reaper archive
# holds no Ultra-Coverage set and no 890xx code at all. The REAL Bones Ultra-Coverage products --
# reaper/09966 and 09976-09981, 150 refs between them -- enumerate 094xx codes, of which 0 match
# verbatim and all 150 match only after `lstrip("0")`: the OPPOSITE normalisation category from the
# one the old wording filed them under.
#
# NO REF NEEDS ANY OTHER RULE -- and AK needs none at all: its refs are alpha-prefixed, so
# `lstrip("0")` is a no-op on every one of them, and the archive already stores the same zero-padded
# form the source prints (AK004, AK012, AK088). Do NOT "helpfully" extend the rule to strip zeros
# after the prefix. AK011/AK012/AK088/AK089 are genuinely absent from
# data/paints/brands/ak-interactive.yaml and AK11/AK88 do not exist either, so the only thing such
# a rule could do is convert honest refusals into silent misses.
#
# `from` ON A SET says where its refs came from, and the two are not the same claim. "stated" is a
# machine-readable contents array the source published (mfr-reaper's `associatedProducts`) and is
# exhaustive by construction. "description" is resolve/set_refs.py reading codes out of the
# source's own prose, which is NOT guaranteed exhaustive -- measured live 2026-08-07, a substantial
# minority of AK's boxed-set pages state a colour COUNT in words and enumerate nothing at all, and
# a few print a second, explicitly not-included bulleted list in the identical shape. Treat a
# "description" set as a LOWER BOUND on the box; treat a "stated" one as the box.
#
# ONE PHYSICAL BOX MAY APPEAR TWICE, under two manufacturers, and that is intended rather than a
# bug to de-duplicate. AK's "Quick Gen" boxes are sold by Warlord too, and because AK publishes
# ZERO barcodes anywhere the two product records can never join -- so `warlord-games/AK17522` and
# `ak-interactive/AK17522` are two records of one box, each stating its contents from its own
# source's words. This relation is keyed by PRODUCT id, not by box, so both belong in it; a test
# forbidding identical member sets under different manufacturers would forbid a true statement.
# What would be wrong is one of them silently winning.
#
# A ref naming ZERO or SEVERAL paints goes to `unresolved:` with its raw code and a reason.
# Nothing is guessed (Catalog.pins, BrandHarvest.add_enrich, HarvestApplier.ApplyEnrichment).
#
# A CODE THE SAME SET LISTS TWICE gets ONE extra question before it is refused, and only one: does
# the name the source printed beside that occurrence identify exactly one paint? warlord-games/
# AK17522 lists AK17068 as both "OLD GOLD" and "COLD STEEL" -- a typo in AK's own copy, since the
# archive holds Cold Steel at AK17070. The repeat resolves to Cold Steel BY NAME, keeps `ref:
# AK17068` verbatim, and carries `resolvedBy: statedName` so the repair is visible rather than
# laundered. This is the narrowest possible use of the second field: the first occurrence still
# resolves by code alone, so the branch cannot overturn any verdict the code already reached, and
# every uncertainty (no prose, misaligned prose, a name naming zero or several paints, or one
# already in the box) still refuses. See _stated_prose and _by_stated_name.
#
# A CODE THE MANUFACTURER MISTYPED carries the OTHER value of that field, `resolvedBy: correction`,
# and it is worth reading carefully because it is the one thing in this file that overrules a
# printed code without the source's own words settling it. It means: a HUMAN declared, in
# data/catalog/set-refs.yaml (models/catalog.py::SetRefs), scoped to ONE product id, with the
# evidence written out beside the entry, that the manufacturer mistyped a code in its own contents
# prose. ONLY a human may write one -- nothing here computes a correction, and nothing may: no edit
# distance, no nearest-code search, no fuzzy name match. The generator reads that file and applies
# an exact {stated ref: real code} substitution to what it LOOKS UP, and to nothing else, so `ref:`
# below still carries the string the source printed and `contentSkus` on the product record stays
# verbatim. The repair is a line in a diff, not a laundered value.
#
# IT IS THE DELIBERATE EXCEPTION TO THE DO-NOT-REPAIR RULE STATED FURTHER DOWN, and the distinction
# is INFERENCE vs a reviewed human statement: what is forbidden is a GENERATOR deciding for itself
# what a source meant in order to make its own output look complete. A maintainer stating a fact in
# a committed file and being reviewed on it is the same separation `overrides.yaml` draws
# everywhere else in this repo. It lives in its own file rather than in overrides.yaml because
# `classify --apply` rewrites that one wholesale and deleted the block once already (2026-08-11).
# Measured 2026-08-11, one member in this whole relation carries it: ak-interactive/AK11781's
# `AK111424` -> AK11424 (1 of 1,212 ak-interactive members; 0 of reaper's 802 and 0 of
# warlord-games' 90). tests/test_repo_data.py::test_every_set_ref_correction_is_live_and_resolvable
# holds every entry to both halves of its claim -- the mistyped ref must STILL be printed, and the
# corrected code must name exactly one paint IN THE BRANDS THIS MANUFACTURER ACTUALLY SEARCHES.
#
# A REFUSAL MAY BE A SOURCE COVERAGE GAP RATHER THAN BAD DATA -- do not "fix" one by hand-editing
# the paint archive. reaper/08906 -> 29815 and reaper/09916 -> 29107 were exactly that: both are
# material:"paint" on reapermini.com, but 29815's whole range (Master Series Paints High Density)
# had no `linePages` entry in data/catalog/sources/mfr-reaper.yaml, and 29107 was missing from the
# Core Colors singles population. The fix was to extend the descriptor and re-acquire, and that has
# since been done -- both resolve today. The RULE is what to carry forward, not the example:
# extend the source, never edit the archive to make a ref resolve.
#
# THIS RECORDS WHAT THE SOURCE'S CONTENTS ARRAY SAYS, NOT WHAT IS IN THE BOX, and the rule that
# follows is: a generator that rewrites a source's claim so its own output resolves is worse than
# one that refuses. reaper/08906 ("Learn To Paint Kit: Core Skills") is the worked example. Its
# `associatedProducts` lists 29815 "HD Dragon Blue", and while 29815 was still unacquired that ref
# was recorded as REFUSED rather than quietly repaired to the 9472 "Dragon Blue" the archive did
# hold -- a different pot in a different range, which is exactly the kind of thing a
# make-it-resolve repair invents. 29815 has since been acquired and resolves on its own terms.
#
# THE SENTENCE THIS REPLACES ASSERTED A DIVERGENCE THAT IS NOT IN THE DATA. It said 08906's "own
# description enumerates '09472-Dragon Blue' among its bottles" while the array said 29815, and
# measured 2026-08-11 against data/catalog/products/reaper.yaml that is wrong three ways: ZERO of
# the 115 reaper product records carry a `description` field at all (all 29 reaper sets are
# `from: stated`, per the `from` paragraph above), 09472 appears in no 08906 ref list, and the two
# products that DO enumerate it are reaper/09917 and reaper/09980. So for reaper the array-vs-prose
# divergence is currently unobservable, and the rule above now rests on the refusal, which is in
# the committed data, rather than on a second contents list that never was. If a
# `from: description` source ever contradicts its own array, THAT is the example to write here.
#
# QUANTITY. A member MAY carry `quantity: <int>` -- how many of that item the source states the
# box contains. ABSENT MEANS THE SOURCE DID NOT SAY, NOT ONE UNIT: writing `quantity: 1` everywhere
# would assert a count for every member reapermini.com never counted, and would be unrecoverable,
# since a fabricated 1 is indistinguishable from a measured one. `counts.quantified` therefore
# reports how many counts were ASSERTED, as a number rather than as a silence.
#
# REAPER STATES NONE. Its `associatedProducts` entries carry {sku, name, category, filename,
# material} and no count field of any kind (measured live 2026-08-07), so no strategy change can
# recover a quantity from that source, and the set comprehension in
# strategies/reaper.py::_content_skus discards nothing.
#
# AK STATES THEM IN PROSE, AND THEY NOW TRAVEL. `resolve/set_refs.py` captures a `- 2x AK17080 -`
# prefix, and `_stated_prose` below carries it onto the member along the same proven alignment the
# stated-name repair uses. Until that was wired the prefix was parsed and then dropped by
# `content_skus_from_description`, so `quantified` was pinned at 0 by the PIPELINE rather than by
# the sources -- it could not have reported a count even for a source that stated one.
#
# IT MAY STILL READ 0, and that is a different fact from "nobody states a count". A set enters this
# relation only if its description enumerates at least two DISTINCT codes (see
# `content_skus_from_description`), and the AK rows that state a quantity today enumerate exactly
# one code each, so the floor excludes them before this key can apply. Re-derive the current split
# with `enumerated_members` over the crossed AK rows.
"""


def paints_for_ref(catalogs: list[Catalog], code: str) -> list[tuple[Catalog, dict]]:
    """EVERY paint this manufacturer's search space offers for `code` -- 0, 1 or several.

    THE WHOLE RESOLUTION RULE, IN ONE PLACE, and public rather than `_`-prefixed because it has a
    second caller BY DESIGN: tests/test_repo_data.py::
    test_every_set_ref_correction_is_live_and_resolvable imports THIS function to decide whether a
    declared setRefs correction resolves. That guard used to spell the rule itself, and the two
    spellings disagreed in BOTH directions (measured 2026-08-11):

      - IT RESOLVED CODES THIS GENERATOR NEVER LOOKS AT. The guard globbed every file in
        data/paints/brands/ and passed on a repo-wide unique hit, so a correction pointing an
        ak-interactive ref at `RC078` -- which exists exactly once, in ak-real-color, an archive
        ak-interactive's sets never search -- was reported "live and resolvable" while this
        function returns [] and the generator writes `unresolved`. 4,925 of the 6,049 codes that
        are unique repo-wide (of 6,192 distinct codes across the 21 archives) sit outside
        ak-interactive's scope like that; warlord-games 4,701, reaper 5,555.
      - IT REFUSED CODES THIS GENERATOR RESOLVES. The guard did no zero-strip, so a reaper
        correction written in reaper's OWN printed vocabulary (`09412`) failed it with zero hits
        while resolving fine here. That is the normal shape rather than an edge case: 345 of
        reaper's 403 distinct refs are zero-padded and the archive stores 0 of its 494 codes with
        a leading zero.

    So this is the f181a73 rule -- a predicate spelled twice is a predicate that will disagree with
    itself -- applied to the PREDICATE, where paints/catalog.py already applied it to the index
    underneath.

    KEPT HERE, NOT IN paints/catalog.py BESIDE `Catalog`, and that is deliberate. The leading-zero
    fallback is a set-contents POLICY, not a property of a brand archive: HEADER above documents
    it, fences it ("do NOT extend the rule to strip zeros after the prefix") and is emitted into
    the committed files, so the rule and its warning stay in one place. `Catalog.paints_for_code`
    stays the raw, un-normalised question -- gen_paint_harvest.py imports that module too and must
    NOT strip, so it cannot pick this up by accident.

    `or code` keeps an all-zero code from normalising to "" and matching the blank-code bucket.
    Collected across EVERY listed brand: a code naming one paint in two different archives is
    genuinely ambiguous and must be refused, not won by whichever brand happens to be listed first.
    """
    return [
        (catalog, paint)
        for catalog in catalogs
        for paint in (catalog.paints_for_code(code)
                      or catalog.paints_for_code(code.lstrip("0") or code))
    ]


def _member_sort_key(member: dict) -> tuple:
    return (member["ref"], member.get("paint", ""))


def _stated_prose(product: dict) -> list[tuple[str, str, int | None]] | None:
    """What the source printed BESIDE each code -- name AND quantity -- aligned to `contentSkus`.

    None unless the alignment is PROVEN rather than assumed: the codes re-read out of the
    description must equal `contentSkus` element-for-element, in order. Anything less and both the
    name and the count are dropped -- either one attached to the wrong code is a fabricated fact,
    and this function exists to repair exactly that kind of mistake, so it must not be able to
    make one.

    None for a `stated` product too. A machine-readable contents array (reaper's
    `associatedProducts`) has no prose to re-read, so a repeat there stays refused: the source
    genuinely said the same code twice and said nothing else to tell the two apart.

    THIS IS THE ONLY PATH A QUANTITY CAN TRAVEL, which is why this returns the whole triple rather
    than just the names. `contentSkus` is a flat list of codes and carries no counts, so re-reading
    the description HERE -- against an alignment the product record itself proves -- is what lets
    the quantity prefix `resolve/set_refs.py` captures reach a member. Before this it was parsed
    and then discarded one function later, so `counts.quantified` could only ever be 0.
    """
    if (product.get("contentSkusFrom") or "stated") != "description":
        return None
    enumerated = enumerated_members(product.get("description"))
    if [code for code, _, _ in enumerated] != list(product["contentSkus"]):
        return None
    return enumerated


def _attach_quantity(member: dict, prose: list[tuple[str, str, int | None]] | None, index: int) -> None:
    """Copy the source's stated per-member count onto `member`, when it stated one.

    ABSENT MEANS THE SOURCE DID NOT SAY, NOT ONE UNIT -- so a member the source gave no count for
    gets no key at all rather than a defaulted 1, and `counts.quantified` stays a count of what was
    actually asserted rather than of what was assumed.
    """
    quantity = prose[index][2] if prose else None
    if quantity is not None:
        member["quantity"] = quantity


def _by_stated_name(name: str | None, catalogs: list[Catalog]) -> tuple[Catalog, dict] | None:
    """The ONE paint the source's stated name identifies, across every listed brand -- or None.

    Deliberately stricter than `match_name` alone. That returns a "{Name}|{Set}" key, and a key
    can be answered by several paints (mr-hobby ships Mr Color 20 and 323 both named "Light
    Blue"); a member must name ONE pot because it carries that pot's `productCode`. So the key
    must be unambiguous within its catalog AND unique across the catalogs searched.
    """
    hits: list[tuple[Catalog, dict]] = []
    for catalog in catalogs:
        key = catalog.match_name(name)
        if key is None:
            continue
        paints = catalog.by_key.get(key, [])
        if len(paints) != 1:
            return None
        hits.append((catalog, paints[0]))
    return hits[0] if len(hits) == 1 else None


def resolve_manufacturer(manufacturer: str, products: list[dict], catalogs: list[Catalog],
                         set_refs: dict[str, dict[str, str]] | None = None) -> dict:
    """The whole relation for one manufacturer: {counts, sets}.

    `catalogs` is every paint archive this manufacturer's sets may draw from, in search order --
    see MANUFACTURER_BRANDS for why that is a list. A ref is looked up in ALL of them and the
    verdict is on the union, so list order bounds the search without ever breaking a tie.
    """
    sets: dict[str, dict] = {}
    n_refs = n_members = n_unresolved = 0
    brands = ", ".join(c.slug for c in catalogs)
    for product in sorted(products, key=lambda p: p["id"]):
        members: list[dict] = []
        unresolved: list[dict] = []
        seen_refs: set[str] = set()
        prose = _stated_prose(product)
        # Maintainer-declared repairs for codes THIS product mistypes, keyed by the ref as printed
        # (models/catalog.py::SetRefs). Nothing is computed here -- an entry exists only because
        # somebody wrote it and cited the evidence in data/catalog/set-refs.yaml.
        corrections = (set_refs or {}).get(product["id"], {})
        for i, ref in enumerate(product["contentSkus"]):
            n_refs += 1
            # A CODE THE SOURCE LISTS TWICE IN ONE BOX IS NEVER RESOLVED TWICE BY CODE. Measured
            # 2026-08-07: warlord-games/AK17522 "Metallics" enumerates AK17068 as both "OLD GOLD"
            # (which the archive confirms at AK17068) and "COLD STEEL" (which the archive holds at
            # AK17070) -- a typo in AK's own copy. Resolving both occurrences by code would claim
            # the box holds two pots of Old Gold and lose Cold Steel entirely; de-duplicating
            # upstream would lose it just as silently.
            #
            # THE CODE IS THE KEY; THE STATED NAME IS THE TIE-BREAK, consulted ONLY here, where the
            # source has contradicted itself. The first occurrence resolves by code exactly as
            # before -- this branch cannot change any verdict the code alone already reached. A
            # repeat asks a different question, because its code is spoken for: does the name the
            # source printed beside THIS occurrence identify exactly one paint? For AK17522 it
            # does, "COLD STEEL" -> Cold Steel|Quick Gen at AK17070, and `ref` keeps the typo
            # AK17068 verbatim so the repair is legible in a diff rather than laundered.
            #
            # This is not guessing (Catalog.pins, BrandHarvest.add_enrich): nothing is invented,
            # a second field the SOURCE ITSELF wrote decides, and every way of failing to be
            # certain -- no prose, misaligned prose, a name naming zero paints, several paints,
            # or one already in this box -- still refuses, with the reason saying which.
            #
            # Inert for reaper: strategies/reaper.py builds contentSkus from a SET, reapermini.com
            # repeats no sku in any of its 31 set items (measured live 2026-08-07 over 848
            # associatedProducts entries), and a `stated` product has no prose to consult anyway.
            if ref in seen_refs:
                stated = prose[i][1] if prose else None
                hit = _by_stated_name(stated, catalogs) if stated else None
                if hit is not None and not any(
                    m["brand"] == hit[0].slug and m["paint"] == hit[0].key_of(hit[1])
                    for m in members
                ):
                    catalog, paint = hit
                    repaired = {
                        "ref": ref,
                        "brand": catalog.slug,
                        "paint": catalog.key_of(paint),
                        "productCode": str(paint.get("productCode") or ""),
                        # WHY THIS MEMBER'S productCode DISAGREES WITH ITS ref. Present only on
                        # the name-resolved repeats, so its absence is the norm and its presence
                        # is a flag: a reviewer sorting on this field sees every place the
                        # source's own code list was overruled, and by what.
                        "resolvedBy": "statedName",
                        "statedName": stated,
                    }
                    _attach_quantity(repaired, prose, i)
                    members.append(repaired)
                    continue
                if not stated:
                    why = ("and the source states no name beside this occurrence to tell it "
                           "apart -- its contents are not prose-derived, or the description no "
                           "longer re-reads to this exact code list")
                elif hit is None:
                    why = (f"and the name stated beside this one ({stated!r}) names no single "
                           f"paint in brand(s) '{brands}'")
                else:
                    why = (f"and the name stated beside this one ({stated!r}) names a paint "
                           f"already in this set")
                unresolved.append({
                    "ref": ref,
                    "reason": f"this set lists the same product code more than once {why}",
                })
                continue
            seen_refs.add(ref)
            # A declared correction replaces the code we LOOK UP and nothing else: `ref` below
            # stays the string the source printed, so the repair is legible in the committed file
            # instead of laundered into it.
            #
            # The lookup itself is `paints_for_ref` (verbatim, then leading-zero-stripped, across
            # every listed brand) rather than the expression it used to be, because the setRefs
            # guard has to reach the SAME verdict and was reaching a different one in both
            # directions -- see that function.
            lookup = corrections.get(ref, ref)
            hits: list[tuple[Catalog, dict]] = paints_for_ref(catalogs, lookup)
            if len(hits) == 1:
                catalog, paint = hits[0]
                member = {
                    "ref": ref,
                    # The archive this ref actually resolved in -- per MEMBER, because one box can
                    # legitimately mix brands (a Warlord set of Army Painter pots that also ships
                    # an AK bottle). The set-level `brand` says what was SEARCHED; this says what
                    # was FOUND, and only this one is safe to join on.
                    "brand": catalog.slug,
                    "paint": catalog.key_of(paint),
                    "productCode": str(paint.get("productCode") or ""),
                }
                if lookup != ref:
                    # Same shape the stated-name repair uses: the member says WHY its productCode
                    # disagrees with its ref, so `resolvedBy` sorts every overruled code into view
                    # whether a human or the source's own words did the overruling.
                    member["resolvedBy"] = "correction"
                _attach_quantity(member, prose, i)
                members.append(member)
            elif not hits:
                # The reason NAMES THE TWO CASES, because they need opposite responses and the
                # bare fact does not distinguish them. Both were live in this file at once:
                # reaper/08906 -> 29815 was a coverage gap (the site states the paint inside its
                # sets and the strategy was not reading it -- fixed by acquiring it), while
                # warlord-games/AK17524 -> AK17082 was a paint that genuinely has no listing
                # anywhere, because AK makes "Wolf Blue Grey" for that one box and says so in the
                # set's own description. The first is fixed upstream; the second can only ever be
                # fixed here, by minting the record, and a reviewer told merely "no paint carries
                # this code" reads BOTH as "go and acquire it" and waits forever on the second.
                unresolved.append({
                    "ref": ref,
                    "reason": (
                        f"no paint in brand(s) '{brands}' carries this product code -- either it "
                        "has not been acquired yet (fix the source), or the manufacturer makes it "
                        "only for this set and lists it nowhere, in which case mint it in "
                        "data/paints/overrides.yaml `additions:` with `soldSeparately: false` "
                        "rather than leaving it refused forever"
                    ),
                })
            else:
                # Refused, not decided by file order. reaper has 0 duplicated codes of 492 so
                # this is dead for the only brand here today, but 198 codes across the 21 brand
                # files are duplicated (measured 2026-08-07) -- see Catalog._paints_by_code. The
                # same branch now also catches a code that resolves in two DIFFERENT brands.
                unresolved.append({
                    "ref": ref,
                    "reason": (f"{len(hits)} paints in brand(s) '{brands}' carry this product "
                               f"code: "
                               + ", ".join(sorted(f"{c.slug}/{c.key_of(p)}" for c, p in hits))),
                })
        n_members += len(members)
        n_unresolved += len(unresolved)
        # `from` is copied off the product record, never inferred here: the generator cannot tell
        # a prose-derived list from a stated one by looking at the refs, and guessing would be
        # exactly the laundering this field exists to prevent. Defaults to "stated" so a record
        # written before the field existed reads as the stronger claim it was.
        entry: dict = {
            "name": product.get("name") or "",
            "brand": brands,
            "from": product.get("contentSkusFrom") or "stated",
        }
        if members:
            entry["members"] = sorted(members, key=_member_sort_key)
        if unresolved:
            entry["unresolved"] = sorted(unresolved, key=lambda u: u["ref"])
        sets[product["id"]] = entry

    quantified = sum(1 for s in sets.values() for m in s.get("members", []) if "quantity" in m)
    return {
        # Derivable from the body, and that is fine: `refs` vs `members` is the first thing a
        # reviewer reads and the cheapest thing a reproducibility test can assert.
        "counts": {
            "sets": len(sets),
            "refs": n_refs,
            "members": n_members,
            "unresolved": n_unresolved,
            "quantified": quantified,
        },
        "sets": sets,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Read data/catalog/set-refs.yaml with plain yaml, not the SetRefs model: this script runs in
    # CI as `uv run --with pyyaml python ...` and importing pydantic here would break that line.
    # The model still validates the same file in test_repo_data.py, so a malformed block fails
    # loudly there rather than being tolerated everywhere.
    set_refs = ((yaml.safe_load(SET_REFS.read_text(encoding="utf-8")) or {}).get("setRefs")
                if SET_REFS.exists() else None) or {}
    written: set[str] = set()
    refused: list[str] = []

    for path in sorted(PRODUCTS_DIR.glob("*.yaml")):
        manufacturer = path.stem
        catalog_doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        products = [p for p in (catalog_doc.get("products") or []) if p.get("contentSkus")]
        if not products:
            continue
        brands = MANUFACTURER_BRANDS.get(manufacturer)
        if not brands:
            refused.append(manufacturer)
            continue
        catalogs = [Catalog(b, BRANDS_DIR) for b in brands]
        brand = ", ".join(brands)
        if not any(c.paints for c in catalogs):
            # The paint archive is written by a different pipeline (the C# tool). On a fresh
            # clone, or if this ever runs before that tool, resolving would refuse every ref and
            # commit a file claiming the whole brand is missing. Skip instead -- same posture as
            # gen_paint_barcodes.py's absent-evidence skip.
            print(f"SKIP {manufacturer}: paint archive data/paints/brands/{brand}.yaml is empty "
                  f"or absent; leaving any existing set-contents file untouched.")
            written.add(manufacturer)
            continue

        relation = resolve_manufacturer(manufacturer, products, catalogs, set_refs)
        out = OUT_DIR / f"{manufacturer}.yaml"
        # write_bytes (not write_text) so the committed file is LF on every platform -- write_text
        # would emit CRLF on Windows and churn the diff for a maintainer running this locally.
        # dump_yaml (not yaml.safe_dump) because refs and product codes are zero-padded numeric
        # strings: safe_dump emits `ref: 09148` unquoted, which a YAML 1.2 consumer reads as a
        # number. yamlio force-quotes exactly that shape.
        out.write_bytes((HEADER + dump_yaml({manufacturer: relation})).encode("utf-8"))
        written.add(manufacturer)
        counts = relation["counts"]
        print(f"{manufacturer} -> {out.relative_to(REPO)}: {counts['sets']} sets, "
              f"{counts['refs']} refs -> {counts['members']} members, "
              f"{counts['unresolved']} unresolved, {counts['quantified']} with a quantity")
        for set_id, entry in relation["sets"].items():
            for u in entry.get("unresolved", []):
                print(f"    UNRESOLVED {set_id} ref={u['ref']}: {u['reason']}")

    # The output directory is written by nothing else, so a file with no surviving inputs is a
    # fossil that a byte-compare test would happily pass. Delete it rather than let the relation
    # outlive the relation it describes.
    for stale in sorted(OUT_DIR.glob("*.yaml")):
        if stale.stem not in written:
            stale.unlink()
            print(f"REMOVED stale {stale.relative_to(REPO)} (manufacturer states no contentSkus)")

    for manufacturer in refused:
        print(f"REFUSED {manufacturer}: states contentSkus but has no MANUFACTURER_BRANDS entry -- "
              f"add one naming its paint brand slug(s); nothing is guessed here.")


if __name__ == "__main__":
    main()
