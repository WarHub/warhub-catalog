"""resolve/set_refs.py: reading a boxed set's member codes out of the source's own prose.

The parser is pinned against COMMITTED evidence, not invented fixtures. 24 warlord-games products
already carry member-enumerating descriptions in data/catalog/products/, so the whole zero-network
floor -- 24 sets, 90 enumerated lines, 62 distinct refs -- is a regression fixture that costs no
acquire and no network. The live-payload cases below are labelled as such and carry the date they
were captured; they are the shapes the committed corpus cannot show, because AK's own 256 boxed-set
rows resolve to 0 descriptions until `mfr-ak-interactive` is next acquired.
"""
from pathlib import Path

import re

import pytest
import yaml

from warhub_acquisition.resolve.set_refs import content_skus_from_description, enumerated_members

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTS_DIR = REPO_ROOT / "data/catalog/products"


def _derived_from_committed_products() -> dict[str, list[str]]:
    if not PRODUCTS_DIR.exists():
        pytest.skip("data/catalog/products/ not present")
    derived: dict[str, list[str]] = {}
    for path in sorted(PRODUCTS_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for product in doc.get("products") or []:
            refs = content_skus_from_description(product.get("description"))
            if refs:
                derived[product["id"]] = refs
    return derived


# Manufacturers whose descriptions may legitimately enumerate AK codes. `warlord-games` resells
# AK Quick Gen boxes and states their members; `ak-interactive` joins the moment the maintainer
# runs `warhub-data acquire` + `resolve`, which is the workflow this whole branch exists to
# enable. Anything else is a loosened regex eating another brand's prose.
_MAY_ENUMERATE_AK = {"warlord-games", "ak-interactive"}

# Measured 2026-08-07 over the 22,529 committed products (11,503 with a description).
_FLOOR_SETS, _FLOOR_LINES = 24, 90


def test_the_committed_corpus_meets_its_floor_and_admits_no_other_brand() -> None:
    """Two properties, deliberately separated, because they fail in opposite directions.

    PRECISION is an equality-shaped concern -- a loosened regex enrolls another manufacturer's
    prose -- so it is asserted as a closed allow-list of manufacturers plus a shape check on every
    extracted code. That survives the corpus growing.

    COVERAGE is a floor. An earlier draft pinned all four numbers exactly (24 sets / 90 lines / 62
    distinct) and reasoned that only an equality catches a loosened regex. True, but it would have
    gone RED on first real use: the moment `warhub-data acquire` + `resolve` land AK's own
    descriptions, ~210 of its 256 sets derive contents and every one of those equalities breaks at
    once -- on a CI run belonging to whoever ran the pipeline, not to whoever changed the regex.
    A test that fails for doing the thing it was written to enable teaches people to edit tests.
    """
    derived = _derived_from_committed_products()

    manufacturers = {product_id.split("/")[0] for product_id in derived}
    assert manufacturers <= _MAY_ENUMERATE_AK, (
        f"AK member codes derived from {sorted(manufacturers - _MAY_ENUMERATE_AK)} -- either the "
        f"pattern loosened, or a new reseller genuinely states AK contents and belongs in "
        f"_MAY_ENUMERATE_AK with a measurement"
    )
    stray = [r for refs in derived.values() for r in refs if not re.fullmatch(r"AK\d{3,6}", r)]
    assert not stray, f"non-AK-shaped codes extracted: {sorted(set(stray))[:10]}"
    for product_id, refs in derived.items():
        assert len(set(refs)) >= 2, f"{product_id}: a one-code list is a cross-reference, not a set"

    assert len(derived) >= _FLOOR_SETS, (
        f"{len(derived)} sets derive contents, floor is {_FLOOR_SETS} -- coverage went DOWN, so "
        f"the pattern lost something it used to match"
    )
    assert sum(len(refs) for refs in derived.values()) >= _FLOOR_LINES


def test_the_one_false_positive_in_the_corpus_stays_out() -> None:
    """`AK-47` on two Walking Dead equipment cards (mantic-games/MGWD126, MGWEB777) is the only
    AK-shaped token in 11,503 descriptions that is not a paint code. It is excluded twice over --
    the pattern permits no separator and floors at 3 digits -- and this pins both."""
    assert content_skus_from_description("- AK-47 assault rifle\n- AK-47 ammunition") is None
    assert content_skus_from_description("Contains:\n- AK47 one\n- AK99 two") is None


def test_a_single_code_is_a_cross_reference_not_a_set() -> None:
    """One bullet naming one code is "pairs well with", not a boxed set of one. Publishing it
    would give every singles page that mentions a companion pot a one-item membership."""
    assert content_skus_from_description("Contains:\n- AK11405 RED") is None
    assert content_skus_from_description("Contains:\n- AK11405 RED\n- AK11404 BLUE") == [
        "AK11405", "AK11404",
    ]


def test_a_code_in_flowing_prose_is_not_a_member() -> None:
    """Live 2026-08-07, AK11621's copy reads "...in miniature (previously AK3010)" -- a RETIRED
    code, not a member. Anchoring refs to a list item excludes it; a whole-text sweep would not."""
    description = (
        "Contains:\n"
        "- AK11405 RED\n"
        "- AK11404 BLUE\n"
        "\n"
        "Designed to paint skin tones in miniature (previously AK3010).\n"
    )
    assert content_skus_from_description(description) == ["AK11405", "AK11404"]


def test_a_repeated_code_survives_to_be_refused() -> None:
    """warlord-games/AK17522 lists AK17068 twice: "OLD GOLD" (archive-confirmed) and "COLD STEEL"
    (which the archive holds at AK17070) -- a typo in AK's copy. De-duplicating here would drop
    Cold Steel with no trace; keeping the repeat lets gen_set_contents.py refuse it by name."""
    derived = _derived_from_committed_products()
    refs = derived["warlord-games/AK17522"]
    assert refs == ["AK17065", "AK17066", "AK17067", "AK17068", "AK17069", "AK17068"]
    names = {code: name for code, name, _qty in
             enumerated_members(_description_of("warlord-games/AK17522"))}
    assert names["AK17068"] == "COLD STEEL"  # last-wins in a dict; both lines were parsed


def test_a_comma_separated_bullet_is_a_member_not_a_silent_loss() -> None:
    """The separator is not always a space, and requiring one lost a whole set.

    ak-interactive/AK11774 "WWII JAPANESE ARMY AFV COLORS" prints every member as
    `<li>AK11435, IJA KHAKI (Field Drab)</li>`. Under the space-only rule all 6 were rejected, the
    set fell below the two-distinct-codes floor, and its refs appeared in NEITHER `members` NOR
    `unresolved` -- invisible, because the set was simply absent from the relation. That is the
    one failure the file's own invariant is written to forbid.

    Live shape, captured 2026-08-07; it cannot come from the committed corpus, because AK's own
    descriptions land only after the next acquire.
    """
    html = ("<p>This set contains:</p><ul>"
            "<li>AK11435, IJA KHAKI (Field Drab)</li>"
            "<li>AK11906, IJA TEA BROWN</li>"
            "<li>AK11902, IJA GREEN</li></ul>")
    assert content_skus_from_description(html) == ["AK11435", "AK11906", "AK11902"]


def test_a_stated_per_member_quantity_is_captured_not_dropped() -> None:
    """AK writes `- 2x AK17080 - MEDIUM FOR QUICK GEN PAINTS (18ml)`. The anchored rule rejected a
    quantity-prefixed bullet outright, so the line VANISHED rather than landing without its count
    -- and `counts.quantified: 0` is documented as "the source did not say", which that would have
    made false the moment a paint bullet carried one."""
    members = enumerated_members("<ul><li>2x AK17080 - MEDIUM FOR QUICK GEN PAINTS (18ml)</li></ul>")
    assert members == [("AK17080", "MEDIUM FOR QUICK GEN PAINTS (18ml)", 2)]


def test_a_code_glued_to_its_name_is_not_split() -> None:
    """Widening the separator must not let `AK11435IJA KHAKI` become a code plus a name -- the
    alternation requires punctuation OR whitespace, never neither."""
    assert enumerated_members("<ul><li>AK11435IJA KHAKI</li><li>AK11906IJA TEA</li></ul>") == []


def _description_of(product_id: str) -> str:
    manufacturer = product_id.split("/")[0]
    doc = yaml.safe_load((PRODUCTS_DIR / f"{manufacturer}.yaml").read_text(encoding="utf-8"))
    return next(p["description"] for p in doc["products"] if p["id"] == product_id)


# --- Shapes only the LIVE payload has. Captured 2026-08-07 from ---------------------------------
# GET https://ak-interactive.com/wp-json/wc/store/products?category=b2b-quick-gen-sets&lang=en
# and trimmed to the structure under test. They are here because AK's 256 committed boxed-set rows
# carry 0 descriptions today, so the committed corpus cannot exercise HTML, bilingual duplication,
# or a not-included list -- and those are exactly where a plausible parser goes wrong.

AK17524_LIVE = (
    '<span class="collapseomatic " id="englang" title="ENGLISH">ENGLISH</span>'
    '<div id="target-englang" class="collapseomatic_content ">\n'
    "<p>The selected tones in this <strong>QUICK GEN</strong> set are perfect.</p>\n"
    "<p>Contains:</p>\n<ul>\n"
    '<li><strong>AK17082 WOLF BLUE GREY </strong><span style="color: #ff0000">*Special color '
    "only for this set &#8211; not sold separately.</span></li>\n"
    '<li><a href="https://ak-interactive.com/product/dirty-yellow/">AK17007 DIRTY YELLOW</a></li>\n'
    '<li><a href="https://ak-interactive.com/product/space-red/">AK17034 SPACE RED</a></li>\n'
    "</ul>\n</div><br />\n"
    '<span class="collapseomatic " id="esplang" title="ESPAÑOL">ESPAÑOL</span>'
    '<div id="target-esplang" class="collapseomatic_content "></p>\n'
    "<p>Contiene:</p>\n<ul>\n"
    "<li><strong>AK17082 WOLF BLUE GREY</strong></li>\n"
    "<li>AK17007 DIRTY YELLOW</li>\n<li>AK17034 SPACE RED</li>\n</ul>\n</div></p>"
)


def test_the_spanish_half_of_a_bilingual_description_is_not_a_second_membership() -> None:
    """THE bug this parser exists to avoid. Live-verified 2026-08-07: all 999 rows of AK's
    `paints-acrylics` category answer `short_description` as a collapseomatic accordion holding
    the full English block AND the full Spanish block, each with its own <ul> of the same codes.
    An unbounded scan reports every AK set's members exactly twice -- and gen_set_contents.py's
    within-set repeat rule would then refuse half of every set in the file."""
    assert content_skus_from_description(AK17524_LIVE) == ["AK17082", "AK17007", "AK17034"]


def test_html_and_markdown_reach_the_same_answer() -> None:
    """`legacy-catalog` holds curated markdown, AK's Store API answers raw HTML. One rule must read
    both, or the parser proven on committed data is not the parser that runs on live data."""
    markdown = (
        "The selected tones in this QUICK GEN set are perfect.\n\nContains:\n\n"
        "- AK17082 WOLF BLUE GREY\n- AK17007 DIRTY YELLOW\n- AK17034 SPACE RED\n"
    )
    assert content_skus_from_description(markdown) == content_skus_from_description(AK17524_LIVE)


AK11701_LIVE = (
    '<span class="collapseomatic " id="englang" title="ENGLISH">ENGLISH</span>'
    '<div id="target-englang" class="collapseomatic_content ">\n'
    "<p>Metallic briefcase containing 233 bottles in total.</p>\n"
    "<p>*These acrylic effects are not included:</p>\n<ul>\n"
    "<li>AK11260 &#8211; BLOOD EFFECT</li>\n<li>AK11261 &#8211; VISCERA EFFECT</li>\n"
    "<li>AK11262 &#8211; CHIPPING EFFECT</li>\n</ul>\n</div>"
)


def test_an_explicitly_not_included_list_never_becomes_a_membership() -> None:
    """AK enumerates NOT-INCLUDED items in exactly the shape it enumerates contents. Measured
    2026-08-07 over the 256 boxed-set rows, 6 carry such a marker and all 20 member-shaped lines
    after it are not-included items (AK11701's 3 effects; AK8252/3/4/5's "OPTIONAL MATERIALS").

    A fabricated membership is strictly worse than a missing one -- a refusal is visible in the
    relation and a false member is indistinguishable from a true one -- so the rule stops dead at
    the marker and AK11701, which states 233 colours and lists none of them, yields nothing."""
    assert content_skus_from_description(AK11701_LIVE) is None


AK8252_LIVE = (
    '<span class="collapseomatic " id="englang" title="ENGLISH">ENGLISH</span>'
    '<div id="target-englang" class="collapseomatic_content ">\n'
    "<p>This set contains:</p>\n"
    "<p>3Gen Acrylics:</p>\n<ul>\n<li>AK11001 &#8211; WHITE</li>\n"
    "<li>AK11029 &#8211; BLACK</li>\n</ul>\n"
    "<p>Enamel Effects:</p>\n<ul>\n<li>AK012 &#8211; DUST WASH</li>\n</ul>\n"
    "<p>OPTIONAL MATERIALS (not included)</p>\n<ul>\n<li>AK9999 &#8211; THINNER</li>\n</ul>\n"
    "</div>"
)


def test_contents_split_over_several_lists_are_all_collected() -> None:
    """11 of the 256 sets group their contents under sub-headings ("3Gen Acrylics:", "Enamel
    Effects:", "Brushes:"). A single-contiguous-run rule truncated AK11757 and AK11763 at 3 of 18
    members, so the scan spans intervening prose -- and still stops at the not-included marker."""
    assert content_skus_from_description(AK8252_LIVE) == ["AK11001", "AK11029", "AK012"]


def test_a_malformed_code_is_captured_so_it_can_be_refused_rather_than_vanish() -> None:
    """Live 2026-08-07, AK11781 lists "AK111424 - Grey Green": six digits, a typo for AK11424, on a
    perfectly formed bullet. A five-digit ceiling matches nothing on that line and the member
    disappears without a trace anywhere; the six-digit ceiling turns it into a ref that
    gen_set_contents.py refuses BY NAME. Measured, widening the ceiling changes only this token."""
    description = "Contains:\n- AK11425 Field Grey\n- AK111424 Grey Green\n- AK11003 White Grey\n"
    assert content_skus_from_description(description) == ["AK11425", "AK111424", "AK11003"]


AK8253_LIVE_SHAPE = (
    "MATERIALS INCLUDED\n"
    "3Gen Acrylics:\n- AK11253 Grey Primer\n- AK11001 White\n- AK11029 Black\n"
    "Enamel Effects:\n- AK014 Winter Streaking Grime*\n"
    "Brushes:\n- AK604 Round Brush 2\n- AK610 Flat Brush 4\n"
    "INCLUDES:\n- Acetate sheet\n"
)


def test_a_late_sub_header_does_not_swallow_the_contents_above_it() -> None:
    """A "Contains:"-style anchor is the obvious design and it is the one measured mistake this
    parser made. An anchor can only earn anything by SKIPPING member-shaped lines before it, and
    across every committed description and all 999 live rows the only lines it ever skipped were
    real members: AK8253 prints a late "INCLUDES:" sub-header (acetate sheet, paper posters) BELOW
    its six paints and two brushes, and a first-header rule dropped all 9 of that set's refs.

    Removing the anchor changed exactly one set in the whole corpus, 0 members -> 9. What keeps
    prose out of a membership is the BULLET requirement, not a header -- so the shape of the header
    (measured live: "This set contains:" 138, "Contains:" 37, "The set contains:" 31, and 44 sets
    with none at all) stopped mattering entirely.
    """
    assert content_skus_from_description(AK8253_LIVE_SHAPE) == [
        "AK11253", "AK11001", "AK11029", "AK014", "AK604", "AK610",
    ]
    for header in ("This set contains:", "The set contains:", "It includes:", ""):
        assert content_skus_from_description(f"{header}\n- AK11405 RED\n- AK11404 BLUE") == [
            "AK11405", "AK11404",
        ], header
