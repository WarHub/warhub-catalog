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
    public void Apply_KeepsAdditionalEans_FromTheBarcodeFile()
    {
        // 9 Citadel sprays are sold under two concurrent regional trade SKUs (R/O Europe + UK/ROW,
        // one shared SSC code). Both barcodes are live; the second used to be dropped at parse
        // because PaintOverride had no AdditionalEans, so a scan of the UK/ROW pot resolved to
        // nothing.
        string path = WriteTemp("""
            citadel-colour:
              "Averland Sunset|Base":
                ean: "5011921172221"
                additionalEans:
                  - "5011921175291"
            """);
        try
        {
            IReadOnlyList<Paint> result = BarcodeEnricher.Apply(SamplePaints, "citadel-colour", path);
            Paint averland = result.Single(p => p.Name == "Averland Sunset");
            Assert.Equal("5011921172221", averland.Ean);
            Assert.Equal(["5011921175291"], averland.AdditionalEans);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void Apply_KeepsFilePrimary_WhenPaintAlreadyHasADifferentEan()
    {
        // Abaddon Black already carries a hand-set Ean, which still wins the primary slot -- but
        // the file's own barcode must not vanish just because it lost that contest.
        string path = WriteTemp("""
            citadel-colour:
              "Abaddon Black|Base":
                ean: "5011921172221"
            """);
        try
        {
            IReadOnlyList<Paint> result = BarcodeEnricher.Apply(SamplePaints, "citadel-colour", path);
            Paint abaddon = result.Single(p => p.Name == "Abaddon Black");
            Assert.Equal("5011921000000", abaddon.Ean);
            Assert.Equal(["5011921172221"], abaddon.AdditionalEans);
        }
        finally { File.Delete(path); }
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
