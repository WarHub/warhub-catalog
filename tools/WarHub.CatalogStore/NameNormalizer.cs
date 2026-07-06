using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace WarHub.CatalogStore;

/// <summary>
/// Produces a deterministic, conservative normalized form of a product/paint name
/// for use as the stable identity key. Intentionally does NOT strip punctuation,
/// to avoid collapsing genuinely-distinct records.
/// </summary>
public static partial class NameNormalizer
{
    [GeneratedRegex(@"\s+")]
    private static partial Regex Whitespace();

    public static string Normalize(string name)
    {
        string nfkc = (name ?? string.Empty).Normalize(NormalizationForm.FormKC);
        string collapsed = Whitespace().Replace(nfkc, " ").Trim();
        collapsed = collapsed.Trim('\'', '"');
        collapsed = Whitespace().Replace(collapsed, " ").Trim();
        return collapsed.ToLowerInvariant();
    }
}
