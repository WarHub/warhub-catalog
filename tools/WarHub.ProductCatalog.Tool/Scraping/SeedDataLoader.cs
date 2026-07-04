using WarHub.ProductCatalog.Tool.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.ProductCatalog.Tool.Scraping;

/// <summary>
/// Loads products from manually curated YAML seed files.
/// Seed files use the same format as the output FactionCatalog YAML.
/// </summary>
public static class SeedDataLoader
{
    private static readonly IDeserializer YamlDeserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    /// <summary>
    /// Loads all seed files from a directory. Each .yaml file contains an array of RawProduct.
    /// </summary>
    public static async Task<IReadOnlyList<RawProduct>> LoadAsync(string seedDirectory, CancellationToken ct = default)
    {
        if (!Directory.Exists(seedDirectory))
            return [];

        string[] files = Directory.GetFiles(seedDirectory, "*.yaml", SearchOption.AllDirectories);
        var allProducts = new List<RawProduct>();

        foreach (string file in files.OrderBy(f => f))
        {
            string yaml = await File.ReadAllTextAsync(file, ct);
            List<RawProduct>? products = YamlDeserializer.Deserialize<List<RawProduct>>(yaml);
            if (products is not null)
            {
                allProducts.AddRange(products);
            }
        }

        return allProducts;
    }

    /// <summary>
    /// Loads products from a single seed file.
    /// </summary>
    public static async Task<IReadOnlyList<RawProduct>> LoadFileAsync(string filePath, CancellationToken ct = default)
    {
        if (!File.Exists(filePath))
            return [];

        string yaml = await File.ReadAllTextAsync(filePath, ct);
        List<RawProduct>? products = YamlDeserializer.Deserialize<List<RawProduct>>(yaml);
        return products?.AsReadOnly() ?? (IReadOnlyList<RawProduct>)[];
    }
}
