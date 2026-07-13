"""Cross-stack golden fixture.

Proves the Python canonical-YAML writer (``resolve_catalog``) and the .NET publisher
(``YamlSource`` + ``ProductBuilder``) agree byte-for-byte on the same small catalog: two
products covering the ean/confidence matrix (confirmed via a curated assertion,
provisional via a lone retailer assertion), quantity present/absent (publisher defaults
to 1 when absent), and faction present/null.

The committed fixture lives at
``tools/WarHub.Catalog.Publish.Tests/fixtures/canonical-golden/`` and is consumed
directly by ``CanonicalGoldenTests.cs`` on the .NET side. This test regenerates the same
three files from the fixed in-code catalog below via the real resolver path and asserts
byte-equality with what's committed -- drift fails CI with instructions to regenerate.

Regenerate (after a deliberate, reviewed change) with:
    REGEN_GOLDEN=1 uv run pytest -q tests/test_golden_fixture.py
"""
import json
import os
from pathlib import Path

from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import write_yaml

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "WarHub.Catalog.Publish.Tests"
    / "fixtures"
    / "canonical-golden"
)

# Static taxonomy label files: inputs to the resolver, not derived from evidence, so
# they're just the fixed content itself (copied verbatim into the tmp catalog and
# byte-compared against the committed fixture, same as the generated products file).
GAME_SYSTEMS_YAML = """\
gameSystems:
  - slug: warhammer-40k
    label: Warhammer 40,000
"""

FACTIONS_YAML = """\
factions:
  - slug: necrons
    label: Necrons
"""


def _line(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _seed(tmp_path: Path) -> DataPaths:
    paths = DataPaths(tmp_path)

    write_yaml(
        paths.taxonomy / "manufacturers.yaml",
        {
            "manufacturers": [
                {
                    "slug": "games-workshop",
                    "name": "Games Workshop",
                    "codePattern": r"\d{11}",
                    "codeStrip": ["GWS"],
                    "gs1Prefixes": ["5011921"],
                    "vendorNames": [],
                }
            ]
        },
    )
    (paths.taxonomy / "game-systems.yaml").write_text(GAME_SYSTEMS_YAML, encoding="utf-8", newline="\n")
    (paths.taxonomy / "factions.yaml").write_text(FACTIONS_YAML, encoding="utf-8", newline="\n")

    write_yaml(paths.sources / "mfr-gw-algolia.yaml",
               {"id": "mfr-gw-algolia", "kind": "manufacturer", "strategy": "algolia"})
    write_yaml(paths.sources / "curated-warhub.yaml",
               {"id": "curated-warhub", "kind": "curated", "strategy": "manual"})
    write_yaml(paths.sources / "ret-goblin.yaml",
               {"id": "ret-goblin", "kind": "retailer", "strategy": "shopify"})

    # Product B (Boarding Patrol: Death Guard) has no codePattern-valid sku on either
    # source, so the two observations only merge via this forced join -- which also
    # means the resolved entity has no productCode, exercising the publisher's
    # productCode -> sku fallback.
    write_yaml(
        paths.matches,
        {
            "joins": {"ret-goblin:boarding-patrol-death-guard": "games-workshop/boarding-patrol-death-guard"},
            "aliases": {},
        },
    )

    # Product A: Combat Patrol: Necrons -- confirmed EAN (curated assertion), quantity
    # present (3), faction present (necrons).
    algolia = paths.evidence_products / "mfr-gw-algolia" / "observations.jsonl"
    algolia.parent.mkdir(parents=True)
    algolia.write_text(
        _line({
            "key": "mfr-gw-algolia:necrons", "name": "Combat Patrol: Necrons",
            "manufacturer": "games-workshop", "sku": "99120110052", "priceGbp": 76.5,
            "availability": "in_stock",
            "hints": {"gameSystem": "warhammer-40k", "faction": "necrons", "quantity": 3},
            "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "algolia@1",
        }) + "\n"
        # Product B: Boarding Patrol: Death Guard -- provisional EAN (lone retailer
        # assertion), quantity absent, faction absent.
        + _line({
            "key": "mfr-gw-algolia:boarding-patrol-death-guard", "name": "Boarding Patrol: Death Guard",
            "manufacturer": "games-workshop", "sku": "BOARD-DG", "priceGbp": 65.0,
            "availability": "in_stock", "hints": {"gameSystem": "warhammer-40k"},
            "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "algolia@1",
        }) + "\n",
        encoding="utf-8", newline="\n",
    )

    curated = paths.evidence_products / "curated-warhub" / "observations.jsonl"
    curated.parent.mkdir(parents=True)
    curated.write_text(
        _line({
            "key": "curated-warhub:necrons", "name": "Combat Patrol: Necrons",
            "manufacturer": "games-workshop", "sku": "99120110052", "ean": "5011921194506",
            "firstSeen": "2026-07-01", "lastSeen": "2026-07-12", "extractor": "manual@1",
        }) + "\n",
        encoding="utf-8", newline="\n",
    )

    goblin = paths.evidence_products / "ret-goblin" / "observations.jsonl"
    goblin.parent.mkdir(parents=True)
    goblin.write_text(
        _line({
            "key": "ret-goblin:boarding-patrol-death-guard",
            "name": "Warhammer 40k: Boarding Patrol Death Guard",
            "manufacturer": "games-workshop", "sku": "GWS-BOARD-DG", "ean": "5011921194605",
            "url": "https://goblingaming/boarding-patrol-death-guard",
            "firstSeen": "2026-07-05", "lastSeen": "2026-07-12", "extractor": "shopify-handle-js@2",
        }) + "\n",
        encoding="utf-8", newline="\n",
    )

    return paths


def _generated_files(paths: DataPaths) -> dict[str, Path]:
    return {
        "products/games-workshop.yaml": paths.catalog_products / "games-workshop.yaml",
        "taxonomy/game-systems.yaml": paths.taxonomy / "game-systems.yaml",
        "taxonomy/factions.yaml": paths.taxonomy / "factions.yaml",
    }


def test_golden_fixture_matches_committed_output(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    catalog = resolve_catalog(paths)
    assert [p.id for p in catalog["games-workshop"]] == [
        "games-workshop/99120110052",
        "games-workshop/boarding-patrol-death-guard",
    ]

    generated = _generated_files(paths)

    if os.environ.get("REGEN_GOLDEN") == "1":
        for rel, src in generated.items():
            dst = FIXTURE_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        return

    for rel, src in generated.items():
        committed = FIXTURE_DIR / rel
        assert committed.exists(), (
            f"golden fixture {committed} is missing. Regenerate with:\n"
            "    REGEN_GOLDEN=1 uv run pytest -q tests/test_golden_fixture.py"
        )
        actual = src.read_text(encoding="utf-8")
        expected = committed.read_text(encoding="utf-8")
        assert actual == expected, (
            f"{rel} drifted from the committed golden fixture at {committed}.\n"
            "If this drift is an intentional, reviewed writer-format change, regenerate with:\n"
            "    REGEN_GOLDEN=1 uv run pytest -q tests/test_golden_fixture.py\n"
            "then review and commit the diff under "
            "tools/WarHub.Catalog.Publish.Tests/fixtures/canonical-golden/."
        )
