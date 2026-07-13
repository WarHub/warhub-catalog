# Archive Mining, Corroboration & LLM Classification Implementation Plan (Plan 4 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push EAN coverage past 60% and recover out-of-print products by (a) classifying the 2,486 parked live-source entities with capped LLM assistance, (b) mining web.archive.org for archived Shopify JSON-LD EANs and old-GW-webstore product codes, (c) corroborating provisional EANs via free barcode databases, and (d) closing Plan-3 deferrals (Tistaminis CAD, Miniaturicum, barcode give-up, CMON via Playwright, weekly sweep).

**Architecture:** Everything extends the Plan-3 acquisition engine unchanged: new strategies register in `STRATEGIES`, new sources are descriptors + mappings, all writes flow through `EvidenceStore`/`CursorStore` with contract checks before writes. LLM outputs NEVER write evidence directly — they write **committed review-then-apply files** (`data/catalog/mappings/*`, `matches.yaml`, classification files) with model+input-hash provenance, so resolution stays deterministic and re-runs are free. Probe ground truth: `docs/research/2026-07-12-source-probe-webarchive.md`, `...-retailers-barcodedb.md`, `...-manufacturers.md` (CMON section).

**Tech Stack:** existing `tools/acquisition/` (httpx, pydantic, PyYAML) + `anthropic` SDK (new, Task 5) + `playwright` (new, optional-extra, Task 10). C# untouched except the additive `priceCad` (Task 8).

## Global Constraints

