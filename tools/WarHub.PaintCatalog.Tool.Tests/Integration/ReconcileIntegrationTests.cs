using WarHub.CatalogStore.Ledger;
using WarHub.CatalogStore.Reconcile;
using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Output;
using WarHub.PaintCatalog.Tool.Reconcile;

namespace WarHub.PaintCatalog.Tool.Tests.Integration;

/// <summary>
/// Exercises the same map -> load -> reconcile -> ledger -> write wiring Program.cs's
/// finalization pass performs per brand (see Program.cs), proving the append-only /
/// liveness-ledger contract end to end without needing to spawn the CLI process.
/// Modeled on WarHub.ProductCatalog.Tool.Tests/Integration/ReconcileStabilityTests.cs.
/// </summary>
public class ReconcileIntegrationTests
{
    private static Paint P(string name, string set = "Base", string? code = "0605", string hex = "#000000") => new()
    {
        Name = name, Set = set, ProductCode = code, R = 0, G = 0, B = 0, Hex = hex,
    };

    private static string NewTempDir() =>
        Path.Combine(Path.GetTempPath(), "warhub-paint-reconcile-test", Guid.NewGuid().ToString("N"));

    /// <summary>
    /// Simulates one Program.cs finalization pass for a single brand: map -> load -> reconcile
    /// -> ledger update -> apply transitions -> write. Mirrors Program.cs's per-brand foreach.
    /// </summary>
    private static async Task<LivenessLedger> RunOneBrandAsync(
        string outputDir, string brandSlug, IReadOnlyList<Paint> paints, LivenessLedger ledger,
        string today, bool sourceSucceeded = true)
    {
        var adapter = new PaintRecordAdapter();
        var reconciler = new CatalogReconciler<PaintRecord>(adapter);

        List<PaintRecord> fresh = paints.Select(PaintRecordMapper.ToRecord).ToList();
        string brandFilePath = Path.Combine(outputDir, "brands", $"{brandSlug}.yaml");
        IReadOnlyList<PaintRecord> existing = await BrandArchiveWriter.LoadAsync(brandFilePath);

        var noAliases = new Dictionary<string, string>();
        var noRetract = new HashSet<string>();
        ReconcileResult<PaintRecord> reconciled = reconciler.Reconcile(existing, fresh, noAliases, noRetract, today);

        var seenLedgerKeys = reconciled.SeenKeys.Select(k => $"{brandSlug}/{k}").ToHashSet(StringComparer.Ordinal);
        var knownLedgerKeys = reconciled.Records.Select(p => $"{brandSlug}/{adapter.IdentityKey(p)}").ToList();
        var currentlyFlagged = reconciled.Records
            .Where(p => p.Status == "suspected-discontinued")
            .Select(p => $"{brandSlug}/{adapter.IdentityKey(p)}")
            .ToHashSet(StringComparer.Ordinal);

        LivenessUpdate live = LivenessUpdater.Apply(
            ledger, brandSlug, sourceSucceeded, paints.Count, seenLedgerKeys, knownLedgerKeys, today,
            currentlyFlaggedKeys: currentlyFlagged);

        List<PaintRecord> finalRecords = reconciled.Records.Select(p =>
        {
            string lk = $"{brandSlug}/{adapter.IdentityKey(p)}";
            if (live.Flagged.Contains(lk) && p.Status == "current")
                return p with { Status = "suspected-discontinued", Availability = "unknown" };
            if (live.Reactivated.Contains(lk) && p.Status == "suspected-discontinued")
                return p with { Status = "current" };
            return p;
        }).ToList();

        var archive = new BrandArchive { Brand = brandSlug, BrandSlug = brandSlug, Paints = finalRecords };
        await BrandArchiveWriter.WriteAsync(archive, outputDir);

        return live.Ledger;
    }

