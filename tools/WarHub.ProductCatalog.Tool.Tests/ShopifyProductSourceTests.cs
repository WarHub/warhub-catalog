using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Scraping;

namespace WarHub.ProductCatalog.Tool.Tests;

public class ShopifyProductSourceTests
{
    [Theory]
    [InlineData("29.99", 29.99)]
    [InlineData("105.00", 105.00)]
    [InlineData("5.99", 5.99)]
    [InlineData("0.00", 0)]
    [InlineData("1000.50", 1000.50)]
    public void ParsePrice_WithValidPrices_ReturnsParsedDecimal(string priceStr, decimal expected)
    {
        Assert.Equal(expected, ShopifyProductSource.ParsePrice(priceStr));
    }

    [Fact]
    public void ParsePrice_WithNull_ReturnsNull()
    {
        Assert.Null(ShopifyProductSource.ParsePrice(null));
    }

    [Fact]
    public void ParsePrice_WithEmpty_ReturnsNull()
    {
        Assert.Null(ShopifyProductSource.ParsePrice(""));
    }

    [Fact]
    public void ParsePrice_WithWhitespace_ReturnsNull()
    {
        Assert.Null(ShopifyProductSource.ParsePrice("  "));
    }

    [Fact]
    public void DetermineStatus_PreOrder_FromTag()
    {
        var product = new ShopifyProduct
        {
            Tags = ["preorder", "new"],
            Variants = [new ShopifyVariant { Available = true }],
        };
        Assert.Equal("pre_order", ShopifyProductSource.DetermineStatus(product));
    }

    [Fact]
    public void DetermineStatus_PreOrder_FromHyphenatedTag()
    {
        var product = new ShopifyProduct
        {
            Tags = ["pre-order"],
            Variants = [new ShopifyVariant { Available = true }],
        };
        Assert.Equal("pre_order", ShopifyProductSource.DetermineStatus(product));
    }

    [Fact]
    public void DetermineStatus_Current_WhenAvailable()
    {
        var product = new ShopifyProduct
        {
            Tags = ["new"],
            Variants = [new ShopifyVariant { Available = true }],
        };
        Assert.Equal("current", ShopifyProductSource.DetermineStatus(product));
    }

    [Fact]
    public void DetermineStatus_OutOfStock_WhenNoVariantAvailable()
    {
        var product = new ShopifyProduct
        {
            Tags = [],
            Variants = [new ShopifyVariant { Available = false }],
        };
        Assert.Equal("out_of_stock", ShopifyProductSource.DetermineStatus(product));
    }

    [Fact]
    public void DetermineStatus_OutOfStock_WhenNoVariants()
    {
        var product = new ShopifyProduct
        {
            Variants = null,
        };
        Assert.Equal("out_of_stock", ShopifyProductSource.DetermineStatus(product));
    }

    [Fact]
    public void CleanHtml_RemovesTagsAndDecodes()
    {
        string? result = HtmlCleaner.ToMarkdown("<p>A <strong>bold</strong> &amp; italic text</p>");
        Assert.NotNull(result);
        Assert.Contains("**bold**", result);
        Assert.Contains("&", result);
    }

    [Fact]
    public void CleanHtml_PreservesNewlinesFromParagraphs()
    {
        string? result = HtmlCleaner.ToMarkdown("<p>First</p><p>Second</p>");
        Assert.NotNull(result);
        Assert.Contains("First", result);
        Assert.Contains("Second", result);
    }

    [Fact]
    public void CleanHtml_WithNull_ReturnsNull()
    {
        Assert.Null(HtmlCleaner.ToMarkdown(null));
    }

    [Fact]
    public void CleanHtml_WithEmpty_ReturnsNull()
    {
        Assert.Null(HtmlCleaner.ToMarkdown("  "));
    }

    [Fact]
    public void CleanHtml_WithOnlyTags_ReturnsNull()
    {
        Assert.Null(HtmlCleaner.ToMarkdown("<br/><br/>"));
    }

    [Fact]
    public void MapToRawProduct_WithValidProduct_ReturnsRawProduct()
    {
        var source = new ShopifyProductSource(
            baseUrl: "https://store.example.com",
            manufacturer: "Test Manufacturer",
            defaultGameSystem: "Test Game",
            defaultCurrency: "GBP");

        var product = new ShopifyProduct
        {
            Title = "Space Marine Squad",
            Handle = "space-marine-squad",
            BodyHtml = "<p>A squad of elite warriors.</p>",
            Variants =
            [
                new ShopifyVariant { Sku = "SM001", Price = "29.99", Available = true },
            ],
            Images =
            [
                new ShopifyImage { Src = "https://cdn.shopify.com/image.jpg" },
            ],
            Tags = ["infantry", "new-release"],
        };

        RawProduct? result = source.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal("Space Marine Squad", result.Name);
        Assert.Equal("SM001", result.Sku);
        Assert.Equal(29.99m, result.PriceGbp);
        Assert.Null(result.PriceUsd);
        Assert.Equal("Test Manufacturer", result.Manufacturer);
        Assert.Equal("Test Game", result.GameSystem);
        Assert.Equal("current", result.Status);
        Assert.Equal("https://store.example.com/products/space-marine-squad", result.Url);
        Assert.Equal("https://cdn.shopify.com/image.jpg", result.ImageUrl);
        Assert.Equal("A squad of elite warriors.", result.Description);

        source.Dispose();
    }

