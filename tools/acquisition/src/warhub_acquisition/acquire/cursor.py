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
        write_yaml(self._path(source_id), cursor)
