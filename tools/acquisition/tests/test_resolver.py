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
    gameSystemBasis: stated
    category: miniatures
    categoryBasis: guessed
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


def test_repackaging_forced_join_carries_multi_ean_and_live_price(tmp_path: Path) -> None:
    """End-to-end repackaging join: an OLD product code (curated old barcode + a stale manufacturer
    price) is folded via matches.yaml into the surviving CURRENT code (live manufacturer + retailer
    confirming the new barcode). The resolved entity must (1) keep the live/confirmed barcode as
    primary, (2) retain the displaced old barcode in additionalEans rather than dropping it, (3)
    take the live price over the stale one, and (4) raise no conflict."""
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.taxonomy / "manufacturers.yaml",
        {"manufacturers": [{"slug": "games-workshop", "name": "Games Workshop",
                            "codePattern": r"\d{11}", "codeStrip": ["GWS"],
                            "gs1Prefixes": ["5011921"], "vendorNames": []}]},
    )
    write_yaml(paths.sources / "mfr-gw.yaml", {"id": "mfr-gw", "kind": "manufacturer", "strategy": "algolia"})
    write_yaml(paths.sources / "ret-goblin.yaml", {"id": "ret-goblin", "kind": "retailer", "strategy": "shopify"})
    write_yaml(paths.sources / "legacy-catalog.yaml", {"id": "legacy-catalog", "kind": "curated", "strategy": "manual"})

    def line(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    mfr = paths.evidence_products / "mfr-gw" / "observations.jsonl"
    mfr.parent.mkdir(parents=True)
    mfr.write_text(
        # NEW packaging (surviving code 99120110002): live manufacturer confirms the new barcode
        # and lists the live price 20.0.
        line({"key": "mfr-gw:new", "name": "Widget", "manufacturer": "games-workshop", "sku": "99120110002",
              "ean": "5011921194285", "priceGbp": 20.0, "availability": "in_stock",
              "hints": {"gameSystem": "warhammer-40k"},
              "firstSeen": "2026-07-07", "lastSeen": "2026-07-12", "extractor": "algolia@1"}) + "\n"
        # OLD packaging (folded-in code 99120110001): a STALE manufacturer price 30.0, no barcode.
        + line({"key": "mfr-gw:old", "name": "Widget", "manufacturer": "games-workshop", "sku": "99120110001",
                "priceGbp": 30.0, "availability": "in_stock", "hints": {"gameSystem": "warhammer-40k"},
                "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "algolia@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    ret = paths.evidence_products / "ret-goblin" / "observations.jsonl"
    ret.parent.mkdir(parents=True)
    ret.write_text(
        line({"key": "ret-goblin:new", "name": "Widget 2025", "manufacturer": "games-workshop", "sku": "99120110002",
              "ean": "5011921194285", "firstSeen": "2026-07-08", "lastSeen": "2026-07-12", "extractor": "shopify@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    cur = paths.evidence_products / "legacy-catalog" / "observations.jsonl"
    cur.parent.mkdir(parents=True)
    cur.write_text(
        # OLD curated import carries the OLD (now displaced) barcode.
        line({"key": "legacy-catalog:old", "name": "Widget", "manufacturer": "games-workshop", "sku": "99120110001",
              "ean": "5011921194506", "hints": {"gameSystem": "warhammer-40k"},
              "firstSeen": "2026-07-01", "lastSeen": "2026-07-05", "extractor": "manual@1"}) + "\n"
        # NEW curated import (surviving side), so the surviving entity id is the NEW code.
        + line({"key": "legacy-catalog:new", "name": "Widget", "manufacturer": "games-workshop", "sku": "99120110002",
                "hints": {"gameSystem": "warhammer-40k"},
                "firstSeen": "2026-07-01", "lastSeen": "2026-07-05", "extractor": "manual@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    write_yaml(paths.matches, {"joins": {"legacy-catalog:old": "games-workshop/99120110002"}, "aliases": {}})

    catalog = resolve_catalog(paths)
    products = [p for records in catalog.values() for p in records]
    assert len(products) == 1  # OLD packaging folded into NEW
    prod = products[0]
    assert prod.id == "games-workshop/99120110002"
    assert prod.ean == "5011921194285"
    assert prod.eanConfidence == "confirmed"
    assert prod.additionalEans == ["5011921194506"]  # displaced OLD barcode retained, not dropped
    assert prod.priceGbp == 20.0  # live price wins over the stale 30.0 from the old packaging
    assert read_yaml(paths.conflicts) == {"conflicts": []}

    # single-barcode products never carry the key at all (byte-compatible for existing consumers)
    data = read_yaml(paths.catalog_products / "games-workshop.yaml")
    assert data["products"][0]["additionalEans"] == ["5011921194506"]


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


def test_reclassification_via_overrides_is_post_identity_attribute_patch(tmp_path: Path) -> None:
    """Overrides-based reclassification is a pure post-identity attribute patch.

    Context: issue #12 ("Cross-faction move identity: reclassified product loses EAN + resets
    firstSeen") described the LEGACY .NET pipeline, where identity and EAN merge were scoped
    within a single faction-partitioned YAML file. In the Python resolver, apply_overrides runs
    AFTER join/identity, EAN resolution, and firstSeen derivation (resolve/resolver.py:103,
    resolve/attributes.py:76-82), so an overrides.yaml gameSystem/faction patch structurally
    CANNOT move identity, drop the EAN, or reset firstSeen -- those equalities hold by
    construction, and this test does not (cannot) guard against a faction-scoped-identity
    regression; that guard is test_reclassification_via_changed_source_hint_preserves_identity
    below. What this test pins is the behaviour that makes the mechanism safe: the patch lands
    (gameSystem/faction actually change), it survives CanonicalProduct revalidation, no duplicate
    entity is minted, and no conflict is raised."""
    paths = seed(tmp_path)

    before = resolve_catalog(paths)["games-workshop"][0]
    assert before.id == "games-workshop/99120110077"
    assert before.faction == "necrons"
    assert before.gameSystem == "warhammer-40k"
    assert before.ean == "5011921194285"
    assert before.firstSeen == "2026-07-07"

    # Reclassify via the documented mechanism: an overrides.yaml patch, moving the product to a
    # different game system and faction.
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

    # the patch landed -- these are the non-trivial assertions here
    assert after.gameSystem == "warhammer-age-of-sigmar"
    assert after.faction == "stormcast-eternals"
    assert read_yaml(paths.conflicts) == {"conflicts": []}
    # documented invariant (holds by construction -- overrides apply post-identity): the patch
    # touched nothing but the two classification attributes
    # `gameSystemBasis` moves with them: the override IS what decided the value, and recording
    # which of `stated`/`mapped`/`classified`/`override` decided a gameSystem is the whole point of
    # the field. Everything else must still be untouched.
    assert after.gameSystemBasis == "override"
    assert after.model_dump(exclude={"gameSystem", "faction", "gameSystemBasis"}) == before.model_dump(
        exclude={"gameSystem", "faction", "gameSystemBasis"}
    )


def test_reclassification_via_changed_source_hint_preserves_identity(tmp_path: Path) -> None:
    """Regression guard for issue #12 ("Cross-faction move identity: reclassified product loses
    EAN + resets firstSeen"), via the trigger with teeth: a changed source classification hint.

    A source re-observes the SAME product (same evidence key) but now hints a different
    gameSystem/faction, so the changed classification flows through join/identity input -- if
    entity identity were faction-scoped (as in the legacy .NET pipeline the issue describes),
    the changed hint would mint a NEW entity id, orphaning the EAN and firstSeen on a stale
    duplicate. Because entity_id keys only on manufacturer/code-or-slug (resolve/identity.py)
    and EAN + firstSeen derive from the persisted observations (resolve/attributes.py), the
    entity keeps its id, EAN, eanConfidence and firstSeen while only its classification changes.

    The persisted firstSeen is held fixed here; the EvidenceStore.upsert min(old, fresh) clamp
    for a re-observation carrying a LATER firstSeen is covered separately by
    test_upsert_reobservation_with_changed_hint_clamps_first_seen."""
    paths = seed(tmp_path)
    before = resolve_catalog(paths)["games-workshop"][0]

    # Re-observation of mfr-gw:necrons with a moved classification, firstSeen unchanged.
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
    assert len(products) == 1, "changed classification hint must not mint a duplicate entity"
    after = products[0]
    assert after.id == before.id
    assert after.faction == "stormcast-eternals"
    assert after.gameSystem == "warhammer-age-of-sigmar"
    assert after.ean == before.ean
    assert after.eanConfidence == before.eanConfidence
    assert after.firstSeen == before.firstSeen


def test_upsert_reobservation_with_changed_hint_clamps_first_seen(tmp_path: Path) -> None:
    """Companion to the source-hint regression test above: drive the actual acquire-side write
    path. A second sweep re-observes the SAME evidence key with a changed gameSystem/faction hint
    and a LATER firstSeen (a fresh observation only knows "seen today"). EvidenceStore.upsert
    must clamp the stored firstSeen to min(old, fresh) (evidence/store.py:31-38) -- and a
    subsequent resolve must keep the entity's id, EAN and original firstSeen while adopting the
    new classification."""
    from warhub_acquisition.evidence.store import EvidenceStore
    from warhub_acquisition.models.observation import Observation

    paths = seed(tmp_path)
    before = resolve_catalog(paths)["games-workshop"][0]
    assert before.firstSeen == "2026-07-07"

    store = EvidenceStore(paths.evidence_products)
    store.upsert(
        "mfr-gw",
        Observation(
            key="mfr-gw:necrons", name="Combat Patrol: Necrons", manufacturer="games-workshop",
            sku="99120110077", priceGbp=76.5, availability="in_stock",
            hints={"gameSystem": "warhammer-age-of-sigmar", "faction": "stormcast-eternals"},
            firstSeen="2026-07-15", lastSeen="2026-07-15", extractor="algolia@1",
        ),
    )
    store.save("mfr-gw")

    # the persisted record kept the OLD firstSeen and took the new lastSeen + classification
    stored = EvidenceStore(paths.evidence_products).load("mfr-gw")["mfr-gw:necrons"]
    assert stored.firstSeen == "2026-07-07"
    assert stored.lastSeen == "2026-07-15"
    assert stored.hints == {"gameSystem": "warhammer-age-of-sigmar", "faction": "stormcast-eternals"}

    catalog = resolve_catalog(paths)
    products = [p for records in catalog.values() for p in records]
    assert len(products) == 1
    after = products[0]
    assert after.id == before.id
    assert after.faction == "stormcast-eternals"
    assert after.gameSystem == "warhammer-age-of-sigmar"
    assert after.ean == before.ean
    assert after.eanConfidence == before.eanConfidence
    assert after.firstSeen == before.firstSeen == "2026-07-07"


def test_supersession_publishes_both_records_and_moves_the_retired_barcode(tmp_path: Path) -> None:
    """The archival counterpart to the repackaging-join test above. Same evidence shape, but the
    pair is DECLARED rather than folded: both records must publish, the retired barcode MOVES to
    the retired record (it is not duplicated onto the survivor), the retired record inherits
    `discontinued` from the ordinary lifecycle rules, and the link points both ways."""
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

    mfr = paths.evidence_products / "mfr-gw" / "observations.jsonl"
    mfr.parent.mkdir(parents=True)
    mfr.write_text(
        # RETIRED packaging: the trade row is archived and carries the old barcode.
        line({"key": "mfr-gw:old", "name": "Widget", "manufacturer": "games-workshop", "sku": "99120110001",
              "ean": "5011921062164", "archived": True, "hints": {"gameSystem": "warhammer-40k"},
              "firstSeen": "2026-07-01", "lastSeen": "2026-07-05", "extractor": "algolia@1"}) + "\n"
        + line({"key": "mfr-gw:new", "name": "Widget", "manufacturer": "games-workshop", "sku": "99120110002",
                "ean": "5011921179398", "priceGbp": 20.0, "availability": "in_stock",
                "hints": {"gameSystem": "warhammer-40k"},
                "firstSeen": "2026-07-07", "lastSeen": "2026-07-12", "extractor": "algolia@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    ret = paths.evidence_products / "ret-goblin" / "observations.jsonl"
    ret.parent.mkdir(parents=True)
    ret.write_text(
        # The bridge: still filed under the RETIRED code, but scanning as the CURRENT barcode.
        line({"key": "ret-goblin:widget", "name": "Widget", "manufacturer": "games-workshop",
              "sku": "99120110001", "ean": "5011921179398", "url": "https://goblin/widget",
              "firstSeen": "2026-07-08", "lastSeen": "2026-07-12", "extractor": "shopify@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    write_yaml(paths.matches, {"supersessions": {"games-workshop/99120110001": "games-workshop/99120110002"}})

    catalog = resolve_catalog(paths)
    retired, current = catalog["games-workshop"]

    assert retired.id == "games-workshop/99120110001"
    assert retired.productCode == "99120110001"
    assert retired.ean == "5011921062164"          # its own barcode, kept as the PRIMARY
    assert retired.eanConfidence == "confirmed"
    assert retired.status == "discontinued"        # free from the existing lifecycle rules
    assert retired.supersededBy == "games-workshop/99120110002"
    assert retired.supersedes == []

    assert current.id == "games-workshop/99120110002"
    assert current.ean == "5011921179398"
    assert current.additionalEans == []            # the retired barcode MOVED, it is not duplicated
    assert current.supersedes == ["games-workshop/99120110001"]
    assert current.supersededBy is None
    assert current.url == "https://goblin/widget"  # the re-homed retailer's live listing

    # THE RE-HOMING IS REPORTED, BUT NOT AS A CONFLICT. It is a placement the resolver made on its
    # own and cannot be argued with by editing data, so it goes to rehomed.yaml and leaves the
    # working set empty -- which is the whole point: `conflicts.yaml` is a set of open questions,
    # and a run whose only finding is a re-homing is a clean run.
    assert read_yaml(paths.conflicts)["conflicts"] == []
    assert [c["type"] for c in read_yaml(paths.rehomed)["rehomed"]] == ["supersession-stale-code"]

    # both link keys are omitted entirely where they are empty, so every other record is unchanged
    written = read_yaml(paths.catalog_products / "games-workshop.yaml")["products"]
    assert "supersedes" not in written[0] and written[0]["supersededBy"] == "games-workshop/99120110002"
    assert "supersededBy" not in written[1] and written[1]["supersedes"] == ["games-workshop/99120110001"]


def test_supersession_onto_retracted_raises(tmp_path: Path) -> None:
    import pytest

    paths = seed(tmp_path)
    write_yaml(paths.overrides, {"retract": ["games-workshop/99120110077"], "products": {}})
    write_yaml(paths.matches, {"supersessions": {"games-workshop/old": "games-workshop/99120110077"}})
    with pytest.raises(ValueError, match="retracted"):
        resolve_catalog(paths)


def test_supersession_cycle_raises(tmp_path: Path) -> None:
    import pytest

    paths = seed(tmp_path)
    write_yaml(paths.matches, {"supersessions": {"games-workshop/a": "games-workshop/b",
                                                 "games-workshop/b": "games-workshop/a"}})
    with pytest.raises(ValueError, match="cycle"):
        resolve_catalog(paths)


def test_paint_source_observations_never_publish_as_products(tmp_path: Path) -> None:
    """Paint sources share the evidence layout but feed the PAINT catalog. Before this, every
    paint they observed also published as a product -- measured 4,839 duplicate records across 9
    manufacturers, none of which anyone ever committed."""
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.taxonomy / "manufacturers.yaml",
        {"manufacturers": [{"slug": "games-workshop", "name": "Games Workshop",
                            "codePattern": r"\d{11}", "codeStrip": [], "gs1Prefixes": [],
                            "vendorNames": []},
                           {"slug": "vallejo", "name": "Vallejo", "vendorNames": []}]},
    )
    write_yaml(paths.sources / "mfr-gw.yaml", {"id": "mfr-gw", "kind": "manufacturer", "strategy": "algolia"})
    write_yaml(paths.sources / "mfr-vallejo.yaml",
               {"id": "mfr-vallejo", "kind": "manufacturer", "catalog": "paints", "strategy": "wp-rest-paints"})

    def line(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    gw = paths.evidence_products / "mfr-gw" / "observations.jsonl"
    gw.parent.mkdir(parents=True)
    gw.write_text(
        line({"key": "mfr-gw:necrons", "name": "Combat Patrol: Necrons", "manufacturer": "games-workshop",
              "sku": "99120110077", "hints": {"gameSystem": "warhammer-40k"},
              "firstSeen": "2026-07-07", "lastSeen": "2026-07-12", "extractor": "algolia@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    paint = paths.evidence_products / "mfr-vallejo" / "observations.jsonl"
    paint.parent.mkdir(parents=True)
    paint.write_text(
        line({"key": "mfr-vallejo:model-air-russian-green", "name": "3B Russian Green",
              "manufacturer": "vallejo", "sku": "71281", "hints": {"category": "paint"},
              "firstSeen": "2026-07-23", "lastSeen": "2026-07-30", "extractor": "wp-rest-paints@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )

    catalog = resolve_catalog(paths)

    assert list(catalog) == ["games-workshop"]
    assert not (paths.catalog_products / "vallejo.yaml").exists()
    # the evidence itself is untouched -- gen_paint_harvest.py still reads it
    assert paint.exists()


# --- crossoverToProducts: boxed sets from a paint source ------------------------------------
# Boxed multi-pot sets are products, not paints (maintainer decision 2026-08-05). A paint source
# declares which of its rows those are; the resolver admits exactly those and gen_paint_harvest.py
# refuses exactly those. Fixtures only -- the repo-data half of the contract is in
# test_repo_data.py, and the predicate itself in test_crossover.py.

GSW_SET_RULE = {
    "reason": "boxed multi-pot sets are products; measured 2026-08-05, 69 of 477",
    "category": "paint-set",
    "anyOf": [
        {"hintEquals": {"categorySlug": "paint-sets"}},
        {"nameMatches": r"\b(SET|COLLECTION)\b"},
    ],
}


def seed_paint_source(tmp_path: Path, crossover: dict | None) -> tuple[DataPaths, Path]:
    """A products source plus a paints source holding one set-shaped row and one real single."""
    paths = seed(tmp_path)
    descriptor = {"id": "mfr-gsw", "kind": "manufacturer", "catalog": "paints",
                  "strategy": "sitemap-sd-paints"}
    if crossover is not None:
        descriptor["crossoverToProducts"] = crossover
    write_yaml(paths.sources / "mfr-gsw.yaml", descriptor)

    manufacturers = read_yaml(paths.taxonomy / "manufacturers.yaml")
    manufacturers["manufacturers"].append(
        {"slug": "green-stuff-world", "name": "Green Stuff World", "codePattern": r"\d{3,5}",
         "codeStrip": [], "gs1Prefixes": [], "vendorNames": []}
    )
    write_yaml(paths.taxonomy / "manufacturers.yaml", manufacturers)

    def line(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    path = paths.evidence_products / "mfr-gsw" / "observations.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        line({"key": "mfr-gsw:box", "name": "Paint Set - Chrome", "manufacturer": "green-stuff-world",
              "sku": "12345", "ean": "8435646800011",
              # the store's OWN category is the range, not `paint-sets` -- and it calls the box a
              # paint, which is exactly why `category` has to be stamped
              "hints": {"categorySlug": "chrome-paints", "category": "paint", "volumeMl": 17},
              "firstSeen": "2026-07-24", "lastSeen": "2026-08-05",
              "extractor": "sitemap-sd-paints@1"}) + "\n"
        + line({"key": "mfr-gsw:single", "name": "Acrylic Color WONKA VIOLET",
                "manufacturer": "green-stuff-world", "sku": "3220", "ean": "8435646800028",
                "hints": {"categorySlug": "acrylic-paints", "category": "paint"},
                "firstSeen": "2026-07-24", "lastSeen": "2026-08-05",
                "extractor": "sitemap-sd-paints@1"}) + "\n",
        encoding="utf-8", newline="\n",
    )
    return paths, path


def test_paint_source_without_a_crossover_block_contributes_nothing(tmp_path: Path) -> None:
    """T10 -- today's behaviour, and what the four blockless paint sources still get."""
    paths, evidence = seed_paint_source(tmp_path, crossover=None)
    catalog = resolve_catalog(paths)
    assert list(catalog) == ["games-workshop"]
    assert not (paths.catalog_products / "green-stuff-world.yaml").exists()
    assert evidence.exists()  # gen_paint_harvest.py still reads it


def test_crossover_admits_the_set_and_stamps_its_category(tmp_path: Path) -> None:
    """T11 -- only the SELECTED row crosses, and `category` is the only field that changes."""
    paths, _ = seed_paint_source(tmp_path, GSW_SET_RULE)
    catalog = resolve_catalog(paths)

    assert sorted(catalog) == ["games-workshop", "green-stuff-world"]
    products = catalog["green-stuff-world"]
    assert [p.id for p in products] == ["green-stuff-world/12345"]
    box = products[0]
    # the store said `paint`; the descriptor's `category` overwrites it (without this a 12-pot
    # box publishes as an individual paint -- the lie commit 6b3c930 fixed on the paint side)
    assert box.category == "paint-set"
    assert box.name == "Paint Set - Chrome"
    assert box.ean == "8435646800011"
    # every OTHER hint survives untouched
    assert box.volumeMl == 17
    # the single is still a paint-catalog row and reaches no product file
    assert read_yaml(paths.conflicts) == {"conflicts": []}


def test_crossover_row_without_code_or_ean_is_refused_as_a_conflict(tmp_path: Path) -> None:
    """T12 -- the identity floor. A name-slug entity id is orphaned by a store retitle, so an
    unaddressable set is surfaced for a human instead of published. Measured on real evidence
    2026-08-11: 32 of 562, all mfr-ak-interactive."""
    paths, evidence = seed_paint_source(tmp_path, GSW_SET_RULE)
    rows = evidence.read_text(encoding="utf-8").splitlines()
    rows.append(json.dumps({"key": "mfr-gsw:nameless-box", "name": "Mystery Collection",
                            "manufacturer": "green-stuff-world", "sku": "RANGE-GSW",
                            "hints": {"category": "paint"},
                            "firstSeen": "2026-07-24", "lastSeen": "2026-08-05",
                            "extractor": "sitemap-sd-paints@1"}, sort_keys=True,
                           separators=(",", ":")))
    evidence.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")

    catalog = resolve_catalog(paths)

    assert [p.id for p in catalog["green-stuff-world"]] == ["green-stuff-world/12345"]
    conflicts = read_yaml(paths.conflicts)["conflicts"]
    assert conflicts == [
        {"type": "paint-set-without-identity", "source": "mfr-gsw", "key": "mfr-gsw:nameless-box",
         "sku": "RANGE-GSW", "name": "Mystery Collection"}
    ]


def test_a_refused_crossover_row_is_typed_by_its_own_clause_not_by_the_word_set(
    tmp_path: Path,
) -> None:
    """T12b -- the refusal type must say what the row IS, and the row is not always a set.

    A per-clause `category` lets one source cross two kinds of thing (crossover.py::category_for),
    so a fixed `set-without-identity` filed the auxiliaries as boxes. Measured on real evidence
    2026-08-11: 3 of the 32 refusals -- AKABT111/112/113, the odourless / matt-effect / fast-dry
    thinners -- stamp `hobby-auxiliary`, so a maintainer triaging `set-without-identity` was
    looking for a boxed set and finding a bottle of thinner. The row below is the same shape: it
    matches only the narrow clause, and it must be refused under THAT clause's word.

    The control is the sibling test above -- a `paint-set` refusal from the SAME block still types
    `paint-set-without-identity`, so this pins the derivation and not merely a new constant.
    """
    rule = {**GSW_SET_RULE, "anyOf": [{"nameMatches": r"\bTHINNER\b", "category": "hobby-auxiliary"},
                                      *GSW_SET_RULE["anyOf"]]}
    paths, evidence = seed_paint_source(tmp_path, rule)
    rows = evidence.read_text(encoding="utf-8").splitlines()
    rows.append(json.dumps({"key": "mfr-gsw:nameless-thinner", "name": "Odourless Thinner Set",
                            "manufacturer": "green-stuff-world", "sku": "RANGE-GSW",
                            "hints": {"category": "paint"},
                            "firstSeen": "2026-07-24", "lastSeen": "2026-08-05",
                            "extractor": "sitemap-sd-paints@1"}, sort_keys=True,
                           separators=(",", ":")))
    evidence.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")

    resolve_catalog(paths)

    # The title carries BOTH signals ("Thinner" and "Set"); the narrow clause is first, so it wins
    # -- the same clause-order rule that decides the stamp on an admitted row.
    assert read_yaml(paths.conflicts)["conflicts"] == [
        {"type": "hobby-auxiliary-without-identity", "source": "mfr-gsw",
         "key": "mfr-gsw:nameless-thinner", "sku": "RANGE-GSW", "name": "Odourless Thinner Set"}
    ]


def test_crossover_elsewhere_does_not_disturb_a_products_source(tmp_path: Path) -> None:
    """T13 -- the products half of the partition is byte-identical to the no-crossover run."""
    baseline_paths = seed(tmp_path / "baseline")
    resolve_catalog(baseline_paths)
    baseline = (baseline_paths.catalog_products / "games-workshop.yaml").read_text(encoding="utf-8")

    paths, _ = seed_paint_source(tmp_path / "with-crossover", GSW_SET_RULE)
    resolve_catalog(paths)
    after = (paths.catalog_products / "games-workshop.yaml").read_text(encoding="utf-8")

    assert after == baseline


def test_crossover_rows_alone_do_not_satisfy_the_wipe_guard(tmp_path: Path) -> None:
    """The guard asks about PRODUCT-SOURCE evidence, not about the merged observation list.

    Crossover put crossed paint rows into the same list the guard counted, so a run where every
    `catalog: products` source failed to load would sail past `if not observations`, publish only
    the crossover manufacturers, and then let the stale-file sweep unlink every real product file.
    Losing the entire product catalog to a transient evidence-loading failure is precisely what
    this guard exists to prevent, so crossed rows must not be able to satisfy it.
    """
    import shutil

    import pytest

    paths, _ = seed_paint_source(tmp_path, GSW_SET_RULE)
    resolve_catalog(paths)
    assert (paths.catalog_products / "games-workshop.yaml").exists()
    assert (paths.catalog_products / "green-stuff-world.yaml").exists()

    # Every products source's evidence vanishes; the paints source still loads and still crosses.
    shutil.rmtree(paths.evidence_products / "mfr-gw", ignore_errors=True)
    shutil.rmtree(paths.evidence_products / "ret-goblin", ignore_errors=True)
    assert (paths.evidence_products / "mfr-gsw").exists()

    with pytest.raises(ValueError, match="refusing to wipe"):
        resolve_catalog(paths)
    assert (paths.catalog_products / "games-workshop.yaml").exists()


def _minimal_catalog(paths: DataPaths, observations: str) -> None:
    write_yaml(
        paths.taxonomy / "manufacturers.yaml",
        {"manufacturers": [{"slug": "games-workshop", "name": "Games Workshop",
                            "codePattern": r"\d{11}", "codeStrip": [],
                            "gs1Prefixes": ["5011921"], "vendorNames": []}]},
    )
    write_yaml(paths.sources / "mfr-gw.yaml", {"id": "mfr-gw", "kind": "manufacturer", "strategy": "algolia"})
    path = paths.evidence_products / "mfr-gw" / "observations.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(observations, encoding="utf-8", newline="\n")


def test_a_run_with_nothing_to_report_still_writes_an_empty_rehomed_file(tmp_path: Path) -> None:
    """A stale artifact is worse than an empty one: yesterday's re-homings left on disk would be
    read as today's. Both review files are rewritten every run, whether or not they have rows.
    """
    paths = DataPaths(tmp_path)
    _minimal_catalog(paths, json.dumps({
        "key": "mfr-gw:widget", "name": "Widget", "manufacturer": "games-workshop",
        "sku": "99120110001", "ean": "5011921062164", "firstSeen": "2026-07-07",
        "lastSeen": "2026-07-07", "extractor": "test@1"}) + "\n")

    resolve_catalog(paths)

    assert paths.rehomed.exists()
    assert read_yaml(paths.rehomed) == {"rehomed": []}
    assert read_yaml(paths.conflicts) == {"conflicts": []}


def test_a_stale_rehomed_file_is_replaced_rather_than_appended_to(tmp_path: Path) -> None:
    """The pairing of the test above: a file left from an earlier run must not survive a clean one."""
    paths = DataPaths(tmp_path)
    _minimal_catalog(paths, json.dumps({
        "key": "mfr-gw:widget", "name": "Widget", "manufacturer": "games-workshop",
        "sku": "99120110001", "ean": "5011921062164", "firstSeen": "2026-07-07",
        "lastSeen": "2026-07-07", "extractor": "test@1"}) + "\n")
    write_yaml(paths.rehomed, {"rehomed": [{"type": "supersession-stale-code", "key": "gone:row"}]})

    resolve_catalog(paths)

    assert read_yaml(paths.rehomed) == {"rehomed": []}
