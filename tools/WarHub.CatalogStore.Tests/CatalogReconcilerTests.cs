using WarHub.CatalogStore.Reconcile;

namespace WarHub.CatalogStore.Tests;

public class CatalogReconcilerTests
{
    // Minimal test record + adapter exercising the generic flow.
    private sealed record Rec
    {
        public required string Name { get; init; }
        public string? Url { get; init; }
        public string? Price { get; init; }
        public string? FirstSeen { get; init; }
    }

    private sealed class RecAdapter : ICatalogRecordAdapter<Rec>
    {
        public string IdentityKey(Rec r) => NameNormalizer.Normalize(r.Name);
        public string? Url(Rec r) => r.Url;
        public Rec Merge(Rec existing, Rec fresh) => existing with
        {
            // update-present, keep-on-empty
            Price = string.IsNullOrEmpty(fresh.Price) ? existing.Price : fresh.Price,
            Url = string.IsNullOrEmpty(fresh.Url) ? existing.Url : fresh.Url,
        };
        public Rec WithFirstSeen(Rec r, string isoDate) => r with { FirstSeen = isoDate };
        public bool HasFirstSeen(Rec r) => !string.IsNullOrEmpty(r.FirstSeen);
        public Rec ApplyRename(Rec existing, Rec fresh) => existing with
        {
            Name = fresh.Name,
            Price = string.IsNullOrEmpty(fresh.Price) ? existing.Price : fresh.Price,
        };
    }

    private static readonly Dictionary<string, string> NoAliases = new();
    private static readonly HashSet<string> NoRetract = new();

    private static CatalogReconciler<Rec> NewReconciler() => new(new RecAdapter());

    [Fact]
    public void MissingFromScrape_IsKeptNotDropped()
    {
        var existing = new List<Rec> { new() { Name = "Alpha", FirstSeen = "2026-01-01" } };
        var fresh = new List<Rec>(); // scrape returned nothing

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Single(result.Records);
        Assert.Equal("Alpha", result.Records[0].Name);
        Assert.Empty(result.SeenKeys);
    }

    [Fact]
    public void PartialScrape_DoesNotBlankFields()
    {
        var existing = new List<Rec> { new() { Name = "Alpha", Price = "10", FirstSeen = "2026-01-01" } };
        var fresh = new List<Rec> { new() { Name = "Alpha", Price = null } }; // price missing this run

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal("10", result.Records[0].Price);
        Assert.Contains("alpha", result.SeenKeys);
    }

    [Fact]
    public void UpdatedField_Overwrites()
    {
        var existing = new List<Rec> { new() { Name = "Alpha", Price = "10", FirstSeen = "2026-01-01" } };
        var fresh = new List<Rec> { new() { Name = "Alpha", Price = "12" } };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal("12", result.Records[0].Price);
    }

    [Fact]
    public void NewProduct_GetsFirstSeenToday()
    {
        var existing = new List<Rec>();
        var fresh = new List<Rec> { new() { Name = "Beta" } };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal("2026-07-07", result.Records[0].FirstSeen);
    }

