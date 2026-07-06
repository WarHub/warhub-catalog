using WarHub.CatalogStore.Ledger;

namespace WarHub.CatalogStore.Tests;

public class LivenessUpdaterTests
{
    private static LivenessLedger LedgerWith(params (string Key, int Miss)[] records)
    {
        var l = new LivenessLedger();
        foreach (var (key, miss) in records)
            l.Records[key] = new LedgerRecord { LastSeen = "2026-01-01", MissStreak = miss };
        return l;
    }

    [Fact]
    public void FailedSource_TouchesNoMissCountersAndFlagsNothing()
    {
        LivenessLedger ledger = LedgerWith(("a", 2), ("b", 0));
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: false, scrapedCount: 0,
            seenKeys: new HashSet<string>(), knownKeysForSource: new[] { "a", "b" },
            today: "2026-07-07");

        Assert.Equal(2, result.Ledger.Records["a"].MissStreak);
        Assert.Equal(0, result.Ledger.Records["b"].MissStreak);
        Assert.Empty(result.Flagged);
        Assert.False(result.Ledger.Sources["cmon"].LastRunSucceeded);
        Assert.Equal("2026-07-07", result.Ledger.Sources["cmon"].LastRun);
        Assert.Null(result.Ledger.Sources["cmon"].LastGoodRun);
    }

    [Fact]
    public void SeenKey_ResetsMissStreakAndStampsLastSeen()
    {
        LivenessLedger ledger = LedgerWith(("a", 2));
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: true, scrapedCount: 1,
            seenKeys: new HashSet<string> { "a" }, knownKeysForSource: new[] { "a" },
            today: "2026-07-07");

        Assert.Equal(0, result.Ledger.Records["a"].MissStreak);
        Assert.Equal("2026-07-07", result.Ledger.Records["a"].LastSeen);
        Assert.Equal("2026-07-07", result.Ledger.Sources["cmon"].LastGoodRun);
    }

    [Fact]
    public void UnseenKey_CrossingThreshold_IsFlagged()
    {
        LivenessLedger ledger = LedgerWith(("a", 2)); // 2 -> 3 crosses default threshold 3
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: true, scrapedCount: 5,
            seenKeys: new HashSet<string>(), knownKeysForSource: new[] { "a" },
            today: "2026-07-07");

        Assert.Equal(3, result.Ledger.Records["a"].MissStreak);
        Assert.Contains("a", result.Flagged);
    }

    [Fact]
    public void UnseenKey_BelowThreshold_IsNotFlagged()
    {
        LivenessLedger ledger = LedgerWith(("a", 0));
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: true, scrapedCount: 5,
            seenKeys: new HashSet<string>(), knownKeysForSource: new[] { "a" },
            today: "2026-07-07");

        Assert.Equal(1, result.Ledger.Records["a"].MissStreak);
        Assert.Empty(result.Flagged);
    }

    [Fact]
    public void PreviouslyFlaggedKey_SeenAgain_IsReactivated()
    {
        LivenessLedger ledger = LedgerWith(("a", 5));
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: true, scrapedCount: 5,
            seenKeys: new HashSet<string> { "a" }, knownKeysForSource: new[] { "a" },
            today: "2026-07-07",
            currentlyFlaggedKeys: new HashSet<string> { "a" });

        Assert.Contains("a", result.Reactivated);
        Assert.Equal(0, result.Ledger.Records["a"].MissStreak);
    }

    [Fact]
    public void NewSeenKey_NotPreviouslyKnown_IsRecorded()
    {
        var ledger = new LivenessLedger();
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: true, scrapedCount: 1,
            seenKeys: new HashSet<string> { "new" }, knownKeysForSource: Array.Empty<string>(),
            today: "2026-07-07");

        Assert.Equal(0, result.Ledger.Records["new"].MissStreak);
        Assert.Equal("2026-07-07", result.Ledger.Records["new"].LastSeen);
    }
}
