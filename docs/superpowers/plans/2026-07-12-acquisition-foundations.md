# Acquisition Foundations Implementation Plan (Plan 1 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python acquisition package's foundation — evidence store, EAN validation, deterministic YAML output, and the pure resolver that turns per-source observations into the canonical product catalog — with `resolve` and `report` CLI verbs, all offline.

**Architecture:** Claims-first pipeline per `docs/superpowers/specs/2026-07-12-data-acquisition-rewrite-design.md`. This plan implements the spine only: pydantic models for observations/descriptors, a JSONL evidence store, taxonomy data files, and a deterministic resolver (identity → join → corroborate → attributes/lifecycle → write). No network code — live sources are Plan 3, migration is Plan 2.

**Tech Stack:** Python ≥3.12, uv, pydantic v2, PyYAML, pytest. New package at `tools/acquisition/` (src layout, console script `warhub-data`).

## Global Constraints

- Determinism invariant: identical inputs (evidence + taxonomy + matches + overrides) → byte-identical outputs. No wall-clock, no randomness, no dict-iteration nondeterminism in outputs.
- EANs and other numeric-looking strings are ALWAYS emitted as quoted YAML strings (leading zeros must survive round-trips).
- All emitted text files: UTF-8, LF line endings, trailing newline.
- Evidence is append-only in spirit: observations are upserted, never deleted; `firstSeen` never moves forward.
- The resolver is a pure function; it never reads the previous catalog output.
- Dates are ISO `YYYY-MM-DD` strings in all files.
- Run all Python commands from `tools/acquisition/` with `uv run …`.
- Commit messages end with the two trailer lines used in this repo (Co-Authored-By + Claude-Session).

---

### Task 1: Package scaffold + CI wiring

**Files:**
- Create: `tools/acquisition/pyproject.toml`
- Create: `tools/acquisition/src/warhub_acquisition/__init__.py`
- Create: `tools/acquisition/tests/test_package.py`
- Create: `tools/acquisition/.gitignore`
- Modify: `.github/workflows/ci.yml` (add python job + path filters)
- Modify: `.gitattributes` (force LF for jsonl/py)

**Interfaces:**
- Consumes: nothing.
- Produces: importable package `warhub_acquisition` with `__version__: str`; `uv run pytest` green; CI runs Python tests when `tools/acquisition/**` changes.

- [ ] **Step 1: Write the failing test**

```python
# tools/acquisition/tests/test_package.py
import warhub_acquisition


def test_version() -> None:
    assert warhub_acquisition.__version__ == "0.1.0"
```

- [ ] **Step 2: Create the package files**

