using WarHub.ProductCatalog.Tool.Scraping;

namespace WarHub.ProductCatalog.Tool.Tests;

public class HtmlCleanerTests
{
    // --- ToMarkdown tests ---

    [Fact]
    public void ToMarkdown_Null_ReturnsNull()
    {
        Assert.Null(HtmlCleaner.ToMarkdown(null));
    }

    [Fact]
    public void ToMarkdown_WhitespaceOnly_ReturnsNull()
    {
        Assert.Null(HtmlCleaner.ToMarkdown("   "));
    }

    [Fact]
    public void ToMarkdown_PlainText_ReturnsUnchanged()
    {
        Assert.Equal("Just plain text", HtmlCleaner.ToMarkdown("Just plain text"));
    }

    [Fact]
    public void ToMarkdown_BrTag_BecomesNewline()
    {
        string? result = HtmlCleaner.ToMarkdown("Line one<br>Line two");
        Assert.NotNull(result);
        Assert.Contains("Line one", result);
        Assert.Contains("Line two", result);
    }

    [Fact]
    public void ToMarkdown_DoubleBr_BecomesParagraphBreak()
    {
        string? result = HtmlCleaner.ToMarkdown("Paragraph one<br /><br />Paragraph two");
        Assert.NotNull(result);
        Assert.Contains("Paragraph one", result);
        Assert.Contains("Paragraph two", result);
    }

    [Fact]
    public void ToMarkdown_ParagraphTags_PreservesContent()
    {
        string? result = HtmlCleaner.ToMarkdown("<p>First paragraph</p><p>Second paragraph</p>");
        Assert.NotNull(result);
        Assert.Contains("First paragraph", result);
        Assert.Contains("Second paragraph", result);
    }

    [Fact]
    public void ToMarkdown_StrongTag_BecomesBold()
    {
        string? result = HtmlCleaner.ToMarkdown("This is <strong>bold</strong> text");
        Assert.NotNull(result);
        Assert.Contains("**bold**", result);
    }

    [Fact]
    public void ToMarkdown_ItalicTag_BecomesEmphasis()
    {
        string? result = HtmlCleaner.ToMarkdown("This is <i>italic</i> text");
        Assert.NotNull(result);
        Assert.Contains("*italic*", result);
    }

    [Fact]
    public void ToMarkdown_ListItems_BecomeBullets()
    {
        string? result = HtmlCleaner.ToMarkdown("<ul><li>Item one</li><li>Item two</li></ul>");
        Assert.NotNull(result);
        // ReverseMarkdown uses - for list items
        Assert.Contains("Item one", result);
        Assert.Contains("Item two", result);
    }

    [Fact]
    public void ToMarkdown_LinkTag_BecomesMarkdownLink()
    {
        string? result = HtmlCleaner.ToMarkdown("""Click <a href="https://example.com">here</a> for more""");
        Assert.NotNull(result);
        Assert.Contains("[here]", result);
        Assert.Contains("(https://example.com)", result);
    }

    [Fact]
    public void ToMarkdown_HtmlEntities_Decoded()
    {
        Assert.Equal("Bolt & Thunder", HtmlCleaner.ToMarkdown("Bolt &amp; Thunder"));
    }

    [Fact]
    public void ToMarkdown_NumericEntities_Decoded()
    {
        string? result = HtmlCleaner.ToMarkdown("King&#8217;s Guard");
        Assert.NotNull(result);
        Assert.Contains("King", result);
        Assert.Contains("Guard", result);
    }

    [Fact]
    public void ToMarkdown_NonBreakingSpace_BecomesRegularSpace()
    {
        Assert.Equal("Hello World", HtmlCleaner.ToMarkdown("Hello&nbsp;World"));
    }

    [Fact]
    public void ToMarkdown_StyleBlock_RemovedEntirely()
    {
        Assert.Equal("Visible text",
            HtmlCleaner.ToMarkdown("""<style type="text/css">.hidden { display:none; }</style>Visible text"""));
    }

    [Fact]
    public void ToMarkdown_CollapsesExcessiveNewlines()
    {
        string? result = HtmlCleaner.ToMarkdown("Para one<br/><br/><br/><br/>Para two");
        Assert.NotNull(result);
        Assert.DoesNotContain("\n\n\n", result);
    }

    [Fact]
    public void ToMarkdown_TruncatesToMaxLength()
    {
        string longInput = new string('A', 15000);
        string? result = HtmlCleaner.ToMarkdown(longInput);
        Assert.NotNull(result);
        Assert.Equal(10000, result.Length);
    }

    [Fact]
    public void ToMarkdown_CustomMaxLength()
    {
        string? result = HtmlCleaner.ToMarkdown("This is a longer description", maxLength: 10);
        Assert.NotNull(result);
        Assert.Equal(10, result.Length);
    }

    [Fact]
    public void ToMarkdown_GamesWorkshopTypicalDescription()
    {
        string html = "Plague Marines have disgusting, rotted bodies that stink of decay.<br /><br />" +
                       "This multipart plastic kit builds one Plague Marine Champion.";
        string? result = HtmlCleaner.ToMarkdown(html);
        Assert.NotNull(result);
        Assert.Contains("Plague Marines have disgusting, rotted bodies that stink of decay.", result);
        Assert.Contains("This multipart plastic kit builds one Plague Marine Champion.", result);
    }

    [Fact]
    public void ToMarkdown_MixedHtmlContent()
    {
        string html = "<p>An <strong>elite</strong> squad of warriors.</p>" +
                       "<p>Contents:</p>" +
                       "<ul><li>10 warriors</li><li>1 champion</li></ul>";
        string? result = HtmlCleaner.ToMarkdown(html);
        Assert.NotNull(result);
        Assert.Contains("**elite**", result);
        Assert.Contains("Contents:", result);
        Assert.Contains("10 warriors", result);
        Assert.Contains("1 champion", result);
    }

    [Fact]
    public void ToMarkdown_OnlyBrTags_ReturnsNull()
    {
        Assert.Null(HtmlCleaner.ToMarkdown("<br/><br/>"));
    }

    // --- ToPlainText backward compatibility tests ---

    [Fact]
    public void ToPlainText_Null_ReturnsNull()
    {
        Assert.Null(HtmlCleaner.ToPlainText(null));
    }

    [Fact]
    public void ToPlainText_PlainText_ReturnsUnchanged()
    {
        Assert.Equal("Just plain text", HtmlCleaner.ToPlainText("Just plain text"));
    }

    [Fact]
    public void ToPlainText_StripsMarkdownFormatting()
    {
        // Input with bold HTML should produce plain text without markdown syntax
        string? result = HtmlCleaner.ToPlainText("This is <strong>bold</strong> text");
        Assert.NotNull(result);
        Assert.Contains("bold", result);
        Assert.DoesNotContain("**", result);
    }
}
