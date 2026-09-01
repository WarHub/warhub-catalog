"""GTIN/EAN normalization and validation (EAN-13 and UPC-A)."""


def normalize_ean(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdecimal())
    if digits != "".join(ch for ch in raw if ch not in " -"):
        return None  # contained non-digit junk beyond separators
    if len(digits) == 12:
        digits = "0" + digits  # UPC-A embeds into EAN-13 with a leading zero
    if len(digits) != 13 or int(digits) == 0:
        return None
    return digits


def is_valid_ean(ean: str) -> bool:
    if len(ean) != 13 or not ean.isdigit():
        return False
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(ean[:12]))
    return (10 - total % 10) % 10 == int(ean[12])


# `977` IS THE GS1 PREFIX FOR ISSN -- A PERIODICAL'S SERIAL NUMBER, AND IT NAMES THE SERIES.
# Every issue of a magazine carries the SAME thirteen digits; what separates them is a 2- or
# 5-digit add-on printed beside the barcode, which no source in this repo records. So an ISSN
# barcode is not a product identity: taking it as one fuses every issue ever published into one
# record through the (manufacturer, ean) union.
#
# `978` AND `979` -- ISBN -- ARE DELIBERATELY NOT HERE and must not be added. An ISBN identifies
# one TITLE, it is a perfectly good product barcode, and this catalog leans on it: `9781915319432`
# is the Konflikt '47 rulebook, `9781958872918` a Dave Taylor art book, and matches.yaml already
# adjudicates two products that legitimately share one.
#
# MEASURED 2026-09-01 over every observation in the ledger: 25 carry a `977` value and they are
# three distinct numbers -- `9770957644169` on 15 Wargames Illustrated issues, `9772658712031` and
# `9772658712024` on 10 White Dwarfs. Both magazines were reporting `ean-shared` across years of
# issues, and no product loses an identity it had: an ISSN never identified one.
_SERIAL_PUBLICATION_PREFIX = "977"


def canonical_ean(raw: str | None) -> str | None:
    normalized = normalize_ean(raw)
    if normalized is None or not is_valid_ean(normalized):
        return None
    if normalized.startswith(_SERIAL_PUBLICATION_PREFIX):
        return None
    return normalized
