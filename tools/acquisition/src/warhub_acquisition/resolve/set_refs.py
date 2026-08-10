"""Derive `contentSkus` from a boxed set's own prose, when the source states no structured list.

WHY THIS EXISTS. `mfr-reaper` is the only source that hands us a machine-readable contents array
(`associatedProducts`). Every other brand states what is in the box in a `description` -- and for
AK Interactive that prose is exhaustive and code-bearing, so the membership is already in evidence
and only needs reading. THIS RULE SERVES TWO POPULATIONS: warlord-games (whose descriptions come
from the frozen `legacy-catalog` import) and ak-interactive (whose exhaustive prose describes
contents in code-bearing detail), with AK Interactive now the dominant consumer. Re-derive counts
with `enumerated_members` over the committed product descriptions.

WHY AT RESOLVE TIME, which is the one structural decision here and was got wrong twice on the way:

- NOT in the strategy. Parsing at acquire time is the classification `shopify_paints.py` and
  `mr_hobby.py` exist to forbid: a better regex tomorrow would then cost a full re-fetch instead
  of a `warhub-data resolve` run. The strategy's job is to store the source's words verbatim.
- NOT in tools/acquisition/scripts/gen_set_contents.py. `contentSkus` is populated ONLY from
  `Observation.hints` (resolve/attributes.py:_HINT_FIELDS), which only a strategy writes, so a
  bridge-side parse cannot reach the field at all. It would have to invent a second, parallel
  member source -- and then
  test_set_contents.py::test_the_relation_covers_exactly_the_products_that_state_contents, whose
  whole job is to cross-check the relation against the products that DECLARE contents, would see
  every description-derived set as `extra` and have to be rewritten into a self-check against the
  generator's own regex. Deriving here instead puts the refs on the product record, so that test
  keeps cross-checking two independent things and needed no change at all.
- NOT declared per-source beside `crossoverToProducts`, which was the other candidate. Two
  reasons, both measured. (a) `description` is folded FIRST-WINS across members of different
  sources, so after the fold no single descriptor owns it: warlord-games/AK17501's description
  comes from `legacy-catalog` while ak-interactive/AK17501's will come from `mfr-ak-interactive`,
  and one physical box would need the identical rule declared twice. (b) `legacy-catalog` is
  `kind: curated` / `strategy: none` with no scope at all, and SourceDescriptor forbids
  `crossoverToProducts` on a `catalog: products` source -- there is literally nowhere on that
  descriptor to put it.

AND NOT IN data/catalog/overrides.yaml, which is the loophole worth refusing on the record:
`apply_overrides` revalidates the merged record, so a maintainer COULD hand-write these 90 refs
onto the 24 warlord rows and leave every test byte-identical. Don't. It would hand-copy refs the
description already states, go stale the moment the description changes, turn "a better regex
tomorrow" into a hand re-edit, and not scale to AK's own boxed-set rows at all -- which now
outnumber Warlord's many times over, so the hand-written alternative was never going to hold.

THE REF PATTERN IS AK-SPECIFIC ON PURPOSE, and that is a measurement rather than a preference.
NO OTHER BRAND ENUMERATES MULTIPLE ARMY PAINTER CODES (WP/TL/ST/BR/GM/BF + 3-4 digits), Vallejo
`7x.xxx`, or Scale75 `SSE-`/`SFLOW-` in boxed-set descriptions, so a brand-generic rule would
earn nothing and would put every other brand's prose inside the blast radius. The pattern also
excludes the corpus's one real false positive: `AK-47`, in mantic-games/MGWD126 and
mantic-games/MGWEB777 (Walking Dead equipment cards) -- excluded twice over, by the 3-digit floor
and by permitting no separator.

Deliberately NOT matched: `RC\\d{3}` (ak-real-color). Most of that archive's distinct codes are
duplicated across its paints, so nearly every such ref would refuse anyway -- and not one AK set's
prose names one.
"""
from __future__ import annotations

import html as html_lib
import re

