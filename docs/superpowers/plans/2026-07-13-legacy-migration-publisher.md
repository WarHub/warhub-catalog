# Legacy Migration + Publisher Adaptation Implementation Plan (Plan 2 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the legacy product catalog (12,799 products in `data/products/manufacturers/**`) and curated seed data into the evidence store, resolve the initial canonical catalog under `data/catalog/products/`, prove parity, and switch the .NET publisher to read the new format — retiring the legacy product workflows.

**Architecture:** Per spec §8 (`docs/superpowers/specs/2026-07-12-data-acquisition-rewrite-design.md`). Migration is a pure, idempotent transform: legacy YAML → `legacy-catalog` + `seed-curated` evidence sources (+ taxonomy label files extracted from legacy headers) → `resolve` → canonical catalog. A verifier enforces parity invariants loudly. The publisher gains a canonical-format loader and cuts over atomically; the published JSON contract changes only additively (`eanConfidence`; `quantity` becomes real data). Paints are untouched.

**Tech Stack:** Python (existing `tools/acquisition/` package, Plan 1) for migration; C# (`tools/WarHub.Catalog.Publish`) for the publisher; existing schemas/tests conventions.

## Global Constraints

- Determinism invariant (Plan 1 carried forward): identical inputs → byte-identical outputs; no wall-clock in committed artifacts (migration observations use each record's `firstSeen` for both seen dates).
- Evidence is append-only in spirit; `firstSeen` from legacy records is preserved verbatim.
- All emitted text files: UTF-8, LF, trailing newline. EANs always quoted YAML strings.
- Migration must be idempotent: running `migrate` twice produces byte-identical files.
- Parity is loud: a violated invariant is a non-zero exit, never a warning.
- Published JSON contract: additive changes only (`eanConfidence` added; `quantity` sourced from data with fallback 1; `gameSystem`/`faction` keep publishing human LABELS, mapped from slugs via new taxonomy label files — never slugs).
- .NET: warnings-as-errors; `dotnet test WarHub.Catalog.slnx` green after every task. Python: `uv run pytest` green after every task (run from `tools/acquisition/`).
- `data/paints/**` and the paint publisher path are untouched by this plan.
- `uv` is winget-installed but absent from fresh shells' PATH: in PowerShell first run `$env:Path = [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path`.
- Commit messages end with the two trailer lines used in this repo (Co-Authored-By + Claude-Session).

**Deliberate deferral:** spec §8.2's port of `ManufacturerRegistry` faction lists / game-system maps into per-source hint mappings is NOT in this plan — legacy observations already carry resolved slugs as hints, so those mappings have no consumer until live scraping. Plan 3 ports them alongside the sources that need them. This plan seeds only the slug→label files the publisher needs.

## Legacy input shapes (ground truth, verified 2026-07-13)

Faction file (`data/products/manufacturers/<mfg>/<gs>/<faction>.yaml`) — header `manufacturer, manufacturerSlug, gameSystem, gameSystemSlug, faction, factionSlug` (all labels+slugs), then `products:` where each record uses exactly these keys (optional unless noted): `name*`, `category*`, `packaging*`, `status*`, `availability*`, `firstSeen*`, `sku*` (present on all 12,799), `ean`, `eanSource`, `productCode`, `priceGbp`, `priceUsd`, `priceEur`, `url*`, `imageUrl`, `description`.

Seed file (`data/products/seed/*.yaml`) — flat list; each record: `name*`, `sku`, `ean`, `productType`, `priceGbp/priceUsd/priceEur`, `url`, `imageUrl`, `manufacturer*` (LABEL, e.g. `Games Workshop`), `gameSystem*` (LABEL, e.g. `Warhammer 40,000`), `faction` (LABEL or null), `status`, `contents: [{unitName, quantity, baseSize}]`. Labels map to slugs ONLY via the legacy-header label→slug maps (e.g. `Warhammer 40,000` → `warhammer-40k`; slugify would wrongly give `warhammer-40-000`).

---

### Task 1: Taxonomy vendor-collision guard + Asmodee vendor fix

**Files:**
- Modify: `tools/acquisition/src/warhub_acquisition/taxonomy.py`
- Modify: `tools/acquisition/tests/test_taxonomy.py`
- Modify: `data/catalog/taxonomy/manufacturers.yaml`

**Interfaces:**
- Consumes: existing `Taxonomy.__init__`.
- Produces: `Taxonomy(...)` raises `ValueError` naming the vendor string and both manufacturer slugs when two manufacturers claim the same vendor name (casefolded). `Asmodee` no longer maps to `atomic-mass-games` (Asmodee distributes many brands, incl. CMON).

- [ ] **Step 1: Write the failing test**

Add to `tools/acquisition/tests/test_taxonomy.py`:

```python
def test_duplicate_vendor_name_raises(tmp_path: Path) -> None:
    import pytest

    write_yaml(
        tmp_path / "manufacturers.yaml",
        {
            "manufacturers": [
                {"slug": "a-corp", "name": "A Corp", "vendorNames": ["Shared Vendor"]},
                {"slug": "b-corp", "name": "B Corp", "vendorNames": ["shared vendor"]},
            ]
        },
    )
    with pytest.raises(ValueError, match="Shared Vendor|shared vendor"):
        Taxonomy.load(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `tools/acquisition/`): `uv run pytest tests/test_taxonomy.py -v`
Expected: `test_duplicate_vendor_name_raises` FAILS (no exception raised — last-wins today).

- [ ] **Step 3: Implement the guard**

In `taxonomy.py`, replace the `_vendor_index` dict comprehension in `Taxonomy.__init__` with an explicit loop:

```python
    def __init__(self, manufacturers: dict[str, Manufacturer]) -> None:
        self.manufacturers = manufacturers
        self._vendor_index: dict[str, str] = {}
        for manufacturer in manufacturers.values():
            for vendor in [manufacturer.name, *manufacturer.vendorNames]:
                folded = vendor.casefold()
                existing = self._vendor_index.get(folded)
                if existing is not None and existing != manufacturer.slug:
                    raise ValueError(
                        f"vendor name {vendor!r} claimed by both {existing!r} and {manufacturer.slug!r}"
                    )
                self._vendor_index[folded] = manufacturer.slug
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_taxonomy.py -v` — all PASS.

- [ ] **Step 5: Fix the Asmodee mapping**

In `data/catalog/taxonomy/manufacturers.yaml`, change the atomic-mass-games entry's vendor list from `vendorNames: [Atomic Mass Games, Asmodee]` to `vendorNames: [Atomic Mass Games]`. (AMG products on store.asmodee.com carry vendor "Atomic Mass Games" per the 2026-07-12 probe; "Asmodee" as a vendor string is ambiguous across brands.)

Run the full suite once: `uv run pytest -v` — all PASS (the repo data files are not loaded by unit tests, but Task 8's real run depends on this fix).

- [ ] **Step 6: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/taxonomy.py tools/acquisition/tests/test_taxonomy.py data/catalog/taxonomy/manufacturers.yaml
git commit -m "fix(acquisition): reject duplicate vendor names; drop ambiguous Asmodee mapping"
```

---

### Task 2: Add `sku` to the canonical product

**Files:**
- Modify: `tools/acquisition/src/warhub_acquisition/models/catalog.py`
- Modify: `tools/acquisition/src/warhub_acquisition/resolve/attributes.py`
- Modify: `tools/acquisition/tests/test_attributes.py`
- Modify: `tools/acquisition/tests/test_resolver.py` (golden gains a `sku` line)

**Interfaces:**
- Consumes: Plan 1's `CanonicalProduct`, `resolve_attributes` `_DIRECT_FIELDS`.
- Produces: `CanonicalProduct.sku: str | None` declared immediately after `productCode` (YAML emission order). `resolve_attributes` fills it first-non-None by kind priority from `Observation.sku` (raw, unnormalized — `productCode` remains the identity-grade normalized code). Publisher continuity depends on this: published `productCode` stays `productCode ?? sku`, so products whose sku fails the manufacturer's `codePattern` (common for Warlord) don't regress to null.

- [ ] **Step 1: Write the failing tests**

Add to `tools/acquisition/tests/test_attributes.py`:

```python
def test_sku_is_resolved_first_non_none() -> None:
    members = [
        obs("mfr-gw:necrons", sku=None),
        obs("ret-a:necrons", sku="GWS99120110077"),
    ]
    product = resolve_attributes("e", members, KINDS, NO_EAN, None)
    assert product.sku == "GWS99120110077"
```

In `tools/acquisition/tests/test_resolver.py`, update `EXPECTED_CATALOG`: insert the line `    sku: '99120110077'` immediately after the `productCode: '99120110077'` line (the mfr-gw observation's raw sku wins by kind priority).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_attributes.py tests/test_resolver.py -v`
Expected: `test_sku_is_resolved_first_non_none` fails with pydantic unknown-attribute/`AttributeError`; `test_golden_resolve` fails on the missing `sku` line.

- [ ] **Step 3: Implement**

In `models/catalog.py`, insert into `CanonicalProduct` after `productCode`:

```python
    sku: str | None = None
```

In `resolve/attributes.py`, add `"sku"` to `_DIRECT_FIELDS` (after `"name"`):

```python
_DIRECT_FIELDS = ("name", "sku", "availability", "url", "imageUrl", "priceGbp", "priceUsd", "priceEur")
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -v` — all PASS (84 + 1 new).

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/models/catalog.py tools/acquisition/src/warhub_acquisition/resolve/attributes.py tools/acquisition/tests/test_attributes.py tools/acquisition/tests/test_resolver.py
git commit -m "feat(acquisition): carry raw sku on canonical products"
```

---

### Task 3: Legacy faction-file reader

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/migrate/__init__.py`
- Create: `tools/acquisition/src/warhub_acquisition/migrate/legacy.py`
- Test: `tools/acquisition/tests/test_migrate_legacy.py`

**Interfaces:**
- Consumes: `yaml.safe_load`, `Observation`, `resolve.identity.slugify`.
- Produces:
  - `LegacyExtraction` (dataclass): `observations: list[Observation]` (sorted by key), `game_system_labels: dict[str, str]` (slug → label), `faction_labels: dict[str, str]` (slug → label), `label_to_game_system: dict[str, str]` (label → slug), `label_to_faction: dict[str, str]` (label → slug), `key_collisions: list[dict]`, `invalid_records: list[dict]`.
  - `read_legacy_products(manufacturers_dir: Path, extractor: str = "legacy-catalog@1") -> LegacyExtraction`.
  - Observation mapping per legacy record, given file header `(manufacturerSlug, gameSystemSlug/label, factionSlug/label)`:
    - `key = f"legacy-catalog:{manufacturerSlug}/{gameSystemSlug}/{factionSlug}/{slugify(name)}"`; if that key was already produced (slugify can collapse names the legacy normalizer kept distinct), append `-2`, `-3`, … in file order and record `{"type": "key-collision", "key": ..., "name": ...}` in `key_collisions`.
    - `manufacturer = manufacturerSlug`; `name`, `sku`, `ean` (as-is, unvalidated), `availability`, `url`, `imageUrl` copied; prices coerced with `float()` when present.
    - `firstSeen = lastSeen = record["firstSeen"]` (determinism: no wall clock).
    - `archived = False`; `extractor` as given.
    - `hints`: `gameSystem` = gameSystemSlug, `faction` = factionSlug, plus `category`, `packaging`, `status`, and — only when present — `description`, `eanSource`, `legacyProductCode` (from the record's `productCode`).
  - Raw file text is tab-normalized before parsing — the legacy emitter leaked literal tabs into 3 scraped names. Parsing uses a resolver-stripped loader so untagged int/float/timestamp scalars stay verbatim strings — the legacy emitter left sku values like 3991439_10187 unquoted, which YAML 1.1 would int-mangle.
  - Label maps are accumulated across headers; a label mapping to two different slugs raises `ValueError` naming the label and both slugs.
  - A record missing a required key (`name`, `firstSeen`, …) is recorded in `invalid_records` with file + index and skipped — the count feeds the verifier (expected: zero on real data). Bookkeeping (collision suffixes, seen keys) happens only after a record fully parses, so invalid records can never leave phantom collision entries.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_migrate_legacy.py
from pathlib import Path

from warhub_acquisition.migrate.legacy import read_legacy_products
from warhub_acquisition.yamlio import write_yaml


def make_faction_file(tmp_path: Path, faction_slug: str = "space-marines", products: list | None = None) -> Path:
    directory = tmp_path / "games-workshop" / "warhammer-40k"
    payload = {
        "manufacturer": "Games Workshop",
        "manufacturerSlug": "games-workshop",
        "gameSystem": "Warhammer 40,000",
        "gameSystemSlug": "warhammer-40k",
        "faction": "Space Marines",
        "factionSlug": faction_slug,
        "products": products
        if products is not None
        else [
            {
                "name": "Adrax Agatone",
                "category": "miniatures",
                "packaging": "single",
                "status": "current",
                "availability": "in_stock",
                "firstSeen": "2026-07-07",
                "ean": "5011921140862",
                "eanSource": "shopify:goblingaming.co.uk",
                "sku": "99120101293",
                "productCode": "prod4530362-99120101293",
                "priceGbp": 29,
                "url": "https://example/adrax",
                "imageUrl": "https://example/adrax.jpg",
                "description": "A hero.\nOf Nocturne.",
            }
        ],
    }
    write_yaml(directory / f"{faction_slug}.yaml", payload)
    return tmp_path


def test_maps_record_to_observation(tmp_path: Path) -> None:
    extraction = read_legacy_products(make_faction_file(tmp_path))
    [observation] = extraction.observations
    assert observation.key == "legacy-catalog:games-workshop/warhammer-40k/space-marines/adrax-agatone"
    assert observation.manufacturer == "games-workshop"
    assert observation.sku == "99120101293"
    assert observation.ean == "5011921140862"
    assert observation.priceGbp == 29.0
    assert observation.firstSeen == "2026-07-07"
    assert observation.lastSeen == "2026-07-07"
    assert observation.extractor == "legacy-catalog@1"
    assert observation.hints["gameSystem"] == "warhammer-40k"
    assert observation.hints["faction"] == "space-marines"
    assert observation.hints["status"] == "current"
    assert observation.hints["eanSource"] == "shopify:goblingaming.co.uk"
    assert observation.hints["legacyProductCode"] == "prod4530362-99120101293"
    assert observation.hints["description"] == "A hero.\nOf Nocturne."
    assert extraction.invalid_records == []


def test_label_maps_accumulate(tmp_path: Path) -> None:
    extraction = read_legacy_products(make_faction_file(tmp_path))
    assert extraction.game_system_labels == {"warhammer-40k": "Warhammer 40,000"}
    assert extraction.faction_labels == {"space-marines": "Space Marines"}
    assert extraction.label_to_game_system == {"Warhammer 40,000": "warhammer-40k"}
    assert extraction.label_to_faction == {"Space Marines": "space-marines"}


def test_key_collision_gets_deterministic_suffix(tmp_path: Path) -> None:
    base = {
        "category": "miniatures", "packaging": "single", "status": "current",
        "availability": "in_stock", "firstSeen": "2026-07-07", "sku": "1", "url": "https://x",
    }
    extraction = read_legacy_products(
        make_faction_file(
            tmp_path,
            products=[
                {**base, "name": "Foo!"},
                {**base, "name": "Foo?", "sku": "2"},
            ],
        )
    )
    keys = [o.key for o in extraction.observations]
    assert keys == [
        "legacy-catalog:games-workshop/warhammer-40k/space-marines/foo",
        "legacy-catalog:games-workshop/warhammer-40k/space-marines/foo-2",
    ]
    assert extraction.key_collisions == [
        {"type": "key-collision",
         "key": "legacy-catalog:games-workshop/warhammer-40k/space-marines/foo-2",
         "name": "Foo?"}
    ]


def test_invalid_record_is_reported_not_fatal(tmp_path: Path) -> None:
    extraction = read_legacy_products(
        make_faction_file(tmp_path, products=[{"category": "miniatures"}])  # no name
    )
    assert extraction.observations == []
    assert len(extraction.invalid_records) == 1


def test_colliding_invalid_record_leaves_no_phantom_collision(tmp_path: Path) -> None:
    base = {
        "category": "miniatures", "packaging": "single", "status": "current",
        "availability": "in_stock", "firstSeen": "2026-07-07", "sku": "1", "url": "https://x",
    }
    extraction = read_legacy_products(
        make_faction_file(
            tmp_path,
            products=[
                {**base, "name": "Foo!"},
                {"name": "Foo?"},  # collides AND is invalid (missing required fields)
            ],
        )
    )
    assert [o.key for o in extraction.observations] == [
        "legacy-catalog:games-workshop/warhammer-40k/space-marines/foo"
    ]
    assert extraction.key_collisions == []          # no phantom entry
    assert len(extraction.invalid_records) == 1


def test_non_numeric_price_is_invalid_not_fatal(tmp_path: Path) -> None:
    base = {
        "name": "Bar", "category": "miniatures", "packaging": "single", "status": "current",
        "availability": "in_stock", "firstSeen": "2026-07-07", "sku": "1", "url": "https://x",
        "priceGbp": "N/A",
    }
    extraction = read_legacy_products(make_faction_file(tmp_path, products=[base]))
    assert extraction.observations == []
    assert len(extraction.invalid_records) == 1


def test_bare_numeric_name_is_accepted_verbatim(tmp_path: Path) -> None:
    base = {
        "category": "miniatures", "packaging": "single", "status": "current",
        "availability": "in_stock", "firstSeen": "2026-07-07", "sku": "1", "url": "https://x",
    }
    extraction = read_legacy_products(make_faction_file(tmp_path, products=[{**base, "name": 40000}]))
    [observation] = extraction.observations
    assert observation.name == "40000"
    assert extraction.invalid_records == []


def test_non_scalar_name_is_invalid_not_fatal(tmp_path: Path) -> None:
    base = {
        "category": "miniatures", "packaging": "single", "status": "current",
        "availability": "in_stock", "firstSeen": "2026-07-07", "sku": "1", "url": "https://x",
    }
    extraction = read_legacy_products(
        make_faction_file(tmp_path, products=[{**base, "name": ["not", "a", "name"]}])
    )
    assert extraction.observations == []
    assert len(extraction.invalid_records) == 1


def test_underscore_sku_preserved_verbatim(tmp_path: Path) -> None:
    base = {
        "category": "miniatures", "packaging": "single", "status": "current",
        "availability": "in_stock", "firstSeen": "2026-07-07", "url": "https://x",
    }
    directory = tmp_path / "wyrd-games" / "malifaux"
    directory.mkdir(parents=True)
    (directory / "general.yaml").write_text(
        "manufacturer: Wyrd Games\nmanufacturerSlug: wyrd-games\n"
        "gameSystem: Malifaux\ngameSystemSlug: malifaux\n"
        "faction: General\nfactionSlug: general\n"
        "products:\n"
        "  - name: Some Box\n"
        "    category: miniatures\n    packaging: single\n    status: current\n"
        "    availability: in_stock\n    firstSeen: '2026-07-07'\n"
        "    sku: 3991439_10187\n"
        "    priceUsd: 45\n"
        "    url: https://x\n",
        encoding="utf-8", newline="\n",
    )
    extraction = read_legacy_products(tmp_path)
    [observation] = extraction.observations
    assert observation.sku == "3991439_10187"   # verbatim, not int-mangled
    assert observation.priceUsd == 45.0          # prices still coerce


def test_unquoted_numeric_price_still_floats(tmp_path: Path) -> None:
    extraction = read_legacy_products(make_faction_file(tmp_path))
    [observation] = extraction.observations
    assert observation.priceGbp == 29.0


def test_conflicting_label_raises(tmp_path: Path) -> None:
    import pytest

    make_faction_file(tmp_path)
    directory = tmp_path / "games-workshop" / "warhammer-40k"
    write_yaml(
        directory / "other.yaml",
        {
            "manufacturer": "Games Workshop", "manufacturerSlug": "games-workshop",
            "gameSystem": "Warhammer 40k RENAMED", "gameSystemSlug": "warhammer-40k",
            "faction": "Other", "factionSlug": "other", "products": [],
        },
    )
    with pytest.raises(ValueError, match="warhammer-40k"):
        read_legacy_products(tmp_path)


def test_tab_in_scalar_is_tolerated(tmp_path: Path) -> None:
    directory = tmp_path / "mantic-games" / "deadzone"
    directory.mkdir(parents=True)
    (directory / "general.yaml").write_text(
        "manufacturer: Mantic Games\n"
        "manufacturerSlug: mantic-games\n"
        "gameSystem: Deadzone\n"
        "gameSystemSlug: deadzone\n"
        "faction: General\n"
        "factionSlug: general\n"
        "products:\n"
        "  - name: Enforcer Pathfinder\tMono Cycle\n"
        "    category: miniatures\n"
        "    packaging: single\n"
        "    status: current\n"
        "    availability: in_stock\n"
        "    firstSeen: '2026-07-07'\n"
        "    sku: MGDZM103\n"
        "    url: https://example/pathfinder\n",
        encoding="utf-8", newline="\n",
    )
    extraction = read_legacy_products(tmp_path)
    [observation] = extraction.observations
    assert observation.name == "Enforcer Pathfinder Mono Cycle"
    assert extraction.invalid_records == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_migrate_legacy.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# tools/acquisition/src/warhub_acquisition/migrate/__init__.py
```

```python
# tools/acquisition/src/warhub_acquisition/migrate/legacy.py
"""Read the legacy faction-file tree into legacy-catalog observations."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.identity import slugify

_HINT_KEYS = ("category", "packaging", "status")
_OPTIONAL_HINT_KEYS = ("description", "eanSource")


class _LegacyLoader(yaml.SafeLoader):
    """YAML 1.1 implicit typing mangles legacy scalars (e.g. unquoted sku
    3991439_10187 -> int via digit-separator underscores); parse untagged
    int/float/timestamp scalars as verbatim strings instead. Prices are
    float-coerced explicitly by the record mapping."""


_STRIPPED_TAGS = frozenset({
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:timestamp",
})

_LegacyLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag not in _STRIPPED_TAGS]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass
class LegacyExtraction:
    observations: list[Observation] = field(default_factory=list)
    game_system_labels: dict[str, str] = field(default_factory=dict)
    faction_labels: dict[str, str] = field(default_factory=dict)
    label_to_game_system: dict[str, str] = field(default_factory=dict)
    label_to_faction: dict[str, str] = field(default_factory=dict)
    key_collisions: list[dict] = field(default_factory=list)
    invalid_records: list[dict] = field(default_factory=list)


def _register_label(mapping: dict[str, str], reverse: dict[str, str], slug: str, label: str) -> None:
    existing = mapping.get(slug)
    if existing is not None and existing != label:
        raise ValueError(f"slug {slug!r} has conflicting labels {existing!r} and {label!r}")
    mapping[slug] = label
    existing_slug = reverse.get(label)
    if existing_slug is not None and existing_slug != slug:
        raise ValueError(f"label {label!r} maps to both {existing_slug!r} and {slug!r}")
    reverse[label] = slug


def read_legacy_products(manufacturers_dir: Path, extractor: str = "legacy-catalog@1") -> LegacyExtraction:
    extraction = LegacyExtraction()
    seen_keys: set[str] = set()
    for path in sorted(manufacturers_dir.glob("*/*/*.yaml")):
        # the legacy .NET pipeline emitted literal tabs inside a handful of
        # scraped name scalars (PyYAML rejects them) and unquoted skus like
        # 3991439_10187 that YAML 1.1's int resolver would int-mangle; tabs
        # are normalized to spaces and _LegacyLoader keeps untagged
        # int/float/timestamp scalars as verbatim strings (migration-reader-
        # only leniency)
        data = yaml.load(path.read_text(encoding="utf-8").replace("\t", " "), Loader=_LegacyLoader)
        _register_label(
            extraction.game_system_labels, extraction.label_to_game_system,
            data["gameSystemSlug"], data["gameSystem"],
        )
        _register_label(
            extraction.faction_labels, extraction.label_to_faction,
            data["factionSlug"], data["faction"],
        )
        prefix = f"legacy-catalog:{data['manufacturerSlug']}/{data['gameSystemSlug']}/{data['factionSlug']}"
        for index, record in enumerate(data.get("products") or []):
            try:
                # Read all fallible fields and build candidate dict
                name = record["name"]
                slug = slugify(name)
                hints: dict[str, object] = {
                    "gameSystem": data["gameSystemSlug"],
                    "faction": data["factionSlug"],
                }
                for hint in _HINT_KEYS:
                    hints[hint] = record[hint]
                for hint in _OPTIONAL_HINT_KEYS:
                    if record.get(hint) is not None:
                        hints[hint] = record[hint]
                if record.get("productCode") is not None:
                    hints["legacyProductCode"] = record["productCode"]
                # All float conversions (may raise ValueError)
                priceGbp = float(record["priceGbp"]) if record.get("priceGbp") is not None else None
                priceUsd = float(record["priceUsd"]) if record.get("priceUsd") is not None else None
                priceEur = float(record["priceEur"]) if record.get("priceEur") is not None else None
                # Build candidate dict with sentinel key (will be replaced)
                candidate = {
                    "url": record["url"],
                    "manufacturer": data["manufacturerSlug"],
                    "name": name,
                    "sku": record.get("sku"),
                    "ean": record.get("ean"),
                    "priceGbp": priceGbp,
                    "priceUsd": priceUsd,
                    "priceEur": priceEur,
                    "availability": record["availability"],
                    "imageUrl": record.get("imageUrl"),
                    "hints": hints,
                    "firstSeen": record["firstSeen"],
                    "lastSeen": record["firstSeen"],
                    "extractor": extractor,
                }
            except (KeyError, TypeError, ValueError) as error:
                extraction.invalid_records.append(
                    {"file": str(path), "index": index, "error": repr(error)}
                )
                continue
            # Bookkeeping only after successful record parsing
            base_key = f"{prefix}/{slug}"
            key = base_key
            suffix = 2
            while key in seen_keys:
                key = f"{base_key}-{suffix}"
                suffix += 1
            if key != base_key:
                extraction.key_collisions.append(
                    {"type": "key-collision", "key": key, "name": name}
                )
            seen_keys.add(key)
            observation = Observation(key=key, **candidate)
            extraction.observations.append(observation)
    extraction.observations.sort(key=lambda o: o.key)
    return extraction
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_migrate_legacy.py -v` — all PASS. Then `uv run pytest -v` — full suite green.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/migrate tools/acquisition/tests/test_migrate_legacy.py
git commit -m "feat(acquisition): legacy faction-file reader for migration"
```

---

### Task 4: Seed-file reader

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/migrate/seed.py`
- Test: `tools/acquisition/tests/test_migrate_seed.py`

**Interfaces:**
- Consumes: `yamlio.read_yaml`, `Observation`, `slugify`, `Taxonomy.manufacturer_for_vendor`, and Task 3's `label_to_game_system` / `label_to_faction` maps.
- Produces: `read_seed_products(seed_dir: Path, taxonomy: Taxonomy, label_to_game_system: dict[str, str], label_to_faction: dict[str, str], faction_labels: dict[str, str], extractor: str = "seed-curated@1") -> tuple[list[Observation], dict[str, str]]` (observations sorted by key, plus minted faction slug→label pairs).
  - `key = f"seed-curated:{manufacturer_slug}/{slugify(name)}"`; duplicate key across seed files → `ValueError` (seed is hand-curated; a dup is an authoring error, loud).
  - `manufacturer` label → slug via `taxonomy.manufacturer_for_vendor`; unmapped → `ValueError` naming the label.
  - `gameSystem` label → slug via `label_to_game_system`; unmapped → `ValueError`. `faction` label → slug via `label_to_faction` when non-null; null → no faction hint.
  - Unmapped non-null `faction` label: seed data is curated and may be MORE precise than the legacy scrape's taxonomy (legacy AoS only had Grand Alliance-level factions), so an unmapped faction label MINTS a new faction rather than erroring: `slug = slugify(faction_label)`; if `slug` already exists in `faction_labels` under a DIFFERENT label → `ValueError` (ambiguous, human call); otherwise the mint is recorded in the returned `minted` dict (`minted[slug] = faction_label`) and `slug` is used as the hint. `gameSystem` and `manufacturer` remain strict errors — only `faction` mints.
  - `hints`: `gameSystem`, `faction` (if any), `status` (when present), `productType` (when present), `contents` (verbatim list, when present), `quantity` = sum of `contents[].quantity` (when contents present).
  - `firstSeen = lastSeen = "2026-07-12"` (fixed epoch for seed data: the plan-1 merge date; constant `SEED_FIRST_SEEN` — no wall clock).
  - `sku`, `ean`, prices (float-coerced), `url`, `imageUrl` copied when present.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_migrate_seed.py
from pathlib import Path

import pytest

from warhub_acquisition.migrate.seed import SEED_FIRST_SEEN, read_seed_products
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy
from warhub_acquisition.yamlio import write_yaml

TAXONOMY = Taxonomy(
    {"games-workshop": Manufacturer(slug="games-workshop", name="Games Workshop", vendorNames=["Citadel"])}
)
GS = {"Warhammer 40,000": "warhammer-40k"}
FACTIONS = {"Space Marines": "space-marines"}
FACTION_LABELS = {"space-marines": "Space Marines"}


def make_seed(tmp_path: Path, records: list) -> Path:
    write_yaml(tmp_path / "gw.yaml", records)
    return tmp_path


def seed_record(**kw: object) -> dict:
    base: dict[str, object] = {
        "name": "Intercessors", "sku": "99120101190", "ean": "5011921142439",
        "productType": "single_kit", "priceGbp": 36, "priceUsd": 46,
        "url": "https://example/intercessors",
        "manufacturer": "Games Workshop", "gameSystem": "Warhammer 40,000",
        "faction": "Space Marines", "status": "current",
        "contents": [{"unitName": "Intercessors", "quantity": 10, "baseSize": "32mm"}],
    }
    base.update(kw)
    return base


def test_maps_seed_record(tmp_path: Path) -> None:
    observations, minted = read_seed_products(
        make_seed(tmp_path, [seed_record()]), TAXONOMY, GS, FACTIONS, FACTION_LABELS
    )
    [observation] = observations
    assert minted == {}
    assert observation.key == "seed-curated:games-workshop/intercessors"
    assert observation.manufacturer == "games-workshop"
    assert observation.ean == "5011921142439"
    assert observation.priceUsd == 46.0
    assert observation.firstSeen == SEED_FIRST_SEEN
    assert observation.hints["gameSystem"] == "warhammer-40k"
    assert observation.hints["faction"] == "space-marines"
    assert observation.hints["quantity"] == 10
    assert observation.hints["productType"] == "single_kit"
    assert observation.hints["contents"] == [{"unitName": "Intercessors", "quantity": 10, "baseSize": "32mm"}]


def test_null_faction_omits_hint(tmp_path: Path) -> None:
    observations, _minted = read_seed_products(
        make_seed(tmp_path, [seed_record(name="Ultimate Starter Set", faction=None, contents=None)]),
        TAXONOMY, GS, FACTIONS, FACTION_LABELS,
    )
    [observation] = observations
    assert "faction" not in observation.hints
    assert "quantity" not in observation.hints


def test_unmapped_game_system_label_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Age of Sigmar"):
        read_seed_products(
            make_seed(tmp_path, [seed_record(gameSystem="Age of Sigmar")]), TAXONOMY, GS, FACTIONS, FACTION_LABELS
        )


def test_duplicate_seed_key_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="intercessors"):
        read_seed_products(
            make_seed(tmp_path, [seed_record(), seed_record()]), TAXONOMY, GS, FACTIONS, FACTION_LABELS
        )


def test_unmapped_faction_label_mints_new_slug(tmp_path: Path) -> None:
    observations, minted = read_seed_products(
        make_seed(tmp_path, [seed_record(faction="Stormcast Eternals")]),
        TAXONOMY, GS, FACTIONS, FACTION_LABELS,
    )
    assert observations[0].hints["faction"] == "stormcast-eternals"
    assert minted == {"stormcast-eternals": "Stormcast Eternals"}


def test_minted_slug_colliding_with_different_label_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="stormcast-eternals"):
        read_seed_products(
            make_seed(tmp_path, [seed_record(faction="Stormcast  Eternals")]),  # slugifies same, label text differs
            TAXONOMY, GS, FACTIONS, {"stormcast-eternals": "Stormcast Eternals"},
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_migrate_seed.py -v` — FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# tools/acquisition/src/warhub_acquisition/migrate/seed.py
"""Read curated seed files into seed-curated observations."""
from pathlib import Path

from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.identity import slugify
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import read_yaml

SEED_FIRST_SEEN = "2026-07-12"


def read_seed_products(
    seed_dir: Path,
    taxonomy: Taxonomy,
    label_to_game_system: dict[str, str],
    label_to_faction: dict[str, str],
    faction_labels: dict[str, str],
    extractor: str = "seed-curated@1",
) -> tuple[list[Observation], dict[str, str]]:
    observations: dict[str, Observation] = {}
    minted: dict[str, str] = {}
    for path in sorted(seed_dir.glob("*.yaml")):
        for record in read_yaml(path) or []:
            manufacturer = taxonomy.manufacturer_for_vendor(record["manufacturer"])
            if manufacturer is None:
                raise ValueError(f"seed manufacturer label not in taxonomy: {record['manufacturer']!r} ({path})")
            game_system = label_to_game_system.get(record["gameSystem"])
            if game_system is None:
                raise ValueError(f"seed gameSystem label not in legacy headers: {record['gameSystem']!r} ({path})")
            hints: dict[str, object] = {"gameSystem": game_system}
            faction_label = record.get("faction")
            if faction_label is not None:
                faction = label_to_faction.get(faction_label)
                if faction is None:
                    # seed data is curated and may be MORE precise than the legacy
                    # scrape's taxonomy (e.g. Stormcast Eternals vs Grand Alliance
                    # Order); mint a new faction slug rather than erroring.
                    slug = slugify(faction_label)
                    existing_label = faction_labels.get(slug)
                    if existing_label is not None and existing_label != faction_label:
                        raise ValueError(
                            f"minted faction slug {slug!r} for label {faction_label!r} collides with "
                            f"existing label {existing_label!r} ({path})"
                        )
                    minted[slug] = faction_label
                    faction = slug
                hints["faction"] = faction
            for hint in ("status", "productType"):
                if record.get(hint) is not None:
                    hints[hint] = record[hint]
            contents = record.get("contents")
            if contents:
                hints["contents"] = contents
                hints["quantity"] = sum(int(unit["quantity"]) for unit in contents)
            key = f"seed-curated:{manufacturer}/{slugify(record['name'])}"
            if key in observations:
                raise ValueError(f"duplicate seed product key: {key}")
            observations[key] = Observation(
                key=key,
                url=record.get("url"),
                manufacturer=manufacturer,
                name=record["name"],
                sku=record.get("sku"),
                ean=record.get("ean"),
                priceGbp=float(record["priceGbp"]) if record.get("priceGbp") is not None else None,
                priceUsd=float(record["priceUsd"]) if record.get("priceUsd") is not None else None,
                priceEur=float(record["priceEur"]) if record.get("priceEur") is not None else None,
                imageUrl=record.get("imageUrl"),
                hints=hints,
                firstSeen=SEED_FIRST_SEEN,
                lastSeen=SEED_FIRST_SEEN,
                extractor=extractor,
            )
    return [observations[key] for key in sorted(observations)], minted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_migrate_seed.py -v` — all PASS; then full suite.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/migrate/seed.py tools/acquisition/tests/test_migrate_seed.py
git commit -m "feat(acquisition): seed-file reader for migration"
```

---

### Task 5: Taxonomy label files (writer + loader)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/migrate/labels.py`
- Modify: `tools/acquisition/src/warhub_acquisition/taxonomy.py` (loader)
- Test: `tools/acquisition/tests/test_labels.py`

**Interfaces:**
- Consumes: `yamlio.write_yaml/read_yaml`.
- Produces:
  - `write_label_files(taxonomy_dir: Path, game_system_labels: dict[str, str], faction_labels: dict[str, str]) -> None` — writes `game-systems.yaml` as `{gameSystems: [{slug, label}...]}` and `factions.yaml` as `{factions: [{slug, label}...]}`, sorted by slug. These are the publisher's slug→label source (published JSON keeps human labels).
  - In `taxonomy.py`: `load_labels(taxonomy_dir: Path) -> tuple[dict[str, str], dict[str, str]]` returning (gameSystems, factions) slug→label maps; missing files → empty dicts.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_labels.py
from pathlib import Path

from warhub_acquisition.migrate.labels import write_label_files
from warhub_acquisition.taxonomy import load_labels


def test_round_trip_sorted(tmp_path: Path) -> None:
    write_label_files(tmp_path, {"z-sys": "Z", "a-sys": "A"}, {"orks": "Orks"})
    text = (tmp_path / "game-systems.yaml").read_text(encoding="utf-8")
    assert text.index("a-sys") < text.index("z-sys")
    game_systems, factions = load_labels(tmp_path)
    assert game_systems == {"a-sys": "A", "z-sys": "Z"}
    assert factions == {"orks": "Orks"}


def test_missing_files_empty(tmp_path: Path) -> None:
    assert load_labels(tmp_path) == ({}, {})
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_labels.py -v` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# tools/acquisition/src/warhub_acquisition/migrate/labels.py
"""Write slug->label taxonomy files consumed by the publisher."""
from pathlib import Path

from warhub_acquisition.yamlio import write_yaml


def write_label_files(
    taxonomy_dir: Path,
    game_system_labels: dict[str, str],
    faction_labels: dict[str, str],
) -> None:
    write_yaml(
        taxonomy_dir / "game-systems.yaml",
        {"gameSystems": [{"slug": slug, "label": game_system_labels[slug]} for slug in sorted(game_system_labels)]},
    )
    write_yaml(
        taxonomy_dir / "factions.yaml",
        {"factions": [{"slug": slug, "label": faction_labels[slug]} for slug in sorted(faction_labels)]},
    )
```

Append to `taxonomy.py`:

```python
def load_labels(taxonomy_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    def read_map(path: Path, key: str) -> dict[str, str]:
        if not path.exists():
            return {}
        data = read_yaml(path)
        return {entry["slug"]: entry["label"] for entry in data[key]}

    return (
        read_map(taxonomy_dir / "game-systems.yaml", "gameSystems"),
        read_map(taxonomy_dir / "factions.yaml", "factions"),
    )
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_labels.py -v` then full suite; all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/migrate/labels.py tools/acquisition/src/warhub_acquisition/taxonomy.py tools/acquisition/tests/test_labels.py
git commit -m "feat(acquisition): taxonomy label files for publisher slug->label mapping"
```

---

### Task 6: `migrate` CLI verb (orchestration, idempotent)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/migrate/runner.py`
- Modify: `tools/acquisition/src/warhub_acquisition/cli.py`
- Test: `tools/acquisition/tests/test_migrate_runner.py`

**Interfaces:**
- Consumes: Tasks 3–5, `EvidenceStore`, `Taxonomy.load`, `DataPaths`.
- Produces:
  - `run_migration(paths: DataPaths, legacy_dir: Path, seed_dir: Path) -> MigrationSummary` — dataclass with `legacy_count: int`, `seed_count: int`, `key_collisions: list[dict]`, `invalid_records: list[dict]`, `minted_factions: dict[str, str]`. Orchestrates: `Taxonomy.load(paths.taxonomy)` → `read_legacy_products(legacy_dir)` → `read_seed_products(seed_dir, ..., extraction.faction_labels)` → upsert+save both sources into `EvidenceStore(paths.evidence_products)` → merge minted faction labels into `extraction.faction_labels` (`all_faction_labels = {**extraction.faction_labels, **minted}`) → `write_label_files(paths.taxonomy, extraction.game_system_labels, all_faction_labels)`.
  - CLI: `warhub-data migrate --data <dir> --legacy-dir <dir> --seed-dir <dir>` (defaults `data`, `data/products/manufacturers`, `data/products/seed`) — prints `migrated N legacy + M seed observations; K key collisions; J invalid records`, exit 0 (invalid records are surfaced by Task 7's verifier, not here).
  - Idempotence: running twice yields byte-identical `observations.jsonl` and taxonomy label files (test pins it). Upsert semantics make this hold because `firstSeen == lastSeen` never moves.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_migrate_runner.py
from pathlib import Path

from test_migrate_legacy import make_faction_file
from warhub_acquisition.cli import main
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import write_yaml


def seed_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    data = tmp_path / "data"
    write_yaml(
        data / "catalog" / "taxonomy" / "manufacturers.yaml",
        {"manufacturers": [{"slug": "games-workshop", "name": "Games Workshop",
                            "codePattern": r"\d{11}", "gs1Prefixes": ["5011921"]}]},
    )
    write_yaml(data / "catalog" / "sources" / "legacy-catalog.yaml",
               {"id": "legacy-catalog", "kind": "curated", "strategy": "none"})
    write_yaml(data / "catalog" / "sources" / "seed-curated.yaml",
               {"id": "seed-curated", "kind": "curated", "strategy": "none"})
    legacy = tmp_path / "legacy"
    make_faction_file(legacy)
    seed_dir = tmp_path / "seed"
    write_yaml(
        seed_dir / "gw.yaml",
        [{"name": "Adrax Agatone", "sku": "99120101293", "manufacturer": "Games Workshop",
          "gameSystem": "Warhammer 40,000", "faction": "Space Marines", "status": "current",
          "contents": [{"unitName": "Adrax", "quantity": 1, "baseSize": "40mm"}]}],
    )
    return data, legacy, seed_dir


def run_migrate(data: Path, legacy: Path, seed_dir: Path) -> int:
    return main(["migrate", "--data", str(data), "--legacy-dir", str(legacy), "--seed-dir", str(seed_dir)])


def test_migrate_writes_evidence_and_labels(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    assert run_migrate(data, legacy, seed_dir) == 0
    out = capsys.readouterr().out
    assert "migrated 1 legacy + 1 seed observations" in out
    paths = DataPaths(data)
    assert (paths.evidence_products / "legacy-catalog" / "observations.jsonl").exists()
    assert (paths.evidence_products / "seed-curated" / "observations.jsonl").exists()
    assert (paths.taxonomy / "game-systems.yaml").exists()
    assert (paths.taxonomy / "factions.yaml").exists()


def test_migrate_is_idempotent(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    run_migrate(data, legacy, seed_dir)
    paths = DataPaths(data)
    files = [
        paths.evidence_products / "legacy-catalog" / "observations.jsonl",
        paths.evidence_products / "seed-curated" / "observations.jsonl",
        paths.taxonomy / "game-systems.yaml",
        paths.taxonomy / "factions.yaml",
    ]
    before = [f.read_bytes() for f in files]
    run_migrate(data, legacy, seed_dir)
    assert [f.read_bytes() for f in files] == before


def test_seed_faction_absent_from_legacy_mints_slug(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    write_yaml(
        seed_dir / "gw-age-of-sigmar.yaml",
        [{"name": "Lord-Celestant", "sku": "99120101999", "manufacturer": "Games Workshop",
          "gameSystem": "Warhammer 40,000", "faction": "Stormcast Eternals", "status": "current",
          "contents": [{"unitName": "Lord-Celestant", "quantity": 1, "baseSize": "40mm"}]}],
    )
    assert run_migrate(data, legacy, seed_dir) == 0
    paths = DataPaths(data)
    factions = (paths.taxonomy / "factions.yaml").read_text(encoding="utf-8")
    assert "space-marines" in factions
    assert "stormcast-eternals" in factions
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_migrate_runner.py -v` → argparse error (unknown command `migrate`).

- [ ] **Step 3: Implement**

```python
# tools/acquisition/src/warhub_acquisition/migrate/runner.py
"""Orchestrate the one-time legacy migration into the evidence store."""
from dataclasses import dataclass, field
from pathlib import Path

from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.migrate.labels import write_label_files
from warhub_acquisition.migrate.legacy import read_legacy_products
from warhub_acquisition.migrate.seed import read_seed_products
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.taxonomy import Taxonomy


@dataclass
class MigrationSummary:
    legacy_count: int = 0
    seed_count: int = 0
    key_collisions: list[dict] = field(default_factory=list)
    invalid_records: list[dict] = field(default_factory=list)
    minted_factions: dict[str, str] = field(default_factory=dict)


def run_migration(paths: DataPaths, legacy_dir: Path, seed_dir: Path) -> MigrationSummary:
    taxonomy = Taxonomy.load(paths.taxonomy)
    extraction = read_legacy_products(legacy_dir)
    seed_observations, minted = read_seed_products(
        seed_dir, taxonomy, extraction.label_to_game_system, extraction.label_to_faction, extraction.faction_labels
    )
    store = EvidenceStore(paths.evidence_products)
    for observation in extraction.observations:
        store.upsert("legacy-catalog", observation)
    for observation in seed_observations:
        store.upsert("seed-curated", observation)
    store.save("legacy-catalog")
    store.save("seed-curated")
    all_faction_labels = {**extraction.faction_labels, **minted}
    write_label_files(paths.taxonomy, extraction.game_system_labels, all_faction_labels)
    return MigrationSummary(
        legacy_count=len(extraction.observations),
        seed_count=len(seed_observations),
        key_collisions=extraction.key_collisions,
        invalid_records=extraction.invalid_records,
        minted_factions=minted,
    )
```

In `cli.py`, add the subcommand (same parser loop style; `migrate` gets extra options) and the branch:

```python
    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("--data", type=Path, default=Path("data"))
    migrate.add_argument("--legacy-dir", type=Path, default=Path("data/products/manufacturers"))
    migrate.add_argument("--seed-dir", type=Path, default=Path("data/products/seed"))
```

```python
    if args.command == "migrate":
        from warhub_acquisition.migrate.runner import run_migration

        summary = run_migration(paths, args.legacy_dir, args.seed_dir)
        print(
            f"migrated {summary.legacy_count} legacy + {summary.seed_count} seed observations; "
            f"{len(summary.key_collisions)} key collisions; {len(summary.invalid_records)} invalid records"
        )
        return 0
```

Note: the existing `--data` is-dir guard applies to `migrate` too (the data dir must contain `catalog/taxonomy/manufacturers.yaml`); keep the guard shared.

- [ ] **Step 4: Run tests** — targeted then full suite; all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/migrate/runner.py tools/acquisition/src/warhub_acquisition/cli.py tools/acquisition/tests/test_migrate_runner.py
git commit -m "feat(acquisition): migrate CLI verb orchestrating the legacy import"
```

---

### Task 7: Migration verifier (parity invariants, loud)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/migrate/verify.py`
- Modify: `tools/acquisition/src/warhub_acquisition/cli.py` (extend `migrate` with verification + report)
- Test: `tools/acquisition/tests/test_migrate_verify.py`

**Interfaces:**
- Consumes: `resolve_catalog`, `EvidenceStore`, `canonical_ean`, `read_yaml`, `MigrationSummary`.
- Produces:
  - `verify_migration(paths: DataPaths, summary: MigrationSummary) -> tuple[list[str], str]` — returns (violations, markdown_report). Runs `resolve_catalog(paths)` itself, then checks:
    1. **No lost identities:** every observation key in the evidence store appears in exactly one canonical product's `evidence` list.
    2. **No lost EANs:** every distinct *valid* EAN (via `canonical_ean`) asserted in evidence appears either on some canonical product or inside a conflict payload in `review/conflicts.yaml`.
    3. **Counts:** evidence observation total == `summary.legacy_count + summary.seed_count`.
    4. **Invalid records:** `summary.invalid_records` must be empty.
  - The markdown report contains: totals, per-manufacturer table (records → entities dedup, with EAN, confirmed), distinct-valid-EAN count, invalid-EAN-value count (asserted but failing checksum — reported, not a violation), key collisions, minted factions count, conflicts count.
  - CLI: `migrate` gains `--report <path>` (default `<data>/review/migration-report.md`); after migration it runs verification, writes the report, prints `verification: OK` or the violations, and exits **3** on any violation.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_migrate_verify.py
from pathlib import Path

from test_migrate_runner import seed_repo
from warhub_acquisition.cli import main


def test_migrate_verifies_and_writes_report(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    exit_code = main(["migrate", "--data", str(data), "--legacy-dir", str(legacy), "--seed-dir", str(seed_dir)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "verification: OK" in out
    report = (data / "review" / "migration-report.md").read_text(encoding="utf-8")
    assert "games-workshop" in report
    assert "| manufacturer |" in report
    assert "- minted factions: 0" in report
    # the legacy Adrax and the seed Adrax share sku 99120101293 -> one entity
    catalog = (data / "catalog" / "products" / "games-workshop.yaml").read_text(encoding="utf-8")
    assert catalog.count("- id:") == 1
    assert "quantity: 1" in catalog          # from seed contents
    assert "ean: '5011921140862'" in catalog
    assert "eanConfidence: confirmed" in catalog  # curated-kind assertion


def test_report_table_includes_record_counts(tmp_path: Path, capsys) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    main(["migrate", "--data", str(data), "--legacy-dir", str(legacy), "--seed-dir", str(seed_dir)])
    report = (data / "review" / "migration-report.md").read_text(encoding="utf-8")
    assert "| manufacturer | records | entities | with EAN | confirmed |" in report
    assert "| games-workshop | 2 | 1 | 1 | 1 |" in report  # 1 legacy + 1 seed obs -> 1 entity


def test_violation_exits_3(tmp_path: Path, capsys, monkeypatch) -> None:
    data, legacy, seed_dir = seed_repo(tmp_path)
    import warhub_acquisition.migrate.verify as verify_module

    real = verify_module.verify_migration

    def broken(paths, summary):  # force a violation to pin the exit path
        violations, report = real(paths, summary)
        return (["forced violation"], report)

    monkeypatch.setattr("warhub_acquisition.cli.verify_migration", broken, raising=False)
    monkeypatch.setattr(verify_module, "verify_migration", broken)
    exit_code = main(["migrate", "--data", str(data), "--legacy-dir", str(legacy), "--seed-dir", str(seed_dir)])
    assert exit_code == 3
    assert "forced violation" in capsys.readouterr().out
```

(If the monkeypatch seam proves brittle because `cli.py` imports the function locally, restructure the CLI to import `verify_migration` at module top so the patch has a stable target — note it in the report.)

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError` / missing report.

- [ ] **Step 3: Implement**

```python
# tools/acquisition/src/warhub_acquisition/migrate/verify.py
"""Parity invariants for the legacy migration; violations are loud."""
from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.migrate.runner import MigrationSummary
from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import read_yaml


def verify_migration(paths: DataPaths, summary: MigrationSummary) -> tuple[list[str], str]:
    catalog = resolve_catalog(paths)
    violations: list[str] = []

    evidence = EvidenceStore(paths.evidence_products).load_all()
    all_keys = {key for source in evidence.values() for key in source}
    covered: dict[str, int] = {}
    products = [p for records in catalog.values() for p in records]
    for product in products:
        for key in product.evidence:
            covered[key] = covered.get(key, 0) + 1
    # NOTE: retracted entities (overrides.yaml retract:) are suppressed by the
    # resolver, so their evidence keys will appear here as 'missing'. Retract is
    # unused during migration; if it gains real use, exempt retracted entities'
    # keys from this invariant.
    missing = sorted(all_keys - set(covered))
    if missing:
        violations.append(f"{len(missing)} observation keys not covered by any entity (first: {missing[:5]})")
    doubled = sorted(key for key, count in covered.items() if count > 1)
    if doubled:
        violations.append(f"{len(doubled)} observation keys covered by more than one entity (first: {doubled[:5]})")

    asserted = {
        ean for source in evidence.values() for obs in source.values()
        if (ean := canonical_ean(obs.ean)) is not None
    }
    catalog_eans = {p.ean for p in products if p.ean}
    conflicts = read_yaml(paths.conflicts)["conflicts"] if paths.conflicts.exists() else []
    conflict_eans = {
        value for c in conflicts
        for value in (
            [c.get("ean")] + [a.get("ean") for a in c.get("assertions", [])]
        )
        if value
    }
    lost = sorted(asserted - catalog_eans - conflict_eans)
    if lost:
        violations.append(f"{len(lost)} valid EANs lost (first: {lost[:5]})")

    total = sum(len(source) for source in evidence.values())
    expected = summary.legacy_count + summary.seed_count
    if total != expected:
        violations.append(f"evidence count {total} != migrated count {expected}")
    if summary.invalid_records:
        violations.append(f"{len(summary.invalid_records)} invalid legacy records skipped")

    invalid_ean_count = sum(
        1 for source in evidence.values() for obs in source.values()
        if obs.ean and canonical_ean(obs.ean) is None
    )

    # Count observations (records) by manufacturer
    records_by_manufacturer: dict[str, int] = {}
    for source in evidence.values():
        for obs in source.values():
            if obs.manufacturer:
                records_by_manufacturer[obs.manufacturer] = records_by_manufacturer.get(obs.manufacturer, 0) + 1

    lines = [
        "# Migration report", "",
        f"- observations: {total} (legacy {summary.legacy_count}, seed {summary.seed_count})",
        f"- entities: {len(products)}",
        f"- distinct valid EANs asserted: {len(asserted)}",
        f"- asserted EAN values failing validation: {invalid_ean_count}",
        f"- key collisions: {len(summary.key_collisions)}",
        f"- minted factions: {len(summary.minted_factions)}",
        f"- conflicts: {len(conflicts)}",
        f"- violations: {len(violations)}", "",
        "| manufacturer | records | entities | with EAN | confirmed |", "|---|---|---|---|---|",
    ]
    for manufacturer in sorted(catalog):
        records = catalog[manufacturer]
        with_ean = [p for p in records if p.ean]
        confirmed = [p for p in with_ean if p.eanConfidence == "confirmed"]
        record_count = records_by_manufacturer.get(manufacturer, 0)
        lines.append(f"| {manufacturer} | {record_count} | {len(records)} | {len(with_ean)} | {len(confirmed)} |")
    if violations:
        lines += ["", "## Violations", *[f"- {v}" for v in violations]]
    return violations, "\n".join(lines) + "\n"
```

CLI: import `verify_migration` at module top of `cli.py`; extend the `migrate` branch:

```python
        summary = run_migration(paths, args.legacy_dir, args.seed_dir)
        print(...)  # unchanged summary line
        violations, report = verify_migration(paths, summary)
        report_path = args.report or (args.data / "review" / "migration-report.md")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8", newline="\n")
        if violations:
            for violation in violations:
                print(f"VIOLATION: {violation}")
            return 3
        print("verification: OK")
        return 0
```

with `migrate.add_argument("--report", type=Path, default=None)`.

- [ ] **Step 4: Run tests** — targeted then full suite; all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/migrate/verify.py tools/acquisition/src/warhub_acquisition/cli.py tools/acquisition/tests/test_migrate_verify.py
git commit -m "feat(acquisition): migration parity verifier with loud violations"
```

---

### Task 8: Execute the real migration (data commit)

No new code. This task runs the migration against the repository data and commits the generated artifacts. Executor must have the repo root as working directory context; all commands run from `tools/acquisition/`.

**Files (generated, committed):**
- Create: `data/evidence/products/legacy-catalog/observations.jsonl` (~12,799 lines)
- Create: `data/evidence/products/seed-curated/observations.jsonl` (~40–70 lines)
- Create: `data/catalog/products/<manufacturer>.yaml` (9 files)
- Create: `data/catalog/taxonomy/game-systems.yaml`, `data/catalog/taxonomy/factions.yaml`
- Create: `data/review/migration-report.md`, `data/review/conflicts.yaml`

- [ ] **Step 1: Run the migration**

Run (from `tools/acquisition/`): `uv run warhub-data migrate --data ../../data`
Expected output: `migrated 12799 legacy + <N> seed observations; <K> key collisions; 0 invalid records` then `verification: OK`, exit 0. If exit is 3, STOP: read the printed violations and `data/review/migration-report.md`, and report BLOCKED with them — do not "fix" data by hand.

- [ ] **Step 2: Idempotence check on real data**

Re-run the same command; then `git status --porcelain data/` must show the same file set with no content changes between runs (`git diff --stat` empty after the second run). If files churn, STOP and report BLOCKED with the diff.

- [ ] **Step 3: Sanity-check the report**

Read `data/review/migration-report.md`. Expect: entities ≤ 12,799 (dedup across factions is expected and intended); distinct valid EANs ≥ 5,700 (legacy has 5,853 `ean:` entries; a small number may fail checksum validation and be reported as invalid); violations: 0. Include the report's headline numbers in your task report. Also skim `data/review/conflicts.yaml` — ean-mismatch/ean-shared entries are EXPECTED findings (real data quality signal), not errors; count them in the task report.

- [ ] **Step 4: Run the full test suites once**

`uv run pytest -v` (from tools/acquisition) and `dotnet test WarHub.Catalog.slnx --nologo -v q` (from repo root) — both green (the publisher still reads the legacy tree at this point; nothing it reads changed).

- [ ] **Step 5: Commit the generated data**

```bash
git add data/evidence data/catalog data/review
git commit -m "data: migrate legacy product catalog into the evidence store"
```

---

### Task 9: Publisher canonical DTOs + loaders (additive, no cutover yet)

**Files:**
- Create: `tools/WarHub.Catalog.Publish/CanonicalModels.cs`
- Modify: `tools/WarHub.Catalog.Publish/YamlSource.cs`
- Test: `tools/WarHub.Catalog.Publish.Tests/CanonicalYamlSourceTests.cs`

**Interfaces:**
- Consumes: YamlDotNet deserializer conventions already in `YamlSource.cs:14-17` (CamelCase, IgnoreUnmatchedProperties).
- Produces (namespace `WarHub.Catalog.Publish`):

```csharp
public sealed record CanonicalProductCatalog
{
    public required string Manufacturer { get; init; }
    public required List<CanonicalProduct> Products { get; init; }
}

public sealed record CanonicalProduct
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required string Manufacturer { get; init; }
    public string? ProductCode { get; init; }
    public string? Sku { get; init; }
    public string? Ean { get; init; }
    public string? EanConfidence { get; init; }
    public string? GameSystem { get; init; }     // slug
    public string? Faction { get; init; }        // slug
    public string? Category { get; init; }
    public string? Packaging { get; init; }
    public int? Quantity { get; init; }
    public required string Status { get; init; }
    public string? Availability { get; init; }
    public string? FirstSeen { get; init; }
    public decimal? PriceGbp { get; init; }
    public decimal? PriceUsd { get; init; }
    public decimal? PriceEur { get; init; }
    public string? Url { get; init; }
    public string? ImageUrl { get; init; }
    public string? Description { get; init; }
    public List<string>? Evidence { get; init; }
}

public sealed record TaxonomyLabels(
    IReadOnlyDictionary<string, string> GameSystems,
    IReadOnlyDictionary<string, string> Factions);
```

  - In `YamlSource`: `public static IEnumerable<CanonicalProductCatalog> LoadCanonicalCatalogs(string catalogDir)` — reads `{catalogDir}/products/*.yaml` (NOT recursive), Ordinal-sorted, one `CanonicalProductCatalog` per file. `public static TaxonomyLabels LoadTaxonomyLabels(string catalogDir)` — reads `{catalogDir}/taxonomy/game-systems.yaml` (`gameSystems: [{slug,label}]`) and `taxonomy/factions.yaml` (`factions: [{slug,label}]`); missing file → empty map. Private DTOs for the label files (`LabelEntry { required string Slug; required string Label; }`, wrappers `GameSystemLabelsFile { List<LabelEntry> GameSystems }` / `FactionLabelsFile { List<LabelEntry> Factions }`).

- [ ] **Step 1: Write the failing tests**

```csharp
// tools/WarHub.Catalog.Publish.Tests/CanonicalYamlSourceTests.cs
using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

public class CanonicalYamlSourceTests
{
    private static string WriteTempCatalog()
    {
        string root = Directory.CreateTempSubdirectory("canonical-src").FullName;
        Directory.CreateDirectory(Path.Combine(root, "products"));
        Directory.CreateDirectory(Path.Combine(root, "taxonomy"));
        File.WriteAllText(Path.Combine(root, "products", "test-mfg.yaml"), """
            manufacturer: test-mfg
            products:
              - id: test-mfg/99120110077
                name: 'Combat Patrol: Necrons'
                manufacturer: test-mfg
                productCode: '99120110077'
                sku: '99120110077'
                ean: '5011921194285'
                eanConfidence: confirmed
                gameSystem: test-system
                faction: necrons
                category: miniatures
                quantity: 11
                status: current
                availability: in_stock
                firstSeen: '2026-07-07'
                priceGbp: 76.5
                url: https://example/necrons
                evidence:
                  - legacy-catalog:test-mfg/test-system/necrons/combat-patrol-necrons
            """);
        File.WriteAllText(Path.Combine(root, "taxonomy", "game-systems.yaml"), """
            gameSystems:
              - slug: test-system
                label: Test System
            """);
        File.WriteAllText(Path.Combine(root, "taxonomy", "factions.yaml"), """
            factions:
              - slug: necrons
                label: Necrons
            """);
        return root;
    }

    [Fact]
    public void LoadCanonicalCatalogs_reads_flat_manufacturer_files()
    {
        var catalogs = YamlSource.LoadCanonicalCatalogs(WriteTempCatalog()).ToList();
        var catalog = Assert.Single(catalogs);
        Assert.Equal("test-mfg", catalog.Manufacturer);
        var product = Assert.Single(catalog.Products);
        Assert.Equal("test-mfg/99120110077", product.Id);
        Assert.Equal("5011921194285", product.Ean);
        Assert.Equal("confirmed", product.EanConfidence);
        Assert.Equal(11, product.Quantity);
        Assert.Equal("test-system", product.GameSystem);
        Assert.Equal(76.5m, product.PriceGbp);
    }

    [Fact]
    public void LoadTaxonomyLabels_reads_label_maps()
    {
        var labels = YamlSource.LoadTaxonomyLabels(WriteTempCatalog());
        Assert.Equal("Test System", labels.GameSystems["test-system"]);
        Assert.Equal("Necrons", labels.Factions["necrons"]);
    }

    [Fact]
    public void LoadTaxonomyLabels_missing_files_yield_empty_maps()
    {
        string root = Directory.CreateTempSubdirectory("canonical-empty").FullName;
        var labels = YamlSource.LoadTaxonomyLabels(root);
        Assert.Empty(labels.GameSystems);
        Assert.Empty(labels.Factions);
    }
}
```

- [ ] **Step 2: Run to verify failure** — `dotnet test tools/WarHub.Catalog.Publish.Tests --nologo` → compile errors (types missing).

- [ ] **Step 3: Implement** the records above in `CanonicalModels.cs` and in `YamlSource.cs`:

```csharp
    public static IEnumerable<CanonicalProductCatalog> LoadCanonicalCatalogs(string catalogDir)
    {
        string products = Path.Combine(catalogDir, "products");
        if (!Directory.Exists(products)) { yield break; }
        foreach (string file in Directory
            .EnumerateFiles(products, "*.yaml", SearchOption.TopDirectoryOnly)
            .OrderBy(f => f, StringComparer.Ordinal))
        {
            var catalog = Deserializer.Deserialize<CanonicalProductCatalog>(File.ReadAllText(file));
            if (catalog is not null) { yield return catalog; }
        }
    }

    public static TaxonomyLabels LoadTaxonomyLabels(string catalogDir)
    {
        return new TaxonomyLabels(
            ReadLabels<GameSystemLabelsFile>(Path.Combine(catalogDir, "taxonomy", "game-systems.yaml"))?.GameSystems,
            ReadLabels<FactionLabelsFile>(Path.Combine(catalogDir, "taxonomy", "factions.yaml"))?.Factions);
    }
```

with a small private helper that deserializes when the file exists, and a `TaxonomyLabels` constructor path that converts `List<LabelEntry>?` to `IReadOnlyDictionary<string,string>` (empty when null). Exact shape is the implementer's call; the tests are the contract.

- [ ] **Step 4: Run tests** — `dotnet test WarHub.Catalog.slnx --nologo -v q` — all green (old product path untouched).

- [ ] **Step 5: Commit**

```bash
git add tools/WarHub.Catalog.Publish/CanonicalModels.cs tools/WarHub.Catalog.Publish/YamlSource.cs tools/WarHub.Catalog.Publish.Tests/CanonicalYamlSourceTests.cs
git commit -m "feat(publish): canonical catalog DTOs and loaders"
```

---

### Task 10: Publisher cutover (builder, schema, CLI default, fixtures)

**Files:**
- Modify: `tools/WarHub.Catalog.Publish/ProductBuilder.cs`
- Modify: `tools/WarHub.Catalog.Publish/Documents.cs` (`ProductRecord` gains `EanConfidence`)
- Modify: `tools/WarHub.Catalog.Publish/schema/product-catalog.json` (additive `eanConfidence`)
- Modify: `tools/WarHub.Catalog.Publish/Publisher.cs` (line 28 wiring)
- Modify: `tools/WarHub.Catalog.Publish/Program.cs` (`--products-dir` → `--catalog-dir`, default `data/catalog`; keep `--products-dir` as a hidden alias if trivial, else drop it — CI workflow is updated in Task 12)
- Modify: `tools/WarHub.Catalog.Publish.Tests/PublishFixture.cs`, `PublishTests.cs`

**Interfaces:**
- Consumes: Task 9's loaders.
- Produces:
  - `ProductBuilder.Build(IEnumerable<CanonicalProductCatalog> catalogs, TaxonomyLabels labels, Provenance prov, CatalogWriter writer)`:
    - Partition key = `Slug.Make(product.GameSystem)` when non-null; a null `GameSystem` throws `InvalidOperationException($"product {id} has no gameSystem")` (legacy data always has one; loud beats a junk partition).
    - Partition label = `labels.GameSystems[key]`; missing → `InvalidOperationException` naming the slug.
    - Published record mapping: `Ean` = trimmed-or-null (unchanged rule); `EanConfidence` = pass-through (null omitted); `Name`; `GameSystem` = the label (NOT the slug — published contract unchanged); `Faction` = `labels.Factions[faction-slug]` when faction non-null (missing label → throw), else null; `Category`/`Status`/`Availability` pass-through; `Quantity` = `product.Quantity ?? 1`; `ProductCode` = `product.ProductCode ?? product.Sku`; `Url`; `ImageUrl`.
    - Sorting/consolidation/index logic unchanged (name then ean, Ordinal keys).
  - `ProductRecord` gains `[JsonPropertyOrder(12)] public string? EanConfidence { get; init; }`.
  - Schema `$defs/product` gains `"eanConfidence": {"type": "string", "enum": ["confirmed", "provisional", "conflicted"]}` (not required).
  - `Publisher.Run`: `ProductBuilder.Build(YamlSource.LoadCanonicalCatalogs(o.ProductsDir), YamlSource.LoadTaxonomyLabels(o.ProductsDir), o.Prov, writer)` — `PublishOptions.ProductsDir` now semantically means the catalog dir; rename the record member to `CatalogDir` for honesty.
  - Fixture rewrite: `PublishFixture` writes `data/catalog/products/test-mfg.yaml` + `taxonomy/{game-systems,factions}.yaml` (reuse the YAML from Task 9's test, but with TWO products to preserve existing count/optional-ean assertions: "Alpha Box" with `ean`/`eanConfidence: provisional`/`productCode: PRODA`/`quantity: 2`, "Beta Box" with no ean, `sku: SKUB` only, quantity omitted). Test updates: `Product_ean_is_optional` also asserts Beta's published `productCode == "SKUB"` (sku fallback survives) and Alpha carries `eanConfidence == "provisional"`; `Partition_documents_carry_partition_metadata_and_page_url` keeps `test-system` / `Test System` via the taxonomy file; add `Product_quantity_flows_from_data` (Alpha quantity 2, Beta quantity 1 fallback).

- [ ] **Step 1: Rewrite fixture + tests first, run to verify failure** — `dotnet test tools/WarHub.Catalog.Publish.Tests --nologo` → failures/compile errors (builder still takes `FactionCatalog`).

- [ ] **Step 2: Implement the cutover** (`ProductRecord.EanConfidence`, schema, `Publisher.cs`, `Program.cs` default `data/catalog` with option renamed `--catalog-dir`). Core of the new builder:

```csharp
public static int Build(
    IEnumerable<CanonicalProductCatalog> catalogs,
    TaxonomyLabels labels,
    Provenance prov,
    CatalogWriter writer)
{
    var partitions = new Dictionary<string, PartitionData>(StringComparer.Ordinal);
    foreach (var catalog in catalogs)
    {
        foreach (var p in catalog.Products)
        {
            if (string.IsNullOrEmpty(p.GameSystem))
            {
                throw new InvalidOperationException($"product {p.Id} has no gameSystem");
            }
            string key = Slug.Make(p.GameSystem);
            if (!labels.GameSystems.TryGetValue(key, out string? label))
            {
                throw new InvalidOperationException($"no label for game system slug '{key}' (product {p.Id})");
            }
            string? factionLabel = null;
            if (!string.IsNullOrEmpty(p.Faction))
            {
                if (!labels.Factions.TryGetValue(p.Faction, out factionLabel))
                {
                    throw new InvalidOperationException($"no label for faction slug '{p.Faction}' (product {p.Id})");
                }
            }
            if (!partitions.TryGetValue(key, out var data))
            {
                partitions[key] = data = new PartitionData(label, []);
            }
            data.Products.Add(new ProductRecord
            {
                Ean = string.IsNullOrWhiteSpace(p.Ean) ? null : p.Ean.Trim(),
                EanConfidence = p.EanConfidence,
                Name = p.Name,
                GameSystem = label,
                Faction = factionLabel,
                Category = p.Category ?? "miniatures",
                Status = p.Status,
                Availability = p.Availability ?? "unknown",
                Quantity = p.Quantity ?? 1,
                ProductCode = p.ProductCode ?? p.Sku,
                Url = p.Url,
                ImageUrl = p.ImageUrl,
            });
        }
    }
    // sorting, consolidated write, partition writes, and index write are UNCHANGED
    // from the existing implementation (name-then-ean Ordinal sort, ordered keys,
    // ProductCatalogDocument / IndexDocument emission) — keep those blocks as-is.
    ...
}
```

(`Category`/`Availability` fallbacks mirror the current published records' non-null guarantees: the old schema required both on every legacy record, while `CanonicalProduct` makes them optional; the canonical resolver always fills category, so the fallbacks are belt-and-braces, not new semantics.)

- [ ] **Step 3: Run the full .NET suite** — `dotnet test WarHub.Catalog.slnx --nologo -v q` — all green, warnings-as-errors clean.

- [ ] **Step 4: Delete now-dead legacy product read path** — remove `YamlSource.LoadFactions` and, if now unused by the publisher, the `ProjectReference` usage it required (`FactionCatalog`/`Product` remain in the Tool project for the legacy .NET pipeline — do NOT delete those; only the publisher's use of them). Re-run the suite.

- [ ] **Step 5: Commit**

```bash
git add tools/WarHub.Catalog.Publish tools/WarHub.Catalog.Publish.Tests
git commit -m "feat(publish): read canonical catalog format; publish eanConfidence and real quantities"
```

---

### Task 11: Real-data publish parity check + README updates

**Files:**
- Modify: `README.md` (repo layout, pipeline, build-locally sections)
- No committed dist output (dist/ stays gitignored)

- [ ] **Step 1: Build dist from the migrated catalog**

From repo root: `dotnet run --project tools/WarHub.Catalog.Publish -- --catalog-version 0.0.0-parity --page-base-url http://localhost:8080`
Expected: exit 0, schema validation passes (it runs on every document).

- [ ] **Step 2: Parity assertions (manual but recorded)**

Compare `dist/products.json` against the migration report from Task 8 and record the numbers in your task report:
- `counts.products` == migration report's entity total.
- Sum of `products/index.json` partition `records` == `counts.products`.
- Count of records with `ean` == migration report's "with EAN" total; spot-check 3 known EANs (e.g. `5011921194285`) are present with `eanConfidence`.
- `gameSystem` values are labels (e.g. `Warhammer 40,000`), never slugs; partition keys are slugs.
If any parity check fails, STOP and report BLOCKED with the numbers — the fix belongs in the resolver/builder, not in hand-edits.

- [ ] **Step 3: Update README.md**

- Repo layout: `data/products/` line becomes `data/{evidence,catalog}/ # source of truth: per-source observations + resolved canonical catalog` (legacy `data/products` marked "legacy, retired by the evidence-ledger pipeline; removal tracked for Plan 5"); `tools/` gains `tools/acquisition/ # python: migrate/resolve/report (acquire arrives in Plan 3)`.
- Pipeline section: generation workflows are being replaced (Plan 3 adds the nightly acquisition workflow); publisher reads `data/catalog`.
- Build-locally: publisher invocation unchanged except `--catalog-dir` note.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: point pipeline docs at the evidence-ledger catalog"
```

---

### Task 12: Retire legacy product workflows + close superseded bot PRs

**Files:**
- Delete: `.github/workflows/product-catalog-update.yml`
- Delete: `.github/workflows/product-catalog-enrich.yml`
- Modify: `.github/workflows/catalog-publish.yml` ONLY if it names `--products-dir` explicitly (verify; the default now points at `data/catalog`)

- [ ] **Step 1: Verify catalog-publish.yml invocation**

Read `.github/workflows/catalog-publish.yml`; if the publisher invocation passes `--products-dir`, update it to `--catalog-dir data/catalog`; its `data/**` path trigger already covers the new tree. `paint-catalog-update.yml` stays untouched.

- [ ] **Step 2: Delete the two product workflows**

They write to `data/products/**`, which the publisher no longer reads; leaving them running would produce zombie PRs. `ci.yml` is untouched.

- [ ] **Step 3: Run both test suites once** (python + .NET) — green.

- [ ] **Step 4: Commit**

```bash
git add -A .github/workflows
git commit -m "ci: retire legacy product scraping/enrichment workflows"
```

- [ ] **Step 5: Close superseded bot PRs (execution step, after this plan's PR merges)**

`gh pr close 4 --comment "Superseded by the evidence-ledger pipeline (#19 + this plan): legacy data/products is no longer the publisher's source; live acquisition returns in Plan 3."` and the same for PR 5. Do NOT close #16 (paints — untouched by this plan). This step is performed by the controller at branch-finish time, not by an implementer subagent.

---

## Execution notes for the controller

- Tasks 1–7 are Python-only and sequential (6 depends on 3–5; 7 on 6). Tasks 9–10 are C#. Task 8 must precede 10's real-data step only insofar as Task 11 needs migrated data; the strict order 1→12 is simplest and safe.
- Task 8 and Task 11 are execution tasks — cheap models suffice but they must follow the STOP/BLOCKED gates literally.
- The migration commit (Task 8) is large (~13k-line JSONL); reviewers of that task review the report + spot samples, not the full diff.

## Follow-on (Plan 3 preview, for context only)

Live source framework (fetch strategies, contracts, budgets, cursors), `acquire` verb, health-report PR bodies, nightly workflow; Warlord codePattern tightening; cross-manufacturer EAN-union visibility; report.py hardening; "confirmed EAN never silently replaced" ownership (acquire-time diff tooling).