    /// <summary>
    /// Simulates Program.cs's whole finalization pass across one or more brands, including the
    /// Task 5 health guard (implausible-drop detection) and full-run-gated orphan GC. Mirrors
    /// Program.cs's foreach over pendingBrands plus the post-loop PruneOrphans call: caller
    /// supplies each brand's fresh paints, whether its source nominally "succeeded" (matching
    /// pending.Succeeded), and any keys to retract this run (matching an overrides-driven
    /// retraction), plus whether this simulated run is a full run (no --sample, no --brand
    /// filter) for GC gating.
    /// </summary>
    private static async Task<LivenessLedger> RunFinalizationPassAsync(
        string outputDir,
        IReadOnlyList<(string BrandSlug, IReadOnlyList<Paint> Paints, bool Succeeded, ISet<string> Retracted)> brands,
        LivenessLedger ledger,
        string today,
        bool fullRun)
    {
        var adapter = new PaintRecordAdapter();
        var reconciler = new CatalogReconciler<PaintRecord>(adapter);

        var priorCounts = ledger.Sources.ToDictionary(
            kvp => kvp.Key, kvp => kvp.Value.ProductCount, StringComparer.OrdinalIgnoreCase);
        var liveLedgerKeys = new HashSet<string>(StringComparer.Ordinal);
        var prunableSources = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var (brandSlug, paints, succeeded, retracted) in brands)
        {
            List<PaintRecord> fresh = paints.Select(PaintRecordMapper.ToRecord).ToList();
            string brandFilePath = Path.Combine(outputDir, "brands", $"{brandSlug}.yaml");
            IReadOnlyList<PaintRecord> existing = await BrandArchiveWriter.LoadAsync(brandFilePath);

            var noAliases = new Dictionary<string, string>();
            ReconcileResult<PaintRecord> reconciled = reconciler.Reconcile(existing, fresh, noAliases, retracted, today);

            var seenLedgerKeys = reconciled.SeenKeys.Select(k => $"{brandSlug}/{k}").ToHashSet(StringComparer.Ordinal);
            var knownLedgerKeys = reconciled.Records.Select(p => $"{brandSlug}/{adapter.IdentityKey(p)}").ToList();
            var currentlyFlagged = reconciled.Records
                .Where(p => p.Status == "suspected-discontinued")
                .Select(p => $"{brandSlug}/{adapter.IdentityKey(p)}")
                .ToHashSet(StringComparer.Ordinal);

            int priorCount = priorCounts.GetValueOrDefault(brandSlug);
            bool healthy = succeeded && !LedgerMaintenance.IsImplausibleDrop(priorCount, paints.Count);

            foreach (string key in knownLedgerKeys)
                liveLedgerKeys.Add(key);
            if (healthy)
                prunableSources.Add(brandSlug);
            else
                prunableSources.Remove(brandSlug);

            LivenessUpdate live = LivenessUpdater.Apply(
                ledger, brandSlug, sourceSucceeded: healthy, scrapedCount: paints.Count,
                seenKeys: seenLedgerKeys, knownKeysForSource: knownLedgerKeys, today: today,
                currentlyFlaggedKeys: currentlyFlagged);
            ledger = live.Ledger;

            List<PaintRecord> finalRecords = reconciled.Records.Select(p =>
            {
                string lk = $"{brandSlug}/{adapter.IdentityKey(p)}";
                if (live.Flagged.Contains(lk) && p.Status == "current")
                    return p with { Status = "suspected-discontinued", Availability = "unknown" };
                if (live.Reactivated.Contains(lk) && p.Status == "suspected-discontinued")
                    return p with { Status = "current" };
                return p;
            }).ToList();

            var archive = new BrandArchive { Brand = brandSlug, BrandSlug = brandSlug, Paints = finalRecords };
            await BrandArchiveWriter.WriteAsync(archive, outputDir);
        }

        if (fullRun)
        {
            LedgerMaintenance.PruneOrphans(ledger, liveLedgerKeys, prunableSources);
        }

