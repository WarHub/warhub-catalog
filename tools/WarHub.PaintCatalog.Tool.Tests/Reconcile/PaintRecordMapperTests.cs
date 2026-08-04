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

    [Fact]
    public void ToRecord_CarriesPricesAndLineage()
    {
        Paint p = P() with
        {
            PriceGbp = 3.30m, PriceUsd = 5.60m, PriceEur = 4.40m, PriceCad = 7.25m,
            SupersededBy = "Retributor Armour|Contrast",
            Supersedes = ["Shining Gold|Base"],
        };
        PaintRecord r = PaintRecordMapper.ToRecord(p);

        Assert.Equal(3.30m, r.PriceGbp);
        Assert.Equal(5.60m, r.PriceUsd);
        Assert.Equal(4.40m, r.PriceEur);
        Assert.Equal(7.25m, r.PriceCad);
        Assert.Equal("Retributor Armour|Contrast", r.SupersededBy);
        Assert.Equal(["Shining Gold|Base"], r.Supersedes);
    }

    [Fact]
    public void ToRecord_EmptyLineageAndPrice_StayNull_SoTheKeysAreOmitted()
    {
        PaintRecord r = PaintRecordMapper.ToRecord(P() with { Supersedes = [] });
        Assert.Null(r.Supersedes);      // never an empty list -> omitted from the archive YAML
        Assert.Null(r.SupersededBy);
        Assert.Null(r.PriceGbp);
        Assert.Null(r.PriceCad);
    }
}
