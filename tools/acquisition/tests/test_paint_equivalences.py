# tools/acquisition/tests/test_paint_equivalences.py
"""data/paints/equivalences.yaml: every paint it names must still be a paint the archive holds.

WHAT BREAKS WITHOUT THIS: an equivalence names a paint by VALUE -- there is no id and no foreign
key -- so renaming, re-coding, recolouring or retracting a record does not break the link, it
leaves it pointing at nothing. And the consumer is silent about that by construction:
PaintBuilder.Assemble folds this file into the published catalog by looking each ref up in
`idByNaturalKey` and `continue`-ing when it misses (PaintBuilder.cs:178-200), so a dangling ref is
not an error, it is an equivalent that quietly stops being published. The paint keeps its entry,
just with fewer substitutes than the catalog computed -- and the diff shows nothing, because
retracting a paint over in data/paints/brands/ does not touch a byte of this file.

THIS IS THE NET UNDER ANY IDENTITY-KEY CHANGE, and it is not hypothetical. The equivalence pass
used to run on `allCatalogs`, built from the PRE-reconciliation working list, while `retract:`
removes records only from the reconciler's OUTPUT. Retracting AK's 194 category-duplicate records
left 405 dangling sources and 1,855 dangling match rows, and a second full run reproduced the
identical numbers, so it was not a stale-file problem (PaintCatalogApp.cs:578 -- the fix rebuilds
each BrandCatalog from `finalRecords` before the equivalence pass runs).

THE JOIN KEYS ARE THE TOOLS' OWN, BOTH OF THEM, because there are two different questions and they
fail differently:

  * (brandSlug, name, set, productCode) -- IS THE RECORD STILL THERE. These are the fields
    PaintRecordMapper.ToPaint:20 carries off an archived PaintRecord into the flat `Paint` that
    EquivalenceFinder reads, and the ones it writes back per ref
    (EquivalenceFinder.cs:103-124). `brand` is a display name, so it is not part of the key.
  * the same four PLUS the normalized hex -- CAN THE PUBLISHER STILL RESOLVE IT.
    PaintBuilder.NaturalKey is `brandSlug|name|set|code|hex` (PaintBuilder.cs:20), matching
    PaintRecordAdapter.IdentityKey upstream, and hex is in it because two records can share
    brand|name|set|code and be DIFFERENT COLOURS. A ref that passes the first check and fails this
    one is a paint that was RECOLOURED -- and then the `deltaE` this file states was computed from
    a colour the archive no longer holds, so the number is stale even though the paint is alive.

Measured 2026-08-11 over the 8,461 committed records: 7,893 sources and 39,413 match rows, 0
dangling in either role under either key. Every ref carries a hex (0 of 47,306 missing), so the
stricter check is never vacuously satisfied by a blank.

Existence, not uniqueness: 2 of the 8,461 records share a four-field key with another
(citadel-colour "Kommando Khaki|Foundation (discontinued)" with no productCode, and vallejo
"Viking Grey|Xpress Color Intense|72.483") -- the same two PaintBuilder's comment names as the
reason hex joined its key. Adding hex makes all 8,461 distinct.

Its own module rather than test_repo_data.py: that file is 851 lines of data/catalog guards, and
this pays 8.6 s (measured 2026-08-11) to parse the largest committed file in the repo, 8.8 MB --
worth being able to deselect on its own, and worth parsing ONCE for both checks below.
"""
from pathlib import Path

import pytest

from warhub_acquisition.yamlio import read_yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
BRANDS_DIR = REPO_ROOT / "data/paints/brands"
EQUIVALENCES = REPO_ROOT / "data/paints/equivalences.yaml"


