using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class HarvestApplierTests
{
    private static readonly IReadOnlyList<Paint> SamplePaints =
    [
        new Paint { Name = "Dead White", Set = "Game Color", ProductCode = "72.001", R = 255, G = 255, B = 255, Hex = "#FFFFFF" },
        new Paint { Name = "Black", Set = "Model Color", ProductCode = "70.950", R = 35, G = 29, B = 29, Hex = "#231D1D", Ean = "8429551709507", ImageUrl = "https://existing/img.jpg" },
    ];

    private static string WriteHarvestDir(string yaml, string fileName = "vallejo.yaml")
    {
        string dir = Path.Combine(Path.GetTempPath(), $"harvest-{Guid.NewGuid():N}");
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, fileName), yaml);
        return dir;
    }

    [Fact]
    public void Load_MissingDirectory_ReturnsEmpty()
    {
        Assert.Empty(HarvestApplier.Load(null));
        Assert.Empty(HarvestApplier.Load(Path.Combine(Path.GetTempPath(), "nope-" + Guid.NewGuid())));
    }

    [Fact]
    public void Load_MalformedFile_IsSkippedNotFatal()
    {
        string dir = WriteHarvestDir(": not [ yaml");
        try
        {
            Assert.Empty(HarvestApplier.Load(dir));
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public void ApplyEnrichment_FillsBlankEanAndImageUrl_NeverOverwrites()
    {
        string dir = WriteHarvestDir("""
            vallejo:
              enrich:
                "Dead White|Game Color":
                  imageUrl: "https://acrylicosvallejo.com/img/72001.jpg"
                  sku: "72.001"
                  source: mfr-vallejo
                "Black|Model Color":
                  ean: "9999999999999"
                  imageUrl: "https://acrylicosvallejo.com/img/70950.jpg"
            """);
        try
        {
            var harvests = HarvestApplier.Load(dir);
            IReadOnlyList<Paint> result = HarvestApplier.ApplyEnrichment(SamplePaints, "vallejo", harvests);

            Paint deadWhite = result.Single(p => p.Name == "Dead White");
            Assert.Equal("https://acrylicosvallejo.com/img/72001.jpg", deadWhite.ImageUrl);
            Assert.Null(deadWhite.Ean); // entry had no ean; sku must never touch ProductCode/Ean
            Assert.Equal("72.001", deadWhite.ProductCode);

            Paint black = result.Single(p => p.Name == "Black");
            Assert.Equal("8429551709507", black.Ean); // existing value wins over harvest
            Assert.Equal("https://existing/img.jpg", black.ImageUrl);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public void ApplyEnrichment_UnknownBrand_ReturnsOriginal()
    {
        string dir = WriteHarvestDir("""
            vallejo:
              enrich:
                "Dead White|Game Color": { imageUrl: "x" }
            """);
        try
        {
            var harvests = HarvestApplier.Load(dir);
            Assert.Same(SamplePaints, HarvestApplier.ApplyEnrichment(SamplePaints, "turbo-dork", harvests));
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public void AppendAdditions_AddsNewPaint_WithEmptyHexAndSkipsExistingIdentity()
    {
        string dir = WriteHarvestDir("""
            vallejo:
              additions:
                - name: Old Copper
                  set: True Metallic Metal
                  productCode: "77.703"
                  imageUrl: "https://acrylicosvallejo.com/img/77703.jpg"
                  source: mfr-vallejo
                - name: Dead White
                  set: Game Color
                  productCode: "72.001"
                - name: ""
                  set: True Metallic Metal
            """);
        try
        {
            var harvests = HarvestApplier.Load(dir);
            IReadOnlyList<Paint> result = HarvestApplier.AppendAdditions(SamplePaints, "vallejo", harvests);

            Assert.Equal(3, result.Count); // 2 existing + Old Copper; duplicate + nameless skipped
            Paint added = result.Single(p => p.Name == "Old Copper");
            Assert.Equal("True Metallic Metal", added.Set);
            Assert.Equal("77.703", added.ProductCode);
            Assert.Equal("", added.Hex);
            Assert.Equal(0, added.R);
            Assert.Equal("https://acrylicosvallejo.com/img/77703.jpg", added.ImageUrl);
            Assert.Single(result, p => p.Name == "Dead White"); // not duplicated
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public void AppendAdditions_NoHarvestForBrand_ReturnsOriginal()
    {
        Assert.Same(SamplePaints, HarvestApplier.AppendAdditions(
            SamplePaints, "vallejo", new Dictionary<string, HarvestApplier.BrandHarvest>()));
    }
}
