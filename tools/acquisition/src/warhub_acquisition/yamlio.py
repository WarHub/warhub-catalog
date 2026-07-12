"""Deterministic YAML serialization: stable order, safe quoting, literal blocks."""
import re
from pathlib import Path

import yaml

_ALL_DIGITS = re.compile(r"\d+")


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        # never emit indentless sequences: list items sit indented under their key
        return super().increase_indent(flow, False)


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    if _ALL_DIGITS.fullmatch(value):
        # PyYAML would leave e.g. "0812152031524" unquoted (it fails YAML 1.1
        # int patterns), but YAML 1.2 consumers parse it as int and drop the
        # leading zero -- force-quote every all-digit string
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


def load_yaml(text: str) -> object:
    return yaml.safe_load(text)


def write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(data), encoding="utf-8", newline="\n")


def read_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
