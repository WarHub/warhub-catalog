# Storage-Model Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the deferred follow-ups from Plans 1–3: a deterministic reconciler tiebreak, a tightened quoting regex, a minimal source-health "implausible drop" guard, ledger orphan GC, and test-coverage fills — hardening the append-only model without changing committed data.

**Architecture:** Engine-level changes land in the shared `WarHub.CatalogStore` library (reconciler, serializer, ledger helpers) with unit tests, then wire into both tools' `Program.cs`. GC and the health guard are gated so a degraded or filtered run can never wipe or mis-flag records. A testable entrypoint refactor unlocks a real CLI e2e test for the paint tool.

**Tech Stack:** C# / .NET 10, records, YamlDotNet, xUnit, source-generated regex.

## Global Constraints

- Build clean under `dotnet build WarHub.Catalog.slnx -warnaserror` — 0 warnings, 0 errors.
- The "frozen core" rule from Plans 1–3 no longer applies — this plan may modify `WarHub.CatalogStore` and both tools. Engine changes MUST re-verify BOTH catalogs (product + paint tests green).
- **Determinism must be preserved, not altered:** after the reconciler-tiebreak and regex changes, re-running each tool against the real `data/` tree produces a **byte-identical** result (zero git diff). The GC/health changes must not touch committed data on a normal full run against the current tree.
- GC and miss-flagging are **gated on a healthy, full, authoritative run** — a filtered (`--brand`/seed), sampled, skip-scrape, or degraded-source run prunes nothing and flags nothing.
- Design authority: `docs/superpowers/specs/2026-07-08-hardening-followups-addendum.md`.
- Default health fraction = `0.5`; default miss threshold stays `3`.

---

## File Structure

- `tools/WarHub.CatalogStore/Reconcile/CatalogReconciler.cs` — deterministic fresh ordering.
- `tools/WarHub.CatalogStore/QuotingEventEmitter.cs` — tightened regex.
- `tools/WarHub.CatalogStore/Ledger/LivenessUpdater.cs` — `.Distinct()` on known keys.
- `tools/WarHub.CatalogStore/Ledger/LedgerMaintenance.cs` — **new**: `IsImplausibleDrop` + `PruneOrphans`.
- `tools/WarHub.CatalogStore.Tests/*` — unit tests for the above.
- `tools/WarHub.ProductCatalog.Tool/Program.cs`, and the file holding `LoadExistingFactionProductsAsync` (locate it — `Enrichment/ExistingCatalogLoader.cs` or `Program.cs`) — health guard + GC wiring + deserializer hoist.
- `tools/WarHub.ProductCatalog.Tool/Configuration/ManufacturerRegistry.cs` — no source change; its `NormalizeAvailability` gets a table test in Task 7.
- `tools/WarHub.PaintCatalog.Tool/Program.cs` + **new** `PaintCatalogApp.cs` — health guard + GC wiring + testable entrypoint.
- `tools/WarHub.PaintCatalog.Tool/Migration/PaintMigrator.cs` — DRY cleanup.
- Test projects — new tests per task.

---

### Task 1: Deterministic reconciler tiebreak + alias-retract-guard test

**Files:**
- Modify: `tools/WarHub.CatalogStore/Reconcile/CatalogReconciler.cs`
- Test: `tools/WarHub.CatalogStore.Tests/CatalogReconcilerTests.cs`

**Interfaces:** unchanged public signature; only internal iteration order changes.

- [ ] **Step 1: Write failing tests.** In `CatalogReconcilerTests.cs`, add a fake adapter (or reuse the existing test adapter) and:
  - `Reconcile_UrlRename_IsOrderIndependent`: one archived record with URL `u`; two fresh records A and B (distinct identity keys, neither equal to the archived key) that BOTH carry URL `u`. Run `Reconcile` with fresh `[A,B]` and again with `[B,A]`; assert the resulting record set (and which key inherits the archived `firstSeen`) is **identical** across both orders. Before the fix this differs.
  - `Reconcile_Alias_SkipsRetractedTarget`: archived record `old`; alias map `{ new -> old }`; retract set `{ old }`; fresh `[new]`. Assert `new` is NOT stitched onto `old` (not resurrected) and `old` is dropped from output — i.e. the alias fallback honors the retract guard (mirrors the existing URL-path guard test).

- [ ] **Step 2: Run to verify the order test fails** — `dotnet test tools/WarHub.CatalogStore.Tests --filter CatalogReconciler` → the order-independence test FAILS (the retract-guard test may already pass — that's fine, it's a coverage backfill).

