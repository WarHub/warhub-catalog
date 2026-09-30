"""data/catalog/products/: which file each product record is written to (resolve/layout.py).

The layout is output only. Every reader merges a sharded manufacturer back into one list, so these
tests pin the rule itself and the property the rest of the pipeline relies on: a relayout changes
files, never records.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from warhub_acquisition.report import check_ean_guard
from warhub_acquisition.resolve import layout
from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import write_yaml

from test_resolver import seed

REPO_ROOT = Path(__file__).resolve().parents[3]


def _records(*ids: str) -> list[dict]:
    return [{"id": i, "name": i} for i in ids]


def _ids(files: dict[str, list[dict]]) -> dict[str, list[str]]:
    return {name: [r["id"] for r in records] for name, records in files.items()}


@pytest.fixture
def small(monkeypatch):
    """Thresholds a handful of ids can cross."""
    monkeypatch.setattr(layout, "SHARD_ABOVE", 4)
    monkeypatch.setattr(layout, "SPLIT_ABOVE", 3)
    monkeypatch.setattr(layout, "OWN_FILE_ABOVE", 1)


# 9 ids: 99 holds 6 (991 three, 998 two, 992 one), and one each under 6, WG- and a_b.
IDS = ["m/60011", "m/99121", "m/99122", "m/99123", "m/99201", "m/99851", "m/99852", "m/WG-1", "m/a_b"]


def test_a_manufacturer_at_the_threshold_keeps_its_single_file(small) -> None:
    records = _records("m/1", "m/2", "m/3", "m/4")
    assert layout.shard("m", records) == {"m.yaml": records}


def test_a_bigger_one_is_split_by_code_prefix_into_the_longest_prefix_each_code_starts_with(small) -> None:
    # The root (9 ids) splits; only `9` holds more than one, so it gets a shard and the three
    # singletons stay in the root's, `_`. `9` holds 6 and splits, `99` holds all 6 and splits, and
    # of its children `991` (3) and `998` (2) earn shards while `992` (1) stays in `99`'s. The
    # `9` shard is left holding nothing, so it is never written.
    assert _ids(layout.shard("m", _records(*IDS))) == {
        "m._.yaml": ["m/60011", "m/WG-1", "m/a_b"],
        "m.99.yaml": ["m/99201"],
        "m.991.yaml": ["m/99121", "m/99122", "m/99123"],
        "m.998.yaml": ["m/99851", "m/99852"],
    }


def test_small_prefixes_that_would_still_overfill_their_parent_each_get_a_shard(small) -> None:
    # Five first characters, one record each: none earns a shard on its own, but kept together
    # they would hold 5 > SPLIT_ABOVE, so every one is split out and no shard exceeds the bound.
    files = layout.shard("m", _records("m/a1", "m/b1", "m/c1", "m/d1", "m/e1"))
    assert list(files) == ["m.a.yaml", "m.b.yaml", "m.c.yaml", "m.d.yaml", "m.e.yaml"]


def test_the_key_is_lower_cased_and_filename_safe_so_the_rest_shard_can_never_collide() -> None:
    assert layout.shard_key("warlord-games/WGB-AI-127") == "wgb-ai-127"
    assert layout.shard_key("m/a_b.c d") == "a-b-c-d"
    assert layout.REST not in {layout.shard_key(f"m/{c}") for c in "_-.aZ9"}


def test_a_record_that_crosses_no_threshold_moves_nothing(small) -> None:
    before = layout.shard("m", _records(*IDS))
    after = layout.shard("m", _records(*sorted([*IDS, "m/99853"])))
    where = {r["id"]: name for name, records in after.items() for r in records}
    assert all(where[r["id"]] == name for name, records in before.items() for r in records)
    assert where["m/99853"] == "m.998.yaml"


def test_a_prefix_that_crosses_one_splits_and_moves_only_its_own_records(small) -> None:
    before = {r["id"]: name for name, records in layout.shard("m", _records(*IDS)).items() for r in records}
    after = {
        r["id"]: name
        for name, records in layout.shard("m", _records(*sorted([*IDS, "m/99124"]))).items()
        for r in records
    }
    moved = {i for i in before if before[i] != after[i]}
    assert moved and all(i.startswith("m/991") for i in moved)


def test_a_manufacturer_slug_with_a_dot_is_refused() -> None:
    with pytest.raises(ValueError, match="names a shard"):
        layout.shard("m.x", _records("m.x/1"))


def test_read_catalog_merges_shards_back_into_one_list_in_id_order(tmp_path: Path, small) -> None:
    records = _records(*IDS)
    for name, shard in layout.shard("m", records).items():
        write_yaml(tmp_path / name, {"manufacturer": "m", "products": shard})
    write_yaml(tmp_path / "n.yaml", {"manufacturer": "n", "products": _records("n/1")})
    assert layout.read_catalog(tmp_path) == {"m": records, "n": _records("n/1")}
    assert [r["id"] for r in layout.iter_products(tmp_path)] == [*IDS, "n/1"]


def test_read_catalog_refuses_an_id_two_files_hold(tmp_path: Path) -> None:
    write_yaml(tmp_path / "m.9.yaml", {"manufacturer": "m", "products": _records("m/91")})
    write_yaml(tmp_path / "m.91.yaml", {"manufacturer": "m", "products": _records("m/91")})
    with pytest.raises(ValueError, match="m/91 is in both"):
        layout.read_catalog(tmp_path)


def test_read_catalog_refuses_a_file_that_names_another_manufacturer(tmp_path: Path) -> None:
    write_yaml(tmp_path / "m.9.yaml", {"manufacturer": "n", "products": _records("n/9")})
    with pytest.raises(ValueError, match="m.9.yaml declares manufacturer 'n'"):
        layout.read_catalog(tmp_path)


def _seed_more_gw(paths: DataPaths) -> None:
    """Five more GW products beside seed()'s one, across three code families."""
    gw = paths.evidence_products / "mfr-gw" / "observations.jsonl"
    extra = [("99120110078", "Kit A"), ("99120110079", "Kit B"), ("99120201001", "Kit C"),
             ("60010199001", "Kit D"), ("60010199002", "Kit E")]
    with gw.open("a", encoding="utf-8", newline="\n") as out:
        for code, name in extra:
            out.write(json.dumps(
                {"key": f"mfr-gw:{code}", "name": name, "manufacturer": "games-workshop", "sku": code,
                 "firstSeen": "2026-07-07", "lastSeen": "2026-07-12", "extractor": "algolia@1"},
                sort_keys=True, separators=(",", ":")) + "\n")


