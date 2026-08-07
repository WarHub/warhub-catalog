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
    public List<string>? Supersedes { get; init; }       // retired product records this one replaces
    public string? SupersededBy { get; init; }           // the current record replacing this retired one
    public string? GameSystem { get; init; }     // slug
    public string? Faction { get; init; }        // slug
    public string? Category { get; init; }
    public string? Packaging { get; init; }
    public int? Quantity { get; init; }
    public int? VolumeMl { get; init; }
    /// <summary>Net contents in grams. Sibling of <see cref="VolumeMl"/>; see ProductRecord.</summary>
    public int? WeightG { get; init; }
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
    /// <summary>
    /// The manufacturer's OWN product codes for what a boxed set contains, verbatim from the
    /// source -- not resolved catalog ids. Resolving them needs the paint catalog, which the
    /// Python resolver never loads, so the resolved relation is generated separately into
    /// data/catalog/set-contents/.
    ///
    /// Read here so the publisher can carry it; nothing publishes it yet. Declared
    /// <c>List</c> rather than <c>IReadOnlyList</c> for the same reason
    /// <see cref="PaintCatalog.Tool.Models.PaintRecord.AdditionalEans"/> is: YamlDotNet
    /// serializes a read-only list happily and has no node deserializer for one, so the round trip
    /// dies the first time a record actually gains the key.
    /// </summary>
    public List<string>? ContentSkus { get; init; }
    public List<string>? Evidence { get; init; }
}

public sealed record TaxonomyLabels(
    IReadOnlyDictionary<string, string> GameSystems,
    IReadOnlyDictionary<string, string> Factions);
