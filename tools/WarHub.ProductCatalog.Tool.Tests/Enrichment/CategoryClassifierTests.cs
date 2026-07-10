using WarHub.ProductCatalog.Tool.Enrichment;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Tests.Enrichment;

public class CategoryClassifierTests
{
    private static RawProduct Raw(string name, decimal? gbp = null, List<ProductUnit>? contents = null) => new()
    {
        Name = name,
        Manufacturer = "Games Workshop",
        GameSystem = "Warhammer 40,000",
        PriceGbp = gbp,
        Contents = contents,
    };

    [Theory]
    [InlineData("Battlefield Terrain Set", "terrain", "single")]
    [InlineData("Codex: Space Marines", "book", "single")]
    [InlineData("Combat Patrol: Necrons", "miniatures", "box")]
    [InlineData("Battleforce: Cities of Sigmar", "miniatures", "box")]
    [InlineData("Starter Set", "miniatures", "starter")]
    [InlineData("Paint Set: Base", "paint", "bundle")]
    [InlineData("Intercessors", "miniatures", "single")]
    public void Classify_MapsToCategoryAndPackaging(string name, string category, string packaging)
    {
        var (cat, pack) = CategoryClassifier.Classify(Raw(name));
        Assert.Equal(category, cat);
        Assert.Equal(packaging, pack);
    }

    [Fact]
    public void Classify_HighPricedItem_IsBoxMiniatures()
    {
        var (cat, pack) = CategoryClassifier.Classify(Raw("Big Kit", gbp: 150m));
        Assert.Equal("miniatures", cat);
        Assert.Equal("box", pack);
    }
}
