"""Where each product record lives under data/catalog/products/, and how to read them all back.

ONE FILE PER MANUFACTURER, UNLESS THE MANUFACTURER IS TOO BIG FOR ONE. The resolver owns the file
names, and this module decides them. A manufacturer with at most `SHARD_ABOVE` products gets
`<manufacturer>.yaml`, which is how every manufacturer was written before sharding. A bigger one
is split into shards named `<manufacturer>.<prefix>.yaml`. Each shard has the same document shape
(`manufacturer:` then `products:` in id order), and a record is in the shard whose prefix is the
LONGEST one its code starts with. A record that no prefix claims goes to `<manufacturer>._.yaml`.

THE PREFIXES are decided per manufacturer from its own ids, top down, by record COUNT:

  * a prefix holding more than `SPLIT_ABOVE` products is split one character deeper;
  * each one-character-longer prefix holding more than `OWN_FILE_ABOVE` gets its own shard, and
    is itself split in turn if it holds more than `SPLIT_ABOVE`;
  * the smaller ones stay in the shorter prefix's shard, unless together they would still hold
    more than `SPLIT_ABOVE`. Then every one-character-longer prefix gets its own shard, so no
    shard ever holds more than `SPLIT_ABOVE`.

The code is the part of the id after the manufacturer: the product code for most records, a slug
for the few without one. It is lower-cased, and anything outside `[0-9a-z-]` becomes `-`, so two
shards never differ only in case (Windows and macOS would write them to one file) and `_` is free
to name the rest. Ids never change, so a record's code never changes. The record moves only when
a prefix on its own path crosses a threshold, and that moves only the records under that prefix.

COUNTS, NOT BYTES, and the reason is measured. Replayed over every committed version of the two
files this was built for, a rule that measured bytes relaid records on the commits that added a
field to every record, with no product added or removed. Record counts change only when products
come or go. The commit that introduced this module has the numbers.

Every reader goes through `product_files`, `read_catalog` or `iter_products`, which merge a
sharded manufacturer back into one list in id order: the order its single file held. This module
imports nothing but `yamlio`, so a script run as `uv run --with pyyaml` can use it too.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from warhub_acquisition.yamlio import read_yaml

# A manufacturer with more products than this is sharded. Measured 2026-09-30, it catches the
# two it was sized for (games-workshop 9,167 and warlord-games 4,788) and leaves the next largest,
# mantic-games at 2,905, whole.
SHARD_ABOVE = 4000
# Inside a sharded manufacturer, a code prefix holding more products than this is split.
SPLIT_ABOVE = 1000
# ...and each longer prefix holding more than this gets a shard of its own.
OWN_FILE_ABOVE = 250
# The shard holding the records no prefix claims. Not a possible prefix: `_` never survives
# `shard_key`.
REST = "_"

_NOT_IN_KEY = re.compile(r"[^0-9a-z-]")


def shard_key(product_id: str) -> str:
    """The string a record's shard is chosen by: its code, lower-cased and made filename-safe."""
    return _NOT_IN_KEY.sub("-", product_id.split("/", 1)[1].lower())


def _prefixes(keys: list[str]) -> set[str]:
    chosen: set[str] = set()

    def visit(prefix: str, group: list[str]) -> None:
        chosen.add(prefix)
        if len(group) <= SPLIT_ABOVE:
            return
        children: dict[str, list[str]] = defaultdict(list)
        stays = 0
        for key in group:
            if len(key) > len(prefix):
                children[key[len(prefix)]].append(key)
            else:
                stays += 1
        own = {c for c, members in children.items() if len(members) > OWN_FILE_ABOVE}
        if stays + sum(len(m) for c, m in children.items() if c not in own) > SPLIT_ABOVE:
            own = set(children)
        for c in sorted(own):
            visit(prefix + c, children[c])

    visit("", keys)
    return chosen


def shard(manufacturer: str, records: list[dict]) -> dict[str, list[dict]]:
    """`{file name: records}` for one manufacturer, each list in the order `records` came in.

    `records` are dumped product dicts, each with its `id`. The result is a pure function of the
    set of ids, so the same catalog always lands in the same files.
    """
    if "." in manufacturer:
        raise ValueError(f"manufacturer slug {manufacturer!r} contains '.', which names a shard")
    if len(records) <= SHARD_ABOVE:
        return {f"{manufacturer}.yaml": records}
    keys = [shard_key(record["id"]) for record in records]
    prefixes = _prefixes(keys)
    files: dict[str, list[dict]] = {}
    for record, key in zip(records, keys):
        prefix = next(key[:n] for n in range(len(key), -1, -1) if key[:n] in prefixes)
        files.setdefault(f"{manufacturer}.{prefix or REST}.yaml", []).append(record)
    return dict(sorted(files.items()))


def manufacturer_of(path: Path) -> str:
    """The manufacturer a product file belongs to, whole or shard: its name up to the first dot."""
    return path.name.split(".", 1)[0]


def product_files(directory: Path) -> list[Path]:
    """Every product file, whole or shard, in name order. Empty when the directory is absent."""
    return sorted(directory.glob("*.yaml")) if directory.exists() else []


def read_catalog(directory: Path) -> dict[str, list[dict]]:
    """`{manufacturer: records in id order}`, a sharded manufacturer's files merged into one list.

    Raises on a file whose `manufacturer:` disagrees with its name, and on an id that two files
    both hold. The resolver writes neither, so either one means the tree was edited by hand.
    """
    catalog: dict[str, list[dict]] = {}
    seen: dict[str, Path] = {}
    for path in product_files(directory):
        document = read_yaml(path) or {}
        manufacturer = document.get("manufacturer") or manufacturer_of(path)
        if manufacturer != manufacturer_of(path):
            raise ValueError(f"{path.name} declares manufacturer {manufacturer!r}")
        for record in document.get("products") or []:
            if record["id"] in seen:
                raise ValueError(f"{record['id']} is in both {seen[record['id']].name} and {path.name}")
            seen[record["id"]] = path
        catalog.setdefault(manufacturer, []).extend(document.get("products") or [])
    return {m: sorted(records, key=lambda r: r["id"]) for m, records in sorted(catalog.items())}


def iter_products(directory: Path) -> Iterator[dict]:
    """Every product record, manufacturer by manufacturer, each manufacturer in id order."""
    for records in read_catalog(directory).values():
        yield from records
