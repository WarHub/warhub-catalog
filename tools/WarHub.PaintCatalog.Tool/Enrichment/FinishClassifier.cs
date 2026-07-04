using System.Text.RegularExpressions;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Derives paint finish (Matte, Metallic, Gloss, Satin) from set name and paint name patterns.
/// </summary>
public static partial class FinishClassifier
{
    /// <summary>
    /// Returns a new Paint with the Finish field populated.
    /// </summary>
    public static Paint Enrich(Paint paint, string brandDisplayName)
    {
        string? finish = Classify(brandDisplayName, paint.Set, paint.Name);
        if (finish is null)
            return paint;

        return paint with { Finish = finish };
    }

    /// <summary>
    /// Classifies a paint's finish based on brand, set name, and paint name.
    /// Returns null if no classification can be made.
    /// </summary>
    internal static string? Classify(string brandDisplayName, string set, string name)
    {
        string cleanSet = StripDiscontinued(set);

        // 1. Check set-level metallic indicators
        if (IsMetallicSet(cleanSet))
            return "Metallic";

        // 2. Check name-level metallic indicators
        if (IsMetallicName(name))
            return "Metallic";

        // 3. Brand-specific set → finish mapping
        string? brandFinish = ClassifyByBrand(brandDisplayName, cleanSet, name);
        if (brandFinish is not null)
            return brandFinish;

        // 4. Check for gloss indicators
        if (IsGloss(cleanSet, name))
            return "Gloss";

        // 5. Check for satin indicators
        if (IsSatin(cleanSet, name))
            return "Satin";

        // 6. Default: most miniature paints are matte
        return "Matte";
    }

    private static bool IsMetallicSet(string set)
    {
        string setLower = set.ToLowerInvariant();
        return setLower.Contains("metal color") ||
               setLower.Contains("metallic") ||
               setLower.Contains("liquid gold") ||
               setLower == "metal";
    }

    private static bool IsMetallicName(string name)
    {
        return MetallicNamePattern().IsMatch(name);
    }

    private static bool IsGloss(string set, string name)
    {
        string combined = $"{set} {name}".ToLowerInvariant();
        return combined.Contains("gloss") ||
               combined.Contains("'ardcoat") ||
               combined.Contains("ardcoat") ||
               combined.Contains("stormshield") ||
               combined.Contains("varnish") && combined.Contains("gloss");
    }

    private static bool IsSatin(string set, string name)
    {
        string combined = $"{set} {name}".ToLowerInvariant();
        return combined.Contains("satin");
    }

    private static string? ClassifyByBrand(string brandDisplayName, string set, string name)
    {
        return brandDisplayName switch
        {
            "Citadel Colour" => ClassifyCitadelFinish(set, name),
            "Turbo Dork" => ClassifyTurboDorkFinish(set),
            "Green Stuff World" => ClassifyGswFinish(set),
            _ => null
        };
    }

    private static string? ClassifyCitadelFinish(string set, string name)
    {
        // Citadel Shade/Contrast/Technical can have special finishes
        if (set is "Shade" or "Contrast" or "Glaze")
            return "Matte"; // shades/contrasts dry matte

        return null; // fall through to general detection
    }

    private static string? ClassifyTurboDorkFinish(string set)
    {
        string setLower = set.ToLowerInvariant();
        if (setLower.Contains("turboshift") || setLower.Contains("flourish") || setLower.Contains("colorshift"))
            return "Metallic"; // color-shift paints have metallic finish

        return null;
    }

    private static string? ClassifyGswFinish(string set)
    {
        string setLower = set.ToLowerInvariant();
        if (setLower.Contains("chameleon") || setLower.Contains("colorshift"))
            return "Metallic";

        return null;
    }

    private static string StripDiscontinued(string set)
    {
        int idx = set.IndexOf("(discontinued)", StringComparison.OrdinalIgnoreCase);
        return idx >= 0 ? set[..idx].Trim() : set;
    }

    /// <summary>
    /// Matches common metallic color keywords in paint names.
    /// Excludes words that happen to contain these substrings (e.g., "Goldenbrown" should not match).
    /// Uses word boundaries to match whole words only.
    /// </summary>
    [GeneratedRegex(
        @"\b(gold|silver|bronze|copper|brass|steel|iron|chrome|tin|platinum|pewter|leadbelcher|retributor|runelord|liberator|hashut|sycorax|auric|gehenna|golden griffon|fulgurite|bright silver|dark silver)\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex MetallicNamePattern();
}
