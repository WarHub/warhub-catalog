using WarHub.CatalogStore.Ledger;

namespace WarHub.CatalogStore.Tests;

public class LedgerStoreTests
{
    [Fact]
    public async Task LoadAsync_MissingFile_ReturnsEmptyLedger()
    {
        string path = Path.Combine(Path.GetTempPath(), $"missing-{Guid.NewGuid():N}.yaml");
        LivenessLedger ledger = await LedgerStore.LoadAsync(path, default);
        Assert.Equal(1, ledger.SchemaVersion);
        Assert.Empty(ledger.Sources);
        Assert.Empty(ledger.Records);
    }

    [Fact]
    public async Task SaveThenLoad_RoundTrips()
    {
        string path = Path.Combine(Path.GetTempPath(), $"ledger-{Guid.NewGuid():N}.yaml");
        try
        {
            var ledger = new LivenessLedger
            {
                Sources = { ["cmon"] = new LedgerSource { LastRun = "2026-07-07", LastGoodRun = "2026-07-07", LastRunSucceeded = true, ProductCount = 337 } },
                Records = { ["cmon/asoiaf/baratheon/baratheon-wardens"] = new LedgerRecord { LastSeen = "2026-07-07", MissStreak = 0 } },
            };
            await LedgerStore.SaveAsync(path, ledger, default);
            LivenessLedger back = await LedgerStore.LoadAsync(path, default);

            Assert.True(back.Sources["cmon"].LastRunSucceeded);
            Assert.Equal("2026-07-07", back.Records["cmon/asoiaf/baratheon/baratheon-wardens"].LastSeen);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public async Task Save_DoesNotEmitExplodedDates()
    {
        string path = Path.Combine(Path.GetTempPath(), $"ledger-{Guid.NewGuid():N}.yaml");
        try
        {
            var ledger = new LivenessLedger
            {
                Records = { ["k"] = new LedgerRecord { LastSeen = "2026-07-07", MissStreak = 2 } },
            };
            await LedgerStore.SaveAsync(path, ledger, default);
            string yaml = await File.ReadAllTextAsync(path);
            Assert.DoesNotContain("ticks", yaml);
            Assert.DoesNotContain("dayOfWeek", yaml);
            Assert.Contains("lastSeen: '2026-07-07'", yaml);
        }
        finally { File.Delete(path); }
    }
}
