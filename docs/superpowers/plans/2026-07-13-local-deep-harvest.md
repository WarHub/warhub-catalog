# Local Deep-Harvest Campaign Implementation Plan (Plan 5 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the EAN gap by one-off LOCAL harvesting — no CI timeouts, no throttled runner IPs, a real browser available. Evidence says the gap is 7,547 products, 79% of it Warlord (3,979) + Mantic (1,983), and the single largest cause is **self-inflicted**: our own retailer descriptors are vendor-scoped to Games Workshop, so we enumerate tens of thousands of barcoded products and then throw them away.

**Architecture:** No new pipeline machinery. Widen descriptor scopes, run full local sweeps of existing sources with existing strategies, add two archived-Shopify sources and one new retailer. Every harvest runs through the same evidence ledger → resolver → publisher path.

**Tech Stack:** existing `tools/acquisition/`; local `claude` CLI for any classification of newly-minted entities (`scripts/classify_local.py`); Playwright (optional extra, already present) only where a wall requires it.

## Global Constraints

- All prior invariants hold: politeness in the client (0.5 rps default; ≤1 rps Wayback), determinism (`--run-date` in, sorted iteration), contracts loud, evidence append-only, UA `warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)`.
- **Coverage arithmetic is the gate, not vibes.** Every EXECUTE task reports products-with-EAN before/after and the delta. A task that promises EANs and delivers none STOPS and reports, with the store-side evidence (the Plan-3 Warlord lesson and Plan-4 goblin-archive lesson: a structural ceiling is a finding, not a failure).
- New entities minted by widened scopes need `gameSystem` classification — run `scripts/classify_local.py` after each wave that mints entities, then `--apply` + `resolve`. `gameSystem` is optional now, so an `unknown` verdict publishes rather than parks.
- Suites green after every task: `uv run pytest` (tools/acquisition) and `dotnet test WarHub.Catalog.slnx`.
- `uv` PATH note (Windows dev shells): `$env:Path = [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path`. Use `uv run --no-sync` when a background harvest holds the venv.

## Evidence this plan is built on (2026-07-13 recon; docs/research/2026-07-13-{local-harvest-recon,coverage-arithmetic}.md)

- **Missing-EAN buckets** (7,547 total): warlord/current/has-sku **3,979**; mantic **1,983** (1,031 of them system-less accessories); games-workshop 795; steamforged 160. All current, all SKU-complete — an enrichment gap, not a data-quality one.
- **Goblin Gaming enumerates 13,436 products; we harvest 2,923** (`scope.vendors: [Games Workshop]`). A 1,500-product sample shows it stocks Warlord (4%), Corvus Belli (4%), Atomic Mass Games (4%), TT Combat, plus Mantic/Steamforged/Wyrd. GW barcode fill there was **98.7%**.
- **Tistaminis enumerates 25,000 (platform cap); we harvest 1,178** (`vendors: [Games Workshop, GW-Local]`). CAD store, 97.7% barcode fill on what we did take.
- **Retailer accessory EANs are real**: Goblin, Radaddel, Game Nerdz and Fantasywelt all populate barcodes for paints/bases/mats as reliably as for kits (one GW paint cross-corroborated across three stores).
- **Backlogs**: Radaddel 11,806 URLs remaining (~6.6 h at 0.5 rps, ~23.6% EAN rate → ~2,786 EANs); Game Nerdz 2,364 GW-filtered remaining (~1.3 h, 42.8% → ~1,011 EANs) out of 257,416 total URLs.
- **Fantasywelt** (fantasywelt.de): Cloudflare auto-clears in ~5 s with a real browser; `itemprop="gtin13"` confirmed **including accessories**; ~70k items claimed. **Enumeration is the open problem** (sitemap errored, on-site search broken) — Task 4 solves or drops it.
- **Dead ends, do not spend time on**: Go-UPC and every free barcode DB are **barcode-in only** (live-probed: name/SKU search returns HTTP 400) — they can corroborate 663 provisional EANs (~212 hits) but can NEVER supply a missing one. Wayland has no `gtin13` (and PerimeterX bites after ~6 navigations). Miniature Market's EAN fields are structurally empty. Element Games' EAN-as-URL is legacy-only. CMON has no barcodes at all, ever.
- **Archived Shopify with `gtin13`**: tistaminis.com (`4573102621856`, capture 20221001055446, 10 CDX pages) and wargameportal.com (`5011921171996` = GW Achilles Ridgerunner, capture 20241208110155, 2 CDX pages).

---

### Task 1: Un-scope the retailers we already enumerate (the self-inflicted gap)

**Files:** `data/catalog/sources/ret-goblingaming.yaml`, `ret-tistaminis.yaml`; `tools/acquisition/tests/test_repo_data.py` (if it asserts scope shape).

