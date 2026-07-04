using WarHub.ProductCatalog.Tool.Scraping;

namespace WarHub.ProductCatalog.Tool.Tests;

public class AtomicMassGamesProductSourceTests
{
    [Fact]
    public void MapToRawProduct_WithValidCharacter_ReturnsRawProduct()
    {
        var character = new AmgCharacter
        {
            Id = 21693,
            Title = new AmgRendered { Rendered = "Dormammu Ultimate Encounter" },
            Slug = "dormammu-ultimate-encounter",
            Link = "https://www.atomicmassgames.com/character/dormammu-ultimate-encounter/",
            Content = new AmgRendered
            {
                Rendered = """
                    <h1><span class="product-code">CP217</span> Dormammu Ultimate Encounter</h1>
                    <p>Dormammu is the ruler of the Dark Dimension.</p>
                    <img class="product-image" src="https://cdn.svc.asmodee.net/production-amgcom/uploads/image-converter/2026/02/CP217-web@1400.webp" />
                    """
            },
        };

        var result = AtomicMassGamesProductSource.MapToRawProduct(character, "Marvel Crisis Protocol");

        Assert.NotNull(result);
        Assert.Equal("Dormammu Ultimate Encounter", result.Name);
        Assert.Equal("CP217", result.Sku);
        Assert.Equal("Atomic Mass Games", result.Manufacturer);
        Assert.Equal("Marvel Crisis Protocol", result.GameSystem);
        Assert.Equal("current", result.Status);
        Assert.Equal("https://www.atomicmassgames.com/character/dormammu-ultimate-encounter/", result.Url);
        Assert.NotNull(result.ImageUrl);
        Assert.Contains("asmodee.net", result.ImageUrl);
    }

    [Fact]
    public void MapToRawProduct_WithNullTitle_ReturnsNull()
    {
        var character = new AmgCharacter { Title = null };
        Assert.Null(AtomicMassGamesProductSource.MapToRawProduct(character, "Marvel Crisis Protocol"));
    }

    [Fact]
    public void MapToRawProduct_WithEmptyTitle_ReturnsNull()
    {
        var character = new AmgCharacter { Title = new AmgRendered { Rendered = "  " } };
        Assert.Null(AtomicMassGamesProductSource.MapToRawProduct(character, "Marvel Crisis Protocol"));
    }

    [Theory]
    [InlineData("""<span class="product-code">CP217</span>""", "CP217")]
    [InlineData("""<span class="product-code">SWQ28</span>""", "SWQ28")]
    [InlineData("""<span class="product-code">SWP01</span>""", "SWP01")]
    [InlineData("""<SPAN CLASS="product-code">CP100</SPAN>""", "CP100")]
    public void ExtractSku_FromProductCode_ReturnsSku(string html, string expectedSku)
    {
        Assert.Equal(expectedSku, AtomicMassGamesProductSource.ExtractSku(html));
    }

    [Fact]
    public void ExtractSku_WithNoProductCode_ReturnsNull()
    {
        Assert.Null(AtomicMassGamesProductSource.ExtractSku("<h1>No SKU here</h1>"));
    }

    [Fact]
    public void ExtractSku_WithNullHtml_ReturnsNull()
    {
        Assert.Null(AtomicMassGamesProductSource.ExtractSku(null));
    }

    [Fact]
    public void ExtractProductImage_FromProductImageClass_ReturnsUrl()
    {
        string html = """<img class="product-image" src="https://cdn.svc.asmodee.net/image.webp" />""";
        string? result = AtomicMassGamesProductSource.ExtractProductImage(html);
        Assert.Equal("https://cdn.svc.asmodee.net/image.webp", result);
    }

    [Fact]
    public void ExtractProductImage_FallbackToAsmoDeeCdn_ReturnsUrl()
    {
        string html = """<img src="https://cdn.svc.asmodee.net/production-amgcom/uploads/photo.webp" />""";
        string? result = AtomicMassGamesProductSource.ExtractProductImage(html);
        Assert.Equal("https://cdn.svc.asmodee.net/production-amgcom/uploads/photo.webp", result);
    }

    [Fact]
    public void ExtractProductImage_WithNoImage_ReturnsNull()
    {
        Assert.Null(AtomicMassGamesProductSource.ExtractProductImage("<div>No images</div>"));
    }

    [Fact]
    public void ExtractDescription_FromContentAfterHeading_ReturnsText()
    {
        string html = """
            <h1><span class="product-code">CP217</span> Dormammu</h1>
            <p>Dormammu is the ruler of the Dark Dimension.</p>
            """;

        string? result = AtomicMassGamesProductSource.ExtractDescription(html);
        Assert.NotNull(result);
        Assert.Contains("Dormammu is the ruler", result);
    }

    [Fact]
    public void ExtractDescription_WithNullHtml_ReturnsNull()
    {
        Assert.Null(AtomicMassGamesProductSource.ExtractDescription(null));
    }

    [Fact]
    public void MapToRawProduct_WithHtmlEntities_DecodesName()
    {
        var character = new AmgCharacter
        {
            Title = new AmgRendered { Rendered = "Night&#8217;s Watch: Faction Pack" },
            Slug = "nights-watch-faction-pack",
        };

        var result = AtomicMassGamesProductSource.MapToRawProduct(character, "Marvel Crisis Protocol");

        Assert.NotNull(result);
        Assert.Equal("Night\u2019s Watch: Faction Pack", result.Name);
    }

    [Theory]
    [InlineData("Star Wars X-Wing")]
    [InlineData("Star Wars Armada")]
    public void MapToRawProduct_DiscontiunedGameLines_SetsCorrectGameSystem(string gameSystem)
    {
        var character = new AmgCharacter
        {
            Title = new AmgRendered { Rendered = "Test Ship" },
            Slug = "test-ship",
            Link = "https://www.atomicmassgames.com/character/test-ship/",
        };

        var result = AtomicMassGamesProductSource.MapToRawProduct(character, gameSystem);

        Assert.NotNull(result);
        Assert.Equal(gameSystem, result.GameSystem);
    }
}
