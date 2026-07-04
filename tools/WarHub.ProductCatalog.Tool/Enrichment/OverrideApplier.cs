using WarHub.ProductCatalog.Tool.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.ProductCatalog.Tool.Enrichment;

/// <summary>
/// Applies manual overrides from an overrides YAML file to products.
/// </summary>
public static class OverrideApplier
{
    private static readonly IDeserializer YamlDeserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    /// <summary>
    /// Loads overrides from a YAML file and applies them to the product list.
    /// Override key format: "{manufacturer-slug}/{game-system-slug}/{product-name}"
    /// </summary>
    public static IReadOnlyList<Product> Apply(
        IReadOnlyList<Product> products,
        string manufacturerSlug,
        string gameSystemSlug,
        string? overridesPath)
    {
        if (string.IsNullOrEmpty(overridesPath) || !File.Exists(overridesPath))
            return products;

        string yaml = File.ReadAllText(overridesPath);
        Dictionary<string, Dictionary<string, ProductOverride>>? overrides;
        try
        {
            overrides = YamlDeserializer.Deserialize<Dictionary<string, Dictionary<string, ProductOverride>>>(yaml);
        }
        catch
        {
            return products;
        }

        string sectionKey = $"{manufacturerSlug}/{gameSystemSlug}";
        if (overrides is null || !overrides.TryGetValue(sectionKey, out Dictionary<string, ProductOverride>? sectionOverrides))
            return products;

        return products.Select(p =>
        {
            if (!sectionOverrides.TryGetValue(p.Name, out ProductOverride? over))
                return p;

            return p with
            {
                ProductCode = over.ProductCode ?? p.ProductCode,
                Sku = over.Sku ?? p.Sku,
                Ean = over.Ean ?? p.Ean,
                ProductType = over.ProductType ?? p.ProductType,
                PriceGbp = over.PriceGbp ?? p.PriceGbp,
                PriceUsd = over.PriceUsd ?? p.PriceUsd,
                PriceEur = over.PriceEur ?? p.PriceEur,
                Status = over.Status ?? p.Status,
                Contents = over.Contents ?? p.Contents,
            };
        }).ToList();
    }
}

/// <summary>
/// Override entry for a single product. Null fields are not overridden.
/// </summary>
public record ProductOverride
{
    public string? ProductCode { get; init; }
    public string? Sku { get; init; }
    public string? Ean { get; init; }
    public string? ProductType { get; init; }
    public decimal? PriceGbp { get; init; }
    public decimal? PriceUsd { get; init; }
    public decimal? PriceEur { get; init; }
    public string? Status { get; init; }
    public List<ProductUnit>? Contents { get; init; }
}
