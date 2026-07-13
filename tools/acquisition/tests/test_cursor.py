"""CursorStore: cursor writes must be byte-deterministic regardless of dict insertion order.

Several strategies build their cursor dicts via comprehensions over `set`s (shopify.py's
`new_updated_at`, woo.py's `new_gtin_map`) -- Python's set iteration order is hash-randomized
per-process, so two functionally-identical cursors could otherwise serialize to byte-different
YAML depending on PYTHONHASHSEED, producing spurious git diffs on every run. `CursorStore.save`
is the single choke point that must guarantee determinism regardless of what order a strategy
happened to build its cursor dict in.
"""
from pathlib import Path

from warhub_acquisition.acquire.cursor import CursorStore


def test_save_is_byte_identical_regardless_of_dict_insertion_order(tmp_path: Path) -> None:
    store_a = CursorStore(tmp_path / "a")
    store_b = CursorStore(tmp_path / "b")

    # Same content, deliberately different insertion order (as if built from different set
    # iteration orders) -- both top-level and nested.
    cursor_a = {
        "pending_details": ["h3", "h1", "h2"],
        "updated_at": {
            "zebra-handle": {"updatedAt": "2026-07-10", "ean": "111"},
            "alpha-handle": {"ean": "222", "updatedAt": "2026-07-11"},
        },
        "last_good_count": 42,
    }
    cursor_b = {
        "last_good_count": 42,
        "updated_at": {
            "alpha-handle": {"updatedAt": "2026-07-11", "ean": "222"},
            "zebra-handle": {"ean": "111", "updatedAt": "2026-07-10"},
        },
        "pending_details": ["h3", "h1", "h2"],
    }

    store_a.save("mfr-toy", cursor_a)
    store_b.save("mfr-toy", cursor_b)

    bytes_a = (tmp_path / "a" / "mfr-toy" / "cursor.yaml").read_bytes()
    bytes_b = (tmp_path / "b" / "mfr-toy" / "cursor.yaml").read_bytes()
    assert bytes_a == bytes_b


def test_save_sorts_keys_recursively(tmp_path: Path) -> None:
    store = CursorStore(tmp_path)
    store.save("mfr-toy", {"z": 1, "a": {"z": 1, "a": 2}})

    text = (tmp_path / "mfr-toy" / "cursor.yaml").read_text(encoding="utf-8")
    # top-level "a" (a mapping) must be emitted before top-level "z" (a scalar), and within "a",
    # nested "a" before nested "z".
    assert text.index("a:") < text.index("z:")
    lines = text.splitlines()
    a_block_start = next(i for i, line in enumerate(lines) if line == "a:")
    nested_a_idx = next(i for i in range(a_block_start + 1, len(lines)) if lines[i].strip().startswith("a:"))
    nested_z_idx = next(i for i in range(a_block_start + 1, len(lines)) if lines[i].strip().startswith("z:"))
    assert nested_a_idx < nested_z_idx


def test_save_preserves_list_order(tmp_path: Path) -> None:
    """Only dict keys are sorted -- a list's own order (e.g. a strategy's already-sorted
    pending_details) must survive untouched, not be re-sorted or reversed."""
    store = CursorStore(tmp_path)
    store.save("mfr-toy", {"pending_details": ["c", "a", "b"]})

    reloaded = store.load("mfr-toy")
    assert reloaded["pending_details"] == ["c", "a", "b"]


def test_round_trip_load_then_save_is_idempotent(tmp_path: Path) -> None:
    store = CursorStore(tmp_path)
    original = {"pending_details": ["b", "a"], "updated_at": {"b-handle": {"ean": "2"}, "a-handle": {"ean": "1"}}}
    store.save("mfr-toy", original)
    first_bytes = (tmp_path / "mfr-toy" / "cursor.yaml").read_bytes()

    loaded = store.load("mfr-toy")
    store.save("mfr-toy", loaded)
    second_bytes = (tmp_path / "mfr-toy" / "cursor.yaml").read_bytes()

    assert first_bytes == second_bytes
