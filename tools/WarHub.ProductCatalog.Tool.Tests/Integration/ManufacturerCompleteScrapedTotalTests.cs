using WarHub.CatalogStore.Ledger;
using WarHub.ProductCatalog.Tool.Configuration;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Tests.Integration;

/// <summary>
/// Program.cs is top-level statements with no testable entrypoint (see
/// <see cref="LedgerOrphanGcTests"/>'s remark on the same constraint), so this test
/// file mirrors Program.cs's <c>ComputeManufacturerCompleteScrapedTotals</c> local
/// function and the implausible-drop guard built from it byte-for-byte, to lock in
/// the fix for the bug where the guard was evaluated against a per-faction RUNNING
/// total (<c>mfgScrapedTotals[mfgSlug] + enriched.Count</c>, folded in mid-loop)
/// instead of the manufacturer's COMPLETE scraped total for the run. The running-total
/// version spuriously flagged the first-processed faction of any multi-faction
/// manufacturer as an implausible drop (comparing one faction's count against the
/// full prior manufacturer count), which silently disabled miss-counting/auto-flagging
/// and orphan GC for that faction — and, transitively via prunableSources, for the
/// whole manufacturer in the run's GC.
/// </summary>
public class ManufacturerCompleteScrapedTotalTests
{
    private static RawProduct R(string mfg, string gs, string faction, string name) => new()
    {
        Name = name,
        Manufacturer = mfg,
        GameSystem = gs,
        Faction = faction,
    };

    /// <summary>Mirrors Program.cs's <c>ComputeManufacturerCompleteScrapedTotals</c> exactly:
    /// per-faction-group post-sampling count, summed per manufacturer slug.</summary>
    private static Dictionary<string, int> ComputeManufacturerCompleteScrapedTotals(
        IEnumerable<RawProduct> allRawProducts, int sample)
    {
        var grouped = allRawProducts
            .GroupBy(p => (p.Manufacturer, p.GameSystem, p.Faction ?? "General"));

        var totals = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var group in grouped)
        {
            ManufacturerInfo? mfgInfo = ManufacturerRegistry.GetManufacturer(group.Key.Manufacturer);
            string mfgSlug = mfgInfo?.Slug ?? ManufacturerRegistry.Slugify(group.Key.Manufacturer);
            int groupCount = group.Count();
            int factionScraped = sample > 0 ? Math.Min(sample, groupCount) : groupCount;
            totals[mfgSlug] = totals.GetValueOrDefault(mfgSlug) + factionScraped;
        }
        return totals;
    }

    [Fact]
    public void MultiFactionManufacturer_StableTotal_IsNotImplausibleForAnyFaction()
    {
        // Two factions, 2 + 8 = 10 total this run. Last run's ledger recorded the
        // manufacturer's complete total as 10 too — perfectly stable, no real drop.
        // Deliberately lopsided (2 vs. 8) so the first-processed faction's own slice
        // ("Baratheon", alphabetically first) is small relative to the manufacturer total.
        var raw = new List<RawProduct>();
        for (int i = 0; i < 2; i++) raw.Add(R("CMON", "A Song of Ice and Fire", "Baratheon", $"Baratheon Unit {i}"));
        for (int i = 0; i < 8; i++) raw.Add(R("CMON", "A Song of Ice and Fire", "Stark", $"Stark Unit {i}"));

        Dictionary<string, int> totals = ComputeManufacturerCompleteScrapedTotals(raw, sample: 0);

        string mfgSlug = ManufacturerRegistry.GetManufacturer("CMON")?.Slug ?? ManufacturerRegistry.Slugify("CMON");
        Assert.Equal(10, totals.GetValueOrDefault(mfgSlug));

        const int priorMfgCount = 10;

        // FIXED behavior: both factions of the manufacturer see the same, correct
        // (healthy) verdict, evaluated against the complete total.
        bool implausibleDrop = LedgerMaintenance.IsImplausibleDrop(priorMfgCount, totals.GetValueOrDefault(mfgSlug));
        Assert.False(implausibleDrop);

        // Sanity check demonstrating the bug this fix corrects: under the OLD running-total
        // formula, "Baratheon" (alphabetically first, so processed first by Program.cs's
        // per-faction loop) would have been judged against only its own 2-product slice vs.
        // the FULL prior manufacturer count of 10 — spuriously flagged as an implausible drop,
        // even though the manufacturer as a whole was perfectly stable this run.
        int runningTotalAfterBaratheon = 2;
        bool oldBuggyGuardForBaratheon = LedgerMaintenance.IsImplausibleDrop(priorMfgCount, runningTotalAfterBaratheon);
        Assert.True(oldBuggyGuardForBaratheon,
            "sanity check: the old running-total formula WOULD have spuriously flagged the first-processed faction");
    }

    [Fact]
    public void MultiFactionManufacturer_RealDrop_IsImplausibleForEveryFaction()
    {
        // A real partial/garbled scrape: only 2 of a previously-10-strong manufacturer
        // came back this run, split across two factions (1 each).
        var raw = new List<RawProduct>
        {
            R("CMON", "A Song of Ice and Fire", "Baratheon", "Baratheon Unit 0"),
            R("CMON", "A Song of Ice and Fire", "Stark", "Stark Unit 0"),
        };

        Dictionary<string, int> totals = ComputeManufacturerCompleteScrapedTotals(raw, sample: 0);
        string mfgSlug = ManufacturerRegistry.GetManufacturer("CMON")?.Slug ?? ManufacturerRegistry.Slugify("CMON");
        Assert.Equal(2, totals.GetValueOrDefault(mfgSlug));

        const int priorMfgCount = 10;
        bool implausibleDrop = LedgerMaintenance.IsImplausibleDrop(priorMfgCount, totals.GetValueOrDefault(mfgSlug));

        // Both factions must see the SAME (correctly unhealthy) verdict — no faction gets
        // a free pass just because of processing order.
        Assert.True(implausibleDrop);
    }

    [Fact]
    public void Sampling_IsAppliedPerFactionGroup_BeforeSummingIntoTheManufacturerTotal()
    {
        var raw = new List<RawProduct>();
        for (int i = 0; i < 20; i++) raw.Add(R("CMON", "A Song of Ice and Fire", "Baratheon", $"Baratheon Unit {i}"));
        for (int i = 0; i < 3; i++) raw.Add(R("CMON", "A Song of Ice and Fire", "Stark", $"Stark Unit {i}"));

        // sample=5: Baratheon's 20 clamp to 5, Stark's 3 stay at 3 (min(5,3)) => 8 total.
        Dictionary<string, int> totals = ComputeManufacturerCompleteScrapedTotals(raw, sample: 5);
        string mfgSlug = ManufacturerRegistry.GetManufacturer("CMON")?.Slug ?? ManufacturerRegistry.Slugify("CMON");
        Assert.Equal(8, totals.GetValueOrDefault(mfgSlug));
    }
}
