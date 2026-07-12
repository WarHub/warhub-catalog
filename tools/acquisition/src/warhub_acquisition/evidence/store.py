"""JSONL evidence store: one observations.jsonl per source, sorted by key."""
import json
from pathlib import Path

from warhub_acquisition.models.observation import Observation


class EvidenceStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._sources: dict[str, dict[str, Observation]] = {}

    def _path(self, source_id: str) -> Path:
        return self.root / source_id / "observations.jsonl"

    def load(self, source_id: str) -> dict[str, Observation]:
        if source_id not in self._sources:
            observations: dict[str, Observation] = {}
            path = self._path(source_id)
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line:
                        observation = Observation.model_validate_json(line)
                        observations[observation.key] = observation
            self._sources[source_id] = observations
        return self._sources[source_id]

    def upsert(self, source_id: str, fresh: Observation) -> None:
        observations = self.load(source_id)
        old = observations.get(fresh.key)
        if old is not None:
            fresh = fresh.model_copy(
                update={
                    "firstSeen": min(old.firstSeen, fresh.firstSeen),
                    "lastSeen": max(old.lastSeen, fresh.lastSeen),
                }
            )
        observations[fresh.key] = fresh

    def save(self, source_id: str) -> None:
        observations = self.load(source_id)
        lines = [
            json.dumps(
                observations[key].model_dump(mode="json", exclude_none=True),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for key in sorted(observations)
        ]
        path = self._path(source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    def load_all(self) -> dict[str, dict[str, Observation]]:
        if self.root.exists():
            for child in sorted(self.root.iterdir()):
                if (child / "observations.jsonl").exists():
                    self.load(child.name)
        return {sid: self._sources[sid] for sid in sorted(self._sources)}
