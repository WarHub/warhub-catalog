using WarHub.PaintCatalog.Tool.Scraping;

namespace WarHub.PaintCatalog.Tool.Tests.Scraping;

public class ShopifyPaintSourceTests
{
    [Theory]
    [InlineData("Warpaints Fanatic: Matt White", "Matt White")]
    [InlineData("Speedpaint: Grim Black", "Grim Black")]
    [InlineData("Some Paint Name", "Some Paint Name")]
    public void ExtractPaintName_ParsesTitleFormats(string title, string expectedName)
    {
        string result = ShopifyPaintSource.ExtractPaintName(title);

        Assert.Equal(expectedName, result);
    }

    [Fact]
    public void ExtractPaintLine_DetectsFanatic()
    {
        var tags = new List<string> { "WARPAINTS FANATIC", "tap-shop", "tap-shop-paints" };

        string? line = ShopifyPaintSource.ExtractPaintLine(tags);

        Assert.Equal("Warpaints Fanatic", line);
    }

    [Fact]
    public void ExtractPaintLine_DetectsSpeedpaint()
    {
        var tags = new List<string> { "SPEEDPAINT", "tap-shop-paints" };

        string? line = ShopifyPaintSource.ExtractPaintLine(tags);

        Assert.Equal("Speedpaint", line);
    }

    [Fact]
    public void ExtractPaintLine_ReturnsNull_WhenNoMatch()
    {
        var tags = new List<string> { "tap-shop", "some-other-tag" };

        string? line = ShopifyPaintSource.ExtractPaintLine(tags);

        Assert.Null(line);
    }

    [Fact]
    public void ExtractPracticalColorName_ParsesArmyPainterFormat()
    {
        string bodyHtml = """<strong>Practical Colour Name: </strong>White<br>""";

        string? name = ShopifyPaintSource.ExtractPracticalColorName(bodyHtml);

        Assert.Equal("White", name);
    }

    [Fact]
    public void ExtractPracticalColorName_ParsesAmericanSpelling()
    {
        string bodyHtml = """<strong>Practical Color Name: </strong>Black<br>""";

        string? name = ShopifyPaintSource.ExtractPracticalColorName(bodyHtml);

        Assert.Equal("Black", name);
    }

    [Fact]
    public void ExtractPracticalColorName_ReturnsNull_WhenNotPresent()
    {
        string bodyHtml = """<p>Some description without practical color name</p>""";

        string? name = ShopifyPaintSource.ExtractPracticalColorName(bodyHtml);

        Assert.Null(name);
    }

    [Fact]
    public void MapToEnrichment_ParsesPaintProduct()
    {
        var product = new ShopifyPaintProduct
        {
            Title = "Warpaints Fanatic: Matt White",
            ProductType = "Paint",
            Tags = ["WARPAINTS FANATIC", "tap-shop-paints"],
            BodyHtml = """<strong>Practical Colour Name: </strong>White<br>""",
            Variants =
            [
                new ShopifyPaintVariant
                {
                    Sku = "WP3012P",
                    Barcode = "5713799301207",
                    Available = true,
                }
            ],
            Images =
            [
                new ShopifyPaintImage { Src = "https://cdn.shopify.com/s/files/1/test/WP3012P_0.jpg" }
            ]
        };

        PaintEnrichmentData? data = ShopifyPaintSource.MapToEnrichment(product);

        Assert.NotNull(data);
        Assert.Equal("Matt White", data.PaintName);
        Assert.Equal("WP3012P", data.Sku);
        Assert.Equal("5713799301207", data.Barcode);
        Assert.Equal("Warpaints Fanatic", data.PaintLine);
        Assert.Equal("White", data.PracticalColorName);
        Assert.Contains("WP3012P_0.jpg", data.ImageUrl);
    }

    [Fact]
    public void MapToEnrichment_ReturnsNull_ForNonPaintProducts()
    {
        var product = new ShopifyPaintProduct
        {
            Title = "Painting Mat",
            ProductType = "Accessory",
            Tags = ["tap-shop-accessories"],
        };

        PaintEnrichmentData? data = ShopifyPaintSource.MapToEnrichment(product);

        Assert.Null(data);
    }

    [Fact]
    public void MapToEnrichment_AcceptsPaintTagged_Products()
    {
        var product = new ShopifyPaintProduct
        {
            Title = "Speedpaint: Grim Black",
            ProductType = null,
            Tags = ["tap-shop-paints", "SPEEDPAINT"],
            Variants =
            [
                new ShopifyPaintVariant { Sku = "WP2001P", Available = true }
            ]
        };

        PaintEnrichmentData? data = ShopifyPaintSource.MapToEnrichment(product);

        Assert.NotNull(data);
        Assert.Equal("Grim Black", data.PaintName);
        Assert.Equal("Speedpaint", data.PaintLine);
    }

    [Theory]
    [InlineData(null, null)]
    [InlineData("", null)]
    [InlineData("0", null)]
    [InlineData("5713799301207", "5713799301207")]
    [InlineData("000000000000", null)]
    public void NormalizeBarcode_HandlesEdgeCases(string? input, string? expected)
    {
        string? result = ShopifyPaintSource.NormalizeBarcode(input);

        Assert.Equal(expected, result);
    }
}