- [ ] **Step 3: Make fresh iteration deterministic.** In `Reconcile`, change the two `foreach (T freshRec in fresh)` loops to iterate a pre-sorted sequence:

```csharp
var orderedFresh = fresh.OrderBy(adapter.IdentityKey, StringComparer.Ordinal).ToList();
```

Use `orderedFresh` for BOTH the `consumed` pre-seed loop and the main reconciliation loop (so the pre-seed and the claim order agree). Everything else is unchanged. Add a short comment: `// deterministic order so URL/alias rename claims don't depend on scrape order`.

- [ ] **Step 4: Run tests** — `dotnet test tools/WarHub.CatalogStore.Tests` → all pass (existing + new). Build `-warnaserror` clean.

- [ ] **Step 5: Verify no committed-data churn.** Re-run BOTH tools against the real tree in a scratch output and confirm the reconciler change does not alter output (the final output was already key-sorted, so ordering fresh must not change the merged result for real data). This is validated end-to-end in Task 7's determinism check; note here that no data commit happens.

- [ ] **Step 6: Commit** — `git commit -am "fix(catalogstore): deterministic fresh ordering in reconcile; alias retract-guard test"`

---

### Task 2: Tighten the quoting regex

**Files:**
- Modify: `tools/WarHub.CatalogStore/QuotingEventEmitter.cs`
- Test: `tools/WarHub.CatalogStore.Tests/CatalogSerializerTests.cs`

