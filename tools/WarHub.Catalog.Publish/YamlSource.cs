using WarHub.PaintCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.Catalog.Publish;

/// <summary>
/// Reads the source-of-truth YAML produced by the two catalog tools. Reuses the
/// tools' model records; ignores unmatched keys so tool-specific metadata (e.g. the
/// verbose <c>generatedAt</c> block on brand files) is tolerated.
/// </summary>
internal static class YamlSource
{
    private static readonly IDeserializer Deserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    /// <summary>Loads every faction catalog under <c>{productsDir}/manufacturers/**/*.yaml</c>.</summary>
    public static IEnumerable<FactionCatalog> LoadFactions(string productsDir)
    {
        string manufacturers = Path.Combine(productsDir, "manufacturers");
        if (!Directory.Exists(manufacturers))
        {
            yield break;
        }

        foreach (string file in Directory
            .EnumerateFiles(manufacturers, "*.yaml", SearchOption.AllDirectories)
            .OrderBy(f => f, StringComparer.Ordinal))
        {
            var catalog = Deserializer.Deserialize<FactionCatalog>(File.ReadAllText(file));
            if (catalog is not null)
            {
                yield return catalog;
            }
        }
    }

    /// <summary>Loads every brand catalog under <c>{paintsDir}/brands/*.yaml</c>.</summary>
    public static IEnumerable<BrandCatalog> LoadBrands(string paintsDir)
    {
        string brands = Path.Combine(paintsDir, "brands");
        if (!Directory.Exists(brands))
        {
            yield break;
        }

        foreach (string file in Directory
            .EnumerateFiles(brands, "*.yaml", SearchOption.TopDirectoryOnly)
            .OrderBy(f => f, StringComparer.Ordinal))
        {
            var catalog = Deserializer.Deserialize<BrandCatalog>(File.ReadAllText(file));
            if (catalog is not null)
            {
                yield return catalog;
            }
        }
    }

    /// <summary>Loads the cross-brand equivalences file, if present.</summary>
    public static EquivFile? LoadEquivalences(string paintsDir)
    {
        string file = Path.Combine(paintsDir, "equivalences.yaml");
        return File.Exists(file)
            ? Deserializer.Deserialize<EquivFile>(File.ReadAllText(file))
            : null;
    }
}
