using WarHub.PaintCatalog.Tool.Parsing;

namespace WarHub.PaintCatalog.Tool.Tests.Parsing;

public class HexExtractorTests
{
    [Theory]
    [InlineData("`#474946`", "#474946")]
    [InlineData("`#FFFFFF`", "#FFFFFF")]
    [InlineData("`#000000`", "#000000")]
    [InlineData("`#9A0E05`", "#9A0E05")]
    [InlineData("`#ff00ff`", "#FF00FF")]
    public void Extract_BacktickQuotedHex_ReturnsUppercaseHex(string input, string expected)
    {
        string? result = HexExtractor.Extract(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("![#474946](https://placehold.co/15x15/474946/474946.png) `#474946`", "#474946")]
    [InlineData("![#9A0E05](https://placehold.co/15x15/9A0E05/9A0E05.png) `#9A0E05`", "#9A0E05")]
    [InlineData("![#FFFFFF](https://placehold.co/15x15/FFFFFF/FFFFFF.png) `#FFFFFF`", "#FFFFFF")]
    public void Extract_FullMarkdownImageWithBacktick_ReturnsHex(string input, string expected)
    {
        string? result = HexExtractor.Extract(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("#474946", "#474946")]
    [InlineData("#AABBCC", "#AABBCC")]
    [InlineData("#ff00ff", "#FF00FF")]
    public void Extract_PlainHex_ReturnsFallback(string input, string expected)
    {
        string? result = HexExtractor.Extract(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("")]
    [InlineData("not a hex")]
    [InlineData("12345")]
    [InlineData("#GGG")]
    [InlineData("#XYZXYZ")]
    [InlineData("#GGGGGG")]
    public void Extract_InvalidInput_ReturnsNull(string input)
    {
        string? result = HexExtractor.Extract(input);
        Assert.Null(result);
    }

    [Fact]
    public void Extract_NullInput_ReturnsNull()
    {
        string? result = HexExtractor.Extract(null);
        Assert.Null(result);
    }
}