        return ledger;
    }

    [Fact]
    public async Task FullRun_DropsPreviouslyArchivedPaint_PrunesLedgerKey()
    {
        string dir = NewTempDir();
        try
        {
            var ledger = new LivenessLedger();
            var abaddon = P("Abaddon Black");
            var mephiston = P("Mephiston Red", code: "0606", hex: "#7d1719");
            var adapter = new PaintRecordAdapter();
            string mephistonKey = "citadel-colour/" + adapter.IdentityKey(PaintRecordMapper.ToRecord(mephiston));
            string abaddonKey = "citadel-colour/" + adapter.IdentityKey(PaintRecordMapper.ToRecord(abaddon));

            // First (full) run: both paints present and healthy.
            ledger = await RunFinalizationPassAsync(
                dir,
                [("citadel-colour", new List<Paint> { abaddon, mephiston }, true, new HashSet<string>())],
                ledger, "2026-07-01", fullRun: true);

            Assert.True(ledger.Records.ContainsKey(mephistonKey));

            // Second (full) run: Mephiston Red is retracted (dropped for good from the source),
            // e.g. via an overrides-driven retraction — the reconciler drops it from the output
            // entirely rather than merely missing it. The remaining source is still healthy
            // (1 of 2 is not an implausible drop at the default 0.5 fraction), so it is
            // prunable, and a full run with no --brand filter runs GC.
            var retracted = new HashSet<string> { adapter.IdentityKey(PaintRecordMapper.ToRecord(mephiston)) };
            ledger = await RunFinalizationPassAsync(
                dir,
                [("citadel-colour", new List<Paint> { abaddon }, true, retracted)],
                ledger, "2026-07-02", fullRun: true);

            Assert.False(ledger.Records.ContainsKey(mephistonKey));
            Assert.True(ledger.Records.ContainsKey(abaddonKey));
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task BrandFilteredRun_PrunesNothing_ForAnyBrand()
    {
        string dir = NewTempDir();
        try
        {
            var ledger = new LivenessLedger();
            var citAbaddon = P("Abaddon Black");
            var citMephiston = P("Mephiston Red", code: "0606", hex: "#7d1719");
            var valGrey = P("Grey Primer", set: "Surface", code: "1", hex: "#888888");
            var valWhite = P("White Primer", set: "Surface", code: "2", hex: "#ffffff");
            var adapter = new PaintRecordAdapter();
            string mephistonKey = "citadel-colour/" + adapter.IdentityKey(PaintRecordMapper.ToRecord(citMephiston));
            string valWhiteKey = "vallejo/" + adapter.IdentityKey(PaintRecordMapper.ToRecord(valWhite));

            // Full run seeds both brands.
            ledger = await RunFinalizationPassAsync(
                dir,
                [
                    ("citadel-colour", new List<Paint> { citAbaddon, citMephiston }, true, new HashSet<string>()),
                    ("vallejo", new List<Paint> { valGrey, valWhite }, true, new HashSet<string>()),
                ],
                ledger, "2026-07-01", fullRun: true);

            Assert.True(ledger.Records.ContainsKey(mephistonKey));
            Assert.True(ledger.Records.ContainsKey(valWhiteKey));

            // A --brand citadel-colour run only touches citadel-colour, and retracts Mephiston
            // Red (which would be prunable under a full run). Because this simulates a
            // --brand-filtered run, fullRun is false, so GC must not run at all — nothing
            // prunes, neither for citadel-colour nor for the wholly-untouched vallejo source.
            var retracted = new HashSet<string> { adapter.IdentityKey(PaintRecordMapper.ToRecord(citMephiston)) };
            ledger = await RunFinalizationPassAsync(
                dir,
                [("citadel-colour", new List<Paint> { citAbaddon }, true, retracted)],
                ledger, "2026-07-02", fullRun: false);

            Assert.True(ledger.Records.ContainsKey(mephistonKey));
            Assert.True(ledger.Records.ContainsKey(valWhiteKey));
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task ImplausibleDrop_MarksSourceUnhealthy_SkipsMissCounting()
    {
        string dir = NewTempDir();
        try
        {
            var ledger = new LivenessLedger();
            var paints = Enumerable.Range(0, 10)
                .Select(i => P($"Paint {i}", code: i.ToString()))
                .ToList();

            ledger = await RunFinalizationPassAsync(
                dir, [("citadel-colour", paints, true, new HashSet<string>())],
                ledger, "2026-07-01", fullRun: true);

            Assert.Equal(10, ledger.Sources["citadel-colour"].ProductCount);
            Assert.True(LedgerMaintenance.IsImplausibleDrop(10, 2));

            // Next run's fresh scrape implausibly collapses to 2 of the 10 (< 50% of prior) —
            // signals a garbled/partial scrape, not 8 real discontinuations.
            var collapsed = paints.Take(2).ToList();
            ledger = await RunFinalizationPassAsync(
                dir, [("citadel-colour", collapsed, true, new HashSet<string>())],
                ledger, "2026-07-02", fullRun: true);

            // Source marked unhealthy this run: LastRunSucceeded false, ProductCount NOT
            // overwritten with the garbled count.
            Assert.False(ledger.Sources["citadel-colour"].LastRunSucceeded);
            Assert.Equal(10, ledger.Sources["citadel-colour"].ProductCount);

            // The 8 missing paints must NOT have their miss streak incremented (no
            // miss-counting while the source is unhealthy) — no risk of them being
            // spuriously auto-flagged toward suspected-discontinued off a bad reading.
            var adapter = new PaintRecordAdapter();
            foreach (Paint missing in paints.Skip(2))
            {
                string key = "citadel-colour/" + adapter.IdentityKey(PaintRecordMapper.ToRecord(missing));
                Assert.True(ledger.Records.TryGetValue(key, out LedgerRecord? rec));
                Assert.Equal(0, rec!.MissStreak);
            }
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task FirstRun_CreatesBrandFileAndLedger()
    {
        string dir = NewTempDir();
        try
        {
            var ledger = new LivenessLedger();
            ledger = await RunOneBrandAsync(
                dir, "citadel-colour",
                [P("Abaddon Black"), P("Mephiston Red", code: "0606", hex: "#7d1719")],
                ledger, "2026-07-07");
            await LedgerStore.SaveAsync(Path.Combine(dir, "_liveness.yaml"), ledger);

            Assert.True(File.Exists(Path.Combine(dir, "brands", "citadel-colour.yaml")));
            Assert.True(File.Exists(Path.Combine(dir, "_liveness.yaml")));

            IReadOnlyList<PaintRecord> loaded =
                await BrandArchiveWriter.LoadAsync(Path.Combine(dir, "brands", "citadel-colour.yaml"));
            Assert.Equal(2, loaded.Count);
            Assert.All(loaded, p => Assert.Equal("2026-07-07", p.FirstSeen));
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task IdenticalSecondRun_ProducesByteIdenticalBrandFile()
    {
        string dir = NewTempDir();
        try
        {
            IReadOnlyList<Paint> paints = [P("Abaddon Black"), P("Mephiston Red", code: "0606", hex: "#7d1719")];

            var ledger = new LivenessLedger();
            ledger = await RunOneBrandAsync(dir, "citadel-colour", paints, ledger, "2026-07-07");
            string first = await File.ReadAllTextAsync(Path.Combine(dir, "brands", "citadel-colour.yaml"));

            // A second, later run against the exact same fresh input must reproduce the same
            // file byte-for-byte (write-once FirstSeen, deterministic ordering, no spurious churn).
            ledger = await RunOneBrandAsync(dir, "citadel-colour", paints, ledger, "2026-07-08");
            string second = await File.ReadAllTextAsync(Path.Combine(dir, "brands", "citadel-colour.yaml"));

            Assert.Equal(first, second);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task FilteredSecondRun_DoesNotDropAbsentRecord()
    {
        string dir = NewTempDir();
        try
        {
            var ledger = new LivenessLedger();
            ledger = await RunOneBrandAsync(
                dir, "citadel-colour",
                [P("Abaddon Black"), P("Mephiston Red", code: "0606", hex: "#7d1719")],
                ledger, "2026-07-07");

            IReadOnlyList<PaintRecord> archived =
                await BrandArchiveWriter.LoadAsync(Path.Combine(dir, "brands", "citadel-colour.yaml"));
            Assert.Equal(2, archived.Count);

            // Simulate a second run where the fresh source only reports one of the two paints
            // (e.g. a filtered/partial run, or a paint temporarily missing from the source).
            // Append-only reconciliation must keep the absent record, not drop it.
            ledger = await RunOneBrandAsync(dir, "citadel-colour", [P("Abaddon Black")], ledger, "2026-07-08");
            IReadOnlyList<PaintRecord> afterPartial =
                await BrandArchiveWriter.LoadAsync(Path.Combine(dir, "brands", "citadel-colour.yaml"));

            Assert.Equal(2, afterPartial.Count);
            Assert.Contains(afterPartial, p => p.Name == "Mephiston Red");
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task RepeatedMisses_AutoFlagsThenReactivatesOnReturn()
    {
        string dir = NewTempDir();
        try
        {
            var ledger = new LivenessLedger();
            var both = new List<Paint> { P("Abaddon Black"), P("Mephiston Red", code: "0606", hex: "#7d1719") };
            var onlyOne = new List<Paint> { P("Abaddon Black") };

            ledger = await RunOneBrandAsync(dir, "citadel-colour", both, ledger, "2026-07-01");
            // Miss it three times in a row to cross the default missThreshold (3).
            ledger = await RunOneBrandAsync(dir, "citadel-colour", onlyOne, ledger, "2026-07-02");
            ledger = await RunOneBrandAsync(dir, "citadel-colour", onlyOne, ledger, "2026-07-03");
            ledger = await RunOneBrandAsync(dir, "citadel-colour", onlyOne, ledger, "2026-07-04");

            IReadOnlyList<PaintRecord> flaggedState =
                await BrandArchiveWriter.LoadAsync(Path.Combine(dir, "brands", "citadel-colour.yaml"));
            PaintRecord mephiston = Assert.Single(flaggedState, p => p.Name == "Mephiston Red");
            Assert.Equal("suspected-discontinued", mephiston.Status);
            Assert.Equal("unknown", mephiston.Availability);

            // It reappears in the source: reactivate back to current.
            ledger = await RunOneBrandAsync(dir, "citadel-colour", both, ledger, "2026-07-05");
            IReadOnlyList<PaintRecord> reactivatedState =
                await BrandArchiveWriter.LoadAsync(Path.Combine(dir, "brands", "citadel-colour.yaml"));
            PaintRecord mephistonAgain = Assert.Single(reactivatedState, p => p.Name == "Mephiston Red");
            Assert.Equal("current", mephistonAgain.Status);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }
}
