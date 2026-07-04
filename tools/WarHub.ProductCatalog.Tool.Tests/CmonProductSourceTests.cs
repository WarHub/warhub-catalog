using System.Text.Json;
using WarHub.ProductCatalog.Tool.Scraping;

namespace WarHub.ProductCatalog.Tool.Tests;

public class CmonProductSourceTests
{
    [Theory]
    [InlineData("Stark: Heroes 1", true)]
    [InlineData("Lannister: Attachments 1", true)]
    [InlineData("Night's Watch: Sworn Brothers", true)]
    [InlineData("Free Folk: Frozen Shore Hunters", true)]
    [InlineData("Baratheon: Crownland Scouts", true)]
    [InlineData("Targaryen: Heroes 1", true)]
    [InlineData("Greyjoy: Ironmakers", true)]
    [InlineData("Martell: Sand Skirmishers", true)]
    [InlineData("Bolton: Bastard's Girls", true)]
    [InlineData("Neutral Heroes 1", true)]
    [InlineData("A Song of Ice and Fire Starter Set", true)]
    [InlineData("Zombicide: Black Plague", false)]
    [InlineData("DC Super Heroes United", false)]
    [InlineData("Rocket Punch", false)]
    [InlineData("Marvel United", false)]
    public void IsAsoiafProduct_CorrectlyFilters(string title, bool expected)
    {
        var product = new CmonProduct
        {
            Title = new CmonRendered { Rendered = title },
            Slug = title.ToLowerInvariant().Replace(' ', '-').Replace("'", ""),
        };

        Assert.Equal(expected, CmonProductSource.IsAsoiafProduct(product));
    }

    [Fact]
    public void IsAsoiafProduct_WithNullTitle_ReturnsFalse()
    {
        var product = new CmonProduct { Title = null };
        Assert.False(CmonProductSource.IsAsoiafProduct(product));
    }

    [Fact]
    public void IsAsoiafProduct_WithEmptyTitle_ReturnsFalse()
    {
        var product = new CmonProduct { Title = new CmonRendered { Rendered = "" } };
        Assert.False(CmonProductSource.IsAsoiafProduct(product));
    }

    [Theory]
    [InlineData("Stark: Heroes 1", "Stark")]
    [InlineData("Lannister: Attachments 1", "Lannister")]
    [InlineData("Night's Watch: Sworn Brothers", "Night's Watch")]
    [InlineData("Free Folk: Frozen Shore Hunters", "Free Folk")]
    [InlineData("Baratheon: Crownland Scouts", "Baratheon")]
    [InlineData("Targaryen: Heroes 1", "Targaryen")]
    [InlineData("Greyjoy: Ironmakers", "Greyjoy")]
    [InlineData("Martell: Sand Skirmishers", "Martell")]
    [InlineData("Bolton: Bastard's Girls", "Bolton")]
    [InlineData("Neutral Heroes 1", "Neutral")]
    public void ExtractFaction_FromTitlePrefix_ReturnsFaction(string name, string expectedFaction)
    {
        Assert.Equal(expectedFaction, CmonProductSource.ExtractFaction(name));
    }

    [Fact]
    public void ExtractFaction_FromStarterSet_ReturnsNeutral()
    {
        Assert.Equal("Neutral", CmonProductSource.ExtractFaction("A Song of Ice and Fire Starter Set"));
    }

    [Fact]
    public void ExtractFaction_WithNoMatch_ReturnsNull()
    {
        Assert.Null(CmonProductSource.ExtractFaction("Some Random Product"));
    }

    [Fact]
    public void MapToRawProduct_WithValidProduct_ReturnsRawProduct()
    {
        var product = new CmonProduct
        {
            Id = 12345,
            Title = new CmonRendered { Rendered = "Baratheon: Crownland Scouts" },
            Slug = "baratheon-crownland-scouts",
            Link = "https://www.cmon.com/products/baratheon-crownland-scouts/",
            Acf = new CmonAcf
            {
                HeaderProduct = new CmonHeaderProduct
                {
                    InformationBox = new CmonInformationBox
                    {
                        SubTitle = "House Baratheon's Scouts Come Prepared",
                    },
                },
            },
        };

        var result = CmonProductSource.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal("Baratheon: Crownland Scouts", result.Name);
        Assert.Equal("Baratheon", result.Faction);
        Assert.Equal("CMON", result.Manufacturer);
        Assert.Equal("A Song of Ice and Fire", result.GameSystem);
        Assert.Equal("current", result.Status);
        Assert.Equal("https://www.cmon.com/products/baratheon-crownland-scouts/", result.Url);
        Assert.Equal("House Baratheon's Scouts Come Prepared", result.Description);
    }

