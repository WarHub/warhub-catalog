using WarHub.PaintCatalog.Tool.Parsing;

namespace WarHub.PaintCatalog.Tool.Tests.Parsing;

public class MarkdownPaintParserTests
{
    private const string SevenColumnContent = """
        # Vallejo

        |Name|Code|Set|R|G|B|Hex|
        |---|---|---|---|---|---|---|
        |3B Russian Green|71.281|Model Air|71|73|70|![#474946](https://placehold.co/15x15/474946/474946.png) `#474946`|
        |Black|70.950|Model Color|0|0|0|![#000000](https://placehold.co/15x15/000000/000000.png) `#000000`|
        |Flat Red|70.957|Model Color|180|30|20|![#B41E14](https://placehold.co/15x15/B41E14/B41E14.png) `#B41E14`|
        """;

    private const string SixColumnContent = """
        # Citadel Colour

        |Name|Set|R|G|B|Hex|
        |---|---|---|---|---|---|
        |Mephiston Red|Base|154|14|5|![#9A0E05](https://placehold.co/15x15/9A0E05/9A0E05.png) `#9A0E05`|
        |Abaddon Black|Base|0|0|0|![#000000](https://placehold.co/15x15/000000/000000.png) `#000000`|
        |Agrax Earthshade|Shade|54|42|28|![#362A1C](https://placehold.co/15x15/362A1C/362A1C.png) `#362A1C`|
        """;

    [Fact]
    public void Parse_SevenColumnFormat_ExtractsAllFields()
    {
        var paints = MarkdownPaintParser.Parse(SevenColumnContent);

        Assert.Equal(3, paints.Count);
        Assert.Equal("3B Russian Green", paints[0].Name);
        Assert.Equal("71.281", paints[0].ProductCode);
        Assert.Equal("Model Air", paints[0].Set);
        Assert.Equal(71, paints[0].R);
        Assert.Equal(73, paints[0].G);
        Assert.Equal(70, paints[0].B);
        Assert.Equal("#474946", paints[0].Hex);
    }

    [Fact]
    public void Parse_SixColumnFormat_ExtractsAllFields()
    {
        var paints = MarkdownPaintParser.Parse(SixColumnContent);

        Assert.Equal(3, paints.Count);
        Assert.Equal("Mephiston Red", paints[0].Name);
        Assert.Null(paints[0].ProductCode);
        Assert.Equal("Base", paints[0].Set);
        Assert.Equal(154, paints[0].R);
        Assert.Equal(14, paints[0].G);
        Assert.Equal(5, paints[0].B);
        Assert.Equal("#9A0E05", paints[0].Hex);
    }

    [Fact]
    public void Parse_SixColumnFormat_NeverHasProductCode()
    {
        var paints = MarkdownPaintParser.Parse(SixColumnContent);

        Assert.All(paints, p => Assert.Null(p.ProductCode));
    }

    [Fact]
    public void Parse_SevenColumnFormat_AllHaveProductCode()
    {
        var paints = MarkdownPaintParser.Parse(SevenColumnContent);

        Assert.All(paints, p => Assert.NotNull(p.ProductCode));
    }

    [Fact]
    public void Parse_NullCode_TreatedAsNoCode()
    {
        string content = """
            |Name|Code|Set|R|G|B|Hex|
            |---|---|---|---|---|---|---|
            |Speed Paint One|null|Fanatic|100|100|100|`#646464`|
            |Speed Paint Two|AP123|Fanatic|200|200|200|`#C8C8C8`|
            """;

        var paints = MarkdownPaintParser.Parse(content);

        Assert.Equal(2, paints.Count);
        Assert.Null(paints[0].ProductCode);
        Assert.Equal("AP123", paints[1].ProductCode);
    }

    [Fact]
    public void Parse_DiscontinuedSet_MarkedAsDiscontinued()
    {
        string content = """
            |Name|Set|R|G|B|Hex|
            |---|---|---|---|---|---|
            |Mechrite Red|Foundation (discontinued)|155|30|20|`#9B1E14`|
            |Mephiston Red|Base|154|14|5|`#9A0E05`|
            """;

        var paints = MarkdownPaintParser.Parse(content);

        Assert.Equal(2, paints.Count);
        Assert.True(paints[0].IsDiscontinued);
        Assert.False(paints[1].IsDiscontinued);
    }

    [Fact]
    public void Parse_SpecialCharactersInNames_Preserved()
    {
        string content = """
            |Name|Set|R|G|B|Hex|
            |---|---|---|---|---|---|
            |Waaagh! Flesh|Base|28|84|45|`#1C542D`|
            |'Ardcoat|Technical|255|255|255|`#FFFFFF`|
            |XV-88|Base|114|93|58|`#725D3A`|
            """;

        var paints = MarkdownPaintParser.Parse(content);

        Assert.Equal(3, paints.Count);
        Assert.Equal("Waaagh! Flesh", paints[0].Name);
        Assert.Equal("'Ardcoat", paints[1].Name);
        Assert.Equal("XV-88", paints[2].Name);
    }

    [Fact]
    public void Parse_EmptyContent_ReturnsEmptyList()
    {
        var paints = MarkdownPaintParser.Parse("");

        Assert.Empty(paints);
    }

    [Fact]
    public void Parse_NoTableRows_ReturnsEmptyList()
    {
        string content = """
            # Some Brand

            Just some text without any table rows.
            """;

        var paints = MarkdownPaintParser.Parse(content);

        Assert.Empty(paints);
    }

    [Fact]
    public void Parse_SkipsFooterContent()
    {
        string content = """
            |Name|Set|R|G|B|Hex|
            |---|---|---|---|---|---|
            |Mephiston Red|Base|154|14|5|`#9A0E05`|

            ---

            ![Logo](logo.png)

            Download on the App Store
            """;

        var paints = MarkdownPaintParser.Parse(content);

        Assert.Single(paints);
        Assert.Equal("Mephiston Red", paints[0].Name);
    }

    [Fact]
    public void Parse_MultiplePaints_PreservesOrder()
    {
        var paints = MarkdownPaintParser.Parse(SevenColumnContent);

        Assert.Equal("3B Russian Green", paints[0].Name);
        Assert.Equal("Black", paints[1].Name);
        Assert.Equal("Flat Red", paints[2].Name);
    }

    [Fact]
    public void Parse_InvalidRgbValues_SkipsRow()
    {
        string content = """
            |Name|Set|R|G|B|Hex|
            |---|---|---|---|---|---|
            |Valid Paint|Base|100|100|100|`#646464`|
            |Invalid Paint|Base|abc|100|100|`#646464`|
            |Also Valid|Layer|50|50|50|`#323232`|
            """;

        var paints = MarkdownPaintParser.Parse(content);

        Assert.Equal(2, paints.Count);
        Assert.Equal("Valid Paint", paints[0].Name);
        Assert.Equal("Also Valid", paints[1].Name);
    }
}