# A code the SOURCE PROSE prints. Anchored to a list item, never free-floating, because AK's own
# copy cross-references retired and companion codes in flowing sentences (live 2026-08-07,
# AK11621: "...in miniature (previously AK3010)") and a whole-text sweep would enrol them as
# members. On committed data the anchor costs nothing -- it captures every token a free-floating
# `\bAK\d{3,5}\b` finds -- so it is pure future-proofing bought at zero present price.
#
# SIX DIGITS ARE ALLOWED THOUGH NO PAINT HAS THAT MANY, which looks wrong and is deliberate. Live
# 2026-08-07, AK11781 lists "- AK111424 - Grey Green": a typo for AK11424, on a properly formed
# bullet. Under `AK\d{3,5}` that line matches nothing and vanishes with no trace anywhere. Under
# `AK\d{3,6}` it becomes a ref that gen_set_contents.py refuses BY NAME, which is what this whole
# relation is for. Widening the ceiling changes exactly one token.
_REF = r"AK\d{3,6}"

# THERE IS DELIBERATELY NO "Contains:" ANCHOR, and that is a reversal worth recording because it
# is the obvious design and it is wrong. Anchoring the scan to a contents header would read well on
# committed sets that use a clean standalone "Contains:" line -- but a header anchor can only earn
# anything by SKIPPING member-shaped lines that precede it, and the only lines it ever skipped were
# real members. AK8253 prints a late "INCLUDES:" sub-header (for the acetate sheet and paper
# posters) BELOW its paints, and a first-header rule silently dropped all of that set's refs.
# Removing the anchor changes exactly one set, and changes it from no members to all of them.
#
# What actually keeps prose out of the membership is the BULLET requirement in _MEMBER, not a
# header: live-verified 2026-08-07, AK11621's copy says "...in miniature (previously AK3010)"
# mid-sentence, and that is excluded because it is not on a list item, with or without an anchor.

# STOP HERE, and this is the correction that matters most in this file. AK enumerates NOT-INCLUDED
# items in exactly the same bulleted, code-bearing shape as real contents. A few sets carry such a
# marker and EVERY member-shaped line after it is a not-included item: AK11701 "*These acrylic
# effects are not included:" and AK8252/8253/8254/8255 "OPTIONAL MATERIALS (not included)". A rule
# that simply harvested every list item in the block would publish those lines as members of the
# box, which is a fabricated claim -- strictly worse than the missing member it is trying to avoid,
# because a refusal is visible and a false membership is not.
_EXCLUDED = re.compile(r"not\s+included|no\s+incluid|optional\s+material", re.I)

# SEPARATOR IS NOT ALWAYS A SPACE, and requiring one silently lost a whole set. The first draft
# was `({_REF})\s+`, which rejects every bullet AK writes with a comma -- measured 2026-08-07,
# ak-interactive/AK11774 "WWII JAPANESE ARMY AFV COLORS" prints `<li>AK11435, IJA KHAKI (Field
# Drab)</li>` for its members. All codes resolve to exactly one archive paint, but the set fell
# below the two-distinct-codes floor, `content_skus_from_description` returned None, and the refs
# appeared in NEITHER `members` NOR `unresolved` -- the exact vanishing the relation's own
# invariant forbids, and invisible because the set simply was not in the file.
#
# A punctuation separator OR whitespace, never neither: `AK11435IJA` must not split into a code
# and a name, so the alternation requires at least one of the two.
#
# QUANTITY PREFIX. AK writes `- 2x AK17080 - MEDIUM FOR QUICK GEN PAINTS (18ml)`. The anchored
# rule rejected that line outright, so it vanished rather than landing without its count -- and
# `counts.quantified: 0` is documented as "the source did not say", which would have been false
# the moment a PAINT bullet carried one.
#
# CAPTURED HERE AND CARRIED THROUGH, which needs saying because the two halves live in different
# files: this regex captures the count, and gen_set_contents.py::_stated_prose is what puts it on
# a member -- by re-reading this same enumeration against an alignment the product record proves.
# `content_skus_from_description` below deliberately returns CODES ONLY, because `contentSkus` is
# a flat code list by design; the prose, not that field, is what carries the count. Wiring the
# second half is what stopped `quantified` being pinned at 0 by the pipeline itself.
_MEMBER = re.compile(
    rf"^[-*•]\s*(?:(\d+)\s*[xX×]\s*)?({_REF})(?:\s*[,;:\-–—]\s*|\s+)(\S.*)$"
)

_TAG = re.compile(r"<[^>]+>")
_LIST_ITEM_OPEN = re.compile(r"<li\b[^>]*>", re.I)
_LINE_BREAK = re.compile(r"</(?:li|p|ul|ol|div|h[1-6])\s*>|<br\s*/?>", re.I)
# The accordion AK wraps every description in. See _first_language_block.
_LANGUAGE_BLOCK = re.compile(r"<span[^>]*class=\"[^\"]*collapseomatic", re.I)


