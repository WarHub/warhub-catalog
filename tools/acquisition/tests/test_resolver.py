import json
from pathlib import Path

from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import read_yaml, write_yaml


def seed(tmp_path: Path) -> DataPaths:
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.taxonomy / "manufacturers.yaml",
        {"manufacturers": [{"slug": "games-workshop", "name": "Games Workshop",
                            "codePattern": r"\d{11}", "codeStrip": ["GWS"],
                            "gs1Prefixes": ["5011921"], "vendorNames": []}]},
    )
    write_yaml(paths.sources / "mfr-gw.yaml", {"id": "mfr-gw", "kind": "manufacturer", "strategy": "algolia"})
    write_yaml(paths.sources / "ret-goblin.yaml", {"id": "ret-goblin", "kind": "retailer", "strategy": "shopify"})

    def line(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    gw = paths.evidence_products / "mfr-gw" / "observations.jsonl"
    gw.parent.mkdir(parents=True)
    gw.write_text(
        line({"key": "mfr-gw:necrons", "name": "Combat Patrol: Necrons", "manufacturer": "games-workshop",
              "sku": "99120110077", "priceGbp": 76.5, "availability": "in_stock",
              "hints": {"gameSystem": "warhammer-40k", "faction": "necrons"},
              "firstSeen": "2026-07-07", "lastSeen": "2026-07-12", "extractor": "algolia@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    goblin = paths.evidence_products / "ret-goblin" / "observations.jsonl"
    goblin.parent.mkdir(parents=True)
    goblin.write_text(
        line({"key": "ret-goblin:cp-necrons", "name": "Warhammer 40k: Combat Patrol Necrons",
              "manufacturer": "games-workshop", "sku": "GWS99120110077", "ean": "5011921194285",
              "url": "https://goblin/cp-necrons", "imageUrl": "https://goblin/img.jpg",
              "firstSeen": "2026-07-10", "lastSeen": "2026-07-12", "extractor": "shopify-handle-js@2"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    return paths


EXPECTED_CATALOG = """\
manufacturer: games-workshop
products:
  - id: games-workshop/99120110077
    name: 'Combat Patrol: Necrons'
    manufacturer: games-workshop
    productCode: '99120110077'
    sku: '99120110077'
    ean: '5011921194285'
    eanConfidence: provisional
    gameSystem: warhammer-40k
    faction: necrons
    category: miniatures
    status: current
    availability: in_stock
    firstSeen: '2026-07-07'
    priceGbp: 76.5
    url: https://goblin/cp-necrons
    imageUrl: https://goblin/img.jpg
    evidence:
      - mfr-gw:necrons
      - ret-goblin:cp-necrons
"""


def test_golden_resolve(tmp_path: Path) -> None:
    paths = seed(tmp_path)
    catalog = resolve_catalog(paths)

    out = (paths.catalog_products / "games-workshop.yaml").read_text(encoding="utf-8")
    assert out == EXPECTED_CATALOG
    assert read_yaml(paths.conflicts) == {"conflicts": []}
    assert list(catalog) == ["games-workshop"]

    # determinism: resolving again is byte-identical
    resolve_catalog(paths)
    assert (paths.catalog_products / "games-workshop.yaml").read_text(encoding="utf-8") == out


def test_retract_drops_entity(tmp_path: Path) -> None:
    paths = seed(tmp_path)
    write_yaml(paths.overrides, {"retract": ["games-workshop/99120110077"], "products": {}})
    catalog = resolve_catalog(paths)
    assert catalog == {}
    assert not (paths.catalog_products / "games-workshop.yaml").exists()


def test_alias_onto_retracted_raises(tmp_path: Path) -> None:
    import pytest

    paths = seed(tmp_path)
    write_yaml(paths.overrides, {"retract": ["games-workshop/99120110077"], "products": {}})
    write_yaml(paths.matches, {"joins": {}, "aliases": {"games-workshop/old": "games-workshop/99120110077"}})
    with pytest.raises(ValueError, match="retracted"):
        resolve_catalog(paths)


def test_unknown_evidence_source_raises(tmp_path: Path) -> None:
    import pytest

    paths = seed(tmp_path)
    rogue = paths.evidence_products / "rogue-src" / "observations.jsonl"
    rogue.parent.mkdir(parents=True)
    rogue.write_text(
        '{"extractor":"t@1","firstSeen":"2026-07-12","key":"rogue-src:x","lastSeen":"2026-07-12","manufacturer":"games-workshop","name":"X"}\n',
        encoding="utf-8", newline="\n",
    )
    with pytest.raises(ValueError, match="rogue-src"):
        resolve_catalog(paths)


def test_empty_evidence_refuses_to_wipe_existing_catalog(tmp_path: Path) -> None:
    import shutil

    import pytest

    paths = seed(tmp_path)
    resolve_catalog(paths)
    assert (paths.catalog_products / "games-workshop.yaml").exists()
    shutil.rmtree(paths.evidence_products)
    with pytest.raises(ValueError, match="refusing to wipe"):
        resolve_catalog(paths)
    assert (paths.catalog_products / "games-workshop.yaml").exists()


def test_stale_manufacturer_file_removed_on_rerun(tmp_path: Path) -> None:
    from warhub_acquisition.yamlio import write_yaml as _write_yaml

    paths = seed(tmp_path)
    resolve_catalog(paths)
    assert (paths.catalog_products / "games-workshop.yaml").exists()
    _write_yaml(paths.overrides, {"retract": ["games-workshop/99120110077"], "products": {}})
    resolve_catalog(paths)
    assert not (paths.catalog_products / "games-workshop.yaml").exists()


def test_join_onto_retracted_raises(tmp_path: Path) -> None:
    import pytest

    paths = seed(tmp_path)
    write_yaml(paths.overrides, {"retract": ["games-workshop/99120110077"], "products": {}})
    write_yaml(paths.matches, {"joins": {"ret-goblin:cp-necrons": "games-workshop/99120110077"}, "aliases": {}})
    with pytest.raises(ValueError, match="retracted"):
        resolve_catalog(paths)


def test_unclassified_entity_is_parked(tmp_path: Path) -> None:
    paths = seed(tmp_path)
    rogue = paths.evidence_products / "ret-goblin" / "observations.jsonl"
    line = json.dumps(
        {"key": "ret-goblin:mystery", "name": "Mystery Box No System", "manufacturer": "games-workshop",
         "sku": "99999999999", "firstSeen": "2026-07-12", "lastSeen": "2026-07-12",
         "extractor": "t@1"},
        sort_keys=True, separators=(",", ":"),
    )
    rogue.write_text(rogue.read_text(encoding="utf-8") + line + "\n", encoding="utf-8", newline="\n")
    catalog = resolve_catalog(paths)
    ids = [p.id for records in catalog.values() for p in records]
    assert "games-workshop/99999999999" not in ids
    conflicts = read_yaml(paths.conflicts)["conflicts"]
    assert any(c.get("type") == "unclassified-entity" and c.get("entity") == "games-workshop/99999999999" for c in conflicts)
