using WarHub.ProductCatalog.Tool.Scraping;

namespace WarHub.ProductCatalog.Tool.Tests;

public class AlgoliaProductSourceTests
{
    [Fact]
    public void MapToRawProduct_WithValidHit_ReturnsProduct()
    {
        var hit = new AlgoliaHit
        {
            Name = "Intercessors",
            Sku = "99120101001",
            Slug = "space-marines-intercessors-2024",
            Price = 42.5m,
            Description = "A squad of 10 Intercessors.",
            ProductType = "miniatureKit",
            IsInStock = true,
            IsAvailable = true,
            ObjectID = "OBJ-123",
            Images = ["/app/resources/catalog/product/920x950/intercessors.jpg"],
            GameSystemsRoot = new()
            {
                ["lvl0"] = ["Warhammer 40,000"],
                ["lvl1"] = ["Warhammer 40,000 > Space Marines"],
                ["lvl2"] = ["Warhammer 40,000 > Space Marines > Unit Type"],
                ["lvl3"] = ["Warhammer 40,000 > Space Marines > Unit Type > Infantry"],
            },
        };

        var result = AlgoliaProductSource.MapToRawProduct(hit);

        Assert.NotNull(result);
        Assert.Equal("Intercessors", result.Name);
        Assert.Equal("99120101001", result.Sku);
        Assert.Equal("OBJ-123", result.ProductCode);
        Assert.Equal(42.5m, result.PriceGbp);
        Assert.Equal("https://www.warhammer.com/en-GB/shop/space-marines-intercessors-2024", result.Url);
        Assert.Equal("https://www.warhammer.com/app/resources/catalog/product/920x950/intercessors.jpg", result.ImageUrl);
        Assert.Equal("Games Workshop", result.Manufacturer);
        Assert.Equal("Warhammer 40,000", result.GameSystem);
        Assert.Equal("Space Marines", result.Faction);
        Assert.Equal("current", result.Status);
    }

    [Fact]
    public void MapToRawProduct_WithNullName_ReturnsNull()
    {
        var hit = new AlgoliaHit { Name = null };
        Assert.Null(AlgoliaProductSource.MapToRawProduct(hit));
    }

    [Fact]
    public void MapToRawProduct_WithEmptyName_ReturnsNull()
    {
        var hit = new AlgoliaHit { Name = "  " };
        Assert.Null(AlgoliaProductSource.MapToRawProduct(hit));
    }

    [Theory]
    [InlineData(true, false, false, false, false, false, "pre_order")]
    [InlineData(false, false, true, false, false, true, "limited")]
    [InlineData(false, false, false, true, false, true, "limited")]
    [InlineData(false, false, false, false, true, true, "limited")]
    [InlineData(false, false, false, false, false, false, "discontinued")]
    [InlineData(false, true, false, false, false, true, "current")]
    [InlineData(false, false, false, false, false, true, "out_of_stock")]
    public void DetermineStatus_ReturnsCorrectStatus(
        bool isPreOrder, bool isInStock, bool isLastChance,
        bool isMadeToOrder, bool isStocksLast, bool isAvailable,
        string expected)
    {
        var hit = new AlgoliaHit
        {
            IsPreOrder = isPreOrder,
            IsInStock = isInStock,
            IsLastChanceToBuy = isLastChance,
            IsMadeToOrder = isMadeToOrder,
            IsAvailableWhileStocksLast = isStocksLast,
            IsAvailable = isAvailable,
        };

        Assert.Equal(expected, AlgoliaProductSource.DetermineStatus(hit));
    }

    [Theory]
    [InlineData("Warhammer 40,000 > Space Marines > Unit Type > Infantry", "Space Marines")]
    [InlineData("Age of Sigmar > Stormcast Eternals", "Stormcast Eternals")]
    [InlineData("The Horus Heresy > Legiones Astartes > Troops", "Legiones Astartes")]
    [InlineData("Middle-Earth > The Lord of the Rings™ - Good", "The Lord of the Rings™ - Good")]
    [InlineData("The Old World > Empire of Man > Character", "Empire of Man")]
    public void ExtractFaction_ParsesHierarchyCorrectly(string hierarchy, string expectedFaction)
    {
        Assert.Equal(expectedFaction, AlgoliaProductSource.ExtractFaction(hierarchy));
    }

