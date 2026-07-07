using WarHub.ProductCatalog.Tool.Enrichment;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Tests.Enrichment;

public class ProductEnricherTests
{
    [Fact]
    public void Enrich_BasicProduct_ReturnsEnrichedProduct()
    {
        var raw = new RawProduct
        {
            Name = "  Intercessors  ",
            Sku = "99120101283",
            PriceGbp = 35.00m,
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
            Faction = "Space Marines",
            Status = "current",
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("Intercessors", result.Name);
        Assert.Equal("99120101283", result.Sku);
        Assert.Equal(35.00m, result.PriceGbp);
        Assert.Equal("current", result.Status);
    }

    [Fact]
    public void Enrich_CombatPatrol_ClassifiedCorrectly()
    {
        var raw = new RawProduct
        {
            Name = "Combat Patrol: Space Marines",
            PriceGbp = 85.00m,
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
            Faction = "Space Marines",
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("miniatures", result.Category);
        Assert.Equal("box", result.Packaging);
    }

    [Fact]
    public void Enrich_Battleforce_ClassifiedCorrectly()
    {
        var raw = new RawProduct
        {
            Name = "Battleforce: Necrons Hypercrypt Legion",
            PriceGbp = 130.00m,
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
            Faction = "Necrons",
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("miniatures", result.Category);
        Assert.Equal("box", result.Packaging);
    }

    [Fact]
    public void Enrich_ArmyBox_ClassifiedCorrectly()
    {
        var raw = new RawProduct
        {
            Name = "Army Set: Ironstorm Spearhead",
            PriceGbp = 150.00m,
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
            Faction = "Space Marines",
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("miniatures", result.Category);
        Assert.Equal("box", result.Packaging);
    }

    [Fact]
    public void Enrich_Book_ClassifiedCorrectly()
    {
        var raw = new RawProduct
        {
            Name = "Codex: Space Marines",
            PriceGbp = 35.00m,
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
            Faction = "Space Marines",
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("book", result.Category);
        Assert.Equal("single", result.Packaging);
    }

    [Fact]
    public void Enrich_SingleCharacter_ClassifiedCorrectly()
    {
        var raw = new RawProduct
        {
            Name = "Primaris Captain",
            PriceGbp = 22.50m,
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
            Faction = "Space Marines",
            Contents = [new ProductUnit { UnitName = "Primaris Captain", Quantity = 1, BaseSize = "40mm" }],
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("miniatures", result.Category);
        Assert.Equal("single", result.Packaging);
    }

    [Fact]
    public void Enrich_MultiUnitSet_ClassifiedAsBoxSet()
    {
        var raw = new RawProduct
        {
            Name = "Some Box Set",
            PriceGbp = 50.00m,
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
            Faction = "Space Marines",
            Contents =
            [
                new ProductUnit { UnitName = "Unit A", Quantity = 5 },
                new ProductUnit { UnitName = "Unit B", Quantity = 3 },
            ],
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("miniatures", result.Category);
        Assert.Equal("box", result.Packaging);
    }

    [Fact]
    public void Enrich_ExplicitProductType_PreservesIt()
    {
        var raw = new RawProduct
        {
            Name = "Something",
            ProductType = "terrain",
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("terrain", result.Category);
        Assert.Equal("single", result.Packaging);
    }

    [Fact]
    public void Enrich_DiscontinuedStatus_NormalizedCorrectly()
    {
        var raw = new RawProduct
        {
            Name = "Old Kit",
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
            Status = "No Longer Available",
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("discontinued", result.Status);
    }

    [Fact]
    public void Enrich_NullStatus_DefaultsToCurrent()
    {
        var raw = new RawProduct
        {
            Name = "New Kit",
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("current", result.Status);
    }

    [Fact]
    public void Enrich_HighPriceSingleKit_ClassifiedAsBoxSet()
    {
        var raw = new RawProduct
        {
            Name = "Expensive Something",
            PriceGbp = 120.00m,
            Manufacturer = "Games Workshop",
            GameSystem = "Warhammer 40,000",
        };

        Product result = ProductEnricher.Enrich(raw);

        Assert.Equal("miniatures", result.Category);
        Assert.Equal("box", result.Packaging);
    }
}