```toml
# tools/acquisition/pyproject.toml
[project]
name = "warhub-acquisition"
version = "0.1.0"
description = "WarHub catalog data acquisition and resolution pipeline"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.7",
    "pyyaml>=6.0",
]

[project.scripts]
warhub-data = "warhub_acquisition.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/warhub_acquisition"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

```python
# tools/acquisition/src/warhub_acquisition/__init__.py
__version__ = "0.1.0"
```

```gitignore
# tools/acquisition/.gitignore
.venv/
__pycache__/
*.egg-info/
```

Append to `.gitattributes`:

```gitattributes
*.py text eol=lf
*.jsonl text eol=lf
```

- [ ] **Step 3: Run test to verify it passes**

Run (in `tools/acquisition/`): `uv run pytest -v`
Expected: `test_version PASSED` (uv auto-creates the venv and installs the package; `uv.lock` appears — commit it).

- [ ] **Step 4: Add CI job**

In `.github/workflows/ci.yml`, add `tools/acquisition/**` to both `push` and `pull_request` path filters, and add this job alongside the existing .NET job:

```yaml
  python:
    name: Python tests
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: tools/acquisition
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --locked
      - run: uv run pytest -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition .github/workflows/ci.yml .gitattributes
git commit -m "feat(acquisition): scaffold python package with uv + pytest + CI"
```

---

### Task 2: EAN/GTIN validation

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/ean.py`
- Test: `tools/acquisition/tests/test_ean.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `normalize_ean(raw: str | None) -> str | None` — strips spaces/hyphens; returns 13-digit canonical form (12-digit UPC-A zero-padded to 13) if plausible digits, else `None`.
  - `is_valid_ean(ean: str) -> bool` — 13 digits + correct GTIN check digit (input must already be normalized).
  - `canonical_ean(raw: str | None) -> str | None` — normalize + validate; returns the canonical EAN or `None`. This is the only function later tasks call.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_ean.py
import pytest

from warhub_acquisition.ean import canonical_ean, is_valid_ean, normalize_ean


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5011921194285", "5011921194285"),   # GW Combat Patrol: Necrons
        ("812152031524", "0812152031524"),    # Wyrd UPC-A, zero-padded
        (" 5011921 194285 ", "5011921194285"),
        ("501-1921-194285", "5011921194285"),
        ("0", None),
        ("", None),
        (None, None),
        ("not-a-code", None),
        ("12345", None),                       # too short
        ("50119211942850000", None),           # too long
    ],
)
def test_normalize_ean(raw: str | None, expected: str | None) -> None:
    assert normalize_ean(raw) == expected


@pytest.mark.parametrize(
    ("ean", "valid"),
    [
        ("5011921194285", True),
        ("5011921142361", True),   # GW Primaris Intercessors
        ("5011921146000", True),   # GW Stormraven Gunship
        ("0812152031524", True),   # Wyrd Miss Feasance (padded UPC)
        ("5011921194286", False),  # bad check digit
        ("5060924988049", True),   # Mantic Maul Battleship
    ],
)
def test_is_valid_ean(ean: str, valid: bool) -> None:
    assert is_valid_ean(ean) is valid


def test_canonical_ean_end_to_end() -> None:
    assert canonical_ean("812152031524") == "0812152031524"
    assert canonical_ean("5011921194286") is None  # normalizes but fails checksum
    assert canonical_ean(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ean.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warhub_acquisition.ean'`

- [ ] **Step 3: Write the implementation**

```python
# tools/acquisition/src/warhub_acquisition/ean.py
"""GTIN/EAN normalization and validation (EAN-13 and UPC-A)."""

def normalize_ean(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits != "".join(ch for ch in raw if ch not in " -"):
        return None  # contained non-digit junk beyond separators
    if len(digits) == 12:
        digits = "0" + digits  # UPC-A embeds into EAN-13 with a leading zero
    if len(digits) != 13 or int(digits) == 0:
        return None
    return digits


def is_valid_ean(ean: str) -> bool:
    if len(ean) != 13 or not ean.isdigit():
        return False
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(ean[:12]))
    return (10 - total % 10) % 10 == int(ean[12])


def canonical_ean(raw: str | None) -> str | None:
    normalized = normalize_ean(raw)
    if normalized is None or not is_valid_ean(normalized):
        return None
    return normalized
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ean.py -v`
Expected: all PASS. (The check-digit math: weights 1,3 alternating from the left over the first 12 digits; the real GW/Mantic/Wyrd EANs in the tests were probe-verified on 2026-07-12.)

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/ean.py tools/acquisition/tests/test_ean.py
git commit -m "feat(acquisition): EAN/GTIN normalization and check-digit validation"
```

---

### Task 3: Deterministic YAML writer

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/yamlio.py`
- Test: `tools/acquisition/tests/test_yamlio.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `dump_yaml(data: object) -> str` — deterministic YAML: field order preserved (insertion order), numeric-looking/date-looking strings quoted, multiline strings as literal blocks (`|-`), LF, trailing newline, no line wrapping.
  - `load_yaml(text: str) -> object` — safe load.
  - `write_yaml(path: Path, data: object) -> None` / `read_yaml(path: Path) -> object` — file helpers (UTF-8, LF).

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_yamlio.py
from warhub_acquisition.yamlio import dump_yaml, load_yaml


def test_numeric_like_strings_are_quoted() -> None:
    text = dump_yaml({"ean": "0812152031524", "sku": "99120110077", "n": 5})
    assert "ean: '0812152031524'" in text
    assert "sku: '99120110077'" in text
    assert "n: 5" in text


def test_date_like_strings_are_quoted() -> None:
    assert "firstSeen: '2026-07-07'" in dump_yaml({"firstSeen": "2026-07-07"})


def test_round_trip_preserves_leading_zeros() -> None:
    data = {"ean": "0812152031524"}
    assert load_yaml(dump_yaml(data)) == data


def test_multiline_uses_literal_block() -> None:
    text = dump_yaml({"description": "line one\nline two"})
    assert "description: |-" in text


def test_insertion_order_preserved_and_deterministic() -> None:
    data = {"b": 1, "a": 2}
    text = dump_yaml(data)
    assert text == "b: 1\na: 2\n"
    assert dump_yaml(data) == text


def test_long_urls_not_wrapped() -> None:
    url = "https://example.com/" + "x" * 300
    assert f"url: {url}\n" in dump_yaml({"url": url})


def test_nested_lists_are_indented() -> None:
    text = dump_yaml({"products": [{"id": "a", "name": "X"}]})
    assert text == "products:\n  - id: a\n    name: X\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_yamlio.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# tools/acquisition/src/warhub_acquisition/yamlio.py
"""Deterministic YAML serialization: stable order, safe quoting, literal blocks."""
import re
from pathlib import Path

import yaml

# anything a YAML 1.2 core-schema consumer could read as a number:
# ints (incl. leading-zero), floats, scientific notation, hex, octal
_NUMERIC_LIKE = re.compile(r"[-+]?(\.\d+|\d+(\.\d*)?)([eE][-+]?\d+)?|0[xX][0-9a-fA-F]+|0[oO][0-7]+")


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        # never emit indentless sequences: list items sit indented under their key
        return super().increase_indent(flow, False)


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    if _NUMERIC_LIKE.fullmatch(value):
        # PyYAML's YAML 1.1 resolver misses several shapes a YAML 1.2
        # consumer would read as numbers (leading-zero ints like
        # "0812152031524", dotless scientific notation like "5e3") --
        # force-quote everything number-shaped
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="'")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_Dumper.add_representer(str, _represent_str)


def dump_yaml(data: object) -> str:
    return yaml.dump(
        data,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        width=10_000,
        default_flow_style=False,
    )


def load_yaml(text: str) -> object:
    return yaml.safe_load(text)


def write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(data), encoding="utf-8", newline="\n")


def read_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
```

Note: PyYAML's resolver-driven quoting is NOT sufficient on its own: an all-digit string with a leading zero and a digit 8/9 (e.g. `'0812152031524'`) fails PyYAML's YAML 1.1 int patterns, so PyYAML emits it unquoted — and a YAML 1.2 consumer would then read it as an integer, destroying the leading zero. Hence the explicit force-quote of every number-shaped string (ints incl. leading-zero, floats, scientific notation, hex, octal) in `_represent_str`; the tests in Step 1 pin this.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yamlio.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/yamlio.py tools/acquisition/tests/test_yamlio.py
git commit -m "feat(acquisition): deterministic YAML writer with safe quoting"
```

---

### Task 4: Observation model + JSONL evidence store

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/models/__init__.py`
- Create: `tools/acquisition/src/warhub_acquisition/models/observation.py`
- Create: `tools/acquisition/src/warhub_acquisition/evidence/__init__.py`
- Create: `tools/acquisition/src/warhub_acquisition/evidence/store.py`
- Test: `tools/acquisition/tests/test_evidence_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Observation` (pydantic BaseModel), fields in this exact declaration order:
    `key: str` (format `<source-id>:<source-local-id>`), `url: str | None`,
    `manufacturer: str | None` (manufacturer slug, mapped at acquire time),
    `name: str`, `sku: str | None`, `ean: str | None` (as asserted, unvalidated),
    `priceGbp: float | None`, `priceUsd: float | None`, `priceEur: float | None`,
    `availability: str | None`, `hints: dict[str, object]` (default `{}`),
    `firstSeen: str`, `lastSeen: str` (ISO dates), `missStreak: int = 0`,
    `archived: bool = False`, `extractor: str`.
  - `Observation.source_id` property → `key.split(":", 1)[0]`.
  - `EvidenceStore(root: Path)` with:
    - `load(source_id: str) -> dict[str, Observation]` (empty dict if absent)
    - `upsert(source_id: str, fresh: Observation) -> None` — merge semantics: `firstSeen = min(old, new)`, `lastSeen = max(old, new)`, `missStreak` reset to fresh value, all other fields replaced by fresh.
    - `save(source_id: str) -> None` — writes `<root>/<source-id>/observations.jsonl`, one compact JSON object per line, lines sorted by `key`, keys alphabetical, `exclude_none`, UTF-8, LF, trailing newline.
    - `load_all() -> dict[str, dict[str, Observation]]` — every source dir under root, sorted by source id.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_evidence_store.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_evidence_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# tools/acquisition/src/warhub_acquisition/models/__init__.py
```

```python
# tools/acquisition/src/warhub_acquisition/models/observation.py
"""One source's latest claim about one product."""
from pydantic import BaseModel, ConfigDict, Field


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    url: str | None = None
    manufacturer: str | None = None
    name: str
    sku: str | None = None
    ean: str | None = None
    priceGbp: float | None = None
    priceUsd: float | None = None
    priceEur: float | None = None
    availability: str | None = None
    hints: dict[str, object] = Field(default_factory=dict)
    firstSeen: str
    lastSeen: str
    missStreak: int = 0
    archived: bool = False
    extractor: str

    @property
    def source_id(self) -> str:
        return self.key.split(":", 1)[0]
```

```python
# tools/acquisition/src/warhub_acquisition/evidence/__init__.py
```

```python
# tools/acquisition/src/warhub_acquisition/evidence/store.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_evidence_store.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/models tools/acquisition/src/warhub_acquisition/evidence tools/acquisition/tests/test_evidence_store.py
git commit -m "feat(acquisition): observation model and JSONL evidence store"
```

---

### Task 5: Source descriptors + taxonomy (models, loaders, initial data)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/models/descriptor.py`
- Create: `tools/acquisition/src/warhub_acquisition/taxonomy.py`
- Create: `data/catalog/taxonomy/manufacturers.yaml`
- Create: `data/catalog/sources/legacy-catalog.yaml`
- Create: `data/catalog/sources/seed-curated.yaml`
- Test: `tools/acquisition/tests/test_descriptor.py`, `tools/acquisition/tests/test_taxonomy.py`

**Interfaces:**
- Consumes: `yamlio.read_yaml`.
- Produces:
  - `SourceDescriptor` (pydantic): `id: str`, `kind: Literal["curated", "manufacturer", "retailer", "archive", "barcode-db"]`, `strategy: str`, `baseUrl: str | None = None`, `scope: dict[str, object] = {}`, `politeness: dict[str, object] = {}`, `budget: dict[str, object] = {}`, `contract: Contract | None = None`.
  - `Contract` (pydantic): `minCount: int = 0`, `maxDropPct: float = 100.0`, `requiredFieldRates: dict[str, float] = {}`.
  - `load_descriptors(dir: Path) -> dict[str, SourceDescriptor]` (keyed by id, validates filename == id).
  - `KIND_PRIORITY: dict[str, int]` — `curated=0, manufacturer=1, retailer=2, archive=3, barcode-db=4` (lower = more trusted).
  - `Manufacturer` (pydantic): `slug: str`, `name: str`, `codePattern: str | None` (regex, full-match), `codeStrip: list[str] = []` (prefixes to strip from retailer SKUs), `gs1Prefixes: list[str] = []`, `vendorNames: list[str] = []` (retailer vendor strings that map to this manufacturer).
  - `Taxonomy` class: `load(dir: Path) -> Taxonomy`; `manufacturers: dict[str, Manufacturer]`; `manufacturer_for_vendor(vendor: str) -> str | None` (case-insensitive); `normalize_code(manufacturer: str, sku: str | None) -> str | None` (uppercase, strip spaces, strip configured prefixes and a trailing `-EN`, return only if it full-matches `codePattern`).

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_descriptor.py
from pathlib import Path

from warhub_acquisition.models.descriptor import KIND_PRIORITY, SourceDescriptor, load_descriptors
from warhub_acquisition.yamlio import write_yaml


def test_load_descriptors(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "ret-goblin.yaml",
        {
            "id": "ret-goblin",
            "kind": "retailer",
            "strategy": "shopify",
            "baseUrl": "https://www.goblingaming.co.uk",
            "contract": {"minCount": 8000, "requiredFieldRates": {"name": 1.0, "ean": 0.6}},
        },
    )
    descriptors = load_descriptors(tmp_path)
    assert descriptors["ret-goblin"].kind == "retailer"
    assert descriptors["ret-goblin"].contract.minCount == 8000


def test_kind_priority_ordering() -> None:
    assert KIND_PRIORITY["curated"] < KIND_PRIORITY["manufacturer"] < KIND_PRIORITY["retailer"]
    assert KIND_PRIORITY["retailer"] < KIND_PRIORITY["archive"] < KIND_PRIORITY["barcode-db"]


def test_filename_must_match_id(tmp_path: Path) -> None:
    write_yaml(tmp_path / "wrong-name.yaml", {"id": "ret-goblin", "kind": "retailer", "strategy": "shopify"})
    import pytest

    with pytest.raises(ValueError, match="wrong-name"):
        load_descriptors(tmp_path)
```

```python
# tools/acquisition/tests/test_taxonomy.py
from pathlib import Path

from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import write_yaml


def make_taxonomy(tmp_path: Path) -> Taxonomy:
    write_yaml(
        tmp_path / "manufacturers.yaml",
        {
            "manufacturers": [
                {
                    "slug": "games-workshop",
                    "name": "Games Workshop",
                    "codePattern": r"\d{11}",
                    "codeStrip": ["GWS", "GW-"],
                    "gs1Prefixes": ["5011921"],
                    "vendorNames": ["Games Workshop", "Citadel"],
                },
                {"slug": "wyrd-games", "name": "Wyrd Games", "codePattern": r"WYR\d+", "vendorNames": ["Wyrd Miniatures"]},
            ]
        },
    )
    return Taxonomy.load(tmp_path)


def test_manufacturer_for_vendor_is_case_insensitive(tmp_path: Path) -> None:
    taxonomy = make_taxonomy(tmp_path)
    assert taxonomy.manufacturer_for_vendor("games workshop") == "games-workshop"
    assert taxonomy.manufacturer_for_vendor("Unknown Vendor") is None


def test_normalize_code_strips_and_matches(tmp_path: Path) -> None:
    taxonomy = make_taxonomy(tmp_path)
    assert taxonomy.normalize_code("games-workshop", "GWS99120110077") == "99120110077"
    assert taxonomy.normalize_code("games-workshop", "99120110077-EN") == "99120110077"
    assert taxonomy.normalize_code("games-workshop", "49-04") is None  # short code: not identity-grade
    assert taxonomy.normalize_code("wyrd-games", "wyr21331") == "WYR21331"
    assert taxonomy.normalize_code("games-workshop", None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_descriptor.py tests/test_taxonomy.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementations**

```python
# tools/acquisition/src/warhub_acquisition/models/descriptor.py
"""Source descriptors: declarative definition of one data source."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from warhub_acquisition.yamlio import read_yaml

KIND_PRIORITY: dict[str, int] = {
    "curated": 0,
    "manufacturer": 1,
    "retailer": 2,
    "archive": 3,
    "barcode-db": 4,
}


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minCount: int = 0
    maxDropPct: float = 100.0
    requiredFieldRates: dict[str, float] = Field(default_factory=dict)


class SourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["curated", "manufacturer", "retailer", "archive", "barcode-db"]
    strategy: str
    baseUrl: str | None = None
    scope: dict[str, object] = Field(default_factory=dict)
    politeness: dict[str, object] = Field(default_factory=dict)
    budget: dict[str, object] = Field(default_factory=dict)
    contract: Contract | None = None


def load_descriptors(directory: Path) -> dict[str, SourceDescriptor]:
    descriptors: dict[str, SourceDescriptor] = {}
    for path in sorted(directory.glob("*.yaml")):
        descriptor = SourceDescriptor.model_validate(read_yaml(path))
        if descriptor.id != path.stem:
            raise ValueError(f"descriptor id {descriptor.id!r} does not match filename {path.stem!r} ({path})")
        descriptors[descriptor.id] = descriptor
    return descriptors
```

```python
# tools/acquisition/src/warhub_acquisition/taxonomy.py
"""Taxonomy: manufacturer registry with code patterns and vendor-name mapping."""
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from warhub_acquisition.yamlio import read_yaml


class Manufacturer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    name: str
    codePattern: str | None = None
    codeStrip: list[str] = Field(default_factory=list)
    gs1Prefixes: list[str] = Field(default_factory=list)
    vendorNames: list[str] = Field(default_factory=list)


class Taxonomy:
    def __init__(self, manufacturers: dict[str, Manufacturer]) -> None:
        self.manufacturers = manufacturers
        self._vendor_index = {
            vendor.casefold(): manufacturer.slug
            for manufacturer in manufacturers.values()
            for vendor in [manufacturer.name, *manufacturer.vendorNames]
        }

    @classmethod
    def load(cls, directory: Path) -> "Taxonomy":
        data = read_yaml(directory / "manufacturers.yaml")
        manufacturers = [Manufacturer.model_validate(entry) for entry in data["manufacturers"]]
        return cls({m.slug: m for m in manufacturers})

    def manufacturer_for_vendor(self, vendor: str) -> str | None:
        return self._vendor_index.get(vendor.casefold())

    def normalize_code(self, manufacturer: str, sku: str | None) -> str | None:
        spec = self.manufacturers.get(manufacturer)
        if spec is None or spec.codePattern is None or not sku:
            return None
        code = sku.upper().replace(" ", "")
        for prefix in spec.codeStrip:
            code = code.removeprefix(prefix.upper())
        code = code.removesuffix("-EN")
        return code if re.fullmatch(spec.codePattern, code, flags=re.IGNORECASE) else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_descriptor.py tests/test_taxonomy.py -v`
Expected: all PASS

- [ ] **Step 5: Create the initial repo data files**

```yaml
# data/catalog/taxonomy/manufacturers.yaml
manufacturers:
  - slug: games-workshop
    name: Games Workshop
    codePattern: '\d{11}'
    codeStrip: [GWS, GW-]
    gs1Prefixes: ['5011921']
    vendorNames: [Games Workshop, Citadel, Forge World]
  - slug: atomic-mass-games
    name: Atomic Mass Games
    codePattern: '(SWL|SWP|SWM|CP|AMG)[A-Z]?\d+[A-Z]*'
    vendorNames: [Atomic Mass Games, Asmodee]
  - slug: cmon
    name: CMON
    codePattern: 'CMN[A-Z0-9]+'
    vendorNames: [CMON, Cool Mini or Not]
  - slug: corvus-belli
    name: Corvus Belli
    codePattern: '\d{6}'
    codeStrip: [COR]
    vendorNames: [Corvus Belli]
  - slug: mantic-games
    name: Mantic Games
    codePattern: '[A-Z]{2,10}\d{2,6}[A-Z]*'
    vendorNames: [Mantic Games, Mantic]
  - slug: para-bellum
    name: Para Bellum
    codePattern: 'PB[A-Z]?\w+'
    vendorNames: [Para Bellum, Para Bellum Wargames]
  - slug: steamforged-games
    name: Steamforged Games
    codePattern: 'SF[A-Z0-9-]+'
    vendorNames: [Steamforged Games, Steamforged]
  - slug: warlord-games
    name: Warlord Games
    codePattern: '[0-9]{9,12}|[A-Z0-9-]{6,}'
    vendorNames: [Warlord Games]
  - slug: wyrd-games
    name: Wyrd Games
    codePattern: 'WYR\d+[A-Z ]*'
    vendorNames: [Wyrd Games, Wyrd Miniatures]
```

```yaml
# data/catalog/sources/legacy-catalog.yaml
id: legacy-catalog
kind: curated
strategy: none
```

```yaml
# data/catalog/sources/seed-curated.yaml
id: seed-curated
kind: curated
strategy: none
```

(These code patterns are seeded from the probe evidence and existing data; Plan 2's migration refines them against the full legacy SKU population — a parity check there fails loudly if a pattern rejects real codes.)

- [ ] **Step 6: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/models/descriptor.py tools/acquisition/src/warhub_acquisition/taxonomy.py tools/acquisition/tests/test_descriptor.py tools/acquisition/tests/test_taxonomy.py data/catalog
git commit -m "feat(acquisition): source descriptors, manufacturer taxonomy, initial data files"
```

---

### Task 6: Identity derivation

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/resolve/__init__.py`
- Create: `tools/acquisition/src/warhub_acquisition/resolve/identity.py`
- Test: `tools/acquisition/tests/test_identity.py`

**Interfaces:**
- Consumes: `Taxonomy.normalize_code`.
- Produces:
  - `slugify(name: str) -> str` — NFKD-fold to ASCII, casefold, alnum runs kept, everything else collapses to single `-`, trimmed.
  - `entity_id(manufacturer: str, code: str | None, name: str) -> str` — `"{manufacturer}/{code}"` when code given (already normalized), else `"{manufacturer}/{slugify(name)}"`.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_identity.py
from warhub_acquisition.resolve.identity import entity_id, slugify


def test_slugify() -> None:
    assert slugify("Combat Patrol: Necrons") == "combat-patrol-necrons"
    assert slugify("Adrax Agatone") == "adrax-agatone"
    assert slugify("Tau'nar  Supremacy Suit!") == "tau-nar-supremacy-suit"
    assert slugify("Éléments — Terrain") == "elements-terrain"


def test_entity_id_prefers_code() -> None:
    assert entity_id("games-workshop", "99120110077", "Combat Patrol: Necrons") == "games-workshop/99120110077"


def test_entity_id_falls_back_to_name_slug() -> None:
    assert entity_id("cmon", None, "Zombicide: Black Plague") == "cmon/zombicide-black-plague"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_identity.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# tools/acquisition/src/warhub_acquisition/resolve/__init__.py
```

```python
# tools/acquisition/src/warhub_acquisition/resolve/identity.py
"""Canonical entity identity: manufacturer/productCode, else manufacturer/name-slug."""
import re
import unicodedata


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.casefold())
    return slug.strip("-")


def entity_id(manufacturer: str, code: str | None, name: str) -> str:
    return f"{manufacturer}/{code if code else slugify(name)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_identity.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/resolve tools/acquisition/tests/test_identity.py
git commit -m "feat(acquisition): entity identity derivation (code-first, slug fallback)"
```

---

### Task 7: Entity join (deterministic union-find + matches.yaml)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/resolve/join.py`
- Test: `tools/acquisition/tests/test_join.py`

**Interfaces:**
- Consumes: `Observation`, `Taxonomy`, `KIND_PRIORITY`, `canonical_ean`, `entity_id`, `slugify`.
- Produces:
  - `Matches` (pydantic): `joins: dict[str, str] = {}` (observation key → entity id), `aliases: dict[str, str] = {}` (old entity id → surviving entity id). Loaded from `matches.yaml` by the resolver (Task 10).
  - `JoinResult` (dataclass): `entities: dict[str, list[Observation]]` (entity id → observations, both deterministically sorted), `ambiguous: list[dict]` (conflict payloads for review).
  - `join_observations(observations: list[Observation], taxonomy: Taxonomy, kinds: dict[str, str], matches: Matches) -> JoinResult` where `kinds` maps source id → descriptor kind.
  - Join rules, strongest first: shared `(manufacturer, normalized code)` → same entity; shared validated EAN → same entity; `matches.joins` forces an observation into a named entity. Name-only observations (no code, no valid EAN) attach to an existing same-manufacturer entity when exactly one has the same name slug; if several match, the observation forms its own slug entity and an `ambiguous-join` payload is emitted. Observations without a manufacturer are skipped with an `unattributed` payload. Observations with no code/EAN/forced-join and an empty name slug are excluded and reported as `degenerate-name` payloads.
  - Entity id: from the group's best code — priority (KIND_PRIORITY of source kind, source id, code), i.e. manufacturer-kind sources win; else the best name slug by the same priority. `matches.aliases` remaps any resulting id.
  - If two distinct union-find components resolve to the same final entity id (an alias collapsing two coded groups, or two anchorless groups sharing a manufacturer+name-slug that name-join never merges on its own since it only joins anchorless observations *into* coded groups), their member lists are merged into one entity rather than one silently overwriting the other.
  - `matches.joins` entries that never resolve to their target (typo/stale target, or a target that no group's provisional id ever matches) do not silently no-op: the entry is reported in `result.ambiguous` as `{"type": "unresolved-forced-join", "key": ..., "target": ...}`, and — unlike a resolved forced join — an unresolved one no longer suppresses the name-join fallback for that observation's group.
  - Forced-join targets in `matches.joins` are resolved through `matches.aliases` before matching (a target written as an old id follows the alias like any other id) and applied as a fixpoint over `sorted` entries — re-deriving groups/provisional ids after each successful union — so chained forced joins resolve regardless of entry order, bounded by `len(entries) + 1` passes.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_join.py
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.join import Matches, join_observations
from warhub_acquisition.taxonomy import Manufacturer, Taxonomy

TAXONOMY = Taxonomy(
    {
        "games-workshop": Manufacturer(
            slug="games-workshop", name="Games Workshop", codePattern=r"\d{11}", codeStrip=["GWS"]
        )
    }
)
KINDS = {"mfr-gw": "manufacturer", "ret-goblin": "retailer", "ret-radaddel": "retailer"}


def obs(key: str, **kw: object) -> Observation:
    base: dict[str, object] = {
        "key": key,
        "name": "Combat Patrol: Necrons",
        "manufacturer": "games-workshop",
        "firstSeen": "2026-07-12",
        "lastSeen": "2026-07-12",
        "extractor": "test@1",
    }
    base.update(kw)
    return Observation(**base)


def test_join_by_normalized_code() -> None:
    result = join_observations(
        [obs("mfr-gw:necrons", sku="99120110077"), obs("ret-goblin:cp-necrons", sku="GWS99120110077")],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]
    assert len(result.entities["games-workshop/99120110077"]) == 2


def test_join_by_ean_without_code() -> None:
    result = join_observations(
        [
            obs("mfr-gw:necrons", sku="99120110077", ean="5011921194285"),
            obs("ret-radaddel:necrons-combat-patrol", name="Necrons Combat Patrol", ean="5011921194285"),
        ],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]


def test_name_join_when_unambiguous() -> None:
    result = join_observations(
        [obs("mfr-gw:necrons", sku="99120110077"), obs("ret-goblin:x", sku=None)],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]


def test_name_join_ambiguous_stays_separate_and_reported() -> None:
    result = join_observations(
        [
            obs("mfr-gw:a", sku="99120110077"),
            obs("mfr-gw:b", sku="99120110078"),  # two entities, same name
            obs("ret-goblin:x", sku=None),
        ],
        TAXONOMY, KINDS, Matches(),
    )
    assert "games-workshop/combat-patrol-necrons" in result.entities
    assert result.ambiguous and result.ambiguous[0]["type"] == "ambiguous-join"


def test_matches_joins_force_assignment() -> None:
    matches = Matches(joins={"ret-goblin:x": "games-workshop/99120110077"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("mfr-gw:b", sku="99120110078"), obs("ret-goblin:x", sku=None)],
        TAXONOMY, KINDS, matches,
    )
    assert len(result.entities["games-workshop/99120110077"]) == 2
    assert not result.ambiguous


def test_alias_remaps_entity_id() -> None:
    matches = Matches(aliases={"games-workshop/combat-patrol-necrons": "games-workshop/99120110077"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("ret-goblin:x", sku=None, name="Combat patrol: necrons (NEW)")],
        TAXONOMY, KINDS, matches,
    )
    # slug differs -> own entity "...-new"; alias only remaps exact ids
    assert "games-workshop/combat-patrol-necrons-new" in result.entities


def test_deterministic_ordering() -> None:
    observations = [obs("ret-goblin:b", sku="99120110078"), obs("mfr-gw:a", sku="99120110077")]
    first = join_observations(list(observations), TAXONOMY, KINDS, Matches())
    second = join_observations(list(reversed(observations)), TAXONOMY, KINDS, Matches())
    assert list(first.entities) == list(second.entities) == [
        "games-workshop/99120110077",
        "games-workshop/99120110078",
    ]


def test_degenerate_name_is_excluded_and_reported() -> None:
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("ret-goblin:x", sku=None, name="!!!")],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]
    assert {"type": "degenerate-name", "key": "ret-goblin:x", "name": "!!!"} in result.ambiguous


def test_same_slug_anchorless_groups_merge() -> None:
    result = join_observations(
        [obs("ret-goblin:x", sku=None), obs("ret-radaddel:y", sku=None)],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/combat-patrol-necrons"]
    assert [m.key for m in result.entities["games-workshop/combat-patrol-necrons"]] == ["ret-goblin:x", "ret-radaddel:y"]
    assert result.ambiguous == []


def test_alias_merge_combines_observations() -> None:
    matches = Matches(aliases={"games-workshop/99120110078": "games-workshop/99120110077"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("mfr-gw:b", sku="99120110078", name="Other Name")],
        TAXONOMY, KINDS, matches,
    )
    assert list(result.entities) == ["games-workshop/99120110077"]
    assert sorted(m.key for m in result.entities["games-workshop/99120110077"]) == ["mfr-gw:a", "mfr-gw:b"]


def test_unresolved_forced_join_reported_and_name_join_falls_back() -> None:
    matches = Matches(joins={"ret-goblin:x": "games-workshop/nonexistent"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("ret-goblin:x", sku=None)],
        TAXONOMY, KINDS, matches,
    )
    assert list(result.entities) == ["games-workshop/99120110077"]  # name-join still works
    assert {"type": "unresolved-forced-join", "key": "ret-goblin:x", "target": "games-workshop/nonexistent"} in result.ambiguous


def test_forced_join_target_resolved_through_alias() -> None:
    matches = Matches(
        joins={"ret-goblin:x": "games-workshop/old-id"},
        aliases={"games-workshop/old-id": "games-workshop/99120110077"},
    )
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("mfr-gw:b", sku="99120110078"), obs("ret-goblin:x", sku=None)],
        TAXONOMY, KINDS, matches,
    )
    assert sorted(m.key for m in result.entities["games-workshop/99120110077"]) == ["mfr-gw:a", "ret-goblin:x"]
    assert result.ambiguous == []


def test_degenerate_name_forced_join_still_works() -> None:
    matches = Matches(joins={"ret-goblin:x": "games-workshop/99120110077"})
    result = join_observations(
        [obs("mfr-gw:a", sku="99120110077"), obs("ret-goblin:x", sku=None, name="!!!")],
        TAXONOMY, KINDS, matches,
    )
    assert [m.key for m in result.entities["games-workshop/99120110077"]] == ["mfr-gw:a", "ret-goblin:x"]
    assert result.ambiguous == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_join.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# tools/acquisition/src/warhub_acquisition/resolve/join.py
"""Deterministic entity resolution: group observations via union-find."""
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.models.descriptor import KIND_PRIORITY
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.identity import entity_id, slugify
from warhub_acquisition.taxonomy import Taxonomy


class Matches(BaseModel):
    model_config = ConfigDict(extra="forbid")
    joins: dict[str, str] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)


@dataclass
class JoinResult:
    entities: dict[str, list[Observation]] = field(default_factory=dict)
    ambiguous: list[dict] = field(default_factory=list)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)  # deterministic root choice


def _priority(observation: Observation, kinds: dict[str, str]) -> tuple[int, str]:
    return (KIND_PRIORITY.get(kinds.get(observation.source_id, "barcode-db"), 9), observation.key)


def join_observations(
    observations: list[Observation],
    taxonomy: Taxonomy,
    kinds: dict[str, str],
    matches: Matches,
) -> JoinResult:
    result = JoinResult()
    ordered = sorted(observations, key=lambda o: _priority(o, kinds))

    # classify: unattributed (no manufacturer), degenerate (no code/EAN/forced-join and empty
    # name slug -- would otherwise form a bogus "manufacturer/" entity), else attributed.
    attributed: list[Observation] = []
    codes: dict[str, str | None] = {}
    eans: dict[str, str | None] = {}
    for observation in ordered:
        if not observation.manufacturer:
            result.ambiguous.append({"type": "unattributed", "key": observation.key, "name": observation.name})
            continue
        code = taxonomy.normalize_code(observation.manufacturer, observation.sku)
        ean = canonical_ean(observation.ean)
        forced = matches.joins.get(observation.key)
        if code is None and ean is None and not forced and slugify(observation.name) == "":
            result.ambiguous.append(
                {"type": "degenerate-name", "key": observation.key, "name": observation.name}
            )
            continue
        codes[observation.key] = code
        eans[observation.key] = ean
        attributed.append(observation)

    uf = _UnionFind()
    code_index: dict[tuple[str, str], str] = {}
    ean_index: dict[str, str] = {}
    for observation in attributed:
        code = codes[observation.key]
        ean = eans[observation.key]
        if code is not None:
            anchor = code_index.setdefault((observation.manufacturer, code), observation.key)
            uf.union(anchor, observation.key)
        if ean is not None:
            anchor = ean_index.setdefault(ean, observation.key)
            uf.union(anchor, observation.key)

    # provisional entity id per group
    def group_entity_id(members: list[Observation]) -> str:
        best_code = min(
            (
                (_priority(m, kinds), codes[m.key])
                for m in members
                if codes[m.key] is not None
            ),
            default=None,
        )
        anchor = min(members, key=lambda m: _priority(m, kinds))
        raw = entity_id(anchor.manufacturer, best_code[1] if best_code else None, anchor.name)
        return matches.aliases.get(raw, raw)

    def current_groups_and_ids() -> tuple[dict[str, list[Observation]], dict[str, str]]:
        current: dict[str, list[Observation]] = {}
        for observation in attributed:
            current.setdefault(uf.find(observation.key), []).append(observation)
        return current, {root: group_entity_id(members) for root, members in current.items()}

    # forced joins from matches.yaml: resolve targets through aliases (targets written as old
    # ids follow the alias like everything else), then apply as a fixpoint -- unioning a forced
    # key's group into whichever group currently carries the resolved target id, recomputing
    # groups/provisional ids after each successful union so chained forced joins (where one
    # union changes another group's provisional id) still resolve. Bounded by len(entries) + 1
    # full passes.
    attributed_keys = {observation.key for observation in attributed}
    forced_entries = sorted(
        (key, target) for key, target in matches.joins.items() if key in attributed_keys
    )

    groups, provisional = current_groups_and_ids()
    for _ in range(len(forced_entries) + 1):
        pass_changed = False
        for key, target in forced_entries:
            resolved_target = matches.aliases.get(target, target)
            root = uf.find(key)
            if provisional.get(root) == resolved_target:
                continue
            match_root = next(
                (
                    other_root
                    for other_root, eid in sorted(provisional.items())
                    if eid == resolved_target and other_root != root
                ),
                None,
            )
            if match_root is not None:
                uf.union(root, match_root)
                pass_changed = True
                groups, provisional = current_groups_and_ids()
        if not pass_changed:
            break

    # a forced join has "resolved" once its observation's group carries the (alias-resolved)
    # target id -- record which group roots that applies to, so the name-join pass below only
    # skips groups whose forced join actually took effect (an unresolved forced join must not
    # suppress the name-join fallback).
    resolved_forced_roots: set[str] = set()
    for key, target in forced_entries:
        resolved_target = matches.aliases.get(target, target)
        root = uf.find(key)
        if provisional.get(root) == resolved_target:
            resolved_forced_roots.add(root)

    # name-join pass for anchorless observations (no code, no valid EAN, no resolved forced join)
    slug_index: dict[tuple[str, str], list[str]] = {}
    for root, members in groups.items():
        if any(codes[m.key] is not None for m in members):
            for slug in sorted({slugify(m.name) for m in members}):
                slug_index.setdefault((members[0].manufacturer, slug), []).append(root)

    for root, members in sorted(groups.items()):
        if any(codes[m.key] is not None or eans[m.key] is not None for m in members):
            continue
        if root in resolved_forced_roots:
            continue
        candidates = sorted(
            {r for m in members for r in slug_index.get((m.manufacturer, slugify(m.name)), [])}
        )
        if len(candidates) == 1:
            uf.union(candidates[0], root)
        elif len(candidates) > 1:
            result.ambiguous.append(
                {
                    "type": "ambiguous-join",
                    "keys": sorted(m.key for m in members),
                    "name": members[0].name,
                    "candidates": sorted(provisional[c] for c in candidates),
                }
            )

    # final grouping + ids -- distinct union-find components can still resolve to the same
    # final id (alias collapsing two coded groups, or two anchorless groups sharing a
    # manufacturer+name-slug that name-join never merges since it only joins anchorless INTO
    # coded groups). Merge member lists on collision instead of silently dropping one group.
    final_groups: dict[str, list[Observation]] = {}
    for observation in attributed:
        final_groups.setdefault(uf.find(observation.key), []).append(observation)
    entities: dict[str, list[Observation]] = {}
    for members in final_groups.values():
        entities.setdefault(group_entity_id(members), []).extend(members)
    for members in entities.values():
        members.sort(key=lambda m: _priority(m, kinds))
    result.entities = dict(sorted(entities.items()))

    # report matches.joins entries that never resolved: the observation exists but did not end
    # up in an entity whose id equals the (alias-resolved) target.
    observation_by_key = {observation.key: observation for observation in observations}
    key_to_entity = {
        member.key: eid for eid, members in result.entities.items() for member in members
    }
    for key, target in sorted(matches.joins.items()):
        if key not in observation_by_key:
            continue
        resolved_target = matches.aliases.get(target, target)
        if key_to_entity.get(key) != resolved_target:
            result.ambiguous.append({"type": "unresolved-forced-join", "key": key, "target": target})

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_join.py -v`
Expected: all PASS. If `test_deterministic_ordering` flakes, the bug is a nondeterministic iteration — every loop in `join_observations` must iterate a `sorted(...)` view.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/resolve/join.py tools/acquisition/tests/test_join.py
git commit -m "feat(acquisition): deterministic entity join with manual match overrides"
```

---

### Task 8: EAN corroboration

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/resolve/corroborate.py`
- Test: `tools/acquisition/tests/test_corroborate.py`

**Interfaces:**
- Consumes: `Observation`, `KIND_PRIORITY`, `canonical_ean`.
- Produces:
  - `EanResolution` (dataclass): `ean: str | None`, `confidence: str | None` (`"confirmed" | "provisional" | "conflicted"`), `conflicts: list[dict]`.
  - `resolve_ean(entity: str, members: list[Observation], kinds: dict[str, str]) -> EanResolution`.
  - Rules: collect `(source_id, kind, canonical_ean)` assertions, dedupe by source id (a source asserts one EAN per observation set — if one source asserts two different EANs for the entity, that's a conflict too). `confirmed` = any manufacturer/curated-kind assertion OR ≥2 distinct non-barcode-db sources agreeing. `provisional` = exactly one non-barcode-db assertion, or barcode-db-only assertions. Distinct EAN values → `conflicted`: pick the value with (best kind priority, most asserting sources, lexicographic) and emit an `ean-mismatch` conflict payload listing all assertions.
  - `find_shared_eans(resolutions: dict[str, EanResolution]) -> list[dict]` — same EAN resolved on ≥2 entities → `ean-shared` conflict payloads.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_corroborate.py
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.corroborate import EanResolution, find_shared_eans, resolve_ean

KINDS = {"mfr-w": "manufacturer", "ret-a": "retailer", "ret-b": "retailer", "db-upc": "barcode-db"}


def obs(key: str, ean: str | None) -> Observation:
    return Observation(
        key=key, name="X", manufacturer="warlord-games",
        firstSeen="2026-07-12", lastSeen="2026-07-12", extractor="t@1", ean=ean,
    )


def test_manufacturer_assertion_confirms() -> None:
    resolution = resolve_ean("e", [obs("mfr-w:1", "5060393709671")], KINDS)
    assert resolution.ean == "5060393709671"
    assert resolution.confidence == "confirmed"


def test_two_retailers_confirm() -> None:
    resolution = resolve_ean("e", [obs("ret-a:1", "5060393709671"), obs("ret-b:1", "5060393709671")], KINDS)
    assert resolution.confidence == "confirmed"


def test_single_retailer_is_provisional() -> None:
    assert resolve_ean("e", [obs("ret-a:1", "5060393709671")], KINDS).confidence == "provisional"


def test_barcode_db_alone_never_confirms() -> None:
    resolution = resolve_ean("e", [obs("db-upc:1", "5060393709671")], KINDS)
    assert resolution.confidence == "provisional"
    resolution = resolve_ean("e", [obs("db-upc:1", "5060393709671"), obs("ret-a:1", "5060393709671")], KINDS)
    assert resolution.confidence == "confirmed"  # db + retailer = two independent sources


def test_invalid_ean_ignored() -> None:
    resolution = resolve_ean("e", [obs("ret-a:1", "5011921194286")], KINDS)  # bad checksum
    assert resolution.ean is None
    assert resolution.confidence is None


def test_mismatch_is_conflicted_and_reported() -> None:
    resolution = resolve_ean(
        "e", [obs("mfr-w:1", "5060393709671"), obs("ret-a:1", "5011921194285")], KINDS
    )
    assert resolution.confidence == "conflicted"
    assert resolution.ean == "5060393709671"  # manufacturer kind wins
    assert resolution.conflicts[0]["type"] == "ean-mismatch"


def test_shared_ean_across_entities_reported() -> None:
    resolutions = {
        "a": EanResolution("5060393709671", "confirmed", []),
        "b": EanResolution("5060393709671", "provisional", []),
        "c": EanResolution(None, None, []),
    }
    shared = find_shared_eans(resolutions)
    assert shared == [
        {"type": "ean-shared", "ean": "5060393709671", "entities": ["a", "b"]}
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_corroborate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# tools/acquisition/src/warhub_acquisition/resolve/corroborate.py
"""EAN corroboration: confidence from independent source agreement."""
from dataclasses import dataclass

from warhub_acquisition.ean import canonical_ean
from warhub_acquisition.models.descriptor import KIND_PRIORITY
from warhub_acquisition.models.observation import Observation


@dataclass
class EanResolution:
    ean: str | None
    confidence: str | None
    conflicts: list[dict]


def resolve_ean(entity: str, members: list[Observation], kinds: dict[str, str]) -> EanResolution:
    assertions: dict[str, dict[str, str]] = {}  # ean -> {source_id: kind}
    for member in members:
        ean = canonical_ean(member.ean)
        if ean is None:
            continue
        kind = kinds.get(member.source_id, "barcode-db")
        assertions.setdefault(ean, {})[member.source_id] = kind

    if not assertions:
        return EanResolution(None, None, [])

    def strength(item: tuple[str, dict[str, str]]) -> tuple[int, int, str]:
        ean, sources = item
        best_kind = min(KIND_PRIORITY.get(kind, 9) for kind in sources.values())
        return (best_kind, -len(sources), ean)

    ranked = sorted(assertions.items(), key=strength)
    ean, sources = ranked[0]
    trusted = {sid for sid, kind in sources.items() if kind != "barcode-db"}
    has_authoritative = any(kind in ("manufacturer", "curated") for kind in sources.values())
    if has_authoritative or len(sources) >= 2 and len(trusted) >= 1:
        confidence = "confirmed"
    else:
        confidence = "provisional"

    conflicts: list[dict] = []
    if len(assertions) > 1:
        confidence = "conflicted"
        conflicts.append(
            {
                "type": "ean-mismatch",
                "entity": entity,
                "chosen": ean,
                "assertions": [
                    {"ean": e, "sources": sorted(s)} for e, s in sorted(assertions.items())
                ],
            }
        )
    return EanResolution(ean, confidence, conflicts)


def find_shared_eans(resolutions: dict[str, EanResolution]) -> list[dict]:
    by_ean: dict[str, list[str]] = {}
    for entity, resolution in sorted(resolutions.items()):
        if resolution.ean is not None:
            by_ean.setdefault(resolution.ean, []).append(entity)
    return [
        {"type": "ean-shared", "ean": ean, "entities": entities}
        for ean, entities in sorted(by_ean.items())
        if len(entities) > 1
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_corroborate.py -v`
Expected: all PASS. Note the confirm rule reading: authoritative (manufacturer/curated) assertion confirms alone; otherwise ≥2 sources where at least one is not a barcode DB.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/resolve/corroborate.py tools/acquisition/tests/test_corroborate.py
git commit -m "feat(acquisition): EAN corroboration with confidence and conflict surfacing"
```

---

### Task 9: Attribute resolution, lifecycle, overrides & durable retract

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/resolve/attributes.py`
- Create: `tools/acquisition/src/warhub_acquisition/models/catalog.py`
- Test: `tools/acquisition/tests/test_attributes.py`

**Interfaces:**
- Consumes: `Observation`, `KIND_PRIORITY`, `EanResolution`.
- Produces:
  - `CanonicalProduct` (pydantic), field declaration order = YAML emission order:
    `id, name, manufacturer, productCode, ean, eanConfidence, gameSystem, faction, category, packaging, quantity, status, availability, firstSeen, priceGbp, priceUsd, priceEur, url, imageUrl, description, evidence` (`evidence: list[str]` sorted; all optionals `None`-able except `id`, `name`, `manufacturer`, `status`, `firstSeen`, `evidence`).
  - `Overrides` (pydantic): `retract: list[str] = []` (entity ids), `products: dict[str, dict[str, object]] = {}` (entity id → field overrides).
  - `resolve_attributes(entity: str, members: list[Observation], kinds: dict[str, str], ean: EanResolution, code: str | None, miss_threshold: int = 3) -> CanonicalProduct`:
    - Field precedence: first non-`None` value walking members in their (already sorted) kind-priority order — for `name, availability, url, imageUrl, priceGbp/Usd/Eur, description`(from `hints["description"]`), `gameSystem`/`faction`/`category`/`packaging`/`quantity` (from `hints` of the same names).
    - `category` defaults to `"miniatures"` when no hint supplies it.
    - `firstSeen` = min over members; `evidence` = sorted member keys.
    - Lifecycle: live members = `archived == False`; scraped-live additionally excludes curated-kind sources (curated observations are never re-scraped, so they never participate in miss-streak logic). No live members → `status="discontinued"`. No scraped-live members (curated-only entity) → trust the curated `hints["status"]` claim, defaulting to `"current"`. Any scraped-live member with `missStreak < miss_threshold` → `"current"`; otherwise `"suspected-discontinued"` and `availability="unknown"`. Finally, a curated `discontinued`/`delisted` hint always wins over derivation (a curated `current` does not resurrect a live-source `suspected-discontinued`).
  - `apply_overrides(product: CanonicalProduct, overrides: Overrides) -> CanonicalProduct` — per-field replacement (validated by pydantic).
  - Retract is enforced by the resolver (Task 10): retracted entity ids are dropped after join, and alias targets pointing at retracted ids raise `ValueError`.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_attributes.py
from warhub_acquisition.models.catalog import CanonicalProduct, Overrides
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.attributes import apply_overrides, resolve_attributes
from warhub_acquisition.resolve.corroborate import EanResolution

KINDS = {"legacy-catalog": "curated", "mfr-gw": "manufacturer", "ret-a": "retailer", "arc-x": "archive"}
NO_EAN = EanResolution(None, None, [])


def obs(key: str, **kw: object) -> Observation:
    base: dict[str, object] = {
        "key": key, "name": "Combat Patrol: Necrons", "manufacturer": "games-workshop",
        "firstSeen": "2026-07-12", "lastSeen": "2026-07-12", "extractor": "t@1",
    }
    base.update(kw)
    return Observation(**base)


def members_sorted() -> list[Observation]:
    return [
        obs("mfr-gw:necrons", priceGbp=76.5, url="https://gw/necrons", hints={"gameSystem": "warhammer-40k", "faction": "necrons"}),
        obs("ret-a:necrons", name="Necrons Combat Patrol (GW)", priceGbp=65.0, imageUrl="https://ret/img.jpg"),
    ]


def test_precedence_prefers_manufacturer_then_backfills() -> None:
    product = resolve_attributes("games-workshop/99120110077", members_sorted(), KINDS, NO_EAN, "99120110077")
    assert product.name == "Combat Patrol: Necrons"     # manufacturer wins
    assert product.priceGbp == 76.5
    assert product.imageUrl == "https://ret/img.jpg"     # retailer backfills gaps
    assert product.gameSystem == "warhammer-40k"
    assert product.category == "miniatures"              # default
    assert product.evidence == ["mfr-gw:necrons", "ret-a:necrons"]


def test_lifecycle_current_when_any_live_source_sees_it() -> None:
    product = resolve_attributes("e", [obs("mfr-gw:a", missStreak=0)], KINDS, NO_EAN, None)
    assert product.status == "current"


def test_lifecycle_suspected_when_all_live_sources_miss() -> None:
    product = resolve_attributes("e", [obs("mfr-gw:a", missStreak=3), obs("ret-a:b", missStreak=4)], KINDS, NO_EAN, None)
    assert product.status == "suspected-discontinued"
    assert product.availability == "unknown"


def test_lifecycle_discontinued_when_archive_only() -> None:
    product = resolve_attributes("e", [obs("arc-x:a", archived=True)], KINDS, NO_EAN, None)
    assert product.status == "discontinued"


def test_curated_discontinued_hint_wins() -> None:
    members = [obs("legacy-catalog:a", hints={"status": "delisted"}), obs("mfr-gw:b", missStreak=0)]
    product = resolve_attributes("e", members, KINDS, NO_EAN, None)
    assert product.status == "delisted"


def test_curated_only_entity_trusts_curated_status() -> None:
    # legacy-only products (post-migration) keep their archived status; they are
    # never miss-flagged because no live scraped source covers them
    product = resolve_attributes("e", [obs("legacy-catalog:a", hints={"status": "current"})], KINDS, NO_EAN, None)
    assert product.status == "current"
    product = resolve_attributes("e", [obs("legacy-catalog:a")], KINDS, NO_EAN, None)
    assert product.status == "current"
    product = resolve_attributes("e", [obs("legacy-catalog:a", hints={"status": "suspected-discontinued"})], KINDS, NO_EAN, None)
    assert product.status == "suspected-discontinued"


def test_apply_overrides_replaces_fields() -> None:
    product = resolve_attributes("e", members_sorted(), KINDS, NO_EAN, None)
    overridden = apply_overrides(product, Overrides(products={"e": {"faction": "necrons-fixed", "quantity": 11}}))
    assert overridden.faction == "necrons-fixed"
    assert overridden.quantity == 11
    untouched = apply_overrides(product, Overrides())
    assert untouched == product
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_attributes.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# tools/acquisition/src/warhub_acquisition/models/catalog.py
"""Canonical catalog records and human overrides."""
from pydantic import BaseModel, ConfigDict, Field


class CanonicalProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    manufacturer: str
    productCode: str | None = None
    ean: str | None = None
    eanConfidence: str | None = None
    gameSystem: str | None = None
    faction: str | None = None
    category: str | None = None
    packaging: str | None = None
    quantity: int | None = None
    status: str
    availability: str | None = None
    firstSeen: str
    priceGbp: float | None = None
    priceUsd: float | None = None
    priceEur: float | None = None
    url: str | None = None
    imageUrl: str | None = None
    description: str | None = None
    evidence: list[str] = Field(default_factory=list)


class Overrides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retract: list[str] = Field(default_factory=list)
    products: dict[str, dict[str, object]] = Field(default_factory=dict)
```

```python
# tools/acquisition/src/warhub_acquisition/resolve/attributes.py
"""Fold an entity's observations into one canonical record; derive lifecycle."""
from warhub_acquisition.models.catalog import CanonicalProduct, Overrides
from warhub_acquisition.models.observation import Observation
from warhub_acquisition.resolve.corroborate import EanResolution

_HINT_FIELDS = ("gameSystem", "faction", "category", "packaging", "quantity", "description")
_DIRECT_FIELDS = ("name", "availability", "url", "imageUrl", "priceGbp", "priceUsd", "priceEur")


def _first(values: list[object | None]) -> object | None:
    return next((value for value in values if value is not None), None)


def resolve_attributes(
    entity: str,
    members: list[Observation],
    kinds: dict[str, str],
    ean: EanResolution,
    code: str | None,
    miss_threshold: int = 3,
) -> CanonicalProduct:
    fields: dict[str, object] = {}
    for name in _DIRECT_FIELDS:
        fields[name] = _first([getattr(member, name) for member in members])
    for name in _HINT_FIELDS:
        fields[name] = _first([member.hints.get(name) for member in members])
    fields.setdefault("category", None)
    if fields["category"] is None:
        fields["category"] = "miniatures"

    curated_status = _first(
        [member.hints.get("status") for member in members if kinds.get(member.source_id) == "curated"]
    )
    live = [member for member in members if not member.archived]
    scraped_live = [member for member in live if kinds.get(member.source_id) != "curated"]
    if not live:
        status = "discontinued"
    elif not scraped_live:
        # curated-only entity (e.g. legacy import not yet re-observed live):
        # trust the curated claim; curated sources are never miss-flagged
        status = str(curated_status) if curated_status else "current"
    elif any(member.missStreak < miss_threshold for member in scraped_live):
        status = "current"
    else:
        status = "suspected-discontinued"
        fields["availability"] = "unknown"
    if curated_status in ("discontinued", "delisted"):
        status = str(curated_status)  # explicit curated lifecycle always wins

    return CanonicalProduct(
        id=entity,
        manufacturer=members[0].manufacturer,
        productCode=code,
        ean=ean.ean,
        eanConfidence=ean.confidence,
        status=status,
        firstSeen=min(member.firstSeen for member in members),
        evidence=sorted(member.key for member in members),
        **fields,
    )


def apply_overrides(product: CanonicalProduct, overrides: Overrides) -> CanonicalProduct:
    patch = overrides.products.get(product.id)
    if not patch:
        return product
    return product.model_copy(update=dict(patch))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_attributes.py -v`
Expected: all PASS. Note the curated split: curated observations never participate in miss-streak derivation (they are not re-scraped, so their `missStreak` stays 0 forever) — when scraped sources exist they alone decide current/suspected, and when only curated sources cover the entity, the curated status claim is trusted as-is.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/models/catalog.py tools/acquisition/src/warhub_acquisition/resolve/attributes.py tools/acquisition/tests/test_attributes.py
git commit -m "feat(acquisition): attribute resolution, lifecycle derivation, overrides"
```

---

### Task 10: Resolver orchestration + catalog/conflict writers + golden test

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/resolve/resolver.py`
- Test: `tools/acquisition/tests/test_resolver.py`

**Interfaces:**
- Consumes: everything from Tasks 4–9.
- Produces:
  - `DataPaths` (dataclass): `root: Path` with properties `evidence_products` (`root/evidence/products`), `catalog_products` (`root/catalog/products`), `sources` (`root/catalog/sources`), `taxonomy` (`root/catalog/taxonomy`), `matches` (`root/catalog/matches.yaml`), `overrides` (`root/catalog/overrides.yaml`), `conflicts` (`root/review/conflicts.yaml`).
  - `resolve_catalog(paths: DataPaths) -> dict[str, list[CanonicalProduct]]` — loads everything, joins, corroborates, resolves attributes, applies overrides, drops retracted entities (and raises `ValueError` if `matches.aliases` targets a retracted id), writes one YAML file per manufacturer to `catalog/products/<manufacturer>.yaml` shaped `{manufacturer: <slug>, products: [...]}` (products sorted by id, `exclude_none` fields), writes `review/conflicts.yaml` shaped `{conflicts: [...]}` (deterministically sorted; empty list when clean), removes stale manufacturer files it no longer produces. Returns the catalog keyed by manufacturer slug.

- [ ] **Step 1: Write the failing test**

```python
# tools/acquisition/tests/test_resolver.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# tools/acquisition/src/warhub_acquisition/resolve/resolver.py
"""Pure resolver: evidence + taxonomy + matches + overrides -> canonical catalog."""
from dataclasses import dataclass
from pathlib import Path

from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.models.catalog import CanonicalProduct, Overrides
from warhub_acquisition.models.descriptor import load_descriptors
from warhub_acquisition.resolve.attributes import apply_overrides, resolve_attributes
from warhub_acquisition.resolve.corroborate import find_shared_eans, resolve_ean
from warhub_acquisition.resolve.join import Matches, join_observations
from warhub_acquisition.taxonomy import Taxonomy
from warhub_acquisition.yamlio import read_yaml, write_yaml


@dataclass
class DataPaths:
    root: Path

    @property
    def evidence_products(self) -> Path:
        return self.root / "evidence" / "products"

    @property
    def catalog_products(self) -> Path:
        return self.root / "catalog" / "products"

    @property
    def sources(self) -> Path:
        return self.root / "catalog" / "sources"

    @property
    def taxonomy(self) -> Path:
        return self.root / "catalog" / "taxonomy"

    @property
    def matches(self) -> Path:
        return self.root / "catalog" / "matches.yaml"

    @property
    def overrides(self) -> Path:
        return self.root / "catalog" / "overrides.yaml"

    @property
    def conflicts(self) -> Path:
        return self.root / "review" / "conflicts.yaml"


def _load_optional(path: Path, model: type, default: object) -> object:
    if path.exists():
        return model.model_validate(read_yaml(path))
    return default


def resolve_catalog(paths: DataPaths) -> dict[str, list[CanonicalProduct]]:
    taxonomy = Taxonomy.load(paths.taxonomy)
    descriptors = load_descriptors(paths.sources)
    kinds = {sid: descriptor.kind for sid, descriptor in descriptors.items()}
    matches: Matches = _load_optional(paths.matches, Matches, Matches())
    overrides: Overrides = _load_optional(paths.overrides, Overrides, Overrides())

    retracted = set(overrides.retract)
    for alias_target in matches.aliases.values():
        if alias_target in retracted:
            raise ValueError(f"matches.yaml alias targets retracted entity {alias_target!r}")

    observations = [
        observation
        for source in EvidenceStore(paths.evidence_products).load_all().values()
        for observation in source.values()
    ]
    joined = join_observations(observations, taxonomy, kinds, matches)

    conflicts: list[dict] = list(joined.ambiguous)
    ean_resolutions = {}
    products: dict[str, list[CanonicalProduct]] = {}
    for entity, members in joined.entities.items():
        if entity in retracted:
            continue
        ean = resolve_ean(entity, members, kinds)
        ean_resolutions[entity] = ean
        conflicts.extend(ean.conflicts)
        code = entity.split("/", 1)[1] if any(
            taxonomy.normalize_code(m.manufacturer, m.sku) == entity.split("/", 1)[1] for m in members
        ) else None
        product = apply_overrides(resolve_attributes(entity, members, kinds, ean, code), overrides)
        products.setdefault(product.manufacturer, []).append(product)

    conflicts.extend(find_shared_eans(ean_resolutions))

    paths.catalog_products.mkdir(parents=True, exist_ok=True)
    produced = set()
    for manufacturer in sorted(products):
        records = sorted(products[manufacturer], key=lambda p: p.id)
        write_yaml(
            paths.catalog_products / f"{manufacturer}.yaml",
            {
                "manufacturer": manufacturer,
                "products": [record.model_dump(mode="json", exclude_none=True) for record in records],
            },
        )
        produced.add(f"{manufacturer}.yaml")
    for stale in sorted(paths.catalog_products.glob("*.yaml")):
        if stale.name not in produced:
            stale.unlink()

    write_yaml(paths.conflicts, {"conflicts": sorted(conflicts, key=lambda c: str(sorted(c.items())))})
    return {manufacturer: sorted(records, key=lambda p: p.id) for manufacturer, records in sorted(products.items())}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_resolver.py -v`
Expected: all PASS. If the golden string mismatches on list indentation, adjust `EXPECTED_CATALOG` to PyYAML's actual 2-space-nested list style once — then it is pinned; the byte-determinism assertion is the invariant that matters.

Also run the full suite: `uv run pytest -v` — everything green.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/resolve/resolver.py tools/acquisition/tests/test_resolver.py
git commit -m "feat(acquisition): pure resolver with golden end-to-end test"
```

---

### Task 11: CLI (`resolve`, `report`)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/cli.py`
- Create: `tools/acquisition/src/warhub_acquisition/report.py`
- Test: `tools/acquisition/tests/test_cli.py`

**Interfaces:**
- Consumes: `resolve_catalog`, `DataPaths`, `EvidenceStore`.
- Produces:
  - `warhub-data resolve --data <dir>` — runs `resolve_catalog`, prints `resolved N products across M manufacturers; K conflicts`, exit 0 (exit 2 when conflicts exist — loud but distinguishable from crash).
  - `warhub-data report --data <dir>` — prints a markdown coverage report: per manufacturer `products / with EAN / % / confirmed %`, plus per-source observation counts; pure read, exit 0.
  - `build_report(paths: DataPaths) -> str` in `report.py` (reused by Plan 3's PR-body generation).
  - `main(argv: list[str] | None = None) -> int` argparse entry point wired to the `warhub-data` console script.

- [ ] **Step 1: Write the failing tests**

```python
# tools/acquisition/tests/test_cli.py
from pathlib import Path

from warhub_acquisition.cli import main
from test_resolver import seed  # reuse the fixture builder


def test_resolve_command(tmp_path: Path, capsys) -> None:
    seed(tmp_path)
    exit_code = main(["resolve", "--data", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "resolved 1 products across 1 manufacturers; 0 conflicts" in out
    assert (tmp_path / "catalog" / "products" / "games-workshop.yaml").exists()


def test_report_command(tmp_path: Path, capsys) -> None:
    seed(tmp_path)
    main(["resolve", "--data", str(tmp_path)])
    exit_code = main(["report", "--data", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "| games-workshop | 1 | 1 | 100.0% | 0.0% |" in out
    assert "mfr-gw: 1" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError` (cli module doesn't exist)

- [ ] **Step 3: Write the implementation**

```python
# tools/acquisition/src/warhub_acquisition/report.py
"""Coverage and per-source health report (markdown)."""
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import read_yaml


def build_report(paths: DataPaths) -> str:
    lines = ["## Catalog coverage", "", "| manufacturer | products | with EAN | EAN % | confirmed % |", "|---|---|---|---|---|"]
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        data = read_yaml(path)
        products = data["products"]
        with_ean = [p for p in products if p.get("ean")]
        confirmed = [p for p in with_ean if p.get("eanConfidence") == "confirmed"]
        total = len(products)
        lines.append(
            f"| {data['manufacturer']} | {total} | {len(with_ean)} "
            f"| {100 * len(with_ean) / total:.1f}% | {100 * len(confirmed) / total:.1f}% |"
        )
    lines += ["", "## Evidence sources", ""]
    for source_id, observations in EvidenceStore(paths.evidence_products).load_all().items():
        lines.append(f"- {source_id}: {len(observations)} observations")
    return "\n".join(lines) + "\n"
```

```python
# tools/acquisition/src/warhub_acquisition/cli.py
"""warhub-data CLI: resolve and report (acquire/migrate arrive in later plans)."""
import argparse
from pathlib import Path

from warhub_acquisition.report import build_report
from warhub_acquisition.resolve.resolver import DataPaths, resolve_catalog
from warhub_acquisition.yamlio import read_yaml


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="warhub-data")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("resolve", "report"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    paths = DataPaths(args.data)

    if args.command == "resolve":
        catalog = resolve_catalog(paths)
        total = sum(len(records) for records in catalog.values())
        conflicts = read_yaml(paths.conflicts)["conflicts"]
        print(f"resolved {total} products across {len(catalog)} manufacturers; {len(conflicts)} conflicts")
        return 2 if conflicts else 0

    print(build_report(paths), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v` (full suite)
Expected: all PASS. Also sanity-check the console script wiring: `uv run warhub-data resolve --data ../../data` will fail (no `data/evidence` yet — that's Plan 2's migration); `uv run warhub-data --help` prints usage.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition/src/warhub_acquisition/cli.py tools/acquisition/src/warhub_acquisition/report.py tools/acquisition/tests/test_cli.py
git commit -m "feat(acquisition): warhub-data CLI with resolve and report commands"
```

---

## Follow-on plans (not in this document)

- **Plan 2 — Legacy migration + publisher adaptation:** `migrate` verb (legacy faction YAML → `legacy-catalog` evidence + seed conversion + taxonomy enrichment from `ManufacturerRegistry`), parity checks (counts, EANs, identities), .NET publisher reads `data/catalog/`.
- **Plan 3 — Live source framework + v1 roster:** fetch strategies (shopify, woo-store-api, algolia, appsync, playwright, sitemap+structured-data), politeness/budgets/cursors, contracts enforcement, `acquire` verb, health-report PR bodies.
- **Plan 4 — Archives + LLM:** cdx-archive strategy, LLM extraction/classification/adjudication with committed outputs.
- **Plan 5 — Paints + workflows + retirement:** paint sources + CIEDE2000 port, nightly/weekly GitHub workflows, .NET tool retirement.
