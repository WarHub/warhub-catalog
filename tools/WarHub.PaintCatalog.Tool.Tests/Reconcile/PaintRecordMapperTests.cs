using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Reconcile;
using Xunit;

namespace WarHub.PaintCatalog.Tool.Tests.Reconcile;

public class PaintRecordMapperTests
{
    private static Paint P(bool discontinued = false) => new()
    {
        Name = "Retributor Armour", ProductCode = "AURIC-1", Set = "Base",
        R = 138, G = 110, B = 62, Hex = "#8A6E3E", VolumeMl = 12,
        Packaging = "pot", Ean = "5011921027330", IsDiscontinued = discontinued,
        Type = "Base", Finish = "Metallic", ImageUrl = "https://img/x.jpg",
    };

    [Fact]
    public void ToRecord_SetsSharedCore_AndNestsDetails()
    {
        PaintRecord r = PaintRecordMapper.ToRecord(P());
        Assert.Equal("Retributor Armour", r.Name);
        Assert.Equal("paint", r.Category);
        Assert.Equal("current", r.Status);
        Assert.Equal("unknown", r.Availability);
        Assert.Null(r.FirstSeen);                 // reconciler stamps it
        Assert.Equal("AURIC-1", r.ProductCode);
        Assert.Equal("5011921027330", r.Ean);
        Assert.Equal("https://img/x.jpg", r.ImageUrl);
        Assert.Equal("Base", r.Details.Set);
        Assert.Equal(12, r.Details.VolumeMl);
        Assert.Equal("pot", r.Details.Container);  // renamed from Packaging
        Assert.Equal("Metallic", r.Details.Finish);
    }

    [Fact]
    public void ToRecord_Discontinued_MapsLifecycle()
    {
        PaintRecord r = PaintRecordMapper.ToRecord(P(discontinued: true));
        Assert.Equal("discontinued", r.Status);
        Assert.Equal("out_of_stock", r.Availability);
    }
}