- All Plan-3 invariants hold: determinism (no wall clock — `--run-date` in; sorted iteration into every written file), politeness in the client only (CDX ≤1 req/s per probe evidence: `politeness.rps: 1.0` for archive sources, 0.5 elsewhere), contracts loud (`SourceContractError`, exit 4), evidence append-only, UA `warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)`.
- Archived observations carry `archived: true` and NEVER reset `missStreak` or drive lifecycle (`resolve_attributes` already treats archived members as non-live — verify, don't assume).
- LLM usage (spec §6): scheduled/manual CI with `ANTHROPIC_API_KEY` secret, model `claude-haiku-4-5-20251001`, hard per-run budget (default max 500 requests), every output committed with `{model, inputHash, date}` provenance; identical inputs are NEVER re-queried (hash-keyed cache file). LLM proposals are DATA reviewed via PR — the resolver never calls a model.
- EAN handling: raw digits in evidence; validation/corroboration stays in `ean.py`/`corroborate.py`. Barcode-db kind is corroboration-only: it can flip provisional→confirmed but its assertions never mint entities (enforced: `kind: barcode-db` observations without a joinable key are dropped + counted, never name-joined).
- Honest floors policy: every new contract value derives from live/archive evidence captured during implementation, recorded in the task report (~85% of observed).
- All committed text files UTF-8/LF/trailing newline; commit messages end with the repo's two trailers.
- Suites green after every task: `uv run pytest` (tools/acquisition) and `dotnet test WarHub.Catalog.slnx` (only Task 8 touches C#).
- `uv` PATH note (Windows dev shells): `$env:Path = [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path`.

## Evidence baselines this plan is built on

- Post-Plan-3 catalog: 12,618 products, 6,486 EANs (51.4%); 2,486 parked unclassified entities in `data/review/conflicts.yaml` (1,244 mantic, 1,084 GW paint bundles, 95 wyrd, 49 sfg, 10 pb, 4 warlord); 44 ean-mismatches.
- Wayback CDX verified: `web.archive.org/cdx/search/cdx?url=<domain>/<prefix>*&output=json` with `page=`/`showNumPages=true` paging; ≤1 req/s → zero 429s; avoid server-side regex filters; `statuscode:200` filter is slow-but-OK, prefer local filtering.
- Archived Shopify pages carry JSON-LD `gtin13` (confirmed: goblingaming 2021 capture → `gtin13: 5060504044745`); old GW webstore 2014–2019 pages carry `skuId=<11-digit>` + name + GBP price, NO EANs; warhammer.com archives are SPA shells (skip).
- Barcode DBs: upcitemdb trial API free ~100/day (spotty), Go-UPC web lookup free via HTML (best hit rate, API paid → scrape politely), everything else dead/paid.
- CMON: 320 products via `wp-sitemap-posts-products-1.xml`, Cloudflare-403 to curl, marketing pages only (names/lines/images, NO EANs, no prices).
- Tistaminis: Shopify, CAD currency (Plan-3 evidence), `/products/<handle>.js` barcodes populated, large GW range.

---

### Task 1: Classification pipeline scaffolding (no LLM yet)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/classify/__init__.py`, `classify/queue.py`, `classify/apply.py`
- Modify: `tools/acquisition/src/warhub_acquisition/cli.py` (new verb `classify --emit-queue` / `classify --apply`)
- Test: `tools/acquisition/tests/test_classify_queue.py`, `tests/test_classify_apply.py`

**Interfaces:**
- Consumes: `data/review/conflicts.yaml` (unclassified-entity payloads), evidence stores, taxonomy.
- Produces:
  1. `classify/queue.py`: `build_queue(paths) -> list[dict]` — for every `unclassified-entity` conflict, gather the entity's member observations and emit a queue item `{"entity": id, "name": ..., "vendor/manufacturer": ..., "url": ..., "productType/tags/category hints": [...], "candidates": {"gameSystems": [valid slugs], "factions per gs": {...}}}`; deterministic order (sorted by entity id). CLI `warhub-data classify --emit-queue --data <dir>` writes `data/review/classification-queue.yaml`.
  2. `classify/apply.py`: `apply_classifications(paths) -> int` — reads `data/catalog/classifications/products.yaml` (committed decisions: `{entity: {gameSystem: slug, faction: slug|null, decidedBy: llm|human, model: ..., inputHash: ..., date: ...}}`), validates every slug against taxonomy labels (unknown slug → `ValueError` naming entity+slug), and materializes them as **overrides**: merge into `data/catalog/overrides.yaml` `products.<entity>.gameSystem/faction` (the existing override path — the resolver already applies overrides after attribute folding, and parking happens after `apply_overrides`, so a classified entity un-parks with zero resolver changes — VERIFY this ordering in resolver.py and STOP if wrong).
  3. `classify --apply` then re-runs nothing itself: the operator runs `resolve` after (document in CLI help).
- [ ] Steps: failing tests first (queue built from a tmp data dir with 2 parked entities — exact YAML shape asserted; apply: valid slugs merge into overrides.yaml preserving existing keys + unknown slug raises naming both), RED, implement, GREEN full suite, commit (`feat(classify): classification queue + override-materializing apply`).

---

### Task 2: cdx-archive strategy core (CDX enumeration + snapshot fetch)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/acquire/strategies/cdx_archive.py`
- Create: `tools/acquisition/tests/fixtures/cdx/` (real captured CDX JSON page + archived HTML snippets, trimmed)
- Test: `tools/acquisition/tests/test_strategy_cdx.py`

**Interfaces:**
- Registered as `STRATEGIES["cdx-archive"]`. Descriptor scope: `{cdxUrlPattern: "goblingaming.co.uk/products/*", urlInclude: <regex>, extractor: "shopify-jsonld" | "gw-legacy", snapshotFrom: "2014", snapshotTo: "2021"}`.
- Behavior:
  1. **Enumerate** via CDX (`output=json&collapse=urlkey&fl=original,timestamp,statuscode&from=...&to=...&page=N`, `showNumPages` first). Cache the full URL list in the cursor (`cdx_pages_fetched`, `url_index` — CDX enumeration is expensive; re-enumerate only when `cdx_pages_fetched < showNumPages` or cursor age > `scope.reEnumerateAfterDays` handled as run-date diff). Filter locally: statuscode 200, urlInclude, dedupe by urlkey keeping NEWEST timestamp within [from,to].
  2. **Budgeted snapshot fetches**: `https://web.archive.org/web/<timestamp>id_/<original>` (the `id_` raw-content form — verify live during fixture capture; record the exact form that returns unmodified HTML). Priority: never-fetched, then oldest-fetched (cursor date map). Per page run the descriptor's named extractor:
     - `shopify-jsonld`: JSON-LD Product → gtin13/gtin/sku/name/brand (reuse `sitemap_sd`'s extraction helpers — refactor them into a shared `acquire/extract.py` module rather than duplicating; sitemap_sd imports from there too, its tests must stay green).
     - `gw-legacy`: regex extraction of `skuId=`/`skuid="` 11-digit codes + `<title>`/og:title name + GBP price patterns (write from the real captured fixture; if a page yields no code, count `extraction_failed`).
  3. Observations: `archived: true`, `key = <source-id>:<url-path>`, availability omitted, url = the ORIGINAL live URL (not the wayback URL; store wayback timestamp in a hint `archiveTimestamp`). manufacturer attribution: `shopify-jsonld` → brand/GS1 fallback exactly like sitemap_sd; `gw-legacy` → pinned `scope.manufacturer: games-workshop`.
  4. `full_sweep` ALWAYS False (archives never drive missStreak). Stats: `cdx_pages_fetched, urls_indexed, snapshots_fetched, eans_found, codes_found, extraction_failed, fetch_errors, skipped_unknown_manufacturer`.
  5. Politeness: descriptor `politeness.rps: 1.0` MAX (probe: 1 req/s safe). Wayback 429/5xx handled by the client's existing retry.
- [ ] Steps: capture real fixtures live (ONE CDX page query trimmed to ~20 rows for goblingaming + ONE archived goblin product page trimmed to JSON-LD + ONE old-GW 2016 page trimmed to the skuId region + name/price — 3-4 polite requests total; record what you saw), complete failing tests (enumeration paging + cursor caching, both extractors against real fixtures with exact ean/code asserted, budget/priority, full_sweep False, archived flag, wayback-URL construction), RED, implement (incl. the extract.py refactor), GREEN full suite, commit.

---

### Task 3: Archive source descriptors + EXECUTE first archive harvest (STOP gates)

**Files:** `data/catalog/sources/arc-goblingaming.yaml`, `arc-warlord-store.yaml`, `arc-gw-webstore.yaml` (+ empty mappings); execution.

- Descriptors (kind `archive`): arc-goblingaming `{cdxUrlPattern: goblingaming.co.uk/products/*, extractor: shopify-jsonld, snapshotTo: 2023}` — captures predating the current live harvest recover delisted products; arc-warlord-store `{cdxUrlPattern: store.warlordgames.com/products/*, extractor: shopify-jsonld}` — VERIFY during implementation that archived warlord pages carry JSON-LD gtin13 (one live check; if not, drop this descriptor and record why); arc-gw-webstore `{cdxUrlPattern: games-workshop.com/en-GB/*, extractor: gw-legacy, snapshotFrom: 2014, snapshotTo: 2019, urlInclude: product-slug pattern excluding category/static pages — derive from the CDX sample}`. Contracts: minCount 0, requiredFieldRates `{ean: 0.5}` for shopify-jsonld sources / `{sku: 0.8}` for gw-legacy, maxDropPct 30.
- [ ] **EXECUTE** budgeted first harvests from tools/acquisition (`--budget 500` each, run-date = today UTC; each ≈ 10–17 min at 1 rps). Record stats. **STOP gates:** arc-goblingaming must yield ≥100 EANs at ≥0.5 fill on extracted pages; arc-gw-webstore must yield ≥200 11-digit codes; wholesale extraction failure (>50% extraction_failed) → STOP, report BLOCKED with sample pages before committing evidence.
- [ ] `resolve` + `report` + `report --ean-guard`: expect NEW archived-only entities for OOP products (they carry gameSystem=None → they PARK — that is correct and feeds Task 5's queue; count them) and EAN corroborations/backfills on existing entities (report the confirmed-count delta). Commit evidence+catalog+review with stats.

---

### Task 4: Barcode-db corroboration strategy (upcitemdb + Go-UPC)

**Files:** `acquire/strategies/barcode_db.py`, fixtures, `data/catalog/sources/bdb-upcitemdb.yaml` + `bdb-goupc.yaml`, tests.

- Registered as `STRATEGIES["barcode-db"]`. INVERTED flow: it reads the CURRENT catalog (paths.catalog_products) for entities with `eanConfidence: provisional` (sorted by entity id), takes up to `budget` of them, queries the db for the EAN, and emits observations that CORROBORATE (same ean, `key = <source>:<ean>`, name from the db, manufacturer = the entity's manufacturer — pinned, never guessed from db text).
  - upcitemdb: `GET https://api.upcitemdb.com/prod/trial/lookup?upc=<ean>` (free trial ~100/day → descriptor `budget.requestsPerRun: 80`); a 0-item response = no observation + counted `misses`.
  - Go-UPC: `GET https://go-upc.com/search?q=<ean>` HTML; product-name heading regex from the real fixture; miss = no observation. rps 0.25 (be extra polite — we're a guest).
  - Match sanity: the db-returned title must fuzzy-contain the entity's manufacturer name or a known vendorName (case-insensitive substring) — otherwise count `mismatched_title` and emit NOTHING (a barcode-db hit for a different product must not corroborate).
- `kind: barcode-db` must rank BELOW retailer in `corroborate.py`'s kind priority and in `_priority` join ordering — check the existing kind tables; extend them if barcode-db is missing, with tests.
- Contracts: minCount 0; requiredFieldRates {} (misses are normal); full_sweep always False.
- [ ] Steps: capture real fixtures (one upcitemdb JSON hit, one 0-item response, one Go-UPC HTML hit — use the probe's known-good EANs 5011921146000/5011921194285), failing tests (provisional-selection order + budget, corroboration observation shape, title-sanity rejection, miss counting, kind priority), RED, implement, GREEN, commit. Then **EXECUTE** one run each (budget 80/50), `resolve`, report the provisional→confirmed delta, commit.

---

### Task 5: LLM classification of the parked queue (the un-parking payoff)

**Files:**
- Create: `tools/acquisition/src/warhub_acquisition/classify/llm.py`
- Modify: `tools/acquisition/pyproject.toml` (add `anthropic>=0.40`), `cli.py` (`classify --llm --budget N --model ...`)
- Create: `data/catalog/classifications/products.yaml` (output, committed), `data/review/classification-cache.jsonl` (hash-keyed, committed)
- Test: `tools/acquisition/tests/test_classify_llm.py` (mock transport at the SDK boundary — no real API in tests)

**Interfaces:**
- `classify --llm`: loads the Task-1 queue, skips items whose `inputHash` (sha256 of the canonical queue-item JSON) already appears in the cache, sends up to `--budget` items (default 500) to `claude-haiku-4-5-20251001` in batched prompts (up to 20 items per request; structured JSON out). Prompt contract: the model picks a gameSystem slug FROM THE PROVIDED candidate list only (plus `"unknown"`), optional faction slug from the per-gs candidates, and a 0–1 confidence. Responses with unknown slugs or malformed JSON → item recorded as `{decision: "unknown"}` in cache, never guessed.
  - Acceptance threshold: only `confidence >= 0.8` decisions land in `classifications/products.yaml` (with model/inputHash/date provenance); everything else stays queued with the cache preventing re-query until its inputs change.
  - API key from env `ANTHROPIC_API_KEY`; absent → exit 1 with a clear message.
- Determinism: the pipeline stays deterministic because LLM outputs are COMMITTED data applied via Task 1's `--apply`; `resolve` never varies. Cache/classification files sorted by entity id.
- [ ] Steps: failing tests (mocked SDK: batching, cache hit skips request, threshold filter, unknown-slug rejection, provenance fields, budget cap, missing-key exit), RED, `uv add anthropic`, implement, GREEN, commit.
- [ ] **EXECUTE (controller-gated):** requires `ANTHROPIC_API_KEY` locally — the CONTROLLER runs this step, not a subagent, in ≤500-item batches: `classify --emit-queue` → `classify --llm --budget 500` → spot-check 20 random decisions against the real products (STOP if >2 of 20 are wrong) → `classify --apply` → `resolve` → report coverage delta → commit (`data: LLM classification wave 1 — N entities un-parked`). Repeat until the queue is exhausted or decisions degrade. Record final coverage %.

---

### Task 6: LLM join adjudication (retailer-minted duplicates → matches.yaml proposals)

**Files:** `classify/joins.py`, CLI `classify --propose-joins`, `data/review/join-proposals.yaml` (output), tests.

- Deterministic candidate generation FIRST (no LLM): for every parked or retailer-only entity, find same-manufacturer catalog entities with (a) identical validated EAN (should be rare post-join), (b) normalized-name similarity ≥ threshold (reuse the conservative name-join normalizer), or (c) legacy `legacyProductCode` hints matching sku digits. Each candidate pair goes to the LLM (same batching/cache/threshold machinery as Task 5) with both entities' full context; the model answers same-product true/false + confidence.
- Output: `data/review/join-proposals.yaml` (sorted; provenance) — a HUMAN (or the controller with spot-check gates like Task 5) promotes accepted pairs into `data/catalog/matches.yaml` joins. `classify --propose-joins` never edits matches.yaml itself.
- [ ] Steps: TDD as above; EXECUTE controller-gated like Task 5 (spot-check 20; STOP >2 wrong); after promotion run `resolve` + `report --ean-guard` (joins can change confirmed EANs — guard findings are review items, list them), commit. Record entity-count and coverage deltas.

---

### Task 7: Give-up mechanism for permanently barcode-less detail queues

**Files:** `acquire/strategies/shopify.py`, `woo.py`, tests.

- Cursor gains per-handle `detailMisses` (int): incremented when a detail fetch succeeds but yields NO barcode/gtin; handle drops out of the missing-ean queue when `detailMisses >= 3` (still re-queued if bulk `updated_at` changes — product data changed, worth re-checking). FetchError does NOT increment (transient). Frees ~2,300 nightly Warlord fetches (~77 min/night). Tests: miss increments, cap excludes, updated_at change resets, FetchError doesn't count.
- [ ] TDD, GREEN, commit. Then regenerate cursors deterministically? NO — cursors update naturally on the next nightly run; do not hand-edit committed cursors.

---

### Task 8: Tistaminis (CAD) — priceCad through the stack + descriptor

**Files:** `models/observation.py`, `models/catalog.py`, `tools/WarHub.Catalog.Publish/CanonicalModels.cs` + `ProductBuilder.cs` (+ schema JSON), `data/catalog/sources/ret-tistaminis.yaml` + mapping, tests both stacks.

- Additive `priceCad: float | None` on Observation + CanonicalProduct + published ProductEntry (JsonPropertyOrder after priceEur; schema additive, schemaVersion stays 1.0). Shopify strategy already handles scope.currency — add `cad` to its currency→field table. Descriptor: kind retailer, scope `{vendors: [Games Workshop], currency: cad}`, minCount from live evidence (~85% of observed GW-vendor count — capture during implementation; Plan-3 baseline suggested ~3000+ GW products), rps 0.5, budget 1500.
- [ ] TDD both stacks (golden fixture may need regen — follow test_golden_fixture's REGEN_GOLDEN instructions and commit the byte-diff), full suites green (`uv run pytest` + `dotnet test WarHub.Catalog.slnx`), commit. Then **EXECUTE** budgeted harvest (budget 1500 ≈ 50 min), resolve/report/guard, commit with stats.

---

### Task 9: Miniaturicum descriptor (site-recovery gated)

- [ ] Probe once (single curl). Still 520 → record + SKIP task (re-checked in Plan 5). Recovered → capture the fixture Task 11/Plan 3 could not, create `ret-miniaturicum.yaml` (sitemap-structured-data, JSON-LD extractor, eur, GW-focused urlInclude if feasible), extend test_repo_data, EXECUTE budget 1000, resolve/report, commit.

---

### Task 10: Playwright strategy + CMON (names/lines only)

**Files:** `acquire/strategies/playwright_wp.py`, `pyproject.toml` (playwright as OPTIONAL extra `[project.optional-dependencies] browser = [...]`), `data/catalog/sources/mfr-cmon.yaml` + mapping (24 product lines → gameSystem slugs where they exist in taxonomy), tests (transport-mocked page-content layer; real browser only behind `-m live`).

- Scope: enumerate `wp-sitemap-posts-products-1.xml` (320 URLs, Cloudflare — needs the browser), fetch each product page, extract name + product-line + imageUrl (og: tags / DOM per the real fixture captured via a live browser run). NO EANs, NO prices (marketing site). local id = URL slug; pinned manufacturer cmon. missStreak liveness: full_sweep True only when all 320 fetched this run (they're cheap enough at 320 pages — one run covers them).
- Design the module so the browser is an injected `PageFetcher` callable — unit tests fake it; the real Playwright impl lives behind the optional extra; descriptor validation must not import playwright.
- CI: the nightly workflow gets a group E running ONLY if the extra is installed — `uv sync --extra browser` + `playwright install chromium --with-deps` in that job (document runtime cost). Contract minCount 272 (0.85 × 320).
- [ ] TDD, one live smoke behind `-m live`, EXECUTE (via live path locally), resolve/report, commit. If Cloudflare blocks headless Chromium even with Playwright defaults, STOP and report BLOCKED with the evidence (do not escalate to stealth plugins — that crosses the politeness line; CMON would then wait for a distributor-data alternative in Plan 5).

---

### Task 11: Weekly deep-sweep workflow + roster/docs

**Files:** `.github/workflows/catalog-acquire.yml` (extend), `README.md`.

- Weekly cron (`0 2 * * 6`) dispatch mode: same workflow, an input/schedule-derived `mode=weekly` that (a) adds the archive group (arc-goblingaming, arc-warlord-store, arc-gw-webstore, budgets 500) and barcode-db group (bdb-upcitemdb 80, bdb-goupc 50) to the matrix, (b) raises retailer budgets (radaddel/gamenerdz 2500 — converges their 14k-URL backlog in ~3 weeks). Nightly mode unchanged. Group E (cmon/playwright) weekly-only. The integrate job unchanged (groups are disjoint by source).
- README: pipeline section gains archive/barcode-db/classification description; document `classify` verbs + the ANTHROPIC_API_KEY secret requirement (the classification job is workflow_dispatch-ONLY, never cron — LLM spend stays human-triggered).
- Add a `classify.yml` workflow: workflow_dispatch (inputs: budget), runs emit-queue → llm → apply → resolve → report, pushes to the sticky acquisition PR branch pattern. Requires the secret; fails fast without it.
- [ ] YAML-parse gate + careful self-review (same as Plan 3 T13); commit. First real runs observed post-merge (controller).

---

### Task 12 (final): whole-branch review

Standard: most capable model, code-focused package (exclude bulk evidence), sample committed archive evidence + classification files, ledger-Minors triage roll-up, fix wave, re-review. Extra attention: LLM provenance/caching correctness (nothing re-queries on identical inputs), archive observations never driving lifecycle, barcode-db never minting entities.

## Execution notes for the controller

- Tasks 3, 4, 5, 6, 8, 10 have EXECUTE phases; 5 and 6 are CONTROLLER-run (API key + spot-check gates). Harvest EXECUTEs can run as background processes in parallel across different hosts (Plan-3 pattern), builds pipelined one implementer at a time.
- The ANTHROPIC_API_KEY repo secret must exist before the classify.yml workflow lands — ask the user to add it when presenting this plan.
- Expected coverage arithmetic (honest estimate, not a gate): un-parking ~2,000 of 2,486 parked (most carry retailer EANs) ≈ +13–15pp on the enlarged denominator → ~58–62%; archive-recovered OOP EANs and barcode-db confirmations push further. Set the plan-level gate at **overall ≥60% after Task 6**, with the Plan-3 lesson applied: if the ceiling turns out structural, STOP, document the evidence, adjudicate with data — never silently accept OR silently fail.
- Plan 5 preview: paints migration onto this framework (Army Painter/Vallejo/brand stores), .NET tool retirement, `data/products/` removal, schemaVersion review.
