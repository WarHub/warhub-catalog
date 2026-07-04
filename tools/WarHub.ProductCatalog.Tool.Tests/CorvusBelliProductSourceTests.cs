using System.Text.Json;
using WarHub.ProductCatalog.Tool.Scraping;

namespace WarHub.ProductCatalog.Tool.Tests;

public class CorvusBelliProductSourceTests
{
    private static JsonElement JsonBool(bool value) =>
        JsonSerializer.Deserialize<JsonElement>(value ? "true" : "false");

    [Fact]
    public void MapToRawProduct_WithValidProduct_ReturnsRawProduct()
    {
        var product = new CbProduct
        {
            Shortname = "Steel Phalanx Action Pack",
            Reference = "280888-1149",
            Slug = "steel-phalanx-action-pack",
            Price = 92.5m,
            Outstock = false,
            Preorder = null,
            Seo = ["ALEPH Steel Phalanx Sectorial Pack", "buy ALEPH Steel Phalanx Sectorial Pack"],
            Category = new CbCategory { Cat = "miniatures", Game = "infinity", Type = "wargames" },
            Img = new CbImage
            {
                NextGen = JsonBool(true),
                Front = new CbImageFront { Img = "steel-phalanx-action-pack.png" },
            },
        };

        var result = CorvusBelliProductSource.MapToRawProduct(product, "infinity");

        Assert.NotNull(result);
        Assert.Equal("Steel Phalanx Action Pack", result.Name);
        Assert.Equal("280888-1149", result.Sku);
        Assert.Equal(92.5m, result.PriceEur);
        Assert.Null(result.PriceGbp);
        Assert.Null(result.PriceUsd);
        Assert.Equal("ALEPH", result.Faction);
        Assert.Equal("Corvus Belli", result.Manufacturer);
        Assert.Equal("Infinity", result.GameSystem);
        Assert.Equal("current", result.Status);
        Assert.Equal("https://store.corvusbelli.com/en/wargames/infinity/steel-phalanx-action-pack", result.Url);
        Assert.NotNull(result.ImageUrl);
    }

    [Fact]
    public void MapToRawProduct_WithNullShortname_ReturnsNull()
    {
        var product = new CbProduct { Shortname = null };
        Assert.Null(CorvusBelliProductSource.MapToRawProduct(product, "infinity"));
    }

    [Fact]
    public void MapToRawProduct_WithEmptyShortname_ReturnsNull()
    {
        var product = new CbProduct { Shortname = "  " };
        Assert.Null(CorvusBelliProductSource.MapToRawProduct(product, "infinity"));
    }

    [Theory]
    [InlineData(new[] { "PanOceania Neoterran Capitaline Army" }, "PanOceania")]
    [InlineData(new[] { "Yu Jing Invincible Army Pack" }, "Yu Jing")]
    [InlineData(new[] { "Ariadna Tartary Army Corps" }, "Ariadna")]
    [InlineData(new[] { "Haqqislam Hassassin Bahram Pack" }, "Haqqislam")]
    [InlineData(new[] { "Nomads Jurisdictional Command" }, "Nomads")]
    [InlineData(new[] { "Combined Army Shasvastii" }, "Combined Army")]
    [InlineData(new[] { "ALEPH Steel Phalanx" }, "ALEPH")]
    [InlineData(new[] { "O-12 Starmada Pack" }, "O-12")]
    [InlineData(new[] { "NA2 Spiral Corps" }, "NA2")]
    public void ExtractFaction_FromSeo_MatchesKnownFactions(string[] seo, string expectedFaction)
    {
        string? result = CorvusBelliProductSource.ExtractFaction(seo.ToList(), "Some Product");
        Assert.Equal(expectedFaction, result);
    }

    [Fact]
    public void ExtractFaction_FallsBackToName()
    {
        string? result = CorvusBelliProductSource.ExtractFaction([], "PanOceania Knight");
        Assert.Equal("PanOceania", result);
    }

