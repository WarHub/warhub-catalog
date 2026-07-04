using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class PaintTypeClassifierTests
{
    private static Paint MakePaint(string set, string name = "Test Paint") => new()
    {
        Name = name,
        Set = set,
        R = 100,
        G = 100,
        B = 100,
        Hex = "#646464"
    };

    [Theory]
    [InlineData("Base", "Base")]
    [InlineData("Layer", "Layer")]
    [InlineData("Shade", "Shade")]
    [InlineData("Contrast", "Contrast")]
    [InlineData("Dry", "Dry")]
    [InlineData("Air", "Air")]
    [InlineData("Technical", "Technical")]
    [InlineData("Spray", "Spray")]
    [InlineData("Glaze", "Glaze")]
    [InlineData("Edge", "Layer")]
    [InlineData("Foundation", "Base")]
    public void Classify_Citadel_MapsSetToType(string set, string expectedType)
    {
        Paint paint = MakePaint(set);

        Paint enriched = PaintTypeClassifier.Enrich(paint, "Citadel Colour");

        Assert.Equal(expectedType, enriched.Type);
    }

    [Theory]
    [InlineData("Model Color", "Standard")]
    [InlineData("Game Color", "Standard")]
    [InlineData("Model Air", "Air")]
    [InlineData("Game Air", "Air")]
    [InlineData("Metal Color", "Metallic")]
    [InlineData("Liquid Gold", "Metallic")]
    [InlineData("Xpress Color", "Contrast")]
    [InlineData("Surface Primer", "Primer")]
    [InlineData("Game Color Special FX", "Technical")]
    public void Classify_Vallejo_MapsSetToType(string set, string expectedType)
    {
        Paint paint = MakePaint(set);

        Paint enriched = PaintTypeClassifier.Enrich(paint, "Vallejo");

        Assert.Equal(expectedType, enriched.Type);
    }

    [Theory]
    [InlineData("Warpaints", "Standard")]
    [InlineData("Warpaints Fanatic", "Standard")]
    [InlineData("Speedpaint", "Speedpaint")]
    [InlineData("Washes", "Wash")]
    public void Classify_ArmyPainter_MapsSetToType(string set, string expectedType)
    {
        Paint paint = MakePaint(set);

        Paint enriched = PaintTypeClassifier.Enrich(paint, "Army Painter");

        Assert.Equal(expectedType, enriched.Type);
    }

    [Fact]
    public void Classify_TurboDork_Turboshift_IsColorshift()
    {
        Paint paint = MakePaint("Turboshift");

        Paint enriched = PaintTypeClassifier.Enrich(paint, "Turbo Dork");

        Assert.Equal("Colorshift", enriched.Type);
    }

    [Theory]
    [InlineData("Bone Wash", "Wash")]
    [InlineData("Blue Glaze", "Glaze")]
    [InlineData("Abyss Blue", "Standard")]
    public void Classify_TwoThinCoats_DetectsFromName(string name, string expectedType)
    {
        Paint paint = MakePaint("Acrylic", name);

        Paint enriched = PaintTypeClassifier.Enrich(paint, "Two Thin Coats");

        Assert.Equal(expectedType, enriched.Type);
    }

    [Fact]
    public void Classify_DiscontinuedSet_StillClassifies()
    {
        Paint paint = MakePaint("Foundation (discontinued)");

        Paint enriched = PaintTypeClassifier.Enrich(paint, "Citadel Colour");

        Assert.Equal("Base", enriched.Type);
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
            IsDiscontinued = true,
            VolumeMl = 18,
            Packaging = "dropper"
        };

        Paint enriched = PaintTypeClassifier.Enrich(paint, "Vallejo");

        Assert.Equal("Test Paint", enriched.Name);
        Assert.Equal("70.950", enriched.ProductCode);
        Assert.Equal(18, enriched.VolumeMl);
        Assert.Equal("dropper", enriched.Packaging);
        Assert.True(enriched.IsDiscontinued);
        Assert.Equal("Standard", enriched.Type);
    }

    [Theory]
    [InlineData("AK Interactive", "Standard")]
    [InlineData("AK Real Color", "Standard")]
    [InlineData("Scale75", "Standard")]
    [InlineData("Monument (Pro Acryl)", "Standard")]
    [InlineData("Kimera Kolors", "Standard")]
    [InlineData("Reaper", "Standard")]
    [InlineData("P3 (Privateer Press)", "Standard")]
    [InlineData("Tamiya", "Standard")]
    [InlineData("Humbrol", "Standard")]
    [InlineData("Foundry", "Standard")]
    [InlineData("Mission Models", "Standard")]
    public void Classify_GenericSet_DefaultsToStandard(string brand, string expectedType)
    {
        Paint paint = MakePaint("Some Set");

        Paint enriched = PaintTypeClassifier.Enrich(paint, brand);

        Assert.Equal(expectedType, enriched.Type);
    }

    [Fact]
    public void Classify_GreenStuffWorld_Metallic_IsMetallic()
    {
        Paint paint = MakePaint("Metallic Paints");

        Paint enriched = PaintTypeClassifier.Enrich(paint, "Green Stuff World");

        Assert.Equal("Metallic", enriched.Type);
    }

    [Fact]
    public void Classify_Ammo_Wash_IsWash()
    {
        Paint paint = MakePaint("Panel Washes");

        Paint enriched = PaintTypeClassifier.Enrich(paint, "AMMO by Mig Jimenez");

        Assert.Equal("Wash", enriched.Type);
    }

    [Fact]
    public void Classify_GenericFallback_WashSet()
    {
        string? type = PaintTypeClassifier.Classify("Unknown Brand", "Washes", "Test");

        Assert.Equal("Wash", type);
    }

    [Fact]
    public void Classify_GenericFallback_AirSet()
    {
        string? type = PaintTypeClassifier.Classify("Unknown Brand", "Airbrush Color", "Test");

        Assert.Equal("Air", type);
    }
}