- [ ] **Step 1: Write failing/So tests** in `CatalogSerializerTests.cs`:
  - `Quotes_RealDate` — `"2026-07-08"` still emitted single-quoted (unchanged behavior).
  - `Quotes_Timestamp` — `"2026-07-08T12:00:00Z"` still quoted.
  - `DoesNotQuote_DatePrefixedTitle` — a product named `"2024-01-01 Anniversary Edition"` is emitted **plain** (not quoted): serialize a record with that value and assert the YAML contains it unquoted.
  - `Quotes_SignedHex` — `"-0x1A"` is quoted (currently isn't).

- [ ] **Step 2: Run to verify the new cases fail** — `--filter CatalogSerializer` → `DoesNotQuote_DatePrefixedTitle` and `Quotes_SignedHex` FAIL.

- [ ] **Step 3: Update the regex.** In `QuotingEventEmitter`, change the `[GeneratedRegex(...)]` pattern:
  - Date branch: replace `\d{4}-\d{2}-\d{2}([Tt ].*)?` with `\d{4}-\d{2}-\d{2}([Tt]\S*|\s+\d{1,2}:\d{2}\S*)?` — a bare space now only triggers quoting when followed by a `HH:MM` time.
  - Hex/octal: `0x[0-9a-fA-F]+` → `[-+]?0x[0-9a-fA-F]+`; `0o[0-7]+` → `[-+]?0o[0-7]+`.
  Keep everything else identical.

- [ ] **Step 4: Run tests** — `--filter CatalogSerializer` → all pass; full `dotnet test tools/WarHub.CatalogStore.Tests` green; build clean.

- [ ] **Step 5: Commit** — `git commit -am "fix(catalogstore): bound quoting date-branch to real times; sign hex/octal"`

---

### Task 3: Ledger maintenance helpers (`IsImplausibleDrop`, `PruneOrphans`) + `.Distinct()`

**Files:**
- Create: `tools/WarHub.CatalogStore/Ledger/LedgerMaintenance.cs`
- Modify: `tools/WarHub.CatalogStore/Ledger/LivenessUpdater.cs`
- Test: `tools/WarHub.CatalogStore.Tests/LedgerMaintenanceTests.cs`

**Interfaces produced (consumed by Tasks 4 & 5):**

```csharp
namespace WarHub.CatalogStore.Ledger;

public static class LedgerMaintenance
{
    /// <summary>True when a source's fresh count dropped implausibly vs its last-good count,
    /// signalling a partial/garbled scrape. No prior (priorCount &lt;= 0) ⇒ never implausible.</summary>
    public static bool IsImplausibleDrop(int priorCount, int scrapedCount, double fraction = 0.5)
        => priorCount > 0 && scrapedCount < priorCount * fraction;

    /// <summary>Removes ledger records under the given healthy-and-fully-scraped sources whose keys
    /// are not in <paramref name="liveKeys"/>. Records under any other source are untouched.
    /// Returns the removed keys. Mutates the ledger in place.</summary>
    public static IReadOnlyList<string> PruneOrphans(
        LivenessLedger ledger, IReadOnlySet<string> liveKeys, IReadOnlySet<string> prunableSources);
}
```

**`PruneOrphans` semantics:** a ledger record key has the form `{sourceKey}/...` (product) or
`{brandSlug}/...` (paint). A key is prunable iff its **first path segment** is in `prunableSources`
AND the full key is not in `liveKeys`. Split on the FIRST `/` to get the source segment.

- [ ] **Step 1: Write failing tests** (`LedgerMaintenanceTests.cs`):
  - `IsImplausibleDrop`: `(0, 0)`→false; `(100, 90)`→false; `(100, 40)`→true; `(100, 40, 0.3)`→false; `(0, 0)` and `(5, 100)`→false.
  - `PruneOrphans_RemovesOrphansUnderPrunableSourcesOnly`: ledger with keys `cmon/a/b/x`, `cmon/a/b/y`, `gw/a/b/z`; liveKeys `{cmon/a/b/x}`; prunableSources `{cmon}` → removes `cmon/a/b/y` (orphan under prunable source), keeps `cmon/a/b/x` (live) and `gw/a/b/z` (source not prunable). Returns `[cmon/a/b/y]`.
  - `PruneOrphans_NoPrunableSources_RemovesNothing`.

- [ ] **Step 2: Run to verify fail** — FAIL.

- [ ] **Step 3: Implement `LedgerMaintenance.cs`** per the semantics above (first-segment split via `key.IndexOf('/')`; guard keys with no `/`). Then in `LivenessUpdater.Apply`, dedup the known keys: change the `foreach (string key in knownKeysForSource)` loop to iterate `knownKeysForSource.Distinct()` (or add `.Distinct()` at the call site — do it in `LivenessUpdater` so all callers are covered), and add a one-line comment noting duplicates would otherwise double-increment a streak.

- [ ] **Step 4: Run tests** — `dotnet test tools/WarHub.CatalogStore.Tests` → all pass; build clean.

- [ ] **Step 5: Commit** — `git commit -am "feat(catalogstore): ledger maintenance helpers (implausible-drop guard, orphan prune)"`

---

### Task 4: Wire health guard + orphan GC into the PRODUCT tool

**Files:**
- Modify: `tools/WarHub.ProductCatalog.Tool/Program.cs`
- Modify: the file holding `LoadExistingFactionProductsAsync` (hoist its deserializer)
- Test: `tools/WarHub.ProductCatalog.Tool.Tests/Integration/*` (add a partial-run-doesn't-GC test)

**Context:** In `Program.cs` the per-faction loop computes `sourceHealthy` and, under `authoritativeRun`, calls `LivenessUpdater.Apply` and accumulates `mfgScrapedTotals`. The ledger is saved once at the end.

- [ ] **Step 1: Health guard.** Where `sourceHealthy` is computed (currently `!degradedManufacturers.Contains(mfgSlug)`), fold in the implausible-drop guard using the ledger's prior count for that manufacturer:

```csharp
int priorCount = ledger.Sources.GetValueOrDefault(mfgSlug)?.ProductCount ?? 0;
bool implausible = LedgerMaintenance.IsImplausibleDrop(priorCount, mfgScrapedTotals.GetValueOrDefault(mfgSlug) + enriched.Count);
bool sourceHealthy = !degradedManufacturers.Contains(mfgSlug) && !implausible;
```

(Compute `implausible` against the manufacturer's full running scraped total — mirror how `scrapedCount` is already accumulated. Ensure the comparison uses the same total passed to `LivenessUpdater.Apply`.) Pass `sourceHealthy` as `sourceSucceeded` (already wired). A source failing the guard now flags nothing.

- [ ] **Step 2: Orphan GC.** Define a `fullRun` gate: `bool fullRun = authoritativeRun && seedOnly == false /* and any --manufacturer/faction filter absent */;` (inspect the actual options; a full run means every source was scraped). Accumulate two things across the faction loop: `liveKeys` (union of `{mfgSlug}/{gsSlug}/{factionSlug}/{identityKey}` for every reconciled record) and `prunableSources` (each `mfgSlug` whose run was `sourceHealthy` this run). After the loop, before `LedgerStore.SaveAsync`, if `fullRun`:

```csharp
IReadOnlyList<string> pruned = LedgerMaintenance.PruneOrphans(ledger, liveKeys, prunableSources);
if (verbose && pruned.Count > 0) Console.WriteLine($"Ledger GC: pruned {pruned.Count} orphaned records.");
```

Gate the whole GC block on `authoritativeRun && fullRun` so a sampled/skip-scrape/filtered run prunes nothing.

- [ ] **Step 3: Deserializer hoist.** In `LoadExistingFactionProductsAsync`, replace the per-call `CatalogSerializer.CreateDeserializer()` with a `static readonly IDeserializer` field reused across calls. (If it lives under top-level statements and a static field is awkward, put it on the containing static class.)

- [ ] **Step 4: Tests.** Add an integration test asserting: a full authoritative run over an archive containing a key with no corresponding fresh product (an orphan) prunes that ledger key; and a `--sample`/filtered run leaves the ledger records intact. Model on `Integration/ReconcileStabilityTests.cs`. Keep all existing product tests green (437).

- [ ] **Step 5: Verify** — `dotnet test tools/WarHub.ProductCatalog.Tool.Tests` green; build `-warnaserror` clean.

- [ ] **Step 6: Commit** — `git commit -am "feat(products): implausible-drop health guard + ledger orphan GC (full-run gated)"`

---

### Task 5: Wire health guard + orphan GC into the PAINT tool

**Files:**
- Modify: `tools/WarHub.PaintCatalog.Tool/Program.cs`
- Test: `tools/WarHub.PaintCatalog.Tool.Tests/Integration/*`

**Context:** The paint finalization pass (Plan 2) already computes `authoritativeRun = sample == 0`, iterates `pendingBrands`, and calls `LivenessUpdater.Apply` with `sourceSucceeded: pending.Succeeded` and `scrapedCount: pending.Paints.Count`. Ledger saved at end under `authoritativeRun`.

- [ ] **Step 1: Health guard.** Before the `LivenessUpdater.Apply` call, compute:

```csharp
int priorCount = ledger.Sources.GetValueOrDefault(brandSlug)?.ProductCount ?? 0;
bool healthy = pending.Succeeded && !LedgerMaintenance.IsImplausibleDrop(priorCount, pending.Paints.Count);
```

Pass `sourceSucceeded: healthy`.

- [ ] **Step 2: Orphan GC.** Define `fullRun = authoritativeRun && string.IsNullOrEmpty(brandFilter);` (a `--brand` run must not GC other brands). Accumulate `liveKeys` (union of `{brandSlug}/{identityKey}` for every reconciled record across all brands) and `prunableSources` (each `brandSlug` that was `healthy` this run). After the finalization loop, before `LedgerStore.SaveAsync`, if `fullRun`, call `LedgerMaintenance.PruneOrphans(ledger, liveKeys, prunableSources)` and log the count under `verbose`.

- [ ] **Step 3: Tests.** Extend `Integration/ReconcileIntegrationTests.cs` (or a new file): a full run that drops a previously-archived paint from the source prunes its ledger key; a `--brand`-filtered scenario prunes nothing for other brands. Keep all 279 paint tests green.

- [ ] **Step 4: Verify** — `dotnet test tools/WarHub.PaintCatalog.Tool.Tests` green; build clean.

- [ ] **Step 5: Commit** — `git commit -am "feat(paints): implausible-drop health guard + ledger orphan GC (full-run gated)"`

---

### Task 6: Paint tool testable entrypoint + CLI e2e test

**Files:**
- Create: `tools/WarHub.PaintCatalog.Tool/PaintCatalogApp.cs`
- Modify: `tools/WarHub.PaintCatalog.Tool/Program.cs` (delegate to the new entrypoint), `tools/WarHub.PaintCatalog.Tool/WarHub.PaintCatalog.Tool.csproj` (`InternalsVisibleTo`)
- Test: `tools/WarHub.PaintCatalog.Tool.Tests/Integration/CliEndToEndTests.cs`

- [ ] **Step 1: Extract the entrypoint.** Move the `RootCommand` construction + `SetAction` body from `Program.cs` into `internal static class PaintCatalogApp { public static Task<int> RunAsync(string[] args); }` (and any `migrate` subcommand). `Program.cs` becomes `return await PaintCatalogApp.RunAsync(args);`. Add `<InternalsVisibleTo Include="WarHub.PaintCatalog.Tool.Tests" />` to the csproj if not already present. This is a pure move — behavior identical.

- [ ] **Step 2: Run the full paint suite to confirm the move changed nothing** — `dotnet test tools/WarHub.PaintCatalog.Tool.Tests` → still 279 green (plus you'll add the e2e next). Build clean.

- [ ] **Step 3: Write the e2e test** (`CliEndToEndTests.cs`): create a temp dir with a `--source` markdown fixture whose filename `BrandRegistry.IsMiniatureBrand`/`GetByFileName` recognizes (inspect `BrandRegistry` for a valid brand filename + the minimal markdown the `MarkdownPaintParser` accepts — reuse the shape `SampleModeTests` already relies on). Invoke `await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir])`; assert exit 0, a `brands/{slug}.yaml` exists in the new archival shape (category/details), and `_liveness.yaml` was written with the brand's records. This exercises the two-phase finalization + write path end to end in-process.

- [ ] **Step 4: Verify** — new e2e passes; full paint suite green; build clean.

- [ ] **Step 5: Commit** — `git commit -am "test(paints): testable entrypoint + CLI end-to-end coverage of the finalization path"`

---

### Task 7: Small cleanups — NormalizeAvailability table test, PaintMigrator DRY

**Files:**
- Test: `tools/WarHub.ProductCatalog.Tool.Tests/Configuration/ManufacturerRegistryTests.cs` (or the neighbouring test file)
- Modify: `tools/WarHub.PaintCatalog.Tool/Migration/PaintMigrator.cs`

- [ ] **Step 1: NormalizeAvailability table test.** Add a `[Theory]`/`[InlineData]` covering every branch of `ManufacturerRegistry.NormalizeAvailability`: `available`/`in stock`/`current`→`in_stock`; `pre-order`/`preorder`→`pre_order`; `limited`/`made to order`→`limited`; `out of stock`/`temporarily out of stock`→`out_of_stock`; `discontinued`/`no longer available`→`out_of_stock`; blank/unknown→`unknown`; plus a case/whitespace variant (`"  In Stock "`). Run it — it should pass (documents + locks the mapping).

- [ ] **Step 2: PaintMigrator DRY.** In `PaintMigrator.ToRecord`, the not-yet-migrated branch currently inlines the `PaintRecordMapper.ToRecord` field mapping. Refactor it to build a flat `Paint` from the `LegacyPaint` and call `PaintRecordMapper.ToRecord(paint)`, then set `FirstSeen = firstSeen` (the mapper leaves it null). Keep the already-migrated branch as-is. This removes the drift risk between the mapper and the migrator. Re-run `dotnet test tools/WarHub.PaintCatalog.Tool.Tests --filter PaintMigrator` → the idempotency + mapping tests still pass (byte-identical output — the mapping must be equivalent; if the migrated bytes change, the mapper and old inline logic differed, which is exactly the bug this prevents — reconcile them and re-verify).

- [ ] **Step 3: Verify** — full solution `dotnet test WarHub.Catalog.slnx` green; build `-warnaserror` clean.

- [ ] **Step 4: Commit** — `git commit -am "test(products): NormalizeAvailability table test; refactor(paints): PaintMigrator reuses the mapper"`

---

## Final verification (before the PR)

- [ ] Full solution: `dotnet test WarHub.Catalog.slnx` green; `dotnet build WarHub.Catalog.slnx -warnaserror` 0/0.
- [ ] **Determinism / no-churn:** run both tools against the real tree into a scratch output (products: reconcile mode; paints: `migrate` is done, so run the normal path) and confirm the engine changes produce **zero** diff against the committed `data/` — i.e. re-serialize is byte-identical. Also confirm a normal full run's only data change is (at most) the expected `_liveness.yaml` (and that GC only removes genuine orphans, of which a clean tree has none → zero ledger churn too).
- [ ] The whole-branch review gates the stacked PR against `catalog-publisher-schema` (Plan 3), not `main`.

## Notes for the executor

- Engine tasks (1–3) affect BOTH catalogs — always run both tool test suites after them, not just CatalogStore.
- GC is deliberately conservative: gated on a full, authoritative, unfiltered run AND per-source health. When in doubt, prune nothing. A wrongly-pruned ledger key would re-appear as a fresh miss-streak (harmless) — but a wrongly-pruned key under a rate-limited source could delay a legitimate flag; the health gate prevents that.
- The reconciler and regex changes MUST NOT change committed output. If Task 1 or 2's real-data re-run shows any diff, stop and reconcile before committing data — there is no data commit in this plan.
