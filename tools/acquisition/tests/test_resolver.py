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


def test_barcode_db_source_corroborates_provisional_ean_to_confirmed(tmp_path: Path) -> None:
    """End-to-end: seed() produces a `provisional` ean (a single retailer source). Adding a
    barcode-db observation asserting the SAME ean for the SAME entity must flip it to
    `confirmed` (retailer + barcode-db = two independent sources, at least one non-barcode-db --
    see resolve/corroborate.py's resolve_ean) -- proving the kind-priority wiring end to end
    through the real resolve pipeline, not just the corroborate.py/join.py unit tests."""
    paths = seed(tmp_path)
    write_yaml(
        paths.sources / "bdb-upcitemdb.yaml",
        {"id": "bdb-upcitemdb", "kind": "barcode-db", "strategy": "barcode-db"},
    )

    def line(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    bdb = paths.evidence_products / "bdb-upcitemdb" / "observations.jsonl"
    bdb.parent.mkdir(parents=True)
    bdb.write_text(
        line({"key": "bdb-upcitemdb:5011921194285", "name": "Some DB-sourced title",
              "manufacturer": "games-workshop", "ean": "5011921194285",
              "firstSeen": "2026-07-13", "lastSeen": "2026-07-13", "extractor": "barcode-db@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )

    resolve_catalog(paths)
    data = read_yaml(paths.catalog_products / "games-workshop.yaml")
    product = next(p for p in data["products"] if p["id"] == "games-workshop/99120110077")
    assert product["eanConfidence"] == "confirmed"
    assert product["ean"] == "5011921194285"
    assert set(product["evidence"]) == {"mfr-gw:necrons", "ret-goblin:cp-necrons", "bdb-upcitemdb:5011921194285"}


def test_barcode_db_alone_two_sources_stays_provisional_not_confirmed(tmp_path: Path) -> None:
    """Two barcode-db observations asserting the same ean, with no non-barcode-db assertion, must
    neither mint an entity (join.py's unjoined guard) nor confirm (corroborate.py's non-
    barcode-db requirement) -- this is the negative counterpart to the test above."""
    paths = seed(tmp_path)
    write_yaml(
        paths.sources / "bdb-upcitemdb.yaml",
        {"id": "bdb-upcitemdb", "kind": "barcode-db", "strategy": "barcode-db"},
    )
    write_yaml(
        paths.sources / "bdb-goupc.yaml",
        {"id": "bdb-goupc", "kind": "barcode-db", "strategy": "barcode-db"},
    )

    def line(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    orphan_ean = "5011921142361"  # not asserted by any non-barcode-db source in this seed
    upc = paths.evidence_products / "bdb-upcitemdb" / "observations.jsonl"
    upc.parent.mkdir(parents=True)
    upc.write_text(
        line({"key": f"bdb-upcitemdb:{orphan_ean}", "name": "Primaris Intercessors",
              "manufacturer": "games-workshop", "ean": orphan_ean,
              "firstSeen": "2026-07-13", "lastSeen": "2026-07-13", "extractor": "barcode-db@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    goupc = paths.evidence_products / "bdb-goupc" / "observations.jsonl"
    goupc.parent.mkdir(parents=True)
    goupc.write_text(
        line({"key": f"bdb-goupc:{orphan_ean}", "name": "Primaris Intercessors",
              "manufacturer": "games-workshop", "ean": orphan_ean,
              "firstSeen": "2026-07-13", "lastSeen": "2026-07-13", "extractor": "barcode-db@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )

    catalog = resolve_catalog(paths)
    ids = [p.id for records in catalog.values() for p in records]
    # the two orphaned barcode-db observations must not have minted a new entity
    assert not any(orphan_ean in p.ean for p in [p for records in catalog.values() for p in records] if p.ean)
    conflicts = read_yaml(paths.conflicts)["conflicts"]
    unjoined = [c for c in conflicts if c.get("type") == "barcode-db-unjoined"]
    assert {c["key"] for c in unjoined} == {f"bdb-upcitemdb:{orphan_ean}", f"bdb-goupc:{orphan_ean}"}
    # the original seeded entity is untouched -- still provisional
    data = read_yaml(paths.catalog_products / "games-workshop.yaml")
    product = next(p for p in data["products"] if p["id"] == "games-workshop/99120110077")
    assert product["eanConfidence"] == "provisional"


def test_null_game_system_entity_publishes_with_no_conflict(tmp_path: Path) -> None:
    """gameSystem is optional: a product no source ever hinted a gameSystem for (a base, a
    gaming mat, a paint/tool bundle, dice, an advent calendar, ...) publishes with
    gameSystem: null instead of being parked out of the catalog, and raises no conflict."""
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
    products = {p.id: p for records in catalog.values() for p in records}
    assert "games-workshop/99999999999" in products
    assert products["games-workshop/99999999999"].gameSystem is None
    assert read_yaml(paths.conflicts) == {"conflicts": []}
    # gameSystem: null is omitted (exclude_none), not written as an explicit null in the YAML
    data = read_yaml(paths.catalog_products / "games-workshop.yaml")
    record = next(p for p in data["products"] if p["id"] == "games-workshop/99999999999")
    assert "gameSystem" not in record


def test_reclassification_via_overrides_preserves_identity_ean_and_first_seen(tmp_path: Path) -> None:
    """Regression for issue #12 ("Cross-faction move identity: reclassified product loses EAN +
    resets firstSeen").

    In the LEGACY .NET pipeline product identity and EAN merge were scoped WITHIN a single
    faction-partitioned YAML file, so reclassifying a product into a different faction between
    runs dropped its previously-known EAN, reset its firstSeen, and left a stale duplicate in the
    old faction file.

    The Python resolver is immune by construction: identity is `manufacturer/code-or-slug`
    (resolve/identity.py -- gameSystem/faction never participate), the catalog is partitioned by
    MANUFACTURER not faction (resolve/resolver.py writes one `<manufacturer>.yaml`), and EAN +
    firstSeen are derived from the evidence observations (resolve/attributes.py), NOT from the
    classification. Reclassification is an overrides.yaml patch on gameSystem/faction only.

    This test does a full cross-faction AND cross-game-system move via overrides.yaml and asserts
    identity, EAN, eanConfidence and firstSeen all survive, faction/gameSystem update, and no
    stale duplicate is emitted (still exactly one entity in one manufacturer file, no conflict)."""
    paths = seed(tmp_path)

    before = resolve_catalog(paths)["games-workshop"][0]
    assert before.id == "games-workshop/99120110077"
    assert before.faction == "necrons"
    assert before.gameSystem == "warhammer-40k"
    assert before.ean == "5011921194285"
    assert before.eanConfidence == "provisional"
    assert before.firstSeen == "2026-07-07"

    # Reclassify: the documented mechanism is an overrides.yaml patch. Move the product clear
    # across to a different game system and faction -- the exact scenario issue #12 describes.
    write_yaml(
        paths.overrides,
        {"retract": [], "products": {
            "games-workshop/99120110077": {
                "gameSystem": "warhammer-age-of-sigmar", "faction": "stormcast-eternals"}}},
    )

    catalog = resolve_catalog(paths)
    products = [p for records in catalog.values() for p in records]
    assert len(products) == 1, "reclassification must not mint a duplicate entity"
    after = products[0]

    # identity survives the move
    assert after.id == before.id
    # the classification actually changed
    assert after.gameSystem == "warhammer-age-of-sigmar"
    assert after.faction == "stormcast-eternals"
    # EAN + confidence do NOT regress
    assert after.ean == before.ean
    assert after.eanConfidence == before.eanConfidence
    # firstSeen does NOT reset to "brand new in the destination faction"
    assert after.firstSeen == before.firstSeen
    # partition is by manufacturer, so there is exactly one file and no stale faction duplicate
    assert sorted(f.name for f in paths.catalog_products.glob("*.yaml")) == ["games-workshop.yaml"]
    assert read_yaml(paths.conflicts) == {"conflicts": []}


def test_reclassification_via_changed_source_hint_preserves_identity(tmp_path: Path) -> None:
    """Variant of issue #12 via the OTHER reclassification trigger named in the issue -- a changed
    source hint. A source re-observes the SAME product (same evidence key) but now hints a
    different gameSystem/faction. Because identity keys on manufacturer/code (not the hint) and
    firstSeen is preserved by EvidenceStore.upsert's `min(old, fresh)`, the entity keeps its id,
    EAN and firstSeen while only its classification changes."""
    paths = seed(tmp_path)
    before = resolve_catalog(paths)["games-workshop"][0]

    # Re-observation of mfr-gw:necrons with a moved classification. firstSeen stays 2026-07-07
    # (in a real run EvidenceStore.upsert would clamp it to min(old, fresh); here we assert the
    # resolver honours the persisted firstSeen rather than resetting on the classification change).
    gw = paths.evidence_products / "mfr-gw" / "observations.jsonl"
    gw.write_text(
        json.dumps(
            {"key": "mfr-gw:necrons", "name": "Combat Patrol: Necrons", "manufacturer": "games-workshop",
             "sku": "99120110077", "priceGbp": 76.5, "availability": "in_stock",
             "hints": {"gameSystem": "warhammer-age-of-sigmar", "faction": "stormcast-eternals"},
             "firstSeen": "2026-07-07", "lastSeen": "2026-07-15", "extractor": "algolia@1"},
            sort_keys=True, separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8", newline="\n",
    )

    catalog = resolve_catalog(paths)
    products = [p for records in catalog.values() for p in records]
    assert len(products) == 1
    after = products[0]
    assert after.id == before.id
    assert after.faction == "stormcast-eternals"
    assert after.gameSystem == "warhammer-age-of-sigmar"
    assert after.ean == before.ean
    assert after.eanConfidence == before.eanConfidence
    assert after.firstSeen == before.firstSeen
    assert sorted(f.name for f in paths.catalog_products.glob("*.yaml")) == ["games-workshop.yaml"]
