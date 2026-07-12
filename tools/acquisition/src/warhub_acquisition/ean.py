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


def canonical_ean(raw: str | None) -> str | None:
    normalized = normalize_ean(raw)
    if normalized is None or not is_valid_ean(normalized):
        return None
    return normalized
