using WarHub.ProductCatalog.Tool.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.ProductCatalog.Tool.Enrichment;

/// <summary>
/// Loads full FactionCatalog objects from existing YAML files for enrich-only mode
/// and for preserving EAN data across re-scrapes.
/// </summary>
public static class ExistingCatalogLoader
{
    private static readonly IDeserializer YamlDeserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    /// <summary>
    /// Loads all FactionCatalog YAML files from the output directory.
    /// Optionally filters by manufacturer and/or game system.
    /// </summary>
    public static async Task<IReadOnlyList<FactionCatalog>> LoadAllAsync(
        string outputDir,
        string? manufacturerFilter = null,
        string? gameSystemFilter = null,
        bool verbose = false,
        CancellationToken ct = default)
    {
        string manufacturersDir = Path.Combine(outputDir, "manufacturers");
        if (!Directory.Exists(manufacturersDir))
        {
            if (verbose) Console.WriteLine("  [Enrich] No existing output directory found.");
            return [];
        }

        string[] yamlFiles = Directory.GetFiles(manufacturersDir, "*.yaml", SearchOption.AllDirectories);
        if (verbose)
            Console.WriteLine($"  [Enrich] Found {yamlFiles.Length} YAML catalog files");

        var catalogs = new List<FactionCatalog>();

        foreach (string file in yamlFiles.OrderBy(f => f))
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                string yaml = await File.ReadAllTextAsync(file, ct);
                FactionCatalog? catalog = YamlDeserializer.Deserialize<FactionCatalog>(yaml);
                if (catalog is null)
                    continue;

                // Apply filters
                if (manufacturerFilter is not null &&
                    !catalog.Manufacturer.Equals(manufacturerFilter, StringComparison.OrdinalIgnoreCase))
                    continue;

                if (gameSystemFilter is not null &&
                    !catalog.GameSystem.Equals(gameSystemFilter, StringComparison.OrdinalIgnoreCase))
                    continue;

                catalogs.Add(catalog);
            }
            catch (Exception ex)
            {
                if (verbose)
                    Console.WriteLine($"  [Enrich] Error loading {Path.GetFileName(file)}: {ex.Message}");
            }
        }

        if (verbose)
            Console.WriteLine($"  [Enrich] Loaded {catalogs.Count} catalogs ({catalogs.Sum(c => c.ProductCount)} products)");

        return catalogs;
    }
}
