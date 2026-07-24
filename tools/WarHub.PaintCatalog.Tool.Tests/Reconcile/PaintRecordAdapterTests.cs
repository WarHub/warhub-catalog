using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Reconcile;
using Xunit;

namespace WarHub.PaintCatalog.Tool.Tests.Reconcile;

public class PaintRecordAdapterTests
{
    private static PaintRecord R(string name = "Black", string set = "Base", string? code = "C1",
        string hex = "#000000", string status = "current", string availability = "unknown",
        int? vol = 12, string? finish = "Matte", string? ean = null, string? firstSeen = "2026-01-01") => new()
    {
        Name = name, Category = "paint", Status = status, Availability = availability,
        FirstSeen = firstSeen, ProductCode = code, Ean = ean, ImageUrl = null,
        Details = new PaintDetails { Set = set, R = 0, G = 0, B = 0, Hex = hex, VolumeMl = vol, Container = "pot", Type = "Base", Finish = finish },
    };

    private readonly PaintRecordAdapter _a = new();

    [Fact]
    public void IdentityKey_CombinesSetNameCodeHex_Normalized()
        => Assert.Equal("base|black|c1|#000000", _a.IdentityKey(R(name: "  Black ", set: "Base", code: "C1", hex: "#000000")));

    [Fact]
    public void IdentityKey_DistinguishesSameNameDifferentHex()
        => Assert.NotEqual(_a.IdentityKey(R(hex: "#010101", code: "A")), _a.IdentityKey(R(hex: "#000000", code: "B")));

    [Fact]
    public void Url_IsNull() => Assert.Null(_a.Url(R()));

    [Fact]
    public void Merge_UpdatesPresent_KeepsOnEmpty()
    {
        PaintRecord existing = R(ean: "111", vol: 12, finish: "Matte");
        PaintRecord fresh = R(ean: null, vol: 18, finish: null); // empty ean/finish kept; vol updated
        PaintRecord merged = _a.Merge(existing, fresh);
        Assert.Equal("111", merged.Ean);
        Assert.Equal(18, merged.Details.VolumeMl);
        Assert.Equal("Matte", merged.Details.Finish);
        Assert.Equal("2026-01-01", merged.FirstSeen); // immutable
    }

    [Fact]
    public void Merge_Status_StickyDiscontinued_AgainstFreshCurrent()
    {
        PaintRecord merged = _a.Merge(R(status: "discontinued"), R(status: "current"));
        Assert.Equal("discontinued", merged.Status);
    }

    [Fact]
    public void Merge_Status_FreshDiscontinuedWins()
    {
        PaintRecord merged = _a.Merge(R(status: "current"), R(status: "discontinued"));
        Assert.Equal("discontinued", merged.Status);
    }

    [Fact]
    public void WithFirstSeen_StampsOnlyWhenAbsent()
    {
        Assert.False(_a.HasFirstSeen(R(firstSeen: null)));
        Assert.Equal("2026-07-07", _a.WithFirstSeen(R(firstSeen: null), "2026-07-07").FirstSeen);
        Assert.True(_a.HasFirstSeen(R(firstSeen: "2026-01-01")));
    }

    [Fact]
    public void ApplyRename_AdoptsFreshIdentityFields_KeepsHistory()
    {
        // Colour-backfill alias: an archived colour-less record renamed onto its
        // hex-carrying fresh twin must ADOPT the fresh identity fields (else the stored
        // record disagrees with the key it sits under and the alias must fire forever),
        // while history (FirstSeen) and backfills (Ean) come from the archive side.
        PaintRecord existing = R(hex: "", ean: "111", firstSeen: "2026-07-23");
        PaintRecord fresh = R(hex: "#8A8D91", ean: null, firstSeen: null);
        PaintRecord renamed = _a.ApplyRename(existing, fresh);

        Assert.Equal("#8A8D91", renamed.Details.Hex);
        Assert.Equal("111", renamed.Ean);
        Assert.Equal("2026-07-23", renamed.FirstSeen);
        Assert.Equal(_a.IdentityKey(fresh), _a.IdentityKey(renamed)); // record matches its new key
    }

    [Fact]
    public void ApplyRename_PureNameRename_OnlyChangesName()
    {
        PaintRecord existing = R(name: "Old Name", firstSeen: "2026-01-01");
        PaintRecord fresh = R(name: "New Name", firstSeen: null);
        PaintRecord renamed = _a.ApplyRename(existing, fresh);
        Assert.Equal("New Name", renamed.Name);
        Assert.Equal("2026-01-01", renamed.FirstSeen);
        Assert.Equal(_a.IdentityKey(fresh), _a.IdentityKey(renamed));
    }
}
