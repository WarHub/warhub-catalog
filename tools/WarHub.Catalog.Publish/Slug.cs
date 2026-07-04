using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace WarHub.Catalog.Publish;

/// <summary>
/// Deterministic slug generation for stable, URL-safe ids and partition keys.
/// Lowercase ASCII, non-alphanumeric runs collapse to a single hyphen.
/// </summary>
internal static partial class Slug
{
    [GeneratedRegex("[^a-z0-9]+")]
    private static partial Regex NonAlnum();

    public static string Make(string value)
    {
        // Strip diacritics (é -> e) then transliterate curly quotes away.
        string normalized = value.Normalize(NormalizationForm.FormD);
        var sb = new StringBuilder(normalized.Length);
        foreach (char c in normalized)
        {
            if (CharUnicodeInfo.GetUnicodeCategory(c) != UnicodeCategory.NonSpacingMark)
            {
                sb.Append(c);
            }
        }

        string ascii = sb.ToString().ToLowerInvariant();
        string slug = NonAlnum().Replace(ascii, "-").Trim('-');
        return slug.Length == 0 ? "unknown" : slug;
    }
}