    [Fact]
    public void MapToRawProduct_WithNullTitle_ReturnsNull()
    {
        var source = new ShopifyProductSource(
            baseUrl: "https://store.example.com",
            manufacturer: "Test",
            defaultGameSystem: "Test Game");

        var product = new ShopifyProduct { Title = null };
        Assert.Null(source.MapToRawProduct(product));
        source.Dispose();
    }

    [Fact]
    public void MapToRawProduct_WithUsdCurrency_SetsPriceUsd()
    {
        var source = new ShopifyProductSource(
            baseUrl: "https://store.example.com",
            manufacturer: "Test",
            defaultGameSystem: "Test Game",
            defaultCurrency: "USD");

        var product = new ShopifyProduct
        {
            Title = "Product",
            Handle = "product",
            Variants = [new ShopifyVariant { Price = "19.99", Available = true }],
        };

        RawProduct? result = source.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal(19.99m, result.PriceUsd);
        Assert.Null(result.PriceGbp);
        Assert.Null(result.PriceEur);

        source.Dispose();
    }

    [Fact]
    public void MapToRawProduct_WithEurCurrency_SetsPriceEur()
    {
        var source = new ShopifyProductSource(
            baseUrl: "https://store.example.com",
            manufacturer: "Test",
            defaultGameSystem: "Test Game",
            defaultCurrency: "EUR");

        var product = new ShopifyProduct
        {
            Title = "Product",
            Handle = "product",
            Variants = [new ShopifyVariant { Price = "24.50", Available = true }],
        };

        RawProduct? result = source.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal(24.50m, result.PriceEur);
        Assert.Null(result.PriceGbp);
        Assert.Null(result.PriceUsd);

        source.Dispose();
    }

    [Fact]
    public void MapToRawProduct_WithHtmlEntities_DecodesName()
    {
        var source = new ShopifyProductSource(
            baseUrl: "https://store.example.com",
            manufacturer: "Test",
            defaultGameSystem: "Test Game");

        var product = new ShopifyProduct
        {
            Title = "King&#39;s Guard Elite",
            Handle = "kings-guard-elite",
        };

        RawProduct? result = source.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal("King's Guard Elite", result.Name);
        source.Dispose();
    }

    [Fact]
    public void MapToRawProduct_UsesCustomGameSystemExtractor()
    {
        var source = new ShopifyProductSource(
            baseUrl: "https://store.example.com",
            manufacturer: "Test",
            defaultGameSystem: "Default Game",
            gameSystemExtractor: p => p.ProductType);

        var product = new ShopifyProduct
        {
            Title = "Product",
            Handle = "product",
            ProductType = "Custom Game",
        };

        RawProduct? result = source.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal("Custom Game", result.GameSystem);
        source.Dispose();
    }

    [Fact]
    public void MapToRawProduct_UsesCustomFactionExtractor()
    {
        var source = new ShopifyProductSource(
            baseUrl: "https://store.example.com",
            manufacturer: "Test",
            defaultGameSystem: "Test Game",
            factionExtractor: (p, _) => p.Tags?.FirstOrDefault());

        var product = new ShopifyProduct
        {
            Title = "Product",
            Handle = "product",
            Tags = ["Elite Force"],
        };

        RawProduct? result = source.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal("Elite Force", result.Faction);
        source.Dispose();
    }

    [Theory]
    [InlineData("5060523340118", "5060523340118")]  // Valid EAN-13
    [InlineData("060523340118", "060523340118")]     // Valid UPC-A (12 digits)
    [InlineData("12345678", "12345678")]             // Valid EAN-8
    [InlineData(" 5060523340118 ", "5060523340118")] // Trimmed
    public void NormalizeBarcode_ValidBarcodes_ReturnsNormalized(string input, string expected)
    {
        Assert.Equal(expected, ShopifyProductSource.NormalizeBarcode(input));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("  ")]
    [InlineData("0")]
    [InlineData("000000000000")]
    [InlineData("0000000000000")]
    [InlineData("abc123")]
    [InlineData("12345")]         // Too short
    [InlineData("123456789012345")] // Too long (15 digits)
    public void NormalizeBarcode_InvalidBarcodes_ReturnsNull(string? input)
    {
        Assert.Null(ShopifyProductSource.NormalizeBarcode(input));
    }

    [Fact]
    public void MapToRawProduct_WithBarcode_SetsEan()
    {
        var source = new ShopifyProductSource(
            baseUrl: "https://store.example.com",
            manufacturer: "Test",
            defaultGameSystem: "Test Game",
            defaultCurrency: "GBP");

        var product = new ShopifyProduct
        {
            Title = "Product With EAN",
            Handle = "product-ean",
            Variants =
            [
                new ShopifyVariant { Sku = "SKU1", Price = "10.00", Available = true, Barcode = "5060523340118" },
            ],
        };

        RawProduct? result = source.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal("5060523340118", result.Ean);
        source.Dispose();
    }

    [Fact]
    public void MapToRawProduct_WithEmptyBarcode_EanIsNull()
    {
        var source = new ShopifyProductSource(
            baseUrl: "https://store.example.com",
            manufacturer: "Test",
            defaultGameSystem: "Test Game",
            defaultCurrency: "GBP");

        var product = new ShopifyProduct
        {
            Title = "Product No EAN",
            Handle = "product-no-ean",
            Variants =
            [
                new ShopifyVariant { Sku = "SKU2", Price = "10.00", Available = true, Barcode = "" },
            ],
        };

        RawProduct? result = source.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Null(result.Ean);
        source.Dispose();
    }
}
