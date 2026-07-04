using WarHub.PaintCatalog.Tool.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Applies manual overrides from an overrides YAML file.
/// </summary>
public static class OverrideApplier
{
    private static readonly IDeserializer YamlDeserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    /// <summary>
    /// Loads overrides from a YAML file and applies them to the paint list.
    /// Override key format: "{brand-slug}" → "{Name}|{Set}" → override fields.
    /// When hex is overridden, R/G/B are recomputed to stay in sync.
    /// </summary>
    public static IReadOnlyList<Paint> Apply(IReadOnlyList<Paint> paints, string brandSlug, string? overridesPath)
    {
        if (string.IsNullOrEmpty(overridesPath) || !File.Exists(overridesPath))
            return paints;

        string yaml = File.ReadAllText(overridesPath);
        Dictionary<string, Dictionary<string, PaintOverride>>? overrides;
        try
        {
            overrides = YamlDeserializer.Deserialize<Dictionary<string, Dictionary<string, PaintOverride>>>(yaml);
        }
        catch
        {
            return paints;
        }

        if (overrides is null || !overrides.TryGetValue(brandSlug, out Dictionary<string, PaintOverride>? brandOverrides))
            return paints;

        return paints.Select(p =>
        {
            string key = $"{p.Name}|{p.Set}";
            if (!brandOverrides.TryGetValue(key, out PaintOverride? over))
                return p;

            string newHex = over.Hex ?? p.Hex;
            int newR = p.R;
            int newG = p.G;
            int newB = p.B;

            // When hex is overridden, recompute RGB to keep them in sync
            if (over.Hex is not null && TryParseHex(over.Hex, out int r, out int g, out int b))
            {
                newR = r;
                newG = g;
                newB = b;
            }

            return p with
            {
                ProductCode = over.ProductCode ?? p.ProductCode,
                Hex = newHex,
                R = newR,
                G = newG,
                B = newB,
                VolumeMl = over.VolumeMl ?? p.VolumeMl,
                Packaging = over.Packaging ?? p.Packaging,
                Ean = over.Ean ?? p.Ean,
            };
        }).ToList();
    }

    internal static bool TryParseHex(string hex, out int r, out int g, out int b)
    {
        r = g = b = 0;
        string value = hex.StartsWith('#') ? hex[1..] : hex;
        if (value.Length != 6) return false;

        if (int.TryParse(value[0..2], System.Globalization.NumberStyles.HexNumber, null, out r) &&
            int.TryParse(value[2..4], System.Globalization.NumberStyles.HexNumber, null, out g) &&
            int.TryParse(value[4..6], System.Globalization.NumberStyles.HexNumber, null, out b))
        {
            return true;
        }

        r = g = b = 0;
        return false;
    }
}

/// <summary>
/// Override entry for a single paint. Null fields are not overridden.
/// </summary>
public record PaintOverride
{
    public string? ProductCode { get; init; }
    public string? Hex { get; init; }
    public int? VolumeMl { get; init; }
    public string? Packaging { get; init; }
    public string? Ean { get; init; }
}
