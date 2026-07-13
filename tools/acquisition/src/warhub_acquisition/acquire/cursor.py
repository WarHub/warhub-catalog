"""Per-source cursor: strategy-owned progress state (pages, queues, sweep bookkeeping)."""
from pathlib import Path

from warhub_acquisition.yamlio import read_yaml, write_yaml


class CursorStore:
    def __init__(self, evidence_root: Path) -> None:
        self.evidence_root = evidence_root

    def _path(self, source_id: str) -> Path:
        return self.evidence_root / source_id / "cursor.yaml"

    def load(self, source_id: str) -> dict:
        path = self._path(source_id)
        if not path.exists():
            return {}
        data = read_yaml(path)
        return data if isinstance(data, dict) else {}

    def save(self, source_id: str, cursor: dict) -> None:
        write_yaml(self._path(source_id), _sort_keys_recursive(cursor))


def _sort_keys_recursive(value: object) -> object:
    """Recursively sort every mapping's keys before serialization.

    Several strategies build cursor dicts via comprehensions over `set`s (e.g. shopify.py's
    `new_updated_at`, woo.py's `new_gtin_map`) -- Python's set iteration order is hash-randomized
    per-process, so two functionally-identical cursors (same content, different insertion order)
    would otherwise dump to byte-different YAML depending on PYTHONHASHSEED. Rather than fix every
    such comprehension at its call site, this is the single choke point all cursor writes pass
    through: sort every dict's keys, recursively, right before it hits `write_yaml`
    (`dump_yaml`/`yaml.dump` itself is `sort_keys=False` deliberately, for evidence/catalog writers
    where insertion order IS meaningful -- only cursors get this treatment, and only here).
    """
    if isinstance(value, dict):
        return {key: _sort_keys_recursive(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sort_keys_recursive(item) for item in value]
    return value