**Interfaces:** Removing `scope.vendors` makes the shopify strategy fall back to taxonomy attribution — products whose vendor maps to a tracked manufacturer are observed, everything else counts `skipped_unknown_vendor`. This is existing, tested behavior (`test_scope_vendors_absent_behaves_unchanged`); no code change.

- [ ] **Step 1: Verify the fallback on real data before touching descriptors.** From `tools/acquisition`, write a scratch script (session scratchpad, NOT the repo) that enumerates ONE page of goblin's `/products.json` and, for each product, prints `vendor → taxonomy.manufacturer_for_vendor(vendor)`. Confirm Warlord/Corvus/AMG/Mantic vendors resolve and untracked brands (Pokemon, Ultimate Guard) return None. Record the mapping in your report. If a tracked brand fails to resolve (e.g. Mantic's store vendor string differs), ADD the alias to `data/catalog/taxonomy/manufacturers.yaml` `vendorNames` with the live evidence — that is part of this task.
- [ ] **Step 2: Drop `scope.vendors`** from both descriptors, replacing it with a comment recording why (13,436 vs 2,923; 25,000 vs 1,178) and what now governs (taxonomy attribution). Keep `scope.currency`. Raise `contract.minCount` to a floor consistent with the wider scope ONLY after Step 3's evidence — leave it unchanged for now and note that Step 4 adjusts it.
- [ ] **Step 3: EXECUTE goblin (controller-run, background).** `uv run --no-sync warhub-data acquire --data ..\..\data --source ret-goblingaming --budget 12000 --run-date <today>`. ~10.5k additional detail fetches at 0.5 rps ≈ **6 h**. Record: products_seen, out_of_scope→skipped_unknown_vendor shift, barcodes_found, per-manufacturer breakdown of the new observations (scratch script over the fresh JSONL).
- [ ] **Step 4: EXECUTE tistaminis** the same way (`--budget 25000`; the 25k platform cap means enumeration is already full — the detail queue is what grows). ~10-20 h depending on tracked-vendor share; run in background, it can overlap Task 2's sweeps (different host). Then set both descriptors' `minCount` from observed evidence (~85% of tracked-product count) and commit.
- [ ] **Step 5: Classify + resolve.** New entities will be minted (retailer-only products we've never seen). Run `classify --emit-queue` → `scripts/classify_local.py --mode classify` → `classify --apply` → `resolve` → `report`. **GATE:** warlord-games and mantic-games EAN counts must both RISE. Report the exact deltas. If they don't, STOP and report with the vendor breakdown — it means those stores' Warlord/Mantic stock lacks barcodes, which is a finding.
- [ ] **Step 6: Commit** evidence + catalog + review (`data: un-scoped goblin + tistaminis retailer harvests`).

---

### Task 2: Full local sweeps of the sitemap retailers (and un-GW-scope them too)

**Files:** `data/catalog/sources/ret-radaddel.yaml`, `ret-gamenerdz.yaml`.

- [ ] **Step 1: Broaden `urlInclude`.** Both filters are GW-term regexes today, so they structurally cannot reach Warlord/Mantic — the two buckets that ARE the gap. Game Nerdz demonstrably stocks Bolt Action (live search: 9 hits). Replace each filter with one that also admits Warlord/Mantic/Corvus/AMG/Steamforged/Wyrd product-slug terms (bolt-action, warlord, epic-battles, black-powder, hail-caesar, victory-at-sea, cruel-seas, blood-red-skies, konflikt, kings-of-war, mantic, deadzone, firefight, dreadball, armada, malifaux, wyrd, infinity, corvus, marvel-crisis, star-wars-legion, shatterpoint, guild-ball, godtear, warmachine, epic-encounters…). Derive the term list from the taxonomy's game-system + manufacturer slugs rather than inventing it, and record the resulting URL counts (Radaddel: how many of 12,806 now pass? Game Nerdz: how many of 257,416?). If Game Nerdz's broadened set explodes past ~15k URLs, cap the sweep with `--budget` and note the remainder converges over later runs.
- [ ] **Step 2: EXECUTE Radaddel full sweep** (controller, background): `--budget 13000` ≈ 6.6 h+. **Step 3: EXECUTE Game Nerdz** `--budget 8000` ≈ 4.4 h (different host — runs in parallel).
- [ ] **Step 4: Classify (new entities) → resolve → report.** GATE: combined new EANs ≥ 2,000 (recon projected ~3,797 for the GW-only backlogs alone; a broadened filter should exceed that). Below that → STOP, report per-source stats.
- [ ] **Step 5: Commit.**

---

### Task 3: Archived-Shopify mining, round 2 (the stores that actually carry gtin13)

**Files:** `data/catalog/sources/arc-tistaminis.yaml`, `arc-wargameportal.yaml` (+ empty mappings).

Both confirmed to carry `gtin13` in real captures (see evidence above) — unlike goblin's archives, whose captures mostly predate its barcode theme. Reuse `cdx-archive`/`shopify-jsonld` unchanged: kind archive, baseUrl `https://web.archive.org`, `cdxUrlPattern: <domain>/products/*`, `extractor: shopify-jsonld`, `politeness: {rps: 1.0, timeoutSeconds: 60}`, `contract: {minCount: 0, maxDropPct: 30, requiredFieldRates: {ean: 0.5}}`.

- [ ] Steps: create descriptors + mappings; extend `test_repo_data` coverage implicitly (it globs); EXECUTE both (`--budget 1500` each, sequential — same host, ≤1 rps ≈ 50 min each); classify → resolve → report. GATE: ≥150 archived EANs combined (goblin's structural ~2.6% is the pessimistic floor; these stores' captures are newer). Commit. If yield again lands near-zero, record it and mark archived-Shopify mining as exhausted — that's a real finding, not a retry loop.

---

### Task 4: Fantasywelt — solve enumeration or drop it, with evidence

**Files:** possibly `data/catalog/sources/ret-fantasywelt.yaml` + mapping; possibly a small strategy extension.

Fantasywelt is the largest untapped EAN source (~70k items, `itemprop="gtin13"` confirmed **including accessories**, Cloudflare auto-clears with a real browser). Enumeration is the blocker: its sitemap errored and on-site search is broken.

- [ ] **Step 1: Enumeration recon (timeboxed).** With a real browser, determine the platform (Shopware 6? JTL? — check for `/store-api/`, `/api/`, `window.__` blobs, `sitemap*.xml` variants, category pagination). Try in order: (a) a machine-readable API (Shopware's `/store-api/product` needs a key — check the page JS for one, as we did for Corvus Belli); (b) sitemap variants (`/sitemap.xml`, `/sitemap_index.xml`, `/web/sitemap/...`, gz forms); (c) category-page pagination as a last resort (slower but deterministic). **Timebox: if no enumeration path is found, STOP, write the negative evidence into the research doc, and drop the source** — do not build a fragile category-crawler.
- [ ] **Step 2 (only if enumeration exists):** descriptor + (if needed) a minimal strategy addition reusing `extract.py`'s microdata path; fixtures from real captured pages; TDD as always; EXECUTE budgeted (`--budget 3000`); classify → resolve → report; GATE ≥500 new EANs; commit.

---

### Task 5: Cheap closers (Go-UPC corroboration + CMON metadata)

- [ ] **Go-UPC full sweep** of the 663 `provisional` EANs: `--source bdb-goupc --budget 700` (~45 min at 0.25 rps). Expected ~212 provisional→confirmed. This does NOT change coverage (corroboration only) but hardens confidence. Report the confirmed-count delta. (upcitemdb: 0/77 — do NOT re-run it.)
- [ ] **CMON via headed Playwright** (recon: headed browser clears the challenge that beat headless 3/3): CMON has NO barcodes ever, so this is metadata-only — 320 products, names + product lines + images, filling out a manufacturer where we hold 152 products. Run the existing `playwright-wp` strategy locally with `headless=False` (add the knob if absent: descriptor `scope.headless: false`, defaulting true). Cheap (~11 min). GATE: ≥272 observations. If the headed run also fails, drop CMON permanently and say so.
- [ ] Commit both.

---

### Task 6: Campaign accounting + final review

- [ ] **Coverage report**: a single table — products, with-EAN, coverage %, per-manufacturer — at campaign start (15,348 / 7,801 / 50.8%) vs end. Per-task attribution: which source produced how many new EANs. Write it into `docs/research/2026-07-13-campaign-results.md`.
- [ ] **Honest gate**: the mission's headline metric is EAN coverage. State plainly whether the campaign moved it past 60%, and if not, exactly which buckets remain and why (with store-side evidence, as with Warlord's 43% own-store ceiling).
- [ ] Whole-branch review (most capable model; code-focused package excluding bulk evidence; sample the new evidence), fix wave, PR.

## Execution notes for the controller

- Tasks 1–4 are network-bound and mostly parallelizable **by host**: goblin, tistaminis, radaddel, gamenerdz, web.archive.org, fantasywelt are six distinct hosts — run their harvests concurrently in background, each paced independently. Total wall-clock is dominated by the longest (tistaminis, up to ~20 h).
- Classification runs after each minting wave; the hash cache makes re-runs nearly free for unchanged items.
- Deferred to a future plan (explicitly NOT in scope here): paints migration onto the evidence ledger, retirement of `WarHub.ProductCatalog.Tool` / `WarHub.PaintCatalog.Tool` / `WarHub.CatalogStore`, removal of the legacy `data/products/` tree, and the join-proposal promotions (18 pairs awaiting human adjudication in `data/review/join-proposals.yaml`).
