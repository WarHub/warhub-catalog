"""Canonical entity identity: manufacturer/productCode, else manufacturer/name-slug."""
import re
import unicodedata


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.casefold())
    return slug.strip("-")


def entity_id(manufacturer: str, code: str | None, name: str) -> str:
    return f"{manufacturer}/{code if code else slugify(name)}"