    [Fact]
    public void ExtractFaction_WithNoMatch_ReturnsNull()
    {
        string? result = CorvusBelliProductSource.ExtractFaction(["Generic product"], "Action Pack");
        Assert.Null(result);
    }

    [Fact]
    public void ExtractFaction_WithNullSeo_ReturnsNullOrFallback()
    {
        string? result = CorvusBelliProductSource.ExtractFaction(null, "Generic Product");
        Assert.Null(result);
    }

    [Fact]
    public void ExtractFaction_Warcrow_ReturnsNull_ForInfinityFaction()
    {
        string? result = CorvusBelliProductSource.ExtractFaction(
            ["PanOceania something"], "Test Product", "Warcrow");
        Assert.Null(result);
    }

    [Fact]
    public void ExtractFaction_Aristeia_AlwaysReturnsNull()
    {
        string? result = CorvusBelliProductSource.ExtractFaction(
            ["Some faction text"], "Aristeia! Core", "Aristeia!");
        Assert.Null(result);
    }

    [Fact]
    public void MapToRawProduct_Warcrow_SetsGameSystemCorrectly()
    {
        var product = new CbProduct
        {
            Shortname = "Warcrow Battle Pack",
            Reference = "WFTN",
            Slug = "warcrow-battle-pack-winds-from-the-north",
            Price = 70m,
            Outstock = false,
            Category = new CbCategory { Cat = "miniatures", Game = "warcrow", Type = "wargames" },
        };

        var result = CorvusBelliProductSource.MapToRawProduct(product, "warcrow", "Warcrow");

        Assert.NotNull(result);
        Assert.Equal("Warcrow", result.GameSystem);
        Assert.Contains("/wargames/warcrow/", result.Url);
    }

    [Fact]
    public void MapToRawProduct_Aristeia_UsesBoardgamesUrl()
    {
        var product = new CbProduct
        {
            Shortname = "Aristeia! Core",
            Reference = "CBARIPT",
            Slug = "aristeia-core",
            Price = 50m,
            Outstock = false,
            Category = new CbCategory { Cat = "expansions", Game = "aristeia", Type = "boardgames" },
        };

        var result = CorvusBelliProductSource.MapToRawProduct(product, "aristeia", "Aristeia!");

        Assert.NotNull(result);
        Assert.Equal("Aristeia!", result.GameSystem);
        Assert.Contains("/boardgames/aristeia/", result.Url);
    }

    [Fact]
    public void DetermineStatus_Current()
    {
        var product = new CbProduct { Outstock = false, Preorder = null };
        Assert.Equal("current", CorvusBelliProductSource.DetermineStatus(product));
    }

    [Fact]
    public void DetermineStatus_PreOrder()
    {
        var product = new CbProduct { Outstock = false, Preorder = "2025-03-01" };
        Assert.Equal("pre_order", CorvusBelliProductSource.DetermineStatus(product));
    }

    [Fact]
    public void DetermineStatus_OutOfStock()
    {
        var product = new CbProduct { Outstock = true, Preorder = null };
        Assert.Equal("out_of_stock", CorvusBelliProductSource.DetermineStatus(product));
    }

    [Fact]
    public void BuildImageUrl_WithValidImage_ReturnsUrl()
    {
        var img = new CbImage
        {
            NextGen = JsonBool(true),
            Front = new CbImageFront { Img = "steel-phalanx.png" },
        };

        string? result = CorvusBelliProductSource.BuildImageUrl(img, "steel-phalanx");
        Assert.NotNull(result);
        Assert.Contains("steel-phalanx.png", result);
    }

    [Fact]
    public void BuildImageUrl_WithNullImage_ReturnsNull()
    {
        Assert.Null(CorvusBelliProductSource.BuildImageUrl(null, "slug"));
    }

    [Fact]
    public void BuildImageUrl_WithEmptyImgFile_ReturnsNull()
    {
        var img = new CbImage { Front = new CbImageFront { Img = "" } };
        Assert.Null(CorvusBelliProductSource.BuildImageUrl(img, "slug"));
    }
}