def _hex(value: object) -> str:
    """PaintBuilder.NormalizeHex (PaintBuilder.cs:321): trim, lowercase, ensure a leading '#'.
    Both sides normalize identically so '#9B8C7B' and '#9b8c7b' are one key; blank stays blank."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return text if text.startswith("#") else f"#{text}"


def _ref(record: dict, brand_slug: str, *, archived: bool) -> tuple[str, str, str, str, str]:
    """One paint's key, from either side. `archived` picks where set/hex live: a brand archive
    nests them under `details`, an equivalence ref carries them flat."""
    inner = (record.get("details") or {}) if archived else record
    return (
        brand_slug,
        str(record.get("name") or ""),
        str(inner.get("set") or ""),
        str(record.get("productCode") or ""),
        _hex(inner.get("hex")),
    )


@pytest.fixture(scope="module")
def catalog() -> tuple[set, list]:
    """The committed archive and the committed equivalences, parsed once for both tests.

    Same guard as _require_repo_data() in test_repo_data.py: this package can be built and tested
    outside the monorepo (sdist), where ../../../../data does not exist -- skip cleanly.
    """
    if not EQUIVALENCES.exists() or not BRANDS_DIR.exists():
        pytest.skip("no committed paint archive / equivalences (tested outside the monorepo)")

    live: set[tuple[str, str, str, str, str]] = set()
    for path in sorted(BRANDS_DIR.glob("*.yaml")):
        archive = read_yaml(path) or {}
        # The archive states its own slug; the filename is only a fallback, because the slug is
        # what EquivalenceFinder copied off the BrandCatalog when it wrote these refs.
        slug = str(archive.get("brandSlug") or path.stem)
        for record in archive.get("paints") or []:
            live.add(_ref(record, slug, archived=True))
    assert live, "no paint records read -- the join would be vacuously clean"

    equivalences = (read_yaml(EQUIVALENCES) or {}).get("equivalences") or []
    assert equivalences, "equivalences.yaml holds no entries"
    return live, equivalences


def _refs(equivalences: list):
    """Every ref in the file, in both roles. The relation is symmetric -- a `source` is one paint's
    whole entry, a `matches[].paint` is one row inside somebody else's -- and the publisher must
    resolve BOTH ends before it can link a pair, so neither role is the safe one to skip."""
    for entry in equivalences:
        source = entry.get("source") or {}
        source_key = _ref(source, str(source.get("brandSlug") or ""), archived=False)
        yield "source", source_key, source_key
        for match in entry.get("matches") or []:
            paint = match.get("paint") or {}
            yield ("match", source_key,
                   _ref(paint, str(paint.get("brandSlug") or ""), archived=False))


def test_no_equivalence_names_a_paint_the_archive_no_longer_holds(catalog) -> None:
    """The retraction/rename half: does a record with this (brandSlug, name, set, productCode)
    still exist at all? Measured 2026-08-11: 0 of 47,306 refs dangling."""
    live, equivalences = catalog
    live4 = {key[:4] for key in live}

    dangling = [(role, source[:4], key[:4]) for role, source, key in _refs(equivalences)
                if key[:4] not in live4]
    assert not dangling, (
        f"{len(dangling)} equivalence ref(s) name a paint that is not in data/paints/brands/ -- "
        "it was renamed, re-coded or retracted and this file was not rebuilt from the ARCHIVED "
        "records. Regenerate the paint catalog with --equivalences rather than hand-editing this "
        f"file. Shown as (role, source paint, missing paint). First 5: {dangling[:5]}"
    )


def test_every_equivalence_ref_still_resolves_under_the_publisher_key(catalog) -> None:
    """The recolour half: PaintBuilder joins on `brandSlug|name|set|code|hex`, so a ref that
    survives the check above but fails this one names a paint whose COLOUR moved -- and the
    `deltaE` beside it was computed from the old one. The publisher drops such a ref with a bare
    `continue`, so the paint publishes with a substitute missing and nothing says why.

    Measured 2026-08-11: 0 of 47,306 refs dangling, and 0 refs carry a blank hex, so this is a
    real comparison on every row rather than "" == "".
    """
    live, equivalences = catalog

    dangling = [(role, source, key) for role, source, key in _refs(equivalences)
                if key not in live]
    assert not dangling, (
        f"{len(dangling)} equivalence ref(s) match a live paint on name/set/code but NOT on hex. "
        "The paint was recoloured (a reformulation, a correction, or a swatch pass filling a blank "
        "hex) and every deltaE stated against it is now a claim about a colour the archive no "
        "longer holds -- and PaintBuilder will silently publish the paint with that equivalent "
        f"missing. Regenerate with --equivalences. Shown as (role, source paint, unresolvable "
        f"paint). First 5: {dangling[:5]}"
    )
