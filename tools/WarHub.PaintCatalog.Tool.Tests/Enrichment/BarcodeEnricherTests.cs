using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class BarcodeEnricherTests
{
    private static readonly IReadOnlyList<Paint> SamplePaints =
    [
        new Paint { Name = "Averland Sunset", Set = "Base", R = 250, G = 189, B = 0, Hex = "#FABD00" },
        new Paint { Name = "Abaddon Black", Set = "Base", R = 0, G = 0, B = 0, Hex = "#000000", Ean = "5011921000000" },
    ];

    private static string WriteTemp(string yaml)
    {
        string path = Path.Combine(Path.GetTempPath(), $"barcodes-{Guid.NewGuid():N}.yaml");
        File.WriteAllText(path, yaml);
        return path;
    }

    [Fact]
    public void Apply_NoFile_ReturnsOriginal()
    {
        Assert.Same(SamplePaints, BarcodeEnricher.Apply(SamplePaints, "citadel-colour", null));
        Assert.Same(SamplePaints, BarcodeEnricher.Apply(SamplePaints, "citadel-colour", "/nope.yaml"));
    }

    [Fact]
    public void Apply_FillsEan_ByNameSetKey_ButNotProductCode()
    {
        // Ean backfills; ProductCode must NOT (it is part of the identity key and would re-key the
        // paint), even though the barcode file carries it for reference.
        string path = WriteTemp("""
            citadel-colour:
              "Averland Sunset|Base":
                ean: "5011921185917"
                productCode: "99189950208"
                ssc: "21-01"
            """);
        try
        {
            IReadOnlyList<Paint> result = BarcodeEnricher.Apply(SamplePaints, "citadel-colour", path);
            Paint averland = result.Single(p => p.Name == "Averland Sunset");
            Assert.Equal("5011921185917", averland.Ean);
            Assert.Null(averland.ProductCode);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void Apply_NeverOverwritesAnExistingEan()
    {
        // Abaddon Black already has an EAN; the barcode file must only fill blanks, so a hand
        // override or an already-present value is never clobbered.
        string path = WriteTemp("""
            citadel-colour:
              "Abaddon Black|Base":
                ean: "5011921999999"
            """);
        try
        {
            IReadOnlyList<Paint> result = BarcodeEnricher.Apply(SamplePaints, "citadel-colour", path);
            Assert.Equal("5011921000000", result.Single(p => p.Name == "Abaddon Black").Ean);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void Apply_UnknownBrandOrKey_LeavesPaintUnchanged()
    {
        string path = WriteTemp("""
            citadel-colour:
              "Some Other Paint|Layer":
                ean: "5011921111111"
            """);
        try
        {
            IReadOnlyList<Paint> result = BarcodeEnricher.Apply(SamplePaints, "citadel-colour", path);
            Assert.Null(result.Single(p => p.Name == "Averland Sunset").Ean);
            Assert.Same(SamplePaints, BarcodeEnricher.Apply(SamplePaints, "army-painter", path));
        }
        finally { File.Delete(path); }
    }
}
