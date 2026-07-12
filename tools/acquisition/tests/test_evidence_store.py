from pathlib import Path

from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.observation import Observation


def obs(**kw: object) -> Observation:
    base: dict[str, object] = {
        "key": "ret-goblin:combat-patrol-necrons",
        "name": "Combat Patrol: Necrons",
        "manufacturer": "games-workshop",
        "firstSeen": "2026-07-12",
        "lastSeen": "2026-07-12",
        "extractor": "test@1",
    }
    base.update(kw)
    return Observation(**base)


def test_source_id_property() -> None:
    assert obs().source_id == "ret-goblin"


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    store.upsert("ret-goblin", obs(ean="5011921194285"))
    store.save("ret-goblin")

    reloaded = EvidenceStore(tmp_path).load("ret-goblin")
    assert reloaded["ret-goblin:combat-patrol-necrons"].ean == "5011921194285"


def test_upsert_merges_seen_dates(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    store.upsert("ret-goblin", obs(firstSeen="2026-07-01", lastSeen="2026-07-01"))
    store.upsert("ret-goblin", obs(firstSeen="2026-07-12", lastSeen="2026-07-12", ean="5011921194285"))

    merged = store.load("ret-goblin")["ret-goblin:combat-patrol-necrons"]
    assert merged.firstSeen == "2026-07-01"   # never moves forward
    assert merged.lastSeen == "2026-07-12"
    assert merged.ean == "5011921194285"


def test_file_is_sorted_and_stable(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    store.upsert("ret-goblin", obs(key="ret-goblin:zzz", name="Z"))
    store.upsert("ret-goblin", obs(key="ret-goblin:aaa", name="A"))
    store.save("ret-goblin")

    path = tmp_path / "ret-goblin" / "observations.jsonl"
    text = path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")
    assert '"ret-goblin:aaa"' in lines[0]
    assert text.endswith("\n")

    store2 = EvidenceStore(tmp_path)
    store2.load("ret-goblin")
    store2.save("ret-goblin")
    assert path.read_text(encoding="utf-8") == text  # byte-stable rewrite


def test_load_all(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    store.upsert("b-src", obs(key="b-src:x"))
    store.upsert("a-src", obs(key="a-src:y"))
    store.save("b-src")
    store.save("a-src")

    all_sources = EvidenceStore(tmp_path).load_all()
    assert list(all_sources) == ["a-src", "b-src"]