    [Fact]
    public void ExistingFirstSeen_IsPreserved()
    {
        var existing = new List<Rec> { new() { Name = "Alpha", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec> { new() { Name = "Alpha" } };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal("2020-01-01", result.Records[0].FirstSeen);
    }

    [Fact]
    public void UrlMatch_RenamesInsteadOfDuplicating()
    {
        var existing = new List<Rec> { new() { Name = "Old Name", Url = "http://x/1", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec> { new() { Name = "New Name", Url = "http://x/1" } };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Single(result.Records);
        Assert.Equal("New Name", result.Records[0].Name);
        Assert.Equal("2020-01-01", result.Records[0].FirstSeen);
    }

    [Fact]
    public void AliasMap_StitchesRenameWhenUrlDiffers()
    {
        var existing = new List<Rec> { new() { Name = "Old Name", Url = "http://x/1", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec> { new() { Name = "New Name", Url = "http://x/2" } };
        var aliases = new Dictionary<string, string> { ["new name"] = "old name" };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, aliases, NoRetract, "2026-07-07");

        Assert.Single(result.Records);
        Assert.Equal("New Name", result.Records[0].Name);
        Assert.Equal("2020-01-01", result.Records[0].FirstSeen);
    }

    [Fact]
    public void Retract_DropsRecord()
    {
        var existing = new List<Rec> { new() { Name = "Bad", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec>();
        var retract = new HashSet<string> { "bad" };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, retract, "2026-07-07");

        Assert.Empty(result.Records);
    }

    [Fact]
    public void Output_IsSortedByIdentityKey()
    {
        var existing = new List<Rec>();
        var fresh = new List<Rec>
        {
            new() { Name = "Zeta" },
            new() { Name = "Alpha" },
            new() { Name = "Mu" },
        };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal(new[] { "Alpha", "Mu", "Zeta" }, result.Records.Select(r => r.Name).ToArray());
    }

    [Fact]
    public void IdenticalRescrape_IsStable()
    {
        var existing = new List<Rec>
        {
            new() { Name = "Alpha", Price = "10", FirstSeen = "2020-01-01" },
            new() { Name = "Beta", Price = "20", FirstSeen = "2020-01-01" },
        };
        var fresh = new List<Rec>
        {
            new() { Name = "Alpha", Price = "10" },
            new() { Name = "Beta", Price = "20" },
        };

        ReconcileResult<Rec> first = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");
        ReconcileResult<Rec> second = NewReconciler().Reconcile(first.Records, fresh, NoAliases, NoRetract, "2026-07-08");

        Assert.Equal(
            first.Records.Select(r => (r.Name, r.Price, r.FirstSeen)),
            second.Records.Select(r => (r.Name, r.Price, r.FirstSeen)));
    }

    [Fact]
    public void TwoFreshRecordsSharingUrl_DoNotCollapse()
    {
        // Existing A (key "alpha", url u1). Fresh = an update to A (same key, same url)
        // plus a DIFFERENT product B that happens to share the same url.
        var existing = new List<Rec> { new() { Name = "Alpha", Url = "http://x/1", Price = "10", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec>
        {
            new() { Name = "Alpha", Url = "http://x/1", Price = "11" }, // ordinary update, matches by key
            new() { Name = "Beta", Url = "http://x/1", Price = "5" },   // distinct product sharing the url
        };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal(2, result.Records.Count);
        Assert.Contains(result.Records, r => r.Name == "Alpha" && r.Price == "11");
        Assert.Contains(result.Records, r => r.Name == "Beta");
    }

    [Fact]
    public void AliasTarget_AlreadyMatchedByKey_IsNotStolen()
    {
        // Existing A (key "alpha"). Fresh = an update to A (key alpha) plus a record whose
        // alias points at "alpha"; the alias must NOT steal the already-matched A.
        var existing = new List<Rec> { new() { Name = "Alpha", Price = "10", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec>
        {
            new() { Name = "Alpha", Price = "11" },
            new() { Name = "Gamma", Price = "7" },
        };
        var aliases = new Dictionary<string, string> { ["gamma"] = "alpha" };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, aliases, NoRetract, "2026-07-07");

        Assert.Equal(2, result.Records.Count);
        Assert.Contains(result.Records, r => r.Name == "Alpha" && r.Price == "11");
        Assert.Contains(result.Records, r => r.Name == "Gamma");
    }

    [Fact]
    public void SharedUrl_ThiefProcessedFirst_OwnerKeepsHistory_ThiefIsNew()
    {
        // The record that will steal via URL fallback is iterated BEFORE its rightful
        // composite-match owner. The fix must be order-independent: owner keeps its
        // real FirstSeen; the thief becomes a brand-new record, not a rename.
        var existing = new List<Rec> { new() { Name = "Alpha", Url = "http://x/1", Price = "10", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec>
        {
            new() { Name = "Beta", Url = "http://x/1", Price = "5" },   // thief FIRST
            new() { Name = "Alpha", Url = "http://x/1", Price = "11" }, // real owner SECOND
        };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal(2, result.Records.Count);
        Rec alpha = result.Records.Single(r => r.Name == "Alpha");
        Rec beta = result.Records.Single(r => r.Name == "Beta");
        Assert.Equal("2020-01-01", alpha.FirstSeen); // owner keeps real history
        Assert.Equal("11", alpha.Price);
        Assert.Equal("2026-07-07", beta.FirstSeen);  // thief is new, did NOT inherit Alpha's history
    }
}
