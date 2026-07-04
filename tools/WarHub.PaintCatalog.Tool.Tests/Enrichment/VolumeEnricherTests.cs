using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class VolumeEnricherTests
{
    private static Paint MakePaint(string set) => new()
    {
        Name = "Test Paint",
        Set = set,
        R = 100,
        G = 100,
        B = 100,
        Hex = "#646464"
    };

    [Theory]
    [InlineData("Citadel Colour", "Base", 12, "pot")]
    [InlineData("Citadel Colour", "Layer", 12, "pot")]
    [InlineData("Citadel Colour", "Shade", 18, "pot")]
    [InlineData("Citadel Colour", "Contrast", 18, "pot")]
    [InlineData("Citadel Colour", "Technical", 24, "pot")]
    [InlineData("Citadel Colour", "Spray", 400, "spray")]
    [InlineData("Citadel Colour", "Dry", 12, "pot")]
    [InlineData("Citadel Colour", "Air", 12, "pot")]
    public void Enrich_Citadel_CorrectVolume(string brand, string set, int expectedVolume, string expectedPackaging)
    {
        Paint paint = MakePaint(set);

        Paint enriched = VolumeEnricher.Enrich(paint, brand);

        Assert.Equal(expectedVolume, enriched.VolumeMl);
        Assert.Equal(expectedPackaging, enriched.Packaging);
    }

    [Theory]
    [InlineData("Vallejo", "Model Color", 18, "dropper")]
    [InlineData("Vallejo", "Game Color", 18, "dropper")]
    [InlineData("Vallejo", "Model Air", 17, "dropper")]
    [InlineData("Vallejo", "Mecha Color", 17, "dropper")]
    [InlineData("Vallejo", "Metal Color", 32, "dropper")]
    [InlineData("Vallejo", "Xpress Color", 18, "dropper")]
    public void Enrich_Vallejo_CorrectVolume(string brand, string set, int expectedVolume, string expectedPackaging)
    {
        Paint paint = MakePaint(set);

        Paint enriched = VolumeEnricher.Enrich(paint, brand);

        Assert.Equal(expectedVolume, enriched.VolumeMl);
        Assert.Equal(expectedPackaging, enriched.Packaging);
    }

    [Fact]
    public void Enrich_ArmyPainter_18mlDropper()
    {
        Paint paint = MakePaint("Warpaints");

        Paint enriched = VolumeEnricher.Enrich(paint, "Army Painter");

        Assert.Equal(18, enriched.VolumeMl);
        Assert.Equal("dropper", enriched.Packaging);
    }

    [Fact]
    public void Enrich_Monument_22mlDropper()
    {
        Paint paint = MakePaint("Pro Acryl");

        Paint enriched = VolumeEnricher.Enrich(paint, "Monument (Pro Acryl)");

        Assert.Equal(22, enriched.VolumeMl);
        Assert.Equal("dropper", enriched.Packaging);
    }

    [Fact]
    public void Enrich_UnknownBrand_LeavesVolumeNull()
    {
        Paint paint = MakePaint("Unknown Set");

        Paint enriched = VolumeEnricher.Enrich(paint, "Unknown Brand");

        Assert.Null(enriched.VolumeMl);
        Assert.Null(enriched.Packaging);
    }

    [Fact]
    public void Enrich_DiscontinuedSet_StillGetsVolume()
    {
        Paint paint = MakePaint("Foundation (discontinued)");

        Paint enriched = VolumeEnricher.Enrich(paint, "Citadel Colour");

        // VolumeTable should handle stripping "(discontinued)" suffix
        Assert.NotNull(enriched.VolumeMl);
    }

    [Fact]
    public void Enrich_PreservesOtherFields()
    {
        Paint paint = new()
        {
            Name = "Test Paint",
            ProductCode = "70.950",
            Set = "Model Color",
            R = 100,
            G = 100,
            B = 100,
            Hex = "#646464",
            IsDiscontinued = true
        };

        Paint enriched = VolumeEnricher.Enrich(paint, "Vallejo");

        Assert.Equal("Test Paint", enriched.Name);
        Assert.Equal("70.950", enriched.ProductCode);
        Assert.Equal("Model Color", enriched.Set);
        Assert.Equal(100, enriched.R);
        Assert.True(enriched.IsDiscontinued);
    }
}
