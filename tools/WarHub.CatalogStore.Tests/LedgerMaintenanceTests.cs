using WarHub.CatalogStore.Ledger;

namespace WarHub.CatalogStore.Tests;

public class LedgerMaintenanceTests
{
    [Theory]
    [InlineData(0, 0, false)]
    [InlineData(100, 90, false)]
    [InlineData(100, 40, true)]
    [InlineData(5, 100, false)]
    public void IsImplausibleDrop_DefaultFraction(int priorCount, int scrapedCount, bool expected)
    {
        Assert.Equal(expected, LedgerMaintenance.IsImplausibleDrop(priorCount, scrapedCount));
    }

    [Fact]
    public void IsImplausibleDrop_CustomFraction_NotImplausible()
    {
        Assert.False(LedgerMaintenance.IsImplausibleDrop(100, 40, 0.3));
    }

    private static LivenessLedger LedgerWith(params string[] keys)
    {
        var l = new LivenessLedger();
        foreach (string key in keys)
            l.Records[key] = new LedgerRecord { LastSeen = "2026-01-01", MissStreak = 0 };
        return l;
    }

    [Fact]
    public void PruneOrphans_RemovesOrphansUnderPrunableSourcesOnly()
    {
        LivenessLedger ledger = LedgerWith("cmon/a/b/x", "cmon/a/b/y", "gw/a/b/z");
        var liveKeys = new HashSet<string> { "cmon/a/b/x" };
        var prunableSources = new HashSet<string> { "cmon" };

        IReadOnlyList<string> removed = LedgerMaintenance.PruneOrphans(ledger, liveKeys, prunableSources);

        Assert.Equal(new[] { "cmon/a/b/y" }, removed);
        Assert.True(ledger.Records.ContainsKey("cmon/a/b/x"));
        Assert.False(ledger.Records.ContainsKey("cmon/a/b/y"));
        Assert.True(ledger.Records.ContainsKey("gw/a/b/z"));
    }

    [Fact]
    public void PruneOrphans_NoPrunableSources_RemovesNothing()
    {
        LivenessLedger ledger = LedgerWith("cmon/a/b/x", "cmon/a/b/y", "gw/a/b/z");
        var liveKeys = new HashSet<string> { "cmon/a/b/x" };
        var prunableSources = new HashSet<string>();

        IReadOnlyList<string> removed = LedgerMaintenance.PruneOrphans(ledger, liveKeys, prunableSources);

        Assert.Empty(removed);
        Assert.Equal(3, ledger.Records.Count);
    }

    [Fact]
    public void PruneOrphans_KeyWithNoSlash_IsGuardedAndUntouched()
    {
        LivenessLedger ledger = LedgerWith("noSlashKey");
        var liveKeys = new HashSet<string>();
        var prunableSources = new HashSet<string> { "noSlashKey" };

        IReadOnlyList<string> removed = LedgerMaintenance.PruneOrphans(ledger, liveKeys, prunableSources);

        Assert.Empty(removed);
        Assert.True(ledger.Records.ContainsKey("noSlashKey"));
    }
}
