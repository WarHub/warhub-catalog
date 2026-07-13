using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.Catalog.Publish;

/// <summary>
/// Reads the source-of-truth YAML: the canonical product catalog (this project's own
/// DTOs) and the paint brand/equivalence files. Ignores unmatched keys so upstream
/// metadata (e.g. the verbose <c>generatedAt</c> block on brand files) is tolerated.
/// </summary>
internal static class YamlSource
{
    private static readonly IDeserializer Deserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    /// <summary>Loads every brand catalog under <c>{paintsDir}/brands/*.yaml</c>.</summary>
    public static IEnumerable<BrandFile> LoadBrands(string paintsDir)
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
            var catalog = Deserializer.Deserialize<BrandFile>(File.ReadAllText(file));
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

    /// <summary>Loads every canonical product catalog under <c>{catalogDir}/products/*.yaml</c> (not recursive).</summary>
    public static IEnumerable<CanonicalProductCatalog> LoadCanonicalCatalogs(string catalogDir)
    {
        string products = Path.Combine(catalogDir, "products");
        if (!Directory.Exists(products))
        {
            yield break;
        }

        foreach (string file in Directory
            .EnumerateFiles(products, "*.yaml", SearchOption.TopDirectoryOnly)
            .OrderBy(f => f, StringComparer.Ordinal))
        {
            var catalog = Deserializer.Deserialize<CanonicalProductCatalog>(File.ReadAllText(file));
            if (catalog is not null)
            {
                yield return catalog;
            }
        }
    }

    /// <summary>
    /// Loads the game-system and faction slug-to-label maps from
    /// <c>{catalogDir}/taxonomy/game-systems.yaml</c> and <c>taxonomy/factions.yaml</c>.
    /// A missing file yields an empty map for that dimension.
    /// </summary>
    public static TaxonomyLabels LoadTaxonomyLabels(string catalogDir)
    {
        string taxonomy = Path.Combine(catalogDir, "taxonomy");
        var gameSystems = ReadLabelFile<GameSystemLabelsFile>(Path.Combine(taxonomy, "game-systems.yaml"))?.GameSystems;
        var factions = ReadLabelFile<FactionLabelsFile>(Path.Combine(taxonomy, "factions.yaml"))?.Factions;
        return new TaxonomyLabels(ToLabelMap(gameSystems), ToLabelMap(factions));
    }

    private static T? ReadLabelFile<T>(string file)
    {
        return File.Exists(file)
            ? Deserializer.Deserialize<T>(File.ReadAllText(file))
            : default;
    }

    private static IReadOnlyDictionary<string, string> ToLabelMap(List<LabelEntry>? entries)
    {
        return entries is null
            ? new Dictionary<string, string>()
            : entries.ToDictionary(e => e.Slug, e => e.Label);
    }

    private sealed record LabelEntry
    {
        public required string Slug { get; init; }
        public required string Label { get; init; }
    }

    private sealed record GameSystemLabelsFile
    {
        public required List<LabelEntry> GameSystems { get; init; }
    }

    private sealed record FactionLabelsFile
    {
        public required List<LabelEntry> Factions { get; init; }
    }
}
