using System.Text.RegularExpressions;
using ReverseMarkdown;

namespace WarHub.ProductCatalog.Tool.Scraping;

/// <summary>
/// Converts HTML content to clean Markdown using the ReverseMarkdown library.
/// </summary>
internal static partial class HtmlCleaner
{
    private const int DefaultMaxLength = 10000;

    private static readonly Converter MarkdownConverter = new(new Config
    {
        UnknownTags = Config.UnknownTagsOption.Drop,
        GithubFlavored = true,
        RemoveComments = true,
        SmartHrefHandling = true,
    });

    /// <summary>
    /// Converts HTML to Markdown, preserving formatting like bold, italic, links, and lists.
    /// </summary>
    internal static string? ToMarkdown(string? html, int maxLength = DefaultMaxLength)
    {
        if (string.IsNullOrWhiteSpace(html))
            return null;

        // Remove <style>...</style> blocks before conversion
        string cleaned = StyleBlockRegex().Replace(html, "");

        if (string.IsNullOrWhiteSpace(cleaned))
            return null;

        string markdown = MarkdownConverter.Convert(cleaned);

        // Replace non-breaking spaces with regular spaces
        markdown = markdown.Replace('\u00A0', ' ');

        // Collapse multiple spaces within lines (but preserve newlines)
        markdown = InlineWhitespaceRegex().Replace(markdown, " ");

        // Trim each line
        markdown = string.Join('\n', markdown.Split('\n').Select(line => line.TrimEnd()));

        // Collapse 3+ consecutive newlines to 2 (max one blank line between paragraphs)
        markdown = ExcessiveNewlinesRegex().Replace(markdown, "\n\n");

        markdown = markdown.Trim();

        if (string.IsNullOrWhiteSpace(markdown))
            return null;

        if (markdown.Length > maxLength)
            markdown = markdown[..maxLength];

        return markdown;
    }

    /// <summary>
    /// Converts HTML to clean plain text (strips all formatting).
    /// Kept for backward compatibility - prefer ToMarkdown for richer output.
    /// </summary>
    internal static string? ToPlainText(string? html, int maxLength = 500)
    {
        string? markdown = ToMarkdown(html, maxLength);
        if (markdown is null)
            return null;

        // Strip markdown formatting to get plain text
        string text = MarkdownFormattingRegex().Replace(markdown, "$1");

        // Remove markdown link syntax: [text](url) → text
        text = MarkdownLinkRegex().Replace(text, "$1");

        // Remove markdown list markers
        text = MarkdownListRegex().Replace(text, "");

        return text.Trim();
    }

    // <style ...>...</style> blocks
    [GeneratedRegex(@"<style[^>]*>.*?</style>", RegexOptions.Singleline | RegexOptions.IgnoreCase)]
    private static partial Regex StyleBlockRegex();

    // Multiple spaces/tabs on same line (not newlines)
    [GeneratedRegex(@"[^\S\n]+")]
    private static partial Regex InlineWhitespaceRegex();

    // 3+ consecutive newlines
    [GeneratedRegex(@"\n{3,}")]
    private static partial Regex ExcessiveNewlinesRegex();

    // Markdown bold/italic: **text**, *text*, __text__, _text_
    [GeneratedRegex(@"\*{1,2}([^*]+)\*{1,2}|_{1,2}([^_]+)_{1,2}")]
    private static partial Regex MarkdownFormattingRegex();

    // Markdown links: [text](url)
    [GeneratedRegex(@"\[([^\]]+)\]\([^)]+\)")]
    private static partial Regex MarkdownLinkRegex();

    // Markdown list markers: - or * at start of line
    [GeneratedRegex(@"^[\-\*]\s+", RegexOptions.Multiline)]
    private static partial Regex MarkdownListRegex();
}
