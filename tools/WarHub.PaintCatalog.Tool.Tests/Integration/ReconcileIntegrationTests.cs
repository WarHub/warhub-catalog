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
