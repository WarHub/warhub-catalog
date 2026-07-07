using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Reconcile;

namespace WarHub.ProductCatalog.Tool.Tests.Reconcile;

public class ProductRecordAdapterTests
{
    private static Product P(string name, string? ean = null, decimal? usd = null, string? desc = null,
        string? firstSeen = null, string? url = null, string status = "current", string availability = "in_stock") => new()
    {
        Name = name, Category = "miniatures", Packaging = "single", Status = status, Availability = availability,
        FirstSeen = firstSeen, Ean = ean, PriceUsd = usd, Description = desc, Url = url,
    };

    private readonly ProductRecordAdapter _adapter = new();

    [Fact]
    public void IdentityKey_IsNormalizedName()
    {
        Assert.Equal("space marines", _adapter.IdentityKey(P("  Space  Marines ")));
    }

    [Fact]
    public void Merge_UpdatesPresentField()
    {
        Product merged = _adapter.Merge(P("A", usd: 10m), P("A", usd: 12m));
        Assert.Equal(12m, merged.PriceUsd);
    }

    [Fact]
    public void Merge_KeepsArchivedValueWhenFreshIsEmpty()
    {
        Product merged = _adapter.Merge(P("A", ean: "0123", desc: "kept"), P("A", ean: null, desc: null));
        Assert.Equal("0123", merged.Ean);
        Assert.Equal("kept", merged.Description);
    }

    [Fact]
    public void Merge_PreservesFirstSeenAndCategory()
    {
        Product existing = P("A", firstSeen: "2020-01-01") with { Category = "terrain" };
        Product merged = _adapter.Merge(existing, P("A") with { Category = "miniatures" });
        Assert.Equal("2020-01-01", merged.FirstSeen);
        Assert.Equal("terrain", merged.Category);
    }

    [Fact]
    public void WithFirstSeen_StampsDate()
    {
        Assert.Equal("2026-07-07", _adapter.WithFirstSeen(P("A"), "2026-07-07").FirstSeen);
    }

    [Fact]
    public void HasFirstSeen_ReflectsPresence()
    {
        Assert.False(_adapter.HasFirstSeen(P("A")));
        Assert.True(_adapter.HasFirstSeen(P("A", firstSeen: "2020-01-01")));
    }

    [Fact]
    public void ApplyRename_AdoptsNewNameKeepsIdentity()
    {
        Product existing = P("Old", firstSeen: "2020-01-01", url: "http://x/1");
        Product renamed = _adapter.ApplyRename(existing, P("New", usd: 5m, url: "http://x/1"));
        Assert.Equal("New", renamed.Name);
        Assert.Equal("2020-01-01", renamed.FirstSeen);
        Assert.Equal(5m, renamed.PriceUsd);
    }

    [Fact]
    public void Merge_PreservesDelistedStatus_AgainstFreshCurrent()
    {
        Product existing = P("A", status: "delisted");
        Product merged = _adapter.Merge(existing, P("A", status: "current"));
        Assert.Equal("delisted", merged.Status);
    }

    [Fact]
    public void Merge_PreservesSuspectedDiscontinued_AgainstFreshCurrent()
    {
        Product existing = P("A", status: "suspected-discontinued");
        Product merged = _adapter.Merge(existing, P("A", status: "current"));
        Assert.Equal("suspected-discontinued", merged.Status);
    }

    [Fact]
    public void Merge_AllowsFreshStatus_WhenExistingIsNotManaged()
    {
        Product existing = P("A", status: "current");
        Product merged = _adapter.Merge(existing, P("A", status: "discontinued"));
        Assert.Equal("discontinued", merged.Status);
    }

    [Fact]
    public void Merge_Availability_UpdatesPresent()
    {
        Product existing = P("A", availability: "in_stock");
        Product merged = _adapter.Merge(existing, P("A", availability: "out_of_stock"));
        Assert.Equal("out_of_stock", merged.Availability);
    }

    [Fact]
    public void Merge_Availability_KeepsOnEmpty()
    {
        Product existing = P("A", availability: "in_stock");
        Product merged = _adapter.Merge(existing, P("A", availability: ""));
        Assert.Equal("in_stock", merged.Availability);
    }

    [Fact]
    public void Merge_Status_OverrideDelistedWins()
    {
        Product existing = P("A", status: "current");
        Product merged = _adapter.Merge(existing, P("A", status: "delisted"));
        Assert.Equal("delisted", merged.Status);
    }

    [Fact]
    public void Merge_Status_StickyDiscontinued_AgainstFreshCurrent()
    {
        Product existing = P("A", status: "discontinued");
        Product merged = _adapter.Merge(existing, P("A", status: "current"));
        Assert.Equal("discontinued", merged.Status);
    }
}
