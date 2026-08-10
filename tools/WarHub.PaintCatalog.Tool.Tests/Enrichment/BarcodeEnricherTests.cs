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
    public void Apply_ManufacturerVolume_OverwritesTheVolumeTableGuess()
    {
        // The whole point: VolumeEnricher has already stamped the per-set constant (Citadel Air ->
        // 12 ml) before this runs, so a fill-only-when-blank rule could never fire. GW's own SIZE
        // column says 24 and must win. A fill-blanks rule here would leave 53 Citadel paints wrong.
        Paint air = new() { Name = "Averland Sunset", Set = "Air", R = 250, G = 189, B = 0, Hex = "#FABD00", VolumeMl = 12, Packaging = "pot" };
        string path = WriteTemp("""
            citadel-colour:
              "Averland Sunset|Air":
                ean: "5011921182596"
                volumeMl: 24
            """);
        try
        {
            Paint result = BarcodeEnricher.Apply([air], "citadel-colour", path).Single();
            Assert.Equal(24, result.VolumeMl);
            // Packaging is not the manufacturer's to assert here; the table keeps it.
            Assert.Equal("pot", result.Packaging);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void Apply_NoVolumeInFile_LeavesTheTableVolumeAlone()
    {
        // A bridge entry with no volumeMl (blank SIZE column, an older committed file, or two
        // trade SKUs disagreeing — the generator emits nothing rather than pick one) must not
        // blank out the table's value.
        Paint air = new() { Name = "Averland Sunset", Set = "Air", R = 250, G = 189, B = 0, Hex = "#FABD00", VolumeMl = 12 };
        string path = WriteTemp("""
            citadel-colour:
              "Averland Sunset|Air":
                ean: "5011921182596"
            """);
        try
        {
            Assert.Equal(12, BarcodeEnricher.Apply([air], "citadel-colour", path).Single().VolumeMl);
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

    [Fact]
    public void Apply_CarriesTradePrices_ButNeverAvailability()
    {
        // The manufacturer bridge is allowed to quote list prices. It is NOT allowed to imply
        // stock: a trade sheet says what a pot costs, never whether anyone has one.
        string path = WriteTemp("""
            citadel-colour:
              "Averland Sunset|Base":
                ean: "5011921172221"
                priceGbp: 3.30
                priceUsd: 5.60
                priceEur: 4.40
                priceCad: 7.25
                availability: in_stock
            """);
        try
        {
            Paint averland = BarcodeEnricher.Apply(SamplePaints, "citadel-colour", path)
                .Single(p => p.Name == "Averland Sunset");
            Assert.Equal(3.30m, averland.PriceGbp);
            Assert.Equal(5.60m, averland.PriceUsd);
            Assert.Equal(4.40m, averland.PriceEur);
            Assert.Equal(7.25m, averland.PriceCad);
        }
        finally { File.Delete(path); }
    }
}
