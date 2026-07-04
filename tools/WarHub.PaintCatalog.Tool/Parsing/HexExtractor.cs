using System.Text.RegularExpressions;

namespace WarHub.PaintCatalog.Tool.Parsing;

/// <summary>
/// Extracts hex color values from the Arcturus5404 markdown format.
/// Format: ![#HEX](https://placehold.co/15x15/HEX/HEX.png) `#HEX`
/// </summary>
public static partial class HexExtractor
{
    // Matches `#RRGGBB` within backticks
    [GeneratedRegex(@"`#([0-9A-Fa-f]{6})`")]
    private static partial Regex HexInBackticks();

    /// <summary>
    /// Extracts a clean #RRGGBB hex color from the markdown hex column value.
    /// </summary>
    public static string? Extract(string? rawValue)
    {
        if (string.IsNullOrWhiteSpace(rawValue))
            return null;

        Match match = HexInBackticks().Match(rawValue);
        if (match.Success)
        {
            return $"#{match.Groups[1].Value.ToUpperInvariant()}";
        }

        // Fallback: if it's already a plain hex like #RRGGBB
        if (rawValue.StartsWith('#') && rawValue.Length == 7 &&
            rawValue[1..].All(c => char.IsAsciiHexDigit(c)))
        {
            return rawValue.ToUpperInvariant();
        }

        return null;
    }
}
