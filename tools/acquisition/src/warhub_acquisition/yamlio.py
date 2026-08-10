"""Deterministic YAML serialization: stable order, safe quoting, literal blocks."""
import re
from pathlib import Path

import yaml

# anything a YAML 1.2 core-schema consumer could read as a number:
# ints (incl. leading-zero), floats, scientific notation, hex, octal
_NUMERIC_LIKE = re.compile(r"[-+]?(\.\d+|\d+(\.\d*)?)([eE][-+]?\d+)?|0[xX][0-9a-fA-F]+|0[oO][0-7]+")


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        # never emit indentless sequences: list items sit indented under their key
        return super().increase_indent(flow, False)


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    if _NUMERIC_LIKE.fullmatch(value):
        # PyYAML's YAML 1.1 resolver misses several shapes a YAML 1.2
        # consumer would read as numbers (leading-zero ints like
        # "0812152031524", dotless scientific notation like "5e3") --
        # force-quote everything number-shaped
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="'")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_Dumper.add_representer(str, _represent_str)


def dump_yaml(data: object) -> str:
    return yaml.dump(
        data,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        width=10_000,
        default_flow_style=False,
    )


# READING uses libyaml's C parser where the PyYAML wheel provides it; WRITING deliberately does
# not. `yaml.safe_load` is the pure-Python parser, and this repo parses a lot: measured 2026-08-06,
# `report --ean-guard` spent 135s parsing (15 product catalogs + 21 brand archives, each read twice
# -- once from HEAD via `git show`, once from the working tree) against 2.7s of actual git. It
# exceeded a 10-minute timeout. Swapping the loader took the same 40 files from 113.13s to 15.14s,
# a 7.5x, and `resolve` and every script benefit too since they all come through here.
#
# Verified equivalent, not assumed: all 15 product catalogs, all 21 brand archives, matches.yaml,
# overrides.yaml, equivalences.yaml and conflicts.yaml were parsed with BOTH loaders and compared
# with deep equality -- 40 files, 0 mismatches.
#
# The DUMPER stays pure-Python on purpose. `_Dumper` overrides `increase_indent` to suppress
# indentless sequences, and libyaml's emitter handles indentation internally rather than through
# that hook, so `CSafeDumper` would silently reflow every file this repo has ever written. In a
# git-committed archive that is a diff measured in hundreds of thousands of lines, for no speed
# that matters -- writing is not where the time goes.
try:
    _Loader: type = yaml.CSafeLoader
except AttributeError:  # pragma: no cover -- PyYAML built without libyaml
    _Loader = yaml.SafeLoader


def load_yaml(text: str) -> object:
    return yaml.load(text, Loader=_Loader)


def write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(data), encoding="utf-8", newline="\n")


def read_yaml(path: Path) -> object:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