def test_resolve_shards_a_manufacturer_over_the_threshold_and_its_sweep_retires_the_single_file(
    tmp_path: Path, monkeypatch
) -> None:
    paths = seed(tmp_path)
    _seed_more_gw(paths)
    resolve_catalog(paths)
    single = paths.catalog_products / "games-workshop.yaml"
    assert [p.name for p in layout.product_files(paths.catalog_products)] == ["games-workshop.yaml"]
    before = layout.read_catalog(paths.catalog_products)

    monkeypatch.setattr(layout, "SHARD_ABOVE", 4)
    monkeypatch.setattr(layout, "SPLIT_ABOVE", 2)
    monkeypatch.setattr(layout, "OWN_FILE_ABOVE", 1)
    resolve_catalog(paths)
    files = layout.product_files(paths.catalog_products)
    assert not single.exists()
    assert len(files) > 1 and all(re.fullmatch(r"games-workshop\.[0-9a-z_-]+\.yaml", f.name) for f in files)
    # A PURE RELAYOUT: the same records, the same bytes per record, only in more files.
    assert layout.read_catalog(paths.catalog_products) == before

    written = {f.name: f.read_bytes() for f in files}
    resolve_catalog(paths)
    assert {f.name: f.read_bytes() for f in layout.product_files(paths.catalog_products)} == written

    # And back: a manufacturer that falls under the threshold is one file again, shards swept.
    monkeypatch.setattr(layout, "SHARD_ABOVE", 4000)
    resolve_catalog(paths)
    assert [p.name for p in layout.product_files(paths.catalog_products)] == ["games-workshop.yaml"]
    assert layout.read_catalog(paths.catalog_products) == before


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_the_ean_guard_reads_a_relayout_as_every_barcode_present(tmp_path: Path, small) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init",), ("config", "user.email", "t@example.com"), ("config", "user.name", "T")):
        _git(*args, cwd=repo)
    paths = DataPaths(repo / "data")
    records = [
        {"id": i, "name": i, "manufacturer": "m", "ean": f"50119211{n:05d}", "eanConfidence": "confirmed",
         **({"additionalEans": [f"50119212{n:05d}"]} if n % 2 else {})}
        for n, i in enumerate(IDS)
    ]
    write_yaml(paths.catalog_products / "m.yaml", {"manufacturer": "m", "products": records})
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "one file", cwd=repo)

    (paths.catalog_products / "m.yaml").unlink()
    for name, shard in layout.shard("m", records).items():
        write_yaml(paths.catalog_products / name, {"manufacturer": "m", "products": shard})

    findings = check_ean_guard(paths)
    assert {k: v for k, v in findings.items() if v} == {}


def test_the_committed_catalog_is_laid_out_by_the_rule() -> None:
    """Every manufacturer's committed files are exactly the ones `shard` names for its records.

    Catches a hand-edited tree, and a layout change that landed without the resolve that applies it.
    """
    products = REPO_ROOT / "data" / "catalog" / "products"
    if not products.exists():
        pytest.skip("data/catalog/products/ not present")
    expected = {
        name
        for manufacturer, records in layout.read_catalog(products).items()
        for name in layout.shard(manufacturer, records)
    }
    assert {p.name for p in layout.product_files(products)} == expected


def test_layout_imports_nothing_a_pyyaml_only_script_lacks() -> None:
    """gen_set_contents.py runs as `uv run --with pyyaml python ...` and reads the catalog through
    this module, so it may import only the stdlib and yamlio (whose own imports are pyyaml-only)."""
    found = set()
    for line in Path(layout.__file__).read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(?:from|import)\s+([\w.]+)", line)
        if match:
            found.add(match.group(1))
    assert found == {"__future__", "re", "collections", "collections.abc", "pathlib", "warhub_acquisition.yamlio"}