    [Fact]
    public void MapToRawProduct_WithNullTitle_ReturnsNull()
    {
        var product = new CmonProduct { Title = null };
        Assert.Null(CmonProductSource.MapToRawProduct(product));
    }

    [Fact]
    public void MapToRawProduct_WithHtmlEntities_DecodesName()
    {
        var product = new CmonProduct
        {
            Title = new CmonRendered { Rendered = "Night&#8217;s Watch: Faction Pack" },
            Slug = "nights-watch-faction-pack",
        };

        var result = CmonProductSource.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal("Night\u2019s Watch: Faction Pack", result.Name);
    }

    [Fact]
    public void MapToRawProduct_WithNoDescription_StillSucceeds()
    {
        var product = new CmonProduct
        {
            Title = new CmonRendered { Rendered = "Stark: Heroes 1" },
            Slug = "stark-heroes-1",
        };

        var result = CmonProductSource.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Null(result.Description);
    }

    [Fact]
    public void IsAsoiafProduct_WithAsoiafSlug_ReturnsTrue()
    {
        var product = new CmonProduct
        {
            Title = new CmonRendered { Rendered = "Tabletop Miniatures Game Starter Set" },
            Slug = "asoiaf-starter-set",
        };

        Assert.True(CmonProductSource.IsAsoiafProduct(product));
    }

    [Fact]
    public void MapToRawProduct_WithProductSku_SetsSku()
    {
        var product = new CmonProduct
        {
            Title = new CmonRendered { Rendered = "Stark: Heroes 1" },
            Slug = "stark-heroes-1",
            Acf = new CmonAcf
            {
                ProductSku = "SIF001",
            },
        };

        var result = CmonProductSource.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal("SIF001", result.Sku);
    }

    [Fact]
    public void MapToRawProduct_WithAlternateProductSku_FallsBack()
    {
        var product = new CmonProduct
        {
            Title = new CmonRendered { Rendered = "Lannister: Attachments 1" },
            Slug = "lannister-attachments-1",
            Acf = new CmonAcf
            {
                ProductSku = null,
                AlternateProductSku = "SIF-ALT-002",
            },
        };

        var result = CmonProductSource.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal("SIF-ALT-002", result.Sku);
    }

    [Fact]
    public void MapToRawProduct_WithNoSku_SkuIsNull()
    {
        var product = new CmonProduct
        {
            Title = new CmonRendered { Rendered = "Targaryen: Heroes 1" },
            Slug = "targaryen-heroes-1",
            Acf = new CmonAcf(),
        };

        var result = CmonProductSource.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Null(result.Sku);
    }

    [Theory]
    [InlineData("$39.99", 39.99)]
    [InlineData("$0.99", 0.99)]
    [InlineData("39.99", 39.99)]
    [InlineData("$199.99", 199.99)]
    public void ParseCmonPrice_ValidPrices_ReturnsParsed(string input, double expected)
    {
        JsonElement el = JsonDocument.Parse($"\"{input}\"").RootElement;
        Assert.Equal((decimal)expected, CmonProductSource.ParseCmonPrice(el));
    }

    [Theory]
    [InlineData("null")]
    [InlineData("\"\"")]
    [InlineData("\"  \"")]
    [InlineData("\"$0\"")]
    [InlineData("\"free\"")]
    [InlineData("false")]
    public void ParseCmonPrice_InvalidPrices_ReturnsNull(string json)
    {
        JsonElement el = JsonDocument.Parse(json).RootElement;
        Assert.Null(CmonProductSource.ParseCmonPrice(el));
    }

    [Fact]
    public void ParseCmonPrice_Null_ReturnsNull()
    {
        Assert.Null(CmonProductSource.ParseCmonPrice(null));
    }

    [Fact]
    public void ParseCmonPrice_NumericValue_ReturnsParsed()
    {
        JsonElement el = JsonDocument.Parse("39.99").RootElement;
        Assert.Equal(39.99m, CmonProductSource.ParseCmonPrice(el));
    }

