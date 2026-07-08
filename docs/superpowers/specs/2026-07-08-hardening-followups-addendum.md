# Addendum — Storage-model hardening & follow-ups

**Date:** 2026-07-08
**Parent spec:** `2026-07-07-catalog-storage-model-design.md`
**Follows:** Plans 1–3 (products, paints, publisher). This is Plan 4 of the stack.
**Status:** Approved (user scope decisions)

Plans 1–3 delivered the append-only storage model end to end. During their reviews we logged a set
of deferred follow-ups. This addendum records the **scope** the user chose for a dedicated hardening
stacked PR and the **design approach** for each in-scope item. The "frozen core" constraint of Plans
1–3 lifts here: Plan 4 may touch `WarHub.CatalogStore`, both tools, and the publisher, and must
re-verify both catalogs.

## In scope

### 1. Deterministic reconciler tiebreak (CatalogStore)
`CatalogReconciler.Reconcile` pre-seeds `consumed` so composite-key matches are order-independent,
but the **URL/alias rename claim** still resolves in `fresh` iteration order: if two fresh records
could each claim one archived record's URL, input order decides which inherits its `firstSeen`.
**Fix:** iterate `fresh` in deterministic identity-key order (`OrderBy(adapter.IdentityKey, Ordinal)`)
so the outcome is independent of input order. Also covers same-key fresh-merge order. This is the
last hole in the "identical input → identical output" contract.

### 2. Serializer regex tightening (CatalogStore)
`QuotingEventEmitter`'s ambiguous-scalar regex has an unbounded date branch
`\d{4}-\d{2}-\d{2}([Tt ].*)?` that over-quotes plain titles like `"2024-01-01 Anniversary Edition"`,
and its hex/octal alternatives lack an optional sign (`-0x1A` isn't quoted). **Fix:** require a time
component after a space (`\d{4}-\d{2}-\d{2}([Tt]\S*|\s+\d{1,2}:\d{2}\S*)?`) and add `[-+]?` to the
hex/octal alternatives. Over-quoting is harmless to correctness but the fix keeps serialized titles
clean. Real dates/timestamps must still quote.

### 3. Minimal source-health guard — "implausible drop" (CatalogStore helper + both tools)
The full structured per-scraper signal is deferred (its own later plan). The **minimal** guard the
user chose: compare this run's scraped count for a source against the ledger's last-good
`ProductCount`; if it dropped implausibly (below a fraction, default **0.5**, of the prior count when
a prior exists), treat the source as **not healthy** this run — it drives no miss-counting and no
auto-flagging. This catches a half-returned/garbled scrape without penalizing genuinely small
sources (no prior ⇒ no guard). No scraper rewrites.

### 4. Ledger orphan GC (CatalogStore helper + both tools)
`_liveness.yaml` never removes records orphaned by a rename or retract, so it grows unbounded.
**Fix:** after reconcile, prune ledger records for a source **only when that source was fully and
healthily scraped this run** — i.e. gated on a **full run** (authoritative, unfiltered, scraping on)
**and** the source passing the §3 health guard. Prune only keys under such sources that are absent
from the run's live key set. A degraded or filtered run prunes nothing (so it can never wipe
rate-limited or un-scraped sources). GC and the health guard compose: a source that fails the guard
is neither miss-flagged nor GC'd.

### 5. Test-coverage fills
- **Paint tool CLI e2e:** the tool's `Program` is top-level statements and its two-phase
  `pendingBrands` accumulation + Shopify in-place update + manifest emission have no test that runs
  the entry path. Extract the root-command action into an internal `PaintCatalogApp.RunAsync(args)`
  (top-level file just calls it), expose via `InternalsVisibleTo`, and add an e2e test that invokes
  it in-process against a tiny `--source` markdown fixture, asserting the emitted brand files +
  ledger. (Mirrors nothing today; closes the realest gap.)
- **`NormalizeAvailability`** gets a direct `[Theory]` table test (currently only indirectly covered).
- **Alias retract-guard:** a `CatalogReconciler` test proving the alias fallback skips a retracted
  target (the URL path has one; the alias branch does not).

### 6. Small cleanups
- Hoist the per-call deserializer in `LoadExistingFactionProductsAsync` to a `static readonly`.
- `LivenessUpdater` iterates `knownKeysForSource` without dedup — a duplicate would double-increment
  a miss streak; add `.Distinct()` (or accept an `IReadOnlySet`).
- `PaintMigrator`'s not-yet-migrated branch inlines `PaintRecordMapper.ToRecord`; DRY it by mapping
  the legacy paint through the shared mapper.

## Out of scope (each its own future effort)

- **Full structured per-scraper health signal** (HTTP health + expected-page markers): Plan 5.
- **Cross-faction move identity** (a product reclassified to another faction loses its prior EAN,
  resets `firstSeen`, leaves a stale dup): needs its own brainstorm/spec — a cross-catalog identity
  story, not a mechanical fix.
- **Publisher hex-aware paint de-dup** (the 8-paint collapse): the current consumer-view de-dup is
  arguably correct; changing it is a product decision, deferred.

## Verification contract

- Full solution green + `-warnaserror` clean.
- **Determinism preserved:** re-running each tool against the real `data/` tree still produces a
  byte-identical result (the tiebreak and regex changes must not alter committed output — confirm
  with a zero-diff re-run), and the GC/health changes must not touch committed data on a normal run.
- Both catalogs re-verified (engine changes affect products and paints).