def _first_language_block(description: str) -> str:
    """The first of the source's language blocks, or the whole text when there is only one.

    THE SINGLE MOST LOAD-BEARING BOUND HERE. Live-verified 2026-08-07 on AK's `paints-acrylics`
    rows: `short_description` is a collapseomatic accordion carrying the FULL ENGLISH BLOCK AND THE
    FULL SPANISH BLOCK in one field, each with its own `<ul>` of the SAME codes under its own
    header ("Contains:" / "Contiene:"). Boxed-set rows carry both markers and English is first --
    which is also what the descriptor asks for (`scope.extraParams.lang: en`). Without this cut
    every AK set would report its members exactly twice, and gen_set_contents.py's within-set
    repeat rule would then refuse half of them.

    Cut on the SECOND accordion span rather than on `id="esplang"`: the position is what we know
    (English first, because we asked for English), and a language-specific id would silently take
    the whole thing the day AK adds a third language or renames the container.
    """
    blocks = list(_LANGUAGE_BLOCK.finditer(description))
    return description[: blocks[1].start()] if len(blocks) > 1 else description


def _to_lines(description: str) -> list[str]:
    """Flatten a description to plain text lines, whether it arrived as markdown or as HTML.

    MECHANICAL, NOT INTERPRETIVE -- it renames `<li>` to `- ` and drops tags, which is the same
    thing a browser does to lay the prose out. It is here rather than in the strategy so the
    stored evidence stays byte-verbatim: AK's Store API answers `short_description` as raw HTML
    (live-verified 2026-08-07) while `legacy-catalog`'s frozen import holds the markdown a human
    curated, and both must reach one rule.
    """
    text = _LIST_ITEM_OPEN.sub("\n- ", description)
    text = _LINE_BREAK.sub("\n", text)
    return [html_lib.unescape(_TAG.sub("", line)).strip() for line in text.split("\n")]


def enumerated_members(description: str | None) -> list[tuple[str, str, int | None]]:
    """`(code, stated name, quantity or None)` per enumerated line, SOURCE ORDER, duplicates KEPT.

    Every member-shaped line in the first language block, up to the first not-included marker. NOT
    a single contiguous run: some AK sets split their contents over several lists under sub-headings
    ("3Gen Acrylics:", "Enamel Effects:", "Brushes:"), and a run-based rule would truncate
    AK11757 and AK11763 early. Interleaved prose is skipped rather than treated as a terminator,
    which also means one malformed bullet no longer silently ends the list -- measured,
    AK11781's "AK111424" typo did exactly that.

    DUPLICATES ARE KEPT rather than collapsed, and that is the point of capturing the stated name
    even though nothing joins on it. warlord-games/AK17522 lists AK17068 twice -- as "OLD GOLD"
    (which the archive confirms) and as "COLD STEEL" (which the archive holds at AK17070). A
    de-duplicating rule silently drops Cold Steel with no trace anywhere in the relation; keeping
    the repeat lets gen_set_contents.py refuse it by name, which is the whole reason that file
    exists.
    """
    lines = _to_lines(_first_language_block(description or ""))
    end = next((i for i, line in enumerate(lines) if _EXCLUDED.search(line)), len(lines))
    return [
        (match.group(2), match.group(3).strip(), int(match.group(1)) if match.group(1) else None)
        for match in (_MEMBER.match(line) for line in lines[:end])
        if match
    ]


def content_skus_from_description(description: str | None) -> list[str] | None:
    """The refs a description enumerates, or None when it enumerates no membership.

    >=2 DISTINCT CODES REQUIRED. A single code on a bullet is a cross-reference ("pairs well
    with..."), not a boxed set of one, and calling it a membership would publish a one-item set
    for every singles page that mentions a companion pot. THIS RULE DOES EXCLUDE A FEW ROWS: some
    AK descriptions enumerate exactly one code, and those rows are correctly filtered out. These
    excluded rows happen to be precisely the ones that state a per-member quantity -- so
    `counts.quantified: 0` is partly the source's silence and partly this bar's work.
    """
    refs = [code for code, _name, _qty in enumerated_members(description)]
    if len(set(refs)) < 2:
        return None
    return refs
