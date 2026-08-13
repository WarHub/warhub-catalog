"""Canonical catalog records and human overrides."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CanonicalProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    manufacturer: str
    productCode: str | None = None
    sku: str | None = None
    ean: str | None = None
    eanConfidence: str | None = None
    # Extra barcodes a repackaged product carries beyond its primary `ean` (same contents,
    # new box/barcode -- joined via matches.yaml). Empty for the single-barcode majority, so
    # the published `ean` is unchanged for existing consumers. A confirmed barcode displaced
    # by a repackaging join lands here rather than being silently dropped (see resolve_ean).
    additionalEans: list[str] = Field(default_factory=list)
    # Archival lineage, from matches.yaml `supersessions`. Both records are published: the retired
    # one keeps its own productCode/ean/name and points forward via `supersededBy`; the surviving
    # one lists its predecessors in `supersedes`. Deliberately NOT expressed as a `status` value --
    # `status` is a free string every consumer filters on, and a new value there would silently
    # exclude exactly the archival records this is meant to keep reachable.
    supersedes: list[str] = Field(default_factory=list)
    supersededBy: str | None = None
    gameSystem: str | None = None
    faction: str | None = None
    category: str | None = None
    packaging: str | None = None
    quantity: int | None = None
    volumeMl: int | None = None
    # NET CONTENTS in grams, for the products sold by mass rather than by volume. Sibling of
    # volumeMl, never a replacement -- either, both or neither. Measured 2026-08-06, only a handful
    # of products name a mass at all (the GW `WH COLOUR PLASTIC GLUE (15g)` regional SKUs and
    # Mantic's `Colour Forge Basing Sand - Fine Grit - 400g`) and none of them carries a volume, so
    # this closes an ABSENCE on the product side rather than correcting an error. It exists chiefly so
    # the cross-catalog seam cannot disagree with itself: a barcode resolving to both a paint and
    # a product must not have net contents on one side and silence on the other.
    #
    # NOTHING FEEDS IT YET AND THAT IS DELIBERATE. It flows the moment a source emits a `weightG`
    # hint (it is in resolve.attributes._HINT_FIELDS), and no source does today -- the only
    # mass-shaped hint in the corpus is Shopify's `grams`, which is GROSS SHIPPING weight on well
    # over a thousand observations (a brush 3 g, an 18 ml dropper 26-31 g) and must never be
    # wired here.
    weightG: int | None = None
    status: str
    availability: str | None = None
    firstSeen: str
    priceGbp: float | None = None
    priceUsd: float | None = None
    priceEur: float | None = None
    priceCad: float | None = None
    url: str | None = None
    imageUrl: str | None = None
    description: str | None = None
    # WHAT IS IN THE BOX, as the source states it: the manufacturer's own product codes for the
    # items a boxed set contains. Raw refs, NOT resolved catalog ids -- resolving them needs the
    # PAINT catalog, which this resolver deliberately never loads, so the resolved relation lives
    # in data/catalog/set-contents/ and is generated separately.
    #
    # `mfr-reaper` WAS the only source that stated this, and the reason it went first is that it
    # needed no acquisition at all, not that it was a big win: it hands us a machine-readable array
    # and every one of its refs now resolves against data/paints/brands/reaper.yaml. That is no
    # longer the whole picture. ak-interactive and warlord-games state their contents in prose
    # inside a `description`, resolve/set_refs.py reads it, and AK is now by a wide margin the
    # LARGEST of the three. Re-derive the current split from each file's own `counts` block under
    # data/catalog/set-contents/.
    #
    # FIRST-WINS across kind-ordered members like every other hint, NOT a union: two sources
    # disagreeing about a box's contents is a conflict to surface, and unioning them would
    # fabricate a set neither one asserts.
    #
    # QUANTITY IS NOT HERE, and for reaper no strategy change could recover it -- that SOURCE never
    # states one. This comment previously blamed `strategies/reaper.py::_content_skus` for building
    # a SET, which was wrong in the way that costs someone a pointless re-acquire: it named a
    # mechanism that is inert. Measured live 2026-08-07 over reapermini.com's three set-kind pages,
    # every `associatedProducts` entry carries exactly {sku, name, category, filename, material},
    # there is no count field of any kind, and no set repeats a sku -- so that set comprehension
    # discards nothing on real data.
    #
    # AK IS THE EXCEPTION, and it is why this field stays a plain list of codes. AK's prose DOES
    # state per-member counts ("- 2x AK17080 - ..."), and resolve/set_refs.py captures them -- but
    # they land on the MEMBER in data/catalog/set-contents/, never here, because absence in this
    # list must keep reading as "not stated" and a repeat-preserving list would silently assert a
    # quantity of 1 on every other ref. The relation reserves a per-member `quantity` key on
    # exactly those terms (gen_set_contents.py::_stated_prose populates it), so a value arriving
    # later is additive rather than a re-typing of this field.
    # `| None`, like every other member of `_HINT_FIELDS`: `_first` yields None when no source
    # states one, and None reads correctly as "this source said nothing about the contents",
    # which is a different claim from "this box is empty".
    contentSkus: list[str] | None = None
    # WHERE THE LIST ABOVE CAME FROM, because the two provenances make DIFFERENT claims and a
    # consumer cannot tell them apart from the refs alone.
    #
    # - "stated": a source handed us a machine-readable contents array (today only mfr-reaper's
    #   `associatedProducts`). Exhaustive by construction -- the field either lists the box or is
    #   absent.
    # - "description": resolve/set_refs.py read the refs out of the source's own prose. NOT
    #   guaranteed exhaustive, and that is measured rather than cautious: live 2026-08-07, a
    #   substantial minority of AK's boxed-set rows enumerate no codes at all while still stating a
    #   count in words (AK11701 says 233 colours and lists none), and a few print a second,
    #   explicitly NOT-INCLUDED bulleted list in the identical shape. A prose list is editorial;
    #   an array is data.
    #
    # None whenever `contentSkus` is None, and dropped from the published YAML by exclude_none, so
    # adding it is byte-identical for every product that states no contents -- the overwhelming
    # majority of the catalog. Only reaper's `stated` sets and the description-derived
    # ak-interactive and warlord-games ones carry it. Re-derive by counting `contentSkusFrom:` in
    # data/catalog/products/.
    contentSkusFrom: Literal["stated", "description", "sku"] | None = None
    evidence: list[str] = Field(default_factory=list)


class Overrides(BaseModel):
    # extra="forbid" is what makes this file MACHINE-OWNED safely. classify/apply.py rewrites
    # overrides.yaml wholesale from a hand-built dict of exactly these two keys, so any third
    # top-level key a human adds here is deleted on the next `classify --apply` -- silently, and
    # with its comments, because write_yaml is plain PyYAML. `setRefs` lived here and was lost
    # that way (see data/catalog/set-refs.yaml, 2026-08-11). Forbidding extras turns the next
    # attempt into a ValidationError at load time instead of a quiet deletion at write time.
    model_config = ConfigDict(extra="forbid")
    retract: list[str] = Field(default_factory=list)
    products: dict[str, dict[str, object]] = Field(default_factory=dict)


class SetRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # A CODE THE SOURCE MISTYPED IN ITS OWN CONTENTS PROSE: {product id: {stated ref: real code}}.
    # Read by scripts/gen_set_contents.py when it resolves a set's members, and by nothing else.
    #
    # LIVES IN ITS OWN FILE, data/catalog/set-refs.yaml (DataPaths.set_refs), which no code in this
    # repo writes. It was a key in overrides.yaml until 2026-08-11, and that was a real defect
    # rather than a tidiness complaint: classify/apply.py rebuilds overrides.yaml from a two-key
    # literal, so one `warhub-data classify --apply` deleted the block and its 19 lines of evidence
    # and exited 0. A hand-authored key cannot share a path with a generator's output.
    #
    # WHY THIS IS NOT THE GENERATOR REWRITING THE SOURCE, which gen_set_contents.py's header
    # forbids in those words. That prohibition is on INFERENCE -- a generator that quietly repairs
    # a ref to make its own output look complete, deciding for itself what the source meant. This
    # is the same separation `overrides.yaml` draws everywhere else in this repo: a human may state
    # a correction, in a committed file, with the evidence beside it, and be reviewed on it; a
    # generator may not derive one. Nothing here is computed -- no edit distance, no nearest-code
    # search, no fuzzy name match. An entry exists only because somebody wrote it.
    #
    # SCOPED TO ONE PRODUCT, never to a source or globally. The same string can be a typo in one
    # box and a real code in another, and a correction that cannot say WHERE it applies would
    # silently rewrite both. It also keeps the entry auditable: the box is the evidence.
    #
    # `contentSkus` on the product record stays VERBATIM and is not touched -- it is documented as
    # the manufacturer's own raw refs, and a catalog that quietly launders them loses the only
    # record that the source ever said something else. The correction applies at RESOLUTION, so
    # the member keeps `ref:` exactly as printed and carries `resolvedBy: correction`. That is the
    # same shape the stated-name repair uses for a code a set contradicts itself about.
    #
    # tests/test_repo_data.py::test_every_set_ref_correction_is_live_and_resolvable holds it to
    # both halves of its claim: the mistyped ref must STILL be in that product's contentSkus (if
    # the manufacturer fixes its own prose, the entry is stale and must be deleted, not left to
    # rot), and the corrected code must name exactly one committed paint.
    setRefs: dict[str, dict[str, str]] = Field(default_factory=dict)
