using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class FinishClassifierTests
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
    [InlineData("Base", "Test Paint", "Matte")]
    [InlineData("Layer", "Test Paint", "Matte")]
    [InlineData("Shade", "Test Paint", "Matte")]
    [InlineData("Technical", "Test Paint", "Matte")]
    public void Classify_Citadel_StandardSets_AreMatte(string set, string name, string expectedFinish)
    {
        Paint paint = MakePaint(set, name);

        Paint enriched = FinishClassifier.Enrich(paint, "Citadel Colour");

        Assert.Equal(expectedFinish, enriched.Finish);
    }

    [Theory]
    [InlineData("Metal Color", "Matte")]
    [InlineData("Liquid Gold", "Matte")]
    public void Classify_Vallejo_MetalSets_AreMetallic(string set, string _)
    {
        Paint paint = MakePaint(set);

        Paint enriched = FinishClassifier.Enrich(paint, "Vallejo");

        Assert.Equal("Metallic", enriched.Finish);
    }

    [Theory]
    [InlineData("Retributor Armour", "Metallic")]
    [InlineData("Leadbelcher", "Metallic")]
    [InlineData("Gehenna's Gold", "Metallic")]
    [InlineData("Runelord Brass", "Metallic")]
    [InlineData("Ironbreaker", "Matte")] // "iron" only matches as whole word, not "Ironbreaker"
    public void Classify_Citadel_MetallicNames_DetectedFromName(string name, string expectedFinish)
    {
        Paint paint = MakePaint("Base", name);

        Paint enriched = FinishClassifier.Enrich(paint, "Citadel Colour");

        Assert.Equal(expectedFinish, enriched.Finish);
    }

    [Theory]
    [InlineData("Gold", "Metallic")]
    [InlineData("Silver", "Metallic")]
    [InlineData("Bronze", "Metallic")]
    [InlineData("Copper", "Metallic")]
    [InlineData("Brass", "Metallic")]
    [InlineData("Steel", "Metallic")]
    [InlineData("Chrome", "Metallic")]
    public void Classify_MetallicKeywords_DetectedAcrossBrands(string name, string expectedFinish)
    {
        Paint paint = MakePaint("Standard", name);

        Paint enriched = FinishClassifier.Enrich(paint, "Army Painter");

        Assert.Equal(expectedFinish, enriched.Finish);
    }

    [Theory]
    [InlineData("Turboshift", "Metallic")]
    [InlineData("Flourish", "Metallic")]
    public void Classify_TurboDork_ColorshiftSets_AreMetallic(string set, string expectedFinish)
    {
        Paint paint = MakePaint(set);

        Paint enriched = FinishClassifier.Enrich(paint, "Turbo Dork");

        Assert.Equal(expectedFinish, enriched.Finish);
    }

    [Fact]
    public void Classify_GlossInName_DetectedAsGloss()
    {
        Paint paint = MakePaint("Technical", "'Ardcoat");

        Paint enriched = FinishClassifier.Enrich(paint, "Citadel Colour");

        Assert.Equal("Gloss", enriched.Finish);
    }

    [Fact]
    public void Classify_DefaultFinish_IsMatte()
    {
        Paint paint = MakePaint("Warpaints", "Ultramarine Blue");

        Paint enriched = FinishClassifier.Enrich(paint, "Army Painter");

        Assert.Equal("Matte", enriched.Finish);
    }

    [Fact]
    public void Classify_DiscontinuedSet_StillClassifies()
    {
        Paint paint = MakePaint("Metal Color (discontinued)");

        Paint enriched = FinishClassifier.Enrich(paint, "Vallejo");

        Assert.Equal("Metallic", enriched.Finish);
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
            Type = "Standard",
            VolumeMl = 18
        };

        Paint enriched = FinishClassifier.Enrich(paint, "Vallejo");

        Assert.Equal("Test Paint", enriched.Name);
        Assert.Equal("70.950", enriched.ProductCode);
        Assert.Equal("Standard", enriched.Type);
        Assert.Equal(18, enriched.VolumeMl);
        Assert.Equal("Matte", enriched.Finish);
    }

    [Theory]
    [InlineData("Metallic Paints", "Metallic")]
    [InlineData("Chameleon Paints", "Metallic")]
    public void Classify_GreenStuffWorld_SpecialSets(string set, string expectedFinish)
    {
        Paint paint = MakePaint(set);

        Paint enriched = FinishClassifier.Enrich(paint, "Green Stuff World");

        Assert.Equal(expectedFinish, enriched.Finish);
    }
}
