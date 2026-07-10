using WarHub.CatalogStore.Ledger;
using WarHub.CatalogStore.Reconcile;
using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Reconcile;

namespace WarHub.ProductCatalog.Tool.Tests.Integration;

/// <summary>
/// Program.cs is top-level statements and has no testable entrypoint (that extraction is
/// a separate task), so these tests exercise the orphan-GC wiring directly: they replicate
/// the exact fragment of Program.cs's per-faction loop that builds ledger keys in the
/// tool's key format ({mfgSlug}/{gsSlug}/{factionSlug}/{identityKey}), accumulates
/// liveKeys/prunableSources, and gates the call to LedgerMaintenance.PruneOrphans on
/// authoritativeRun &amp;&amp; fullRun — mirroring Program.cs's own gate exactly.
/// </summary>
public class LedgerOrphanGcTests
{
    private static Product P(string name) => new()
    {
        Name = name,
        Category = "miniatures",
        Packaging = "single",
        Status = "current",
        FirstSeen = "2026-07-01",
        Availability = "in_stock",
    };

    /// <summary>Mirrors Program.cs's per-faction loop body (reconcile → accumulate
    /// liveKeys/prunableSources → gate the GC call) for a single manufacturer/faction.</summary>
    private static (LivenessLedger Ledger, IReadOnlyList<string> Pruned) RunFactionAndMaybeGc(
        LivenessLedger ledger, string mfgSlug, string gsSlug, string factionSlug,
        IReadOnlyList<Product> existing, IReadOnlyList<Product> fresh,
        bool authoritativeRun, bool fullRun)
    {
        var adapter = new ProductRecordAdapter();
        var reconciler = new CatalogReconciler<Product>(adapter);
        ReconcileResult<Product> reconciled = reconciler.Reconcile(
            existing, fresh.ToList(), new Dictionary<string, string>(), new HashSet<string>(), "2026-07-08");

        var liveKeys = new HashSet<string>(StringComparer.Ordinal);
        var prunableSources = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        if (authoritativeRun)
        {
            var seenKeys = reconciled.SeenKeys
                .Select(k => $"{mfgSlug}/{gsSlug}/{factionSlug}/{k}").ToHashSet(StringComparer.Ordinal);
            var knownKeys = reconciled.Records
                .Select(p => $"{mfgSlug}/{gsSlug}/{factionSlug}/{adapter.IdentityKey(p)}").ToList();

            foreach (string key in knownKeys)
                liveKeys.Add(key);
            prunableSources.Add(mfgSlug); // this faction's source was healthy

            LivenessUpdater.Apply(
                ledger, mfgSlug, sourceSucceeded: true, scrapedCount: fresh.Count,
                seenKeys: seenKeys, knownKeysForSource: knownKeys, today: "2026-07-08");
        }

        IReadOnlyList<string> pruned = [];
        if (authoritativeRun && fullRun)
            pruned = LedgerMaintenance.PruneOrphans(ledger, liveKeys, prunableSources);

        return (ledger, pruned);
    }

    [Fact]
    public void FullAuthoritativeRun_PrunesLedgerKeyWithNoFreshOrArchivedRecord()
    {
        var ledger = new LivenessLedger();
        ledger.Records["cmon/asoiaf/baratheon/wardens"] = new LedgerRecord { LastSeen = "2026-06-01", MissStreak = 0 };
        // No "Halberdiers" in the archive or fresh scrape any more — a true orphan.
        ledger.Records["cmon/asoiaf/baratheon/halberdiers"] = new LedgerRecord { LastSeen = "2026-01-01", MissStreak = 5 };

        var existing = new List<Product> { P("Wardens") };
        var fresh = new List<Product> { P("Wardens") };

        (LivenessLedger result, IReadOnlyList<string> pruned) = RunFactionAndMaybeGc(
            ledger, "cmon", "asoiaf", "baratheon", existing, fresh,
            authoritativeRun: true, fullRun: true);

        Assert.Equal(new[] { "cmon/asoiaf/baratheon/halberdiers" }, pruned);
        Assert.False(result.Records.ContainsKey("cmon/asoiaf/baratheon/halberdiers"));
        Assert.True(result.Records.ContainsKey("cmon/asoiaf/baratheon/wardens"));
    }

    [Fact]
    public void SampledRun_IsNotAuthoritative_PrunesNothing()
    {
        var ledger = new LivenessLedger();
        ledger.Records["cmon/asoiaf/baratheon/halberdiers"] = new LedgerRecord { LastSeen = "2026-01-01", MissStreak = 5 };

        var existing = new List<Product> { P("Wardens") };
        var fresh = new List<Product> { P("Wardens") };

        // A --sample run makes authoritativeRun false in Program.cs, so fullRun is also
        // false (fullRun requires authoritativeRun) — the whole GC block is skipped.
        (LivenessLedger result, IReadOnlyList<string> pruned) = RunFactionAndMaybeGc(
            ledger, "cmon", "asoiaf", "baratheon", existing, fresh,
            authoritativeRun: false, fullRun: false);

        Assert.Empty(pruned);
        Assert.True(result.Records.ContainsKey("cmon/asoiaf/baratheon/halberdiers"));
    }

    [Fact]
    public void ManufacturerFilteredRun_IsAuthoritativeButNotFull_PrunesNothing()
    {
        var ledger = new LivenessLedger();
        ledger.Records["cmon/asoiaf/baratheon/halberdiers"] = new LedgerRecord { LastSeen = "2026-01-01", MissStreak = 5 };

        var existing = new List<Product> { P("Wardens") };
        var fresh = new List<Product> { P("Wardens") };

        // A --manufacturer/--game-system filter keeps authoritativeRun true (it's still a
        // full, live, unsampled scrape of what it did touch) but fullRun false in
        // Program.cs, since only a subset of configured sources ran this pass.
        (LivenessLedger result, IReadOnlyList<string> pruned) = RunFactionAndMaybeGc(
            ledger, "cmon", "asoiaf", "baratheon", existing, fresh,
            authoritativeRun: true, fullRun: false);

        Assert.Empty(pruned);
        Assert.True(result.Records.ContainsKey("cmon/asoiaf/baratheon/halberdiers"));
    }
}