    [Fact]
    public void MapToRawProduct_WithPrice_SetsPriceUsd()
    {
        var product = new CmonProduct
        {
            Title = new CmonRendered { Rendered = "Stark: Heroes 1" },
            Slug = "stark-heroes-1",
            Acf = new CmonAcf
            {
                HeaderProduct = new CmonHeaderProduct
                {
                    InformationBox = new CmonInformationBox
                    {
                        Price = JsonDocument.Parse("\"$39.99\"").RootElement,
                    },
                },
            },
        };

        var result = CmonProductSource.MapToRawProduct(product);

        Assert.NotNull(result);
        Assert.Equal(39.99m, result.PriceUsd);
    }

    [Fact]
    public void ExtractImageUrl_WithNull_ReturnsNull()
    {
        Assert.Null(CmonProductSource.ExtractImageUrl(null));
    }

    [Fact]
    public void ExtractImageUrl_WithStringElement_ReturnsUrl()
    {
        var json = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(
            "\"https://www.cmon.com/images/product.jpg\"");

        Assert.Equal("https://www.cmon.com/images/product.jpg", CmonProductSource.ExtractImageUrl(json));
    }

    [Fact]
    public void ExtractImageUrl_WithObjectUrl_ReturnsUrl()
    {
        var json = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(
            """{"url": "https://www.cmon.com/images/product.jpg", "width": 800}""");

        Assert.Equal("https://www.cmon.com/images/product.jpg", CmonProductSource.ExtractImageUrl(json));
    }

    [Fact]
    public void ExtractImageUrl_WithSizesLarge_ReturnsLargeUrl()
    {
        var json = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(
            """{"sizes": {"large": "https://www.cmon.com/images/large.jpg", "medium": "https://www.cmon.com/images/medium.jpg"}}""");

        Assert.Equal("https://www.cmon.com/images/large.jpg", CmonProductSource.ExtractImageUrl(json));
    }

    [Fact]
    public void ExtractImageUrl_WithFalseElement_ReturnsNull()
    {
        var json = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>("false");

        Assert.Null(CmonProductSource.ExtractImageUrl(json));
    }

    // NormalizeProductName tests

    [Theory]
    [InlineData("Stark: Heroes 1", "stark heroes 1")]
    [InlineData("Lannister: Red Cloaks", "lannister red cloaks")]
    [InlineData("Night's Watch: Sworn Brothers", "nights watch sworn brothers")]
    [InlineData("Bolton Bastard\u2019s Girls", "bolton bastards girls")]
    [InlineData("Free Folk: Frozen Shore Hunters", "free folk frozen shore hunters")]
    [InlineData("Neutral: Golden Company Swordsmen", "neutral golden company swordsmen")]
    public void NormalizeProductName_CatalogNames_NormalizesCorrectly(string input, string expected)
    {
        Assert.Equal(expected, CmonProductSource.NormalizeProductName(input));
    }

    [Theory]
    [InlineData("A Song of Ice & Fire: Lannister Red Cloaks", "lannister red cloaks")]
    [InlineData("A Song of Ice and Fire: Neutral Faction Pack", "neutral faction pack")]
    [InlineData("Brazen Beasts - A Song Of Ice & Fire Miniatures Game", "brazen beasts")]
    [InlineData("Ironborn Reavers - Song of Ice & Fire Miniatures Game", "ironborn reavers")]
    public void NormalizeProductName_RetailerNames_StripsGamePrefix(string input, string expected)
    {
        Assert.Equal(expected, CmonProductSource.NormalizeProductName(input));
    }

    [Theory]
    [InlineData("Stark: Heroes 1", "A Song of Ice & Fire: Stark Heroes 1")]
    [InlineData("Lannister: Red Cloaks", "A Song of Ice & Fire: Lannister Red Cloaks")]
    [InlineData("Night's Watch: Sworn Brothers", "A Song of Ice and Fire: Night\u2019s Watch Sworn Brothers")]
    public void NormalizeProductName_CatalogAndRetailerMatch(string catalogName, string retailerName)
    {
        Assert.Equal(
            CmonProductSource.NormalizeProductName(catalogName),
            CmonProductSource.NormalizeProductName(retailerName));
    }
}