    [Theory]
    [InlineData("Warhammer 40,000", "Warhammer 40,000")]
    [InlineData("Age of Sigmar", "Age of Sigmar")]
    [InlineData("Horus Heresy", "The Horus Heresy")]
    [InlineData("Middle-earth", "Middle-Earth")]
    [InlineData("The Old World", "The Old World")]
    [InlineData("Other Games", "Other Games")]
    public void MapGameSystem_MapsCorrectly(string input, string expected)
    {
        Assert.Equal(expected, AlgoliaProductSource.MapGameSystem(input));
    }

    [Theory]
    [InlineData("The Horus Heresy", "Horus Heresy")]
    [InlineData("Middle-Earth", "Middle-earth")]
    [InlineData("The Old World", "The Old World")]
    [InlineData("Other Games", "Other Games")]
    public void MapAlgoliaGameSystem_MapsCorrectly(string algolia, string expected)
    {
        Assert.Equal(expected, AlgoliaProductSource.MapAlgoliaGameSystem(algolia));
    }

    [Fact]
    public void ClassifyAlgoliaProductType_CombatPatrol()
    {
        var hit = new AlgoliaHit { Name = "Combat Patrol: Space Marines" };
        Assert.Equal("combat_patrol", AlgoliaProductSource.ClassifyAlgoliaProductType(hit));
    }

    [Fact]
    public void ClassifyAlgoliaProductType_Battleforce()
    {
        var hit = new AlgoliaHit { Name = "Battleforce: Orks - Green Tide" };
        Assert.Equal("battleforce", AlgoliaProductSource.ClassifyAlgoliaProductType(hit));
    }

    [Fact]
    public void ClassifyAlgoliaProductType_VehicleFromHierarchy()
    {
        var hit = new AlgoliaHit
        {
            Name = "Rhino",
            GameSystemsRoot = new()
            {
                ["lvl0"] = ["Warhammer 40,000"],
                ["lvl3"] = ["Warhammer 40,000 > Space Marines > Unit Type > Vehicle"],
            },
        };
        Assert.Equal("vehicle", AlgoliaProductSource.ClassifyAlgoliaProductType(hit));
    }

    [Fact]
    public void ClassifyAlgoliaProductType_CharacterFromHierarchy()
    {
        var hit = new AlgoliaHit
        {
            Name = "Captain Uriel Ventris",
            GameSystemsRoot = new()
            {
                ["lvl0"] = ["Warhammer 40,000"],
                ["lvl3"] = ["Warhammer 40,000 > Space Marines > Unit Type > Character"],
            },
        };
        Assert.Equal("character", AlgoliaProductSource.ClassifyAlgoliaProductType(hit));
    }

    [Fact]
    public void ClassifyAlgoliaProductType_UnknownReturnsNull()
    {
        var hit = new AlgoliaHit { Name = "Intercessors" };
        Assert.Null(AlgoliaProductSource.ClassifyAlgoliaProductType(hit));
    }

    [Theory]
    [InlineData("P-240927-99120113100", "99120113100")]
    [InlineData("P-228993-99120112057", "99120112057")]
    [InlineData("prod5100348-60040199167", "60040199167")]
    [InlineData("P-240864-99861499022", "99861499022")]
    [InlineData("99120101001", "99120101001")]  // Already a plain SKU
    [InlineData("OBJ-123", "123")]  // Short format
    [InlineData(null, null)]
    [InlineData("", null)]
    [InlineData("  ", null)]
    public void ExtractGwSku_ExtractsCorrectly(string? input, string? expected)
    {
        Assert.Equal(expected, AlgoliaProductSource.ExtractGwSku(input));
    }

    [Fact]
    public void MapToRawProduct_WithRealAlgoliaFormat_ExtractsSku()
    {
        var hit = new AlgoliaHit
        {
            Name = "Combat Patrol: Kroot",
            Sku = "P-240927-99120113100",
            Slug = "combat-patrol-kroot-2026",
            Price = 105m,
            ProductType = "miniatureKit",
            IsInStock = true,
            IsAvailable = true,
            ObjectID = "P-240927-99120113100",
            GameSystemsRoot = new()
            {
                ["lvl0"] = ["Warhammer 40,000"],
            },
        };

        var result = AlgoliaProductSource.MapToRawProduct(hit);

        Assert.NotNull(result);
        Assert.Equal("99120113100", result.Sku);  // Extracted GW SKU
        Assert.Equal("P-240927-99120113100", result.ProductCode);  // Full Algolia objectID
    }
}
