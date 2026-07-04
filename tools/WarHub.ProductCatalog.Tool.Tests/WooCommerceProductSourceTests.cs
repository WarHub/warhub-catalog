using WarHub.ProductCatalog.Tool.Scraping;

namespace WarHub.ProductCatalog.Tool.Tests;

public class WooCommerceProductSourceTests
{
    [Fact]
    public void MapToRawProduct_WithValidProduct_ReturnsRawProduct()
    {
        var product = new WooCommerceProduct
        {
            Id = 1,
            Name = "Hundred Kingdoms: Men at Arms",
            Sku = "PBW2101",
            Permalink = "https://eshop.para-bellum.com/product/hundred-kingdoms-men-at-arms/",
            ShortDescription = "<p>A regiment of Men at Arms.</p>",
            IsPurchasable = true,
            IsInStock = true,
            Prices = new WooCommercePrice
            {
                Price = "2999",
                CurrencyCode = "USD",
                CurrencyMinorUnit = 2,
            },
            Images =
            [
                new WooCommerceImage { Src = "https://eshop.para-bellum.com/wp-content/uploads/men-at-arms.jpg" },
            ],
            Categories =
            [
                new WooCommerceCategory { Name = "Conquest", Slug = "conquest" },
                new WooCommerceCategory { Name = "Hundred Kingdoms", Slug = "hundred-kingdoms" },
            ],
        };

        var result = WooCommerceProductSource.MapToRawProduct(product, "Para Bellum", "Conquest");

        Assert.NotNull(result);
        Assert.Equal("Hundred Kingdoms: Men at Arms", result.Name);
        Assert.Equal("PBW2101", result.Sku);
        Assert.Equal(29.99m, result.PriceUsd);
        Assert.Equal("Hundred Kingdoms", result.Faction);
        Assert.Equal("Para Bellum", result.Manufacturer);
        Assert.Equal("Conquest", result.GameSystem);
        Assert.Equal("current", result.Status);
        Assert.Equal("https://eshop.para-bellum.com/product/hundred-kingdoms-men-at-arms/", result.Url);
        Assert.Equal("https://eshop.para-bellum.com/wp-content/uploads/men-at-arms.jpg", result.ImageUrl);
        Assert.Equal("A regiment of Men at Arms.", result.Description);
    }

    [Fact]
    public void MapToRawProduct_WithNullName_ReturnsNull()
    {
        var product = new WooCommerceProduct { Name = null };
        Assert.Null(WooCommerceProductSource.MapToRawProduct(product, "Para Bellum", "Conquest"));
    }

    [Fact]
    public void MapToRawProduct_WithEmptyName_ReturnsNull()
    {
        var product = new WooCommerceProduct { Name = "  " };
        Assert.Null(WooCommerceProductSource.MapToRawProduct(product, "Para Bellum", "Conquest"));
    }

    [Fact]
    public void MapToRawProduct_WithHtmlEntities_DecodesName()
    {
        var product = new WooCommerceProduct
        {
            Name = "W&#8217;adrhŭn: Slingers",
            IsPurchasable = true,
            IsInStock = true,
        };

        var result = WooCommerceProductSource.MapToRawProduct(product, "Para Bellum", "Conquest");

        Assert.NotNull(result);
        Assert.Equal("W\u2019adrhŭn: Slingers", result.Name);
    }

    [Theory]
    [InlineData("2999", "USD", 2, 29.99)]
    [InlineData("10500", "USD", 2, 105.00)]
    [InlineData("599", "USD", 2, 5.99)]
    [InlineData("0", "USD", 2, 0)]
    [InlineData("1000", "JPY", 0, 1000)]
    public void ParseWooCommercePrice_ConvertsFromMinorUnits(
        string priceStr, string currency, int minorUnit, decimal expected)
    {
        var price = new WooCommercePrice
        {
            Price = priceStr,
            CurrencyCode = currency,
            CurrencyMinorUnit = minorUnit,
        };

        decimal? result = WooCommerceProductSource.ParseWooCommercePrice(price);
        Assert.Equal(expected, result);
    }

    [Fact]
    public void ParseWooCommercePrice_WithNullPrice_ReturnsNull()
    {
        Assert.Null(WooCommerceProductSource.ParseWooCommercePrice(null));
    }

    [Fact]
    public void ParseWooCommercePrice_WithEmptyString_ReturnsNull()
    {
        var price = new WooCommercePrice { Price = "" };
        Assert.Null(WooCommerceProductSource.ParseWooCommercePrice(price));
    }

    [Theory]
    [InlineData("Hundred Kingdoms", "Hundred Kingdoms")]
    [InlineData("Spires", "Spires")]
    [InlineData("Dweghom", "Dweghom")]
    [InlineData("City States", "City States")]
    [InlineData("Sorcerer Kings", "Sorcerer Kings")]
    [InlineData("Yoroni", "Yoroni")]
    [InlineData("Weaver Courts", "Weaver Courts")]
    public void ExtractFaction_MatchesKnownFactions(string categoryName, string expectedFaction)
    {
        var categories = new List<WooCommerceCategory>
        {
            new() { Name = "Conquest", Slug = "conquest" },
            new() { Name = categoryName, Slug = categoryName.ToLowerInvariant().Replace(' ', '-') },
        };

        Assert.Equal(expectedFaction, WooCommerceProductSource.ExtractFaction(categories));
    }

    [Fact]
    public void ExtractFaction_WithNoMatchingCategory_ReturnsNull()
    {
        var categories = new List<WooCommerceCategory>
        {
            new() { Name = "Conquest", Slug = "conquest" },
            new() { Name = "Pre-Orders", Slug = "pre-orders" },
        };

        Assert.Null(WooCommerceProductSource.ExtractFaction(categories));
    }

    [Fact]
    public void ExtractFaction_WithEmptyCategories_ReturnsNull()
    {
        Assert.Null(WooCommerceProductSource.ExtractFaction([]));
        Assert.Null(WooCommerceProductSource.ExtractFaction(null));
    }

    [Fact]
    public void DetermineStatus_PreOrder()
    {
        var product = new WooCommerceProduct
        {
            IsPurchasable = true,
            IsInStock = true,
            Categories = [new WooCommerceCategory { Name = "Pre-Orders" }],
        };
        Assert.Equal("pre_order", WooCommerceProductSource.DetermineStatus(product));
    }

    [Fact]
    public void DetermineStatus_Current()
    {
        var product = new WooCommerceProduct
        {
            IsPurchasable = true,
            IsInStock = true,
        };
        Assert.Equal("current", WooCommerceProductSource.DetermineStatus(product));
    }

    [Fact]
    public void DetermineStatus_OutOfStock()
    {
        var product = new WooCommerceProduct
        {
            IsPurchasable = true,
            IsInStock = false,
        };
        Assert.Equal("out_of_stock", WooCommerceProductSource.DetermineStatus(product));
    }

    [Fact]
    public void DetermineStatus_Discontinued()
    {
        var product = new WooCommerceProduct
        {
            IsPurchasable = false,
            IsInStock = false,
        };
        Assert.Equal("discontinued", WooCommerceProductSource.DetermineStatus(product));
    }
}
