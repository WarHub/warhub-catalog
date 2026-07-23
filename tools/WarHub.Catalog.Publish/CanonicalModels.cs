namespace WarHub.Catalog.Publish;

/// <summary>
/// Canonical, publisher-native DTOs for the migrated catalog layout
/// (<c>data/catalog/products/*.yaml</c> and <c>data/catalog/taxonomy/*.yaml</c>). These are additive:
/// consumed by ProductBuilder via YamlSource.LoadCanonicalCatalogs.
/// </summary>
public sealed record CanonicalProductCatalog
{
    public required string Manufacturer { get; init; }
    public required List<CanonicalProduct> Products { get; init; }
}

public sealed record CanonicalProduct
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required string Manufacturer { get; init; }
    public string? ProductCode { get; init; }
    public string? Sku { get; init; }
    public string? Ean { get; init; }
    public string? EanConfidence { get; init; }
    public List<string>? AdditionalEans { get; init; }   // extra barcodes of a repackaged product
    public string? GameSystem { get; init; }     // slug
    public string? Faction { get; init; }        // slug
    public string? Category { get; init; }
    public string? Packaging { get; init; }
    public int? Quantity { get; init; }
    public int? VolumeMl { get; init; }
    public required string Status { get; init; }
    public string? Availability { get; init; }
    public string? FirstSeen { get; init; }
    public decimal? PriceGbp { get; init; }
    public decimal? PriceUsd { get; init; }
    public decimal? PriceEur { get; init; }
    public decimal? PriceCad { get; init; }
    public string? Url { get; init; }
    public string? ImageUrl { get; init; }
    public string? Description { get; init; }
    public List<string>? Evidence { get; init; }
}

public sealed record TaxonomyLabels(
    IReadOnlyDictionary<string, string> GameSystems,
    IReadOnlyDictionary<string, string> Factions);
