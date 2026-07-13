# Live Source Framework Implementation Plan (Plan 3 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the live acquisition layer — polite budgeted fetching, declarative per-source strategies with loud contracts, the `acquire` CLI verb, health reporting, and scheduled workflows — and run it for real: the Shopify per-product-page barcode harvest (Warlord Games' ~5.8k products first) is the headline EAN-coverage payoff this whole rewrite exists for.

**Architecture:** Per spec §6–7 (`docs/superpowers/specs/2026-07-12-data-acquisition-rewrite-design.md`) and the probe evidence in `docs/research/2026-07-12-*.md`. Each source = committed descriptor + strategy implementation + committed hint mappings. Acquisition upserts observations (append-only), updates cursors, enforces contracts loudly, and feeds the existing resolver untouched except for two hardening changes (cross-manufacturer EAN scoping; unclassified-entity parking). CMON/Playwright, web-archive mining, barcode DBs, and LLM extraction are Plan 4. Paints are Plan 5.

**Tech Stack:** Python (existing `tools/acquisition/`): httpx (new dependency) for HTTP with a fake-transport test seam; PyYAML/pydantic as before. C# only for Task 12's cross-stack fixture tests. GitHub Actions for scheduling.

## Global Constraints

- Determinism where it matters: evidence/catalog files stay byte-deterministic given identical inputs; acquisition takes `--run-date YYYY-MM-DD` (workflows pass `$(date -u +%F)`) — no wall-clock inside library code. Cursors record run dates, not timestamps.
- Politeness is enforced in ONE place (the client), driven by descriptor `politeness.rps`; default 0.5 rps; every request carries the UA `warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)`.
- Contracts are loud: a violated source contract raises `SourceContractError`; the CLI exits 4 for contract failures (distinct from 2=conflicts, 3=verify). A failed source NEVER deletes or decays evidence (append-only); it can only fail to refresh it.
- missStreak semantics: incremented ONLY by a full, contract-passing sweep of a source that didn't observe the key; budgeted/partial runs never increment; any run that observes a key resets its streak to 0. (This is the liveness engine — spec §5 lifecycle depends on it.)
- Confirmed-EAN protection: `report --ean-guard` compares the working-tree catalog against `git show HEAD:<file>` and lists every entity whose previously `confirmed` EAN changed value — exit 5 when any exist. Workflows run it so a silent replacement can never merge unnoticed.
- Retailer observations attribute manufacturers via `Taxonomy.manufacturer_for_vendor`; unmatched vendors are SKIPPED (retailers stock brands we don't track) but counted per-source in the health report.
- Every new observation field/hint arrives as slugs already mapped via committed per-source mapping files (`data/catalog/mappings/<source-id>.yaml`); unmapped raw values are recorded (health report) and the hint omitted, never guessed.
- Fixtures for extractors are REAL captured responses (trimmed), committed under `tools/acquisition/tests/fixtures/` — capture steps are part of the tasks; live smoke tests are opt-in (`-m live`, excluded by default addopts).
- All emitted text files UTF-8/LF/trailing newline; commit messages end with the repo's two trailer lines (Co-Authored-By + Claude-Session).
- Suites green after every task: `uv run pytest` (tools/acquisition) and `dotnet test WarHub.Catalog.slnx`.
- `uv` PATH note (Windows dev shells): `$env:Path = [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path`.

## Probe ground truth this plan is built on (2026-07-12, docs/research/)

- Shopify bulk `/products.json?limit=250&page=N` enumerates products (id, handle, title, vendor, product_type, tags, variants[].{sku,price,updated_at}) but `variants[].barcode` is ALWAYS null in bulk; the per-handle endpoint `/products/<handle>.js` returns `variants[].barcode` populated (confirmed: store.warlordgames.com, steamforged.com, giveusyourmoneypleasethankyou-wyrd.com, goblingaming.co.uk, tistaminis.com).
- Warlord store ≈5,843 products (3 sitemaps); Steamforged ≈1,062; Wyrd ≈707; Goblin ≈12–15k (GW-focused); Tistaminis large GW range.
- WooCommerce Store API `/wp-json/wc/store/products?per_page=100&page=N` with `X-WP-Total` header (Mantic ≈2,789, eshop.para-bellum.com 384); Mantic product PAGES carry JSON-LD `gtin`.
- GW: Algolia app `m5ziqznq2h`, index `prod-lazarus-product-en-gb` (the retired .NET tool's hard-coded search key works; port it), no EANs.
- Corvus Belli: AppSync GraphQL gateway, api key in store JS, `send` command payloads (port from retired .NET source).
- Miniaturicum (JTL): JSON-LD `gtin13` on product pages, sitemap ≈25k locs. Radaddel (Shopware 6): microdata `itemprop="gtin13"`, sitemap 12,806. Game Nerdz (BigCommerce): `BCData.product_attributes.upc` in page JS, `/xmlsitemap.php`.

---

### Task 1: Resolver hardening bundle (cross-manufacturer EANs, unclassified parking, report/verify fills)

**Files:**
- Modify: `tools/acquisition/src/warhub_acquisition/resolve/join.py`
- Modify: `tools/acquisition/src/warhub_acquisition/resolve/resolver.py`
- Modify: `tools/acquisition/src/warhub_acquisition/report.py`
- Test: `tools/acquisition/tests/test_join.py`, `tests/test_resolver.py`, `tests/test_report.py` (new), `tests/test_migrate_verify.py`, `tests/test_repo_data.py` (new)

**Interfaces:**
- Consumes: existing join/resolver/report internals.
- Produces:
  1. **EAN joins are manufacturer-scoped**: `ean_index` keys become `(manufacturer, ean)`; when the same validated EAN is asserted by observations of two DIFFERENT manufacturers, the observations are NOT unioned and `result.ambiguous` gains `{"type": "cross-manufacturer-ean", "ean": ..., "keys": [sorted keys]}`. Rationale (plan-authored deviation from the spec's literal "shared validated EAN → same entity"): GS1 EANs are manufacturer-scoped; a cross-manufacturer match is bad data to surface, not a merge instruction. `find_shared_eans` continues to catch same-EAN-two-entities within and across manufacturers at the resolution layer.
  2. **Unclassified-entity parking**: in `resolve_catalog`, an entity whose resolved `gameSystem` is None is EXCLUDED from the written catalog and `review/conflicts.yaml` gains `{"type": "unclassified-entity", "entity": id, "names": [first member name]}`. (Publisher throws on null gameSystem; parking keeps publish loud-safe while the review queue shows what needs mapping. Migrated legacy data always has gameSystem — invariant: parking count 0 after a re-run of migrate, asserted in Task 2's gate.)
  3. `report.py` hardening: manufacturer files with zero products render `0 | 0 | 0.0% | 0.0%` instead of ZeroDivisionError; malformed catalog file → `ValueError` naming the file.
  4. `verify.py` chosen-key unit test: a hand-built conflicts.yaml containing an ean-mismatch payload (chosen + assertions) proves the not-lost exemption matches the real payload shape.
  5. **Repo-data validation test** (`tests/test_repo_data.py`): loads the REAL committed `data/catalog/{sources,taxonomy,mappings?}` through the real models (descriptors validate, taxonomy loads, label files load, matches/overrides parse) so a config typo fails CI. Uses a repo-root fixture: `REPO_DATA = Path(__file__).resolve().parents[3] / "data"`; skip cleanly (`pytest.skip`) if the directory is absent (sdist safety).

- [ ] **Step 1: Write the failing tests**

`tests/test_join.py` additions:

```python
def test_shared_ean_across_manufacturers_does_not_merge() -> None:
    taxonomy = Taxonomy(
        {
            "games-workshop": Manufacturer(slug="games-workshop", name="Games Workshop", codePattern=r"\d{11}"),
            "wyrd-games": Manufacturer(slug="wyrd-games", name="Wyrd Games", codePattern=r"WYR\d+"),
        }
    )
    result = join_observations(
        [
            obs("mfr-gw:a", sku="99120110077", ean="5011921194285"),
            obs("ret-x:b", manufacturer="wyrd-games", name="Other Thing", sku=None, ean="5011921194285"),
        ],
        taxonomy, {**KINDS, "ret-x": "retailer"}, Matches(),
    )
    assert "games-workshop/99120110077" in result.entities
    assert "wyrd-games/other-thing" in result.entities
    assert {"type": "cross-manufacturer-ean", "ean": "5011921194285",
            "keys": ["mfr-gw:a", "ret-x:b"]} in result.ambiguous


def test_shared_ean_same_manufacturer_still_merges() -> None:
    result = join_observations(
        [
            obs("mfr-gw:a", sku="99120110077", ean="5011921194285"),
            obs("ret-goblin:x", sku=None, name="Different Listing Name", ean="5011921194285"),
        ],
        TAXONOMY, KINDS, Matches(),
    )
    assert list(result.entities) == ["games-workshop/99120110077"]
```

`tests/test_resolver.py` addition (extend `seed` usage):

```python
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
```

`tests/test_report.py` (new): zero-product file renders zeros; malformed file raises ValueError naming it. `tests/test_migrate_verify.py`: chosen-key payload exemption test. `tests/test_repo_data.py`: real-data loads (descriptors, taxonomy incl. labels, overrides/matches when present).

Write all of these completely (the shapes above are exact; the remaining three files follow the same pattern — arrange a tmp catalog dir / hand-built payloads, assert the exact message or rendering).

- [ ] **Step 2: RED** — run the touched test files; new tests fail for the stated reasons (merge happens today; unclassified entity crashes or publishes; ZeroDivision; missing test files).

- [ ] **Step 3: Implement.** join.py: key `ean_index` by `(observation.manufacturer, ean)`; detect cross-manufacturer duplicates via a second dict `ean_owners: dict[str, str]` (ean → first manufacturer) and emit the payload (sorted keys) when a second manufacturer asserts the same ean. resolver.py: after `apply_overrides`, `if product.gameSystem is None: conflicts.append({...}); continue` (before the manufacturer-bucket append). report.py: guard `total == 0`; wrap `read_yaml` errors. Keep every loop sorted.

- [ ] **Step 4: GREEN** — full suite `uv run pytest -v`; then re-run migration end-to-end once (`uv run warhub-data migrate --data ..\..\data --legacy-dir ..\..\data\products\manufacturers --seed-dir ..\..\data\products\seed`) — MUST still report `verification: OK` with the same entity count and zero data churn (`git status --porcelain data/` empty). Any churn → STOP: the hardening changed real-data semantics; report BLOCKED with the diff.

- [ ] **Step 5: Commit**

```bash
git add tools/acquisition data/  # data only if step 4 produced no churn (it must not)
git commit -m "feat(acquisition): manufacturer-scoped EAN joins, unclassified parking, report hardening"
```

---

### Task 2: Warlord codePattern tightening (data-gated)

**Files:**
- Modify: `data/catalog/taxonomy/manufacturers.yaml`
- Test: `tools/acquisition/tests/test_taxonomy.py`

**Interfaces:**
- Produces: warlord-games `codePattern` becomes `'[0-9]{9,12}|(?=[A-Z0-9-]*[A-Z])[A-Z0-9-]{6,}'` — pure-digit codes capped at 12 digits (an EAN-13 can no longer be identity-grade) and the alphanumeric branch requires at least one letter.

- [ ] **Step 1: Analysis gate (before any edit).** From `tools/acquisition`, run a scratch script over `data/evidence/products/legacy-catalog/observations.jsonl`: for every observation with `manufacturer == "warlord-games"`, compute `normalize_code` under BOTH the current and the proposed pattern; print counts and every sku whose identity-grade status CHANGES. Expected: the only changers are 13+-digit pure-numeric or letterless junk skus (if any exist). **If ANY changer currently anchors an entity id in `data/catalog/products/warlord-games.yaml` (grep the affected code as `id: warlord-games/<code>`), STOP and report BLOCKED with the list — identity churn needs controller-approved aliases.** Record the analysis output in your report.

- [ ] **Step 2: Failing test** — add to `test_taxonomy.py` (create a Taxonomy with the NEW pattern inline):

```python
def test_warlord_pattern_rejects_ean13_and_letterless_junk(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "manufacturers.yaml",
        {"manufacturers": [{"slug": "warlord-games", "name": "Warlord Games",
                            "codePattern": '[0-9]{9,12}|(?=[A-Z0-9-]*[A-Z])[A-Z0-9-]{6,}'}]},
    )
    taxonomy = Taxonomy.load(tmp_path)
    assert taxonomy.normalize_code("warlord-games", "5060393709671") is None      # EAN-13
    assert taxonomy.normalize_code("warlord-games", "402615006") == "402615006"    # 9-digit own-store sku
    assert taxonomy.normalize_code("warlord-games", "WGB-AI-02") == "WGB-AI-02"
    assert taxonomy.normalize_code("warlord-games", "------") is None              # letterless junk
```

RED against the OLD pattern semantics is not applicable (the test builds its own taxonomy) — instead verify the assertions against the new regex by running the test after Step 3 only; the real gate is Step 1 + Step 4.

- [ ] **Step 3: Apply** the new pattern in `data/catalog/taxonomy/manufacturers.yaml` (single line change).

- [ ] **Step 4: Re-migrate gate.** Run migrate; expect `verification: OK`, unchanged entity totals (unless Step 1 predicted specific changes the controller approved), zero unexpected churn in `git status --porcelain data/`. Full suite green.

- [ ] **Step 5: Commit** (`fix(taxonomy): warlord codePattern can no longer swallow EAN-13s`).

---

### Task 3: Acquisition infrastructure (client, cursors, contracts, sweep semantics)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/acquire/__init__.py`
- Create: `tools/acquisition/src/warhub_acquisition/acquire/client.py`
- Create: `tools/acquisition/src/warhub_acquisition/acquire/cursor.py`
- Create: `tools/acquisition/src/warhub_acquisition/acquire/runner.py`
- Modify: `tools/acquisition/pyproject.toml` (add `httpx>=0.27`)
- Test: `tools/acquisition/tests/test_acquire_client.py`, `tests/test_acquire_runner.py`

**Interfaces:**
- `PoliteClient(base_url: str | None, rps: float = 0.5, user_agent: str = UA, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep)` — `.get_json(url, params=None) -> object` and `.get_text(url) -> str`; enforces min-interval between requests via injected `sleep` (testable), retries 3x with exponential backoff on 429/5xx/transport errors (respecting `Retry-After` when present), raises `FetchError(url, status)` after retries. The injected `transport` is the test seam (httpx.MockTransport).
- `CursorStore(evidence_root: Path)` — per-source `cursor.yaml`: `load(source_id) -> dict` (empty default), `save(source_id, cursor: dict)` via yamlio (deterministic). Cursor content is strategy-owned (page numbers, pending handle queues, last full sweep date, last good counts).
- `acquire/runner.py`:
  - `SourceContractError(Exception)` with a machine-readable `.details: dict`.
  - `StrategyResult` (dataclass): `observations: list[Observation]`, `full_sweep: bool`, `stats: dict[str, int]` (fetched/new candidate counts, skipped_unknown_vendor, unmapped_hints…), `cursor: dict`.
  - `Strategy = Callable[[SourceDescriptor, PoliteClient, dict cursor, AcquireContext], StrategyResult]` — registry `STRATEGIES: dict[str, Strategy]` filled by Tasks 5/8/9/10/11.
  - `AcquireContext` (dataclass): `taxonomy: Taxonomy`, `mappings: dict[str, dict]` (per-source hint maps), `run_date: str`, `budget: int | None`.
  - `run_source(descriptor, paths, context, transport=None) -> SourceHealth`: builds client from descriptor politeness; loads cursor; invokes strategy; **contract checks** (fresh observation count ≥ `contract.minCount` when `full_sweep`; drop vs cursor's `last_good_count` ≤ `maxDropPct`; per-field fill rates ≥ `requiredFieldRates`) → `SourceContractError` BEFORE any evidence write; upserts observations (firstSeen=lastSeen=run_date; store upsert keeps older firstSeen); on `full_sweep` and contract pass: unseen existing keys get `missStreak+1` (via a store-level helper you add: `EvidenceStore.mark_missed(source_id, seen_keys: set[str]) -> int`), seen keys reset to 0 (upsert already writes 0); saves evidence + cursor (cursor gains `last_good_count`, `last_run_date`); returns `SourceHealth` (dataclass: source id, counts, contract ok, unmapped/skipped stats).
- `Observation` upsert note: fresh observations carry `missStreak=0`; `mark_missed` rewrites only unseen records.

- [ ] **Step 1: Failing tests.** `test_acquire_client.py`: MockTransport-driven — pacing calls injected sleep with expected delay; 429-with-Retry-After retried then succeeds; 3 failures raise FetchError. `test_acquire_runner.py`: a toy strategy returning canned observations — contract minCount violation raises SourceContractError and writes NOTHING; healthy full sweep writes evidence, increments missStreak on an unseen pre-existing key, resets a seen one, saves cursor with last_good_count; budgeted partial (`full_sweep=False`) never increments missStreak; drop >50% vs last_good_count on a full sweep raises. Write these tests completely against the interfaces above.

- [ ] **Step 2: RED** (ModuleNotFoundError / missing httpx). `uv add httpx` (updates pyproject + lock).

- [ ] **Step 3: Implement** the three modules exactly per the Interfaces block. Keep `run_source` free of strategy knowledge; keep all writes after all checks.

- [ ] **Step 4: GREEN** — full suite. **Step 5: Commit** (`feat(acquisition): polite client, cursors, contract-enforced source runner`).

---

### Task 4: `acquire` CLI verb + health report + confirmed-EAN guard

**Files:**
- Modify: `tools/acquisition/src/warhub_acquisition/cli.py`
- Modify: `tools/acquisition/src/warhub_acquisition/report.py`
- Create: `tools/acquisition/src/warhub_acquisition/acquire/health.py`
- Test: `tools/acquisition/tests/test_cli_acquire.py`, `tests/test_ean_guard.py`

**Interfaces:**
- CLI: `warhub-data acquire --data <dir> --source <id> [--source <id> ...] [--budget N] [--run-date YYYY-MM-DD]` — runs each named source (or every source whose descriptor has a registered strategy when none named) sequentially in sorted order; prints one line per source (`<id>: ok fetched=N new=M ...` or `CONTRACT VIOLATION <id>: <details>`); writes `data/review/acquisition-health.md` (markdown per-source table + unmapped/skipped rollups) via `health.py`; exit 4 if any source violated its contract (others still ran).
- CLI: `warhub-data report --ean-guard` — additionally loads each `catalog/products/*.yaml` from `git show HEAD:<repo-relative-path>` (subprocess, repo root derived from the data dir's parent; if the file is absent in HEAD treat as empty), compares entities present in both: previous `eanConfidence == "confirmed"` and EAN value changed → listed; any hit → exit 5 with a `## Confirmed-EAN changes` section in stdout. Pure read.
- `run_date` defaults to... nothing: `--run-date` is REQUIRED for `acquire` (no wall clock in the pipeline; workflows pass it).

- [ ] Steps: tests first (toy strategy + tmp git repo fixture for the guard: `git init`, commit a catalog with a confirmed EAN, mutate working tree, assert exit 5 + message; and the no-change → exit 0 path), RED, implement, GREEN (full suite), commit (`feat(acquisition): acquire verb, health report, confirmed-EAN guard`). Write the tests completely; the guard's git interaction uses `subprocess.run(["git", "show", f"HEAD:{rel}"], ...)` with `cwd=repo_root`.

---

### Task 5: Shopify strategy (bulk enumeration + per-handle barcode fetch)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/acquire/strategies/__init__.py`
- Create: `tools/acquisition/src/warhub_acquisition/acquire/strategies/shopify.py`
- Create: `tools/acquisition/tests/fixtures/shopify/` (captured real JSON, trimmed)
- Test: `tools/acquisition/tests/test_strategy_shopify.py`

**Interfaces:**
- Registered as `STRATEGIES["shopify"]`. Behavior:
  1. **Enumerate** `GET {base}/products.json?limit=250&page=N` until empty page. Per product: stable local id = `handle`; candidate observation from bulk data alone: name=title, sku=first variant sku, prices (variant price → priceGbp/Usd per descriptor `scope.currency`, default gbp), url=`{base}/products/{handle}`, imageUrl=first image src when present, availability from `variants[].available` if present else omitted, vendor→manufacturer via taxonomy (miss → skip + count), hints from mapping file applied to `product_type`/`tags` (gameSystem/faction slugs; unmapped counted).
  2. **Detail queue for barcodes**: a product needs a detail fetch when (a) it's new (no existing observation) OR (b) existing observation has no `ean` OR (c) bulk `updated_at` newer than cursor's recorded value. Detail fetch = `GET {base}/products/{handle}.js` → `variants[].barcode` (first non-empty, digits-only after strip; store raw digits — validation stays downstream); merge into the candidate.
  3. **Budget**: `context.budget` caps DETAIL fetches per run (enumeration is always full — it's ~25–60 cheap pages). Priority: new products, then missing-EAN, then stalest `updated_at`. Products enumerated but not detail-fetched this run still upsert their bulk-level observation (keeps lastSeen fresh; their queue position persists via cursor `pending_details` list).
  4. `full_sweep=True` when enumeration completed AND `pending_details` is empty after this run; else False. Stats: fetched_pages, products_seen, details_fetched, barcodes_found, skipped_unknown_vendor, unmapped_hints.
  5. Cursor: `{"updated_at": {handle: iso}, "pending_details": [...], "last_good_count": N, "last_run_date": ...}` — keep it compact (updated_at map only for products with an ean already, to detect changes; others are always detail-candidates until they have one).
- Extractor version: `shopify@1` (bulk-only observations) / detail-merged observations also `shopify@1` — one version string.

- [ ] **Step 1: Capture fixtures (live, polite).** From tools/acquisition: `curl.exe -s -A "warhub-catalog-bot/1.0" "https://store.warlordgames.com/products.json?limit=2"` → trim to 2 products (keep full variant/image structure) → `tests/fixtures/shopify/warlord-bulk-page1.json`; craft page2 empty `{"products": []}`. `curl.exe -s -A ... "https://store.warlordgames.com/products/<one handle from page1>.js"` → trim variants to 2 → `tests/fixtures/shopify/warlord-detail.js.json`. Record in your report which handle and what barcode value the real response carried (expect a 5060393… gtin13). Commit fixtures.
- [ ] **Step 2: Failing tests** (MockTransport routing the fixture files by URL): enumeration+detail produces observations with ean from the detail fixture; unknown vendor skipped+counted; budget=0 upserts bulk-only observations and queues details in cursor; second run with unchanged updated_at and existing ean does no detail fetch (assert via transport call log); mapping file applies gameSystem hint; full_sweep flag semantics. Write completely.
- [ ] **Step 3: RED → implement → GREEN** (full suite). **Step 4: Commit** (`feat(acquisition): shopify strategy with per-handle barcode harvesting`).

---

### Task 6: Shopify descriptors + hint mappings (Warlord, Steamforged, Wyrd, Goblin, Tistaminis)

**Files:**
- Create: `data/catalog/sources/mfr-warlord-store.yaml`, `mfr-steamforged.yaml`, `mfr-wyrd-store.yaml`, `ret-goblingaming.yaml`, `ret-tistaminis.yaml`
- Create: `data/catalog/mappings/mfr-warlord-store.yaml` (+ one per source; retailer maps may be empty scaffolds `{gameSystem: {}, faction: {}}`)
- Modify: `tools/acquisition/src/warhub_acquisition/acquire/runner.py` mappings loader if needed
- Test: extend `tools/acquisition/tests/test_repo_data.py` (descriptors + mappings validate; every mapped slug exists in taxonomy label files)

**Interfaces / content:** descriptors per spec §6 shape with probe-derived contracts — mfr-warlord-store: kind manufacturer, strategy shopify, baseUrl https://store.warlordgames.com, politeness rps 0.5, budget pagesPerRun 400, contract {minCount: 5000, maxDropPct: 30, requiredFieldRates: {name: 1.0, sku: 0.8}}; steamforged minCount 900; wyrd-store (baseUrl https://giveusyourmoneypleasethankyou-wyrd.com) minCount 600; ret-goblingaming (scope.vendors: [Games Workshop], currency gbp) minCount 6000; ret-tistaminis (scope.vendors: [Games Workshop], currency usd — VERIFY currency from a live product during implementation) minCount 3000 (conservative; adjust from first live run evidence and record why). Warlord gameSystem mapping seeded from the retired .NET `WarlordGamesGameSystem` logic — port the product_type/tags → slug table from git history (`git show 1593ee1^:tools/WarHub.ProductCatalog.Tool/ProductCatalogApp.cs`, method around line 876) into `data/catalog/mappings/mfr-warlord-store.yaml` as data; unmappable types stay unmapped (health-reported), NOT guessed.

- [ ] Steps: write mapping/descriptor files; extend test_repo_data.py (mappings reference only known taxonomy slugs — for slugs not in labels yet, the test permits them only if listed under an explicit `newGameSystems:`/`newFactions:` allowlist in the mapping file — none initially, keep strict); full suite; live smoke (opt-in, not CI): `uv run pytest -m live` running ONE budgeted (`budget=3`) real acquire of mfr-warlord-store against a tmp data dir asserting ≥1 observation with a valid EAN. Mark with `@pytest.mark.live` and register the marker + `addopts = "-m 'not live'"` in pyproject. Commit (`feat(acquisition): shopify source roster — warlord, steamforged, wyrd, goblin, tistaminis`).

---

### Task 7: EXECUTE — first live harvest (the EAN payoff)

No new code. Execution task with STOP gates, run from tools/acquisition against the repo `--data ..\..\data`.

- [ ] **Step 1:** `uv run warhub-data acquire --data ..\..\data --source mfr-warlord-store --budget 6000 --run-date <today UTC>` (full detail sweep; ~5.8k detail fetches at 0.5 rps ≈ 3.5h — run in background, this is the expensive one; if the store throttles hard, halve budget and do two runs). Contract must pass. Then the same for `mfr-steamforged` (budget 1200), `mfr-wyrd-store` (budget 800), `ret-goblingaming` (budget 3000 — partial is fine), `ret-tistaminis` (budget 1500).
- [ ] **Step 2:** `uv run warhub-data resolve --data ..\..\data` (exit 2 with conflicts EXPECTED now — new retailer assertions will disagree with some legacy EANs; that is the system working). `uv run warhub-data report --data ..\..\data` and `report --ean-guard` (exit 5 findings = review items; list them in your report — do NOT suppress).
- [ ] **Step 3:** Sanity gates: warlord-games EAN coverage in the report must rise dramatically (legacy baseline: 1,121 of 5,827 warlord entities had EANs — expect ≥4,000 after the store's gtin13 harvest; the probe confirmed barcodes are populated). Overall catalog EAN % must exceed 60% (from 44.1%). If below, STOP and report BLOCKED with per-source stats before committing.
- [ ] **Step 4:** Suites green; commit evidence + catalog + review with a stats-rich message (`data: first live acquisition — warlord/steamforged/wyrd/goblin/tistaminis EAN harvest`).

---

### Task 8: WooCommerce strategy + Mantic JSON-LD gtin + Para Bellum

**Files:** `acquire/strategies/woo.py`, fixtures `tests/fixtures/woo/`, descriptors `mfr-manticgames.yaml` + `mfr-para-bellum.yaml` + mappings, tests `test_strategy_woo.py`.

Registered as `STRATEGIES["woo-store-api"]`. Enumerate `/wp-json/wc/store/products?per_page=100&page=N` (stop via `X-WP-Total`); local id = product id; sku/name/prices (minor units! Woo store API returns prices as strings in minor units with `currency_minor_unit` — convert to major-unit float); Mantic-only extra (descriptor flag `scope.gtinFromJsonLd: true`): detail fetch of the product `permalink` HTML, regex the `<script type="application/ld+json">` blocks, parse JSON, take `gtin`/`gtin13` from the Product node (budgeted, missing-EAN-first, same queue pattern as shopify). Fixtures: one real Mantic products page (trimmed to 2 products) + one real product HTML trimmed to the ld+json script + one Para Bellum page. Same TDD/live-smoke/commit pattern as Tasks 5–6. Contracts: mantic minCount 2000, para-bellum minCount 300. Then EXECUTE both (mantic budget 3000 detail, para-bellum no details) with the same gates (mantic entities should gain EANs; para-bellum has none — expect metadata refresh only), resolve+report+commit.

---

### Task 9: Algolia strategy (Games Workshop)

**Files:** `acquire/strategies/algolia.py`, fixture `tests/fixtures/algolia/gw-page.json`, descriptor `mfr-gw-algolia.yaml` + mapping `data/catalog/mappings/mfr-gw-algolia.yaml`, tests.

Port the retired .NET source: `git show 1593ee1^:tools/WarHub.ProductCatalog.Tool/Scraping/AlgoliaProductSource.cs` — app id, search key, index `prod-lazarus-product-en-gb`, filter `productType:miniatureKit`, pagination via `page`/`nbPages`, hit → observation: sku from last dash-segment of objectID (`P-<n>-<gwSku>`), name, slug URL (`https://www.warhammer.com/en-GB/shop/<slug>`), price, image; gameSystem/faction hints from the `GameSystemsRoot`/hierarchy fields mapped via the mapping file (port the .NET faction skip-list as data). No EANs (probe-confirmed) — GW barcodes come from retailers. local id = objectID. full_sweep when all pages read. Contract minCount 2500. Fixture: one real query response trimmed to 3 hits. EXECUTE (no budget needed — pure JSON API), resolve/report/commit with gates (GW entity count consistent with legacy ~4,616; big drops → STOP).

---

### Task 10: AppSync strategy (Corvus Belli)

**Files:** `acquire/strategies/appsync.py`, fixture, descriptor `mfr-corvus-belli.yaml` + mapping, tests.

Port from `git show 1593ee1^:tools/WarHub.ProductCatalog.Tool/Scraping/CorvusBelliProductSource.cs`: endpoint + api-key header + `listProducts` command payload via POST; product → observation (REF 6-digit sku, name, url, price eur, faction via mapping). Contract minCount 800 (legacy had 1,940 across game systems — verify from the .NET source's actual scope during implementation and set honestly; record reasoning). EXECUTE + gates + commit.

---

### Task 11: Sitemap+structured-data strategy (Miniaturicum, Radaddel, Game Nerdz)

**Files:** `acquire/strategies/sitemap_sd.py`, fixtures (one real product page per site, trimmed to the structured-data block), descriptors `ret-miniaturicum.yaml`, `ret-radaddel.yaml`, `ret-gamenerdz.yaml` + empty mappings, tests.

Registered as `STRATEGIES["sitemap-structured-data"]`. Enumerate product URLs from sitemap(s) (descriptor `scope.sitemaps: [...]`, `scope.urlInclude` regex filter); budgeted page fetches (priority: URLs never fetched, then oldest-fetched via cursor date map); per page extract in order: JSON-LD Product (gtin13/gtin/gtin12, sku, name, brand) → microdata `itemprop="gtin13"` (+sku/name from itemprops) → BigCommerce `var BCData = {...}` JSON (`product_attributes.sku/upc`); manufacturer attribution via brand string → `manufacturer_for_vendor`, else GS1-prefix match of the gtin against taxonomy `gs1Prefixes`, else skip+count. local id = URL path. `full_sweep` only when every sitemap URL passing the filter has been fetched at least once AND no pending queue — practically always False for these large sites (they're pure enrichment; missStreak never driven by them, which is correct: retailer absence ≠ discontinued). Contracts: minCount 0 (partial by design) but requiredFieldRates {ean: 0.5} on the FETCHED set (a structured-data drift breaks extraction loudly). Fixtures per probe: miniaturicum JSON-LD gtin13, radaddel microdata, gamenerdz BCData. EXECUTE budgeted (miniaturicum 1000 / radaddel 1000 / gamenerdz 800; GW-focused urlInclude filters where feasible), resolve/report (EAN corroboration: retailer agreements should flip many provisional→confirmed — record the confirmed-count delta), commit.

---

### Task 12: Cross-stack golden fixture + publisher loud-gate tests (C#)

**Files:** `tools/acquisition/tests/test_golden_fixture.py` (generates), `tools/WarHub.Catalog.Publish.Tests/fixtures/canonical-golden/` (committed output of the Python writer: one products file + both taxonomy files), `tools/WarHub.Catalog.Publish.Tests/CanonicalGoldenTests.cs`, `ProductBuilderGuardTests.cs`.

Python side: a test that regenerates the golden fixture from a fixed in-code catalog (2 products covering ean/confidence/quantity/faction-null) via the REAL writer path (resolve_catalog on a tmp evidence set, then copy) and asserts byte-equality with the committed fixture — drift fails Python CI with instructions to regenerate. C# side: load the SAME committed fixture through YamlSource + ProductBuilder → assert published values; plus guard tests: null gameSystem throws naming product id; missing gs label throws naming slug; missing faction label throws naming slug. Commit both stacks together.

---

### Task 13: Scheduled workflows + publish-trigger tightening + README

**Files:** `.github/workflows/catalog-acquire.yml` (new), `.github/workflows/catalog-publish.yml` (paths), `README.md`.

- `catalog-acquire.yml`: nightly cron `0 4 * * *` + workflow_dispatch (inputs: sources, budget). Job matrix over source GROUPS (group A: mfr-warlord-store, mfr-steamforged, mfr-wyrd-store; group B: mfr-gw-algolia, mfr-manticgames, mfr-para-bellum, mfr-corvus-belli; group C: ret-goblingaming, ret-tistaminis; group D: ret-miniaturicum, ret-radaddel, ret-gamenerdz) — each job: setup uv, `acquire --source ... --budget <group default> --run-date $(date -u +%F)`, upload `data/` changes as artifact; a final `integrate` job downloads artifacts, merges evidence dirs (disjoint by source — plain copy), runs `resolve` + `report` + `report --ean-guard`, opens/updates sticky PR `catalog/acquisition` with the health report + coverage table + guard findings as the PR body (`gh pr create/edit` pattern copied from the deleted product-catalog-update.yml — retrieve via `git show 490d0c9^:.github/workflows/product-catalog-update.yml`). Exit-4 (contract) and exit-5 (ean-guard) surface as PR-body warnings AND job failure so a broken source is loud in the Checks tab.
  Timeout 120 min; concurrency group `catalog-acquire` no-cancel.
- `catalog-publish.yml`: `paths: ["data/catalog/**", "data/paints/**"]` (stops evidence-only/legacy-tree churn from minting releases).
- README: pipeline section gains the nightly acquisition description; note `-m live` smoke tests.
- Deliberate deviation from spec §7: no separate weekly deep-sweep workflow in this plan — the nightly run already does full enumeration (cheap) plus budgeted detail fetches with persistent cursors, which converges to full coverage across nights. The weekly cadence returns in Plan 4 as the archive-mining driver.
- Workflow YAML can't be integration-tested locally: validate with `gh workflow view` after push? NO — worktree flow can't push. Gate: `uv run python -c "import yaml,glob; [yaml.safe_load(open(p,encoding='utf-8')) for p in glob.glob('.github/workflows/*.yml')]"` parses clean + careful self-review + the plan's final review; first real run is observed post-merge (controller responsibility, noted in Execution notes).

---

### Task 14 (final): whole-branch review

Standard: most capable model, code-focused package (exclude bulk evidence), sample committed acquisition data, triage roll-up, fix wave, re-review.

## Execution notes for the controller

- Task 7 is a multi-hour, network-bound run (Warlord ≈5.8k detail fetches at 0.5 rps). Dispatch it with run_in_background awareness and generous timeout; consider `--budget 3000` × 2 sequential runs if the executor's shell timeout bites (cursor picks up where it left off — that's what pending_details is for).
- Execution tasks (7, and the execute-steps inside 8–11) follow STOP gates literally; coverage numbers land in the ledger after each.
- After merge, the controller watches the first nightly `catalog-acquire` run and the tightened publish triggers (workflows can't be exercised pre-merge).
- Plan 4 preview: CMON via Playwright, web-archive CDX mining (OOP recovery), barcode-DB corroboration, LLM extraction/classification/adjudication. Plan 5: paints + .NET tool retirement + data/products removal.
